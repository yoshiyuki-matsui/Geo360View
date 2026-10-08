"""Geo360View全体で共有する小さな変換・入出力ヘルパー。"""

import csv
import math
import os
import re
import unicodedata

from qgis.PyQt.QtCore import QDate, QDateTime, QTime

from .constants import FRAME_IMAGE_FOLDER_SIZE
from .qt_compat import QT_UTC


def _utc_time_spec():
    """QGIS/PyQtのバージョン差を吸収してUTC指定値を返す。"""
    return QT_UTC


def _to_qdatetime(value):
    """PythonのdatetimeをQGIS属性へ入れられるQDateTimeへ変換する。"""
    return QDateTime(
        QDate(value.year, value.month, value.day),
        QTime(value.hour, value.minute, value.second, value.microsecond // 1000),
        _utc_time_spec()
    )


def _format_timestamp(value):
    """出力CSV/JSON用にUTC ISO8601文字列へ整形する。"""
    return value.isoformat(timespec="milliseconds") + "Z"


def _format_distance(value):
    """距離値をCSV向けの小数3桁文字列へ整形する。Noneは空欄にする。"""
    if value is None:
        return ""
    return f"{value:.3f}"


def _base_output_name(video_path, gpx_path):
    """動画名またはGPX名から安全な出力ファイル共通stemを作る。"""
    source_path = video_path or gpx_path or "video_gpx"
    base_name = os.path.splitext(os.path.basename(source_path))[0]
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", base_name).strip("_") or "video_gpx"


def _frame_image_name(frame_num):
    """Exporter互換のフレームJPEGファイル名を返す。"""
    return f"frame_{int(frame_num):07d}.jpg"


def _frame_image_folder(frame_num, frames_per_folder=FRAME_IMAGE_FOLDER_SIZE):
    """フレーム番号からExporter互換の1000件単位サブフォルダ名を返す。"""
    return f"{int(frame_num) // int(frames_per_folder):04d}"


def _frame_image_relative_path(frame_num, frames_per_folder=FRAME_IMAGE_FOLDER_SIZE):
    """images配下で使うExporter互換の相対パスをOS区切りで返す。"""
    return os.path.join(
        _frame_image_folder(frame_num, frames_per_folder),
        _frame_image_name(frame_num)
    )


def _frame_image_relative_posix(frame_num, frames_per_folder=FRAME_IMAGE_FOLDER_SIZE):
    """CSV/JSONへ記録するExporter互換の相対パスをスラッシュ区切りで返す。"""
    return "/".join((
        _frame_image_folder(frame_num, frames_per_folder),
        _frame_image_name(frame_num),
    ))


def _normalize_field_name(value):
    """CSV列名の表記ゆれを比較しやすい正規化名へ変換する。"""
    value = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    return re.sub(r"[\s:./()（）\[\]-]+", "_", value).strip("_")


def _find_field(fieldnames, candidates):
    """候補名リストに近いCSV列を、完全一致優先・部分一致補助で探す。"""
    normalized = [(field, _normalize_field_name(field)) for field in fieldnames or []]
    candidate_names = {_normalize_field_name(candidate) for candidate in candidates}

    for field, normalized_field in normalized:
        if normalized_field in candidate_names:
            return field

    for field, normalized_field in normalized:
        if any(candidate and candidate in normalized_field for candidate in candidate_names):
            return field

    return None


def _safe_gpkg_layer_name(value):
    """GeoPackageのレイヤ名として扱いやすい短いASCII名へ変換する。"""
    value = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "")).strip("_").lower()
    if not value:
        value = "video_gpx_points"
    if value[0].isdigit():
        value = f"layer_{value}"
    return value[:63]


def _looks_like_python_launcher(path):
    """QGIS本体ではなくPython起動ファイルらしいパスかを判定する。"""
    name = os.path.basename(str(path or "")).lower()
    return name.startswith("python")


def _parse_float(value):
    """CSV/JSON/QGIS属性を有限のfloatへ変換する。欠損・不正値はNone。"""
    if value is None:
        return None
    value = unicodedata.normalize("NFKC", str(value)).strip()
    value = value.replace(",", "")
    if not value:
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except ValueError:
        return None


def _open_csv_dict_reader(path):
    """複数エンコーディングと区切り文字推定に対応したDictReaderを開く。"""
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            handle = open(path, "r", encoding=encoding, newline="")
            sample = handle.read(4096)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
            except csv.Error:
                dialect = csv.excel
            return handle, csv.DictReader(handle, dialect=dialect)
        except UnicodeDecodeError as e:
            last_error = e
        except OSError:
            raise
    raise ValueError(f"Could not read CSV encoding: {last_error}")
