"""projection.py tests for QGIS-independent georeferencing math."""

import unittest

from TenkakuNinja import projection


class ProjectionMathTests(unittest.TestCase):
    """viewer/radarと共有する測地計算を確認する。"""

    def test_destination_and_local_vector_are_consistent(self):
        """東へ5m進めた点はlocal vectorでも東5mになる。"""
        start = projection.GeoPoint(lat=35.0, lon=135.0)
        end = projection.destination_point(start.lat, start.lon, 90.0, 5.0)

        dx, dy = projection.local_vector_meters(start.lat, start.lon, end.lat, end.lon)

        self.assertAlmostEqual(dx, 5.0, places=3)
        self.assertAlmostEqual(dy, 0.0, places=3)
        self.assertAlmostEqual(projection.heading_from_vector(dx, dy), 90.0, places=4)

    def test_trajectory_heading_uses_before_after_window(self):
        """前後フレームがある場合はそのベースラインでheadingを出す。"""
        center = projection.GeoPoint(lat=35.0, lon=135.0)
        before = projection.destination_point(center.lat, center.lon, 180.0, 2.0)
        after = projection.destination_point(center.lat, center.lon, 0.0, 2.0)
        positions = {
            20: before,
            30: center,
            40: after,
        }

        result = projection.trajectory_heading(positions, 30, window_frames=10)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.heading_deg, 0.0, places=5)
        self.assertAlmostEqual(result.distance_m, 4.0, places=3)
        self.assertEqual(result.method, "before_after")
        self.assertEqual(result.before_frame, 20)
        self.assertEqual(result.after_frame, 40)

    def test_trajectory_heading_falls_back_to_center_after(self):
        """端部では中心から片側の位置を使ってheadingを出す。"""
        center = projection.GeoPoint(lat=35.0, lon=135.0)
        after = projection.destination_point(center.lat, center.lon, 90.0, 3.0)
        positions = {
            30: center,
            40: after,
        }

        result = projection.trajectory_heading(positions, 30, window_frames=10)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.heading_deg, 90.0, places=4)
        self.assertAlmostEqual(result.distance_m, 3.0, places=3)
        self.assertEqual(result.method, "center_after")


if __name__ == "__main__":
    unittest.main()
