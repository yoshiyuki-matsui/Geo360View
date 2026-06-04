"""GeoPackage/動画から証跡用フレーム画像を一括抽出するExporter。

TenkakuNinjaCoreの運用ルールに合わせ、1000フレームごとのサブフォルダと
`frame_0000000.jpg` 形式のファイル名を維持する。
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import struct
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


DEFAULT_FRAMES_PER_FOLDER = 1000
DEFAULT_FRAME_COLUMN_CANDIDATES = ("frame", "frame_number", "frame_index")
INTERNAL_GPKG_TABLES = {
    "gpkg_spatial_ref_sys",
    "gpkg_contents",
    "gpkg_geometry_columns",
    "gpkg_tile_matrix_set",
    "gpkg_tile_matrix",
    "gpkg_extensions",
    "sqlite_sequence",
    "rtree",
}


@dataclass(frozen=True)
class ExportConfig:
    """CLI指定値をExporter内部で扱いやすい形にまとめる。"""

    database: Path
    video: Path
    output_dir: Path
    layer: str | None
    frame_column: str | None
    frame_start: int | None
    frame_end: int | None
    frames: tuple[int, ...]
    conditions: tuple[str, ...]
    where: str | None
    matched_only: bool
    scale: float
    jpeg_quality: int
    progressive_jpeg: bool
    overwrite: bool
    no_exif: bool
    frames_per_folder: int
    progress_interval: int
    limit: int | None
    interpolation: str


@dataclass
class FrameRecord:
    """GeoPackageから読み取った抽出対象フレームと属性値。"""

    frame: int
    attrs: dict


@dataclass
class ExportResult:
    """1フレーム分の抽出結果をmanifestへ書き出すための構造。"""

    frame: int
    status: str
    path: str
    message: str = ""


def exif_ascii(value):
    """EXIF ASCII型のNULL終端バイト列へ変換する。"""
    return str(value or "").encode("ascii", "replace") + b"\x00"


def decimal_to_dms_rationals(value):
    """十進緯度経度をGPS EXIFの度分秒RATIONAL配列へ変換する。"""
    value = abs(float(value))
    degrees = int(value)
    minutes_float = (value - degrees) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    return [
        (degrees, 1),
        (minutes, 1),
        (round(seconds * 1000000), 1000000),
    ]


def gps_ifd_entries(gps):
    """GPS EXIF IFDに入れる緯度経度・測地系タグを作る。"""
    lat = float(gps["lat"])
    lon = float(gps["lon"])
    return [
        (0x0001, 2, 2, exif_ascii("N" if lat >= 0 else "S")),
        (0x0002, 5, 3, decimal_to_dms_rationals(lat)),
        (0x0003, 2, 2, exif_ascii("E" if lon >= 0 else "W")),
        (0x0004, 5, 3, decimal_to_dms_rationals(lon)),
        (0x0012, 2, 7, exif_ascii("WGS-84")),
    ]


def pack_gps_ifd(entries, data_offset, data):
    """GPS IFDをTIFF形式でpackし、可変長データを共有dataへ追加する。"""
    gps_ifd = bytearray()
    gps_ifd.extend(struct.pack("<H", len(entries)))

    for tag, field_type, count, value in entries:
        if field_type == 5:
            packed_value = struct.pack("<I", data_offset + len(data))
            for numerator, denominator in value:
                data.extend(struct.pack("<II", numerator, denominator))
        elif len(value) <= 4:
            packed_value = value.ljust(4, b"\x00")
        else:
            packed_value = struct.pack("<I", data_offset + len(data))
            data.extend(value)

        gps_ifd.extend(struct.pack("<HHI", tag, field_type, count))
        gps_ifd.extend(packed_value)

    gps_ifd.extend(struct.pack("<I", 0))
    return bytes(gps_ifd)


def minimal_exif_payload(tags, gps=None):
    """ImageDescription/Software/DateTime/GPSだけを持つEXIF payloadを作る。"""
    entries = []
    data = bytearray()

    def add_ascii(tag, value):
        value_bytes = exif_ascii(value)
        entries.append((tag, 2, len(value_bytes), value_bytes))

    def add_long(tag, value):
        entries.append((tag, 4, 1, struct.pack("<I", value)))

    add_ascii(0x010E, tags.get("description", ""))
    add_ascii(0x0131, tags.get("software", "GPXVideoProcessor Exporter"))
    add_ascii(0x0132, tags.get("datetime", ""))
    if gps:
        add_long(0x8825, 0)
    entries.sort(key=lambda item: item[0])

    ifd_offset = 8
    data_offset = ifd_offset + 2 + len(entries) * 12 + 4
    gps_entries = gps_ifd_entries(gps) if gps else []
    if gps_entries:
        data_offset += 2 + len(gps_entries) * 12 + 4

    ifd = bytearray()
    ifd.extend(struct.pack("<H", len(entries)))
    for tag, field_type, count, value_bytes in entries:
        if tag == 0x8825:
            gps_ifd_offset = ifd_offset + 2 + len(entries) * 12 + 4
            packed_value = struct.pack("<I", gps_ifd_offset)
            ifd.extend(struct.pack("<HHI", tag, field_type, count))
            ifd.extend(packed_value)
            continue

        if len(value_bytes) <= 4:
            packed_value = value_bytes.ljust(4, b"\x00")
        else:
            packed_value = struct.pack("<I", data_offset + len(data))
            data.extend(value_bytes)
        ifd.extend(struct.pack("<HHI", tag, field_type, count))
        ifd.extend(packed_value)

    ifd.extend(struct.pack("<I", 0))
    gps_ifd = pack_gps_ifd(gps_entries, data_offset, data) if gps_entries else b""
    tiff = b"II*\x00" + struct.pack("<I", ifd_offset) + bytes(ifd) + gps_ifd + bytes(data)
    return b"Exif\x00\x00" + tiff


def insert_exif(jpeg_bytes, exif_payload):
    """JPEG先頭のSOI直後へAPP1 EXIFセグメントを挿入する。"""
    if not jpeg_bytes.startswith(b"\xff\xd8"):
        return jpeg_bytes
    segment_length = len(exif_payload) + 2
    if segment_length > 65535:
        return jpeg_bytes
    return (
        jpeg_bytes[:2]
        + b"\xff\xe1"
        + struct.pack(">H", segment_length)
        + exif_payload
        + jpeg_bytes[2:]
    )


def normalize_name(value):
    """列名・テーブル名比較用に小文字化した文字列を返す。"""
    return str(value or "").strip().lower()


def quote_identifier(value):
    """SQLite識別子を安全にダブルクォートする。"""
    return '"' + str(value).replace('"', '""') + '"'


def parse_float(value):
    """CSV/GPKG属性値をfloatへ変換する。失敗時はNoneを返す。"""
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_condition_value(raw):
    """条件式右辺の文字列をSQLiteパラメータ値へ変換する。"""
    text = str(raw).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    if text.lower() in ("null", "none"):
        return None
    if text.lower() in ("true", "yes"):
        return 1
    if text.lower() in ("false", "no"):
        return 0
    try:
        if re.search(r"[.eE]", text):
            return float(text)
        return int(text)
    except ValueError:
        return text


def connect_database(path):
    """GeoPackage(SQLite)を読み取り専用で開く。"""
    if not path.is_file():
        raise FileNotFoundError(f"Database not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_columns(conn, table_name):
    """指定テーブルの列名一覧を取得する。"""
    rows = conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})").fetchall()
    return [row["name"] for row in rows]


def feature_tables(conn):
    """GeoPackage内の地物テーブル候補を返す。"""
    rows = conn.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type = 'features' ORDER BY table_name"
    ).fetchall()
    tables = [row["table_name"] for row in rows]
    if tables:
        return tables

    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    candidates = []
    for row in rows:
        name = row["name"]
        lower = normalize_name(name)
        if lower.startswith("sqlite_") or lower.startswith("rtree_") or lower in INTERNAL_GPKG_TABLES:
            continue
        candidates.append(name)
    return candidates


def resolve_layer(conn, requested):
    """CLI指定またはGeoPackage先頭の地物テーブルから対象レイヤ名を決める。"""
    tables = feature_tables(conn)
    if not tables:
        raise ValueError("No feature table was found in the GeoPackage.")

    if requested:
        requested_norm = normalize_name(requested)
        for table in tables:
            if normalize_name(table) == requested_norm:
                return table
        raise ValueError(f"Layer not found: {requested}. Available layers: {', '.join(tables)}")

    return tables[0]


def resolve_column(columns, requested):
    """大文字小文字を吸収して列名を解決する。"""
    requested_norm = normalize_name(requested)
    for column in columns:
        if normalize_name(column) == requested_norm:
            return column
    raise ValueError(f"Column not found: {requested}. Available columns: {', '.join(columns)}")


def resolve_frame_column(columns, requested):
    """frame/frame_number/frame_indexの候補からフレーム列を決める。"""
    if requested:
        return resolve_column(columns, requested)
    for candidate in DEFAULT_FRAME_COLUMN_CANDIDATES:
        try:
            return resolve_column(columns, candidate)
        except ValueError:
            continue
    raise ValueError(
        "Frame column was not found. Specify --frame-column "
        f"(available columns: {', '.join(columns)})"
    )


def condition_sql(columns, expression):
    """`column=value` 形式の条件指定をSQL断片とパラメータへ変換する。"""
    match = re.match(r"^\s*([A-Za-z_][0-9A-Za-z_]*)\s*(>=|<=|!=|=|>|<)\s*(.*?)\s*$", expression)
    if not match:
        raise ValueError(
            f"Unsupported condition: {expression}. Use forms like kp_match=1 or kp_distance_m<=5."
        )

    column_name, operator, raw_value = match.groups()
    column = resolve_column(columns, column_name)
    value = parse_condition_value(raw_value)
    if value is None:
        if operator == "=":
            return f"{quote_identifier(column)} IS NULL", []
        if operator == "!=":
            return f"{quote_identifier(column)} IS NOT NULL", []
        raise ValueError(f"NULL can only be used with = or !=: {expression}")
    return f"{quote_identifier(column)} {operator} ?", [value]


def matched_only_sql(columns):
    """KPマッチ済み行だけに絞るSQL条件を作る。"""
    normalized = {normalize_name(column): column for column in columns}
    if "kp_match" in normalized:
        return f"{quote_identifier(normalized['kp_match'])} = 1", []
    if "kp" in normalized:
        kp_col = quote_identifier(normalized["kp"])
        return f"{kp_col} IS NOT NULL AND TRIM(CAST({kp_col} AS TEXT)) != ''", []
    raise ValueError("--matched-only requires kp_match or kp column in the selected table.")


def read_frame_records(config):
    """GeoPackageから条件に合うフレーム一覧を読み込む。"""
    with connect_database(config.database) as conn:
        layer = resolve_layer(conn, config.layer)
        columns = table_columns(conn, layer)
        frame_column = resolve_frame_column(columns, config.frame_column)

        clauses = [f"{quote_identifier(frame_column)} IS NOT NULL"]
        params = []

        if config.frame_start is not None:
            clauses.append(f"{quote_identifier(frame_column)} >= ?")
            params.append(config.frame_start)
        if config.frame_end is not None:
            clauses.append(f"{quote_identifier(frame_column)} <= ?")
            params.append(config.frame_end)
        if config.frames:
            placeholders = ", ".join("?" for _ in config.frames)
            clauses.append(f"{quote_identifier(frame_column)} IN ({placeholders})")
            params.extend(config.frames)
        if config.matched_only:
            clause, clause_params = matched_only_sql(columns)
            clauses.append(clause)
            params.extend(clause_params)
        for expression in config.conditions:
            clause, clause_params = condition_sql(columns, expression)
            clauses.append(clause)
            params.extend(clause_params)
        if config.where:
            clauses.append(f"({config.where})")

        sql = (
            f"SELECT * FROM {quote_identifier(layer)} "
            f"WHERE {' AND '.join(clauses)} "
            f"ORDER BY {quote_identifier(frame_column)}"
        )
        if config.limit is not None:
            sql += " LIMIT ?"
            params.append(config.limit)

        records = []
        seen = set()
        for row in conn.execute(sql, params):
            attrs = dict(row)
            frame_value = attrs.get(frame_column)
            frame = int(float(frame_value))
            if frame in seen:
                continue
            seen.add(frame)
            records.append(FrameRecord(frame=frame, attrs=attrs))

    return layer, frame_column, records


def frame_output_path(output_dir, frame, frames_per_folder):
    """TenkakuNinjaCoreルールに沿った出力パスを返す。"""
    subfolder = output_dir / f"{frame // frames_per_folder:04d}"
    return subfolder / f"frame_{frame:07d}.jpg"


def interpolation_flag(name, cv2):
    """リサイズ補間名をOpenCV定数へ変換する。"""
    flags = {
        "area": cv2.INTER_AREA,
        "linear": cv2.INTER_LINEAR,
        "lanczos": cv2.INTER_LANCZOS4,
        "nearest": cv2.INTER_NEAREST,
    }
    return flags[name]


def gps_from_attrs(attrs):
    """属性値からEXIF GPS用の緯度経度を取得する。"""
    for lat_name, lon_name in (
        ("aligned_latitude", "aligned_longitude"),
        ("kp_latitude", "kp_longitude"),
        ("latitude", "longitude"),
        ("lat", "lon"),
    ):
        lat = parse_float(attrs.get(lat_name))
        lon = parse_float(attrs.get(lon_name))
        if lat is not None and lon is not None:
            return {"lat": lat, "lon": lon}
    return None


def encode_jpeg(frame, config, cv2):
    """OpenCVフレームを指定品質のJPEG bytesへ変換する。"""
    params = [int(cv2.IMWRITE_JPEG_QUALITY), int(config.jpeg_quality)]
    progressive_flag = getattr(cv2, "IMWRITE_JPEG_PROGRESSIVE", None)
    if progressive_flag is not None and config.progressive_jpeg:
        params.extend([int(progressive_flag), 1])
    ok, encoded = cv2.imencode(".jpg", frame, params)
    if not ok:
        raise RuntimeError("Failed to encode JPEG.")
    return encoded.tobytes()


def write_bytes_atomic(path, data):
    """途中終了で壊れたJPEGを残さないよう、一時ファイルから置換する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, path)


def add_exif(jpeg_bytes, record, config):
    """証跡用に最小EXIFを付与する。"""
    if config.no_exif:
        return jpeg_bytes

    gps = gps_from_attrs(record.attrs)
    description = (
        f"GPXVideoProcessor Exporter frame={record.frame}; "
        f"database={config.database.name}; "
        f"video={config.video.name}; "
        f"scale={config.scale}; "
        f"jpeg_quality={config.jpeg_quality}"
    )
    payload = minimal_exif_payload(
        {
            "description": description,
            "software": "GPXVideoProcessor Exporter",
            "datetime": datetime.now().strftime("%Y:%m:%d %H:%M:%S"),
        },
        gps=gps,
    )
    return insert_exif(jpeg_bytes, payload)


def extract_frames(config, records):
    """指定フレームだけを動画から抽出してJPEG保存する。"""
    try:
        import cv2
    except ImportError as e:
        raise RuntimeError(f"OpenCV (cv2) is not available: {e}")

    if not config.video.is_file():
        raise FileNotFoundError(f"Video not found: {config.video}")
    if config.scale <= 0:
        raise ValueError("--scale must be greater than 0.")
    if not (1 <= config.jpeg_quality <= 100):
        raise ValueError("--jpeg-quality must be between 1 and 100.")
    if config.frames_per_folder <= 0:
        raise ValueError("--frames-per-folder must be greater than 0.")

    cap = cv2.VideoCapture(str(config.video))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {config.video}")

    try:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        original_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        original_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        target_width = max(1, int(round(original_width * config.scale)))
        target_height = max(1, int(round(original_height * config.scale)))
        resize_needed = (target_width, target_height) != (original_width, original_height)
        interpolation = interpolation_flag(config.interpolation, cv2)

        results = []
        expected_next = None
        for index, record in enumerate(records, start=1):
            output_path = frame_output_path(config.output_dir, record.frame, config.frames_per_folder)
            if output_path.exists() and not config.overwrite:
                results.append(ExportResult(record.frame, "skipped", str(output_path), "exists"))
                continue
            if record.frame < 0 or record.frame >= frame_count:
                results.append(ExportResult(record.frame, "error", str(output_path), "frame out of range"))
                continue

            start = time.perf_counter()
            if expected_next != record.frame:
                cap.set(cv2.CAP_PROP_POS_FRAMES, record.frame)
            ok, frame = cap.read()
            expected_next = record.frame + 1
            if not ok or frame is None:
                results.append(ExportResult(record.frame, "error", str(output_path), "read failed"))
                continue

            if resize_needed:
                frame = cv2.resize(frame, (target_width, target_height), interpolation=interpolation)
            jpeg_bytes = encode_jpeg(frame, config, cv2)
            jpeg_bytes = add_exif(jpeg_bytes, record, config)
            write_bytes_atomic(output_path, jpeg_bytes)

            elapsed = time.perf_counter() - start
            results.append(ExportResult(record.frame, "exported", str(output_path), f"{elapsed:.3f}s"))
            if config.progress_interval and index % config.progress_interval == 0:
                print(f"Exported {index}/{len(records)} records...")

    finally:
        cap.release()

    return {
        "video_frame_count": frame_count,
        "original_width": original_width,
        "original_height": original_height,
        "target_width": target_width,
        "target_height": target_height,
        "results": results,
    }


def write_manifest(output_dir, layer, frame_column, records, export_info, config):
    """抽出結果CSVとsummary JSONを書き出す。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    result_by_frame = {result.frame: result for result in export_info["results"]}
    manifest_path = output_dir / "export_manifest.csv"
    summary_path = output_dir / "export_summary.json"

    with manifest_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["frame", "status", "path", "message"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            result = result_by_frame.get(record.frame)
            if result is None:
                continue
            writer.writerow({
                "frame": result.frame,
                "status": result.status,
                "path": result.path,
                "message": result.message,
            })

    counts = {}
    for result in export_info["results"]:
        counts[result.status] = counts.get(result.status, 0) + 1

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "database": str(config.database),
        "layer": layer,
        "frame_column": frame_column,
        "video": str(config.video),
        "output_dir": str(output_dir),
        "record_count": len(records),
        "counts": counts,
        "scale": config.scale,
        "jpeg_quality": config.jpeg_quality,
        "progressive_jpeg": config.progressive_jpeg,
        "frames_per_folder": config.frames_per_folder,
        "video_frame_count": export_info["video_frame_count"],
        "original_size": [export_info["original_width"], export_info["original_height"]],
        "target_size": [export_info["target_width"], export_info["target_height"]],
        "manifest": manifest_path.name,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path, summary_path


def parse_frame_list(value):
    """`1,2,3` や `1 2 3` 形式のフレーム番号リストをtupleへ変換する。"""
    if not value:
        return ()
    parts = re.split(r"[,\s]+", value.strip())
    return tuple(int(part) for part in parts if part)


def build_arg_parser():
    """Exporter CLIの引数定義を作る。"""
    parser = argparse.ArgumentParser(
        description="Export selected video frames from a GeoPackage database."
    )
    parser.add_argument("--database", default="tmp.gpkg", help="Input GeoPackage. Default: tmp.gpkg")
    parser.add_argument("--video", required=True, help="Source MP4 video path.")
    parser.add_argument("--output-dir", help="Output image directory. Default: <database parent>/images")
    parser.add_argument("--layer", help="GeoPackage layer/table name. Default: first feature layer.")
    parser.add_argument("--frame-column", help="Frame column name. Default: frame/frame_number/frame_index auto.")
    parser.add_argument("--frame-start", "--start", dest="frame_start", type=int, help="Inclusive start frame.")
    parser.add_argument("--frame-end", "--end", dest="frame_end", type=int, help="Inclusive end frame.")
    parser.add_argument("--frames", default="", help="Comma/space separated frame list.")
    parser.add_argument(
        "--condition",
        action="append",
        default=[],
        help="Column condition such as kp_match=1 or kp_distance_m<=5. Can be repeated.",
    )
    parser.add_argument("--where", help="Advanced raw SQL WHERE fragment appended with AND.")
    parser.add_argument("--matched-only", action="store_true", help="Keep rows with kp_match=1 or non-empty kp.")
    parser.add_argument("--scale", type=float, default=1.0, help="Output image scale. Default: 1.0")
    parser.add_argument("--jpeg-quality", type=int, default=92, help="JPEG quality 1-100. Default: 92")
    parser.add_argument("--progressive-jpeg", action="store_true", help="Write progressive JPEG when OpenCV supports it.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing frame images.")
    parser.add_argument("--no-exif", action="store_true", help="Do not embed minimal EXIF metadata.")
    parser.add_argument("--frames-per-folder", type=int, default=DEFAULT_FRAMES_PER_FOLDER)
    parser.add_argument("--progress-interval", type=int, default=100)
    parser.add_argument("--limit", type=int, help="Limit selected records for testing.")
    parser.add_argument(
        "--interpolation",
        choices=["area", "linear", "lanczos", "nearest"],
        default="area",
        help="Resize interpolation. Default: area",
    )
    return parser


def config_from_args(args):
    """argparse結果からExporter設定を作る。"""
    database = Path(args.database).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else database.parent / "images"
    return ExportConfig(
        database=database,
        video=Path(args.video).expanduser().resolve(),
        output_dir=output_dir,
        layer=args.layer,
        frame_column=args.frame_column,
        frame_start=args.frame_start,
        frame_end=args.frame_end,
        frames=parse_frame_list(args.frames),
        conditions=tuple(args.condition or []),
        where=args.where,
        matched_only=args.matched_only,
        scale=args.scale,
        jpeg_quality=args.jpeg_quality,
        progressive_jpeg=args.progressive_jpeg,
        overwrite=args.overwrite,
        no_exif=args.no_exif,
        frames_per_folder=args.frames_per_folder,
        progress_interval=args.progress_interval,
        limit=args.limit,
        interpolation=args.interpolation,
    )


def main(argv=None):
    """CLIエントリポイント。"""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)

    start = time.perf_counter()
    layer, frame_column, records = read_frame_records(config)
    if not records:
        print("No frame records matched the given condition.")
        return 1

    print(f"Database: {config.database}")
    print(f"Layer: {layer}")
    print(f"Frame column: {frame_column}")
    print(f"Selected frames: {len(records)}")
    print(f"Output: {config.output_dir}")

    export_info = extract_frames(config, records)
    manifest_path, summary_path = write_manifest(config.output_dir, layer, frame_column, records, export_info, config)

    elapsed = time.perf_counter() - start
    counts = {}
    for result in export_info["results"]:
        counts[result.status] = counts.get(result.status, 0) + 1
    print(f"Done in {elapsed:.2f}s. Counts: {counts}")
    print(f"Manifest: {manifest_path}")
    print(f"Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
