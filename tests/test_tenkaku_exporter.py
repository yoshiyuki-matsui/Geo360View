"""TenkakuNinja Exporterの抽出条件と出力命名規則を検証する。"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from TenkakuNinja import exporter


def export_config(database, **overrides):
    """テスト用Exporter設定を既定値付きで作る。"""
    values = {
        "database": Path(database),
        "video": Path("movie.mp4"),
        "output_dir": Path("images"),
        "layer": None,
        "frame_column": None,
        "frame_start": None,
        "frame_end": None,
        "frames": (),
        "conditions": (),
        "where": None,
        "matched_only": False,
        "scale": 1.0,
        "jpeg_quality": 92,
        "progressive_jpeg": False,
        "overwrite": False,
        "no_exif": False,
        "frames_per_folder": 1000,
        "progress_interval": 100,
        "limit": None,
        "interpolation": "area",
    }
    values.update(overrides)
    return exporter.ExportConfig(**values)


class ExporterPathTests(unittest.TestCase):
    """フレーム番号とファイルパスの対応を固定する。"""

    def test_frame_output_path_uses_1000_frame_folders(self):
        """1000フレーム単位のフォルダと7桁ファイル名を維持する。"""
        output_dir = Path("images")
        cases = {
            0: Path("images/0000/frame_0000000.jpg"),
            999: Path("images/0000/frame_0000999.jpg"),
            1000: Path("images/0001/frame_0001000.jpg"),
            1001: Path("images/0001/frame_0001001.jpg"),
        }
        for frame, expected in cases.items():
            with self.subTest(frame=frame):
                self.assertEqual(exporter.frame_output_path(output_dir, frame, 1000), expected)

    def test_condition_sql_uses_parameters_and_identifier_quoting(self):
        """CLI条件指定はSQL文字列連結ではなくパラメータ化される。"""
        sql, params = exporter.condition_sql(["kp_distance_m", "kp_match"], "kp_distance_m<=5")
        self.assertEqual(sql, '"kp_distance_m" <= ?')
        self.assertEqual(params, [5])

        sql, params = exporter.condition_sql(["kp"], "kp!=''")
        self.assertEqual(sql, '"kp" != ?')
        self.assertEqual(params, [""])

    def test_condition_sql_treats_injection_like_text_as_parameter(self):
        """SQL注入風の右辺はSQL断片ではなくパラメータ値として扱う。"""
        sql, params = exporter.condition_sql(["kp_match"], "kp_match = 1 OR 1=1")
        self.assertEqual(sql, '"kp_match" = ?')
        self.assertEqual(params, ["1 OR 1=1"])

    def test_condition_sql_rejects_unsupported_operator(self):
        """対応外のSQL構文は--conditionでは受け付けない。"""
        with self.assertRaises(ValueError):
            exporter.condition_sql(["kp_match"], "kp_match IS NOT NULL")


class ExporterReadRecordsTests(unittest.TestCase):
    """GeoPackage相当SQLiteからの抽出条件を確認する。"""

    def setUp(self):
        """小さなGeoPackage風SQLiteを作る。"""
        self.temp_context = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_context.name) / "tmp.gpkg"
        with sqlite3.connect(self.database) as conn:
            conn.execute("CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT)")
            conn.execute("INSERT INTO gpkg_contents VALUES ('video_points', 'features')")
            conn.execute(
                """
                CREATE TABLE video_points (
                    fid INTEGER PRIMARY KEY,
                    frame INTEGER,
                    kp_match INTEGER,
                    kp TEXT,
                    kp_distance_m REAL
                )
                """
            )
            conn.executemany(
                "INSERT INTO video_points(frame, kp_match, kp, kp_distance_m) VALUES (?, ?, ?, ?)",
                [
                    (0, 1, "KP000", 0.2),
                    (1, 0, "", None),
                    (2, 1, "KP002", 3.5),
                    (2, 1, "KP002_DUP", 3.8),
                    (1000, 1, "KP1000", 4.9),
                ],
            )

    def tearDown(self):
        """一時DBを破棄する。"""
        self.temp_context.cleanup()

    def test_read_frame_records_filters_range_condition_and_dedupes(self):
        """範囲、列条件、frame重複排除が同時に効く。"""
        config = export_config(
            self.database,
            frame_start=0,
            frame_end=999,
            conditions=("kp_distance_m<=4",),
        )

        layer, frame_column, records = exporter.read_frame_records(config)

        self.assertEqual(layer, "video_points")
        self.assertEqual(frame_column, "frame")
        self.assertEqual([record.frame for record in records], [0, 2])
        self.assertEqual(records[0].attrs["kp"], "KP000")
        self.assertEqual(records[1].attrs["kp"], "KP002")

    def test_read_frame_records_matched_only_uses_kp_match(self):
        """--matched-onlyはkp_match列があればそれを優先する。"""
        config = export_config(self.database, matched_only=True, limit=10)

        _layer, _frame_column, records = exporter.read_frame_records(config)

        self.assertEqual([record.frame for record in records], [0, 2, 1000])

    def test_read_frame_records_frame_list_is_inclusive_and_ordered(self):
        """--frames指定は対象だけをframe昇順で返す。"""
        config = export_config(self.database, frames=(1000, 0))

        _layer, _frame_column, records = exporter.read_frame_records(config)

        self.assertEqual([record.frame for record in records], [0, 1000])


if __name__ == "__main__":
    unittest.main()
