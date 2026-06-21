"""poi_cluster.py tests for grouping repeated detections into representative POIs."""

import json
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path

from TenkakuNinja import gpkg_merge, poi_cluster, projection, schema, sqlite_io


def decode_gpkg_point(blob: bytes) -> tuple[float, float]:
    """Decode the minimal GeoPackage POINT blob written by gpkg_merge."""

    assert blob[:2] == b"GP"
    version, flags, srs_id, wkb_endian, wkb_type, x, y = struct.unpack(
        "<BBiBIdd",
        blob[2:],
    )
    assert version == 0
    assert flags == 1
    assert srs_id == 4326
    assert wkb_endian == 1
    assert wkb_type == 1
    return x, y


class PoiClusterTests(unittest.TestCase):
    """POI候補から同一物らしい代表POIを生成する流れを確認する。"""

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.work_db = self.root / "semantic_work.sqlite"
        self.gpkg = self.root / "tmp.gpkg"
        self.conn = sqlite_io.initialize(self.work_db)
        self.run_id = sqlite_io.create_run(
            self.conn,
            source_video="source.mp4",
            source_gpkg=self.gpkg,
            work_dir=self.root,
        )
        self.insert_target("target_a", 10, 12.0, -15.0, "pothole")
        self.insert_target("target_b", 11, 14.0, -14.0, "pothole")
        self.insert_target("target_c", 12, 16.0, -13.0, "pothole")
        self.insert_target("target_d", 13, 40.0, -4.0, "Red Light")
        self.insert_candidate(
            "cand_a",
            "target_a",
            10,
            "pothole",
            0.75,
            35.000000,
            135.000000,
            "down",
        )
        self.insert_candidate(
            "cand_b",
            "target_b",
            11,
            "pothole",
            0.95,
            35.000006,
            135.000006,
            "front",
        )
        self.insert_candidate(
            "cand_c",
            "target_c",
            12,
            "pothole",
            0.80,
            35.000200,
            135.000200,
            "down",
        )
        self.insert_candidate(
            "cand_d",
            "target_d",
            13,
            "Red Light",
            0.90,
            35.000006,
            135.000006,
            "front",
            model_name="traffic_sign_detector",
            model_run_id="model_traffic",
            projection="elevated_object",
            quality="direction_only",
            position_method="fixed_distance_bearing",
            distance_method="fixed_distance_for_direction_only",
            distance_m=10.0,
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp_context.cleanup()

    def insert_target(self, target_id, frame_index, yaw, pitch, semantic_class):
        sqlite_io.insert_semantic_target(
            self.conn,
            run_id=self.run_id,
            target_id=target_id,
            detection_id=f"det_{target_id}",
            frame_index=frame_index,
            target_source="yolo_cubemap",
            semantic_class=semantic_class,
            confidence=0.8,
            target_yaw_to_camera_heading=yaw,
            target_pitch_deg=pitch,
            ground_distance_m=4.0,
            projection="ground_plane",
            quality="trusted",
            evidence_plane_id=f"plane_{target_id}",
            evidence_image_path=f"cubemap/frame_{frame_index:07d}_front.jpg",
            evidence_face="front",
            evidence_bbox=[10.0, 20.0, 30.0, 40.0],
            bbox_anchor="center",
            payload={
                "anchor_xy_px": [20.0, 30.0],
                "cubemap_uv": {"u": 0.1, "v": -0.2},
                "bbox": [10.0, 20.0, 30.0, 40.0],
            },
        )

    def insert_candidate(
        self,
        candidate_id,
        target_id,
        frame_index,
        semantic_class,
        confidence,
        object_lat,
        object_lon,
        evidence_face,
        camera_lat=35.0,
        camera_lon=135.0,
        bearing_deg=20.0,
        model_name="pothole_detector",
        model_run_id="model_road",
        projection="ground_plane",
        quality="trusted",
        position_method="ground_plane_bearing",
        distance_method="semantic_ground_distance",
        distance_m=4.0,
    ):
        sqlite_io.insert_poi_candidate(
            self.conn,
            run_id=self.run_id,
            target_id=target_id,
            frame_index=frame_index,
            target_source="yolo_cubemap",
            semantic_class=semantic_class,
            confidence=confidence,
            projection=projection,
            model_run_id=model_run_id,
            model_name=model_name,
            evidence_face=evidence_face,
            camera_lat=camera_lat,
            camera_lon=camera_lon,
            object_lat=object_lat,
            object_lon=object_lon,
            bearing_deg=bearing_deg,
            distance_m=distance_m,
            position_method=position_method,
            distance_method=distance_method,
            quality=quality,
            payload={"source": "test"},
            candidate_id=candidate_id,
            replace=True,
        )

    def test_generate_poi_clusters_groups_nearby_same_class_candidates(self):
        """近接する同一クラスだけを束ね、代表候補をスコアで選ぶ。"""
        result = poi_cluster.generate_poi_clusters(
            poi_cluster.PoiClusterConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                cluster_radius_m=2.0,
                clear_existing=True,
            )
        )

        self.assertEqual(result["candidate_count"], 4)
        self.assertEqual(result["cluster_count"], 3)

        rows = sqlite_io.fetch_rows(
            self.conn,
            schema.POI_CLUSTERS_TABLE,
            order_by="semantic_class, observation_count DESC, cluster_id",
        )
        merged = [row for row in rows if row["observation_count"] == 2][0]
        self.assertEqual(merged["representative_candidate_id"], "cand_b")
        self.assertEqual(merged["semantic_class"], "pothole")
        self.assertLess(abs(merged["object_lat"] - 35.000003), 0.00001)
        self.assertIn("cand_a", json.loads(merged["member_candidate_ids_json"]))
        self.assertIn("cand_b", json.loads(merged["member_candidate_ids_json"]))

        members = sqlite_io.fetch_rows(
            self.conn,
            schema.POI_CLUSTER_MEMBERS_TABLE,
            where="cluster_id = ?",
            params=(merged["cluster_id"],),
            order_by="member_rank",
        )
        self.assertEqual(len(members), 2)
        self.assertEqual(members[0]["candidate_id"], "cand_b")
        self.assertEqual(members[0]["is_representative"], 1)

    def test_generate_poi_clusters_can_filter_by_min_observations(self):
        """min_observationsで単発候補を代表POIから外せる。"""
        result = poi_cluster.generate_poi_clusters(
            poi_cluster.PoiClusterConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                cluster_radius_m=2.0,
                min_observations=2,
                clear_existing=True,
            )
        )

        self.assertEqual(result["cluster_count"], 1)
        rows = sqlite_io.fetch_rows(self.conn, schema.POI_CLUSTERS_TABLE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["observation_count"], 2)

    def test_gpkg_merge_can_export_clusters_as_nav_compatible_layer(self):
        """代表POIクラスタをNav互換GPKGレイヤへ出力できる。"""
        poi_cluster.generate_poi_clusters(
            poi_cluster.PoiClusterConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                cluster_radius_m=2.0,
                min_observations=2,
                clear_existing=True,
            )
        )
        result = gpkg_merge.export_poi_candidates(
            gpkg_merge.GpkgMergeConfig(
                work_db=self.work_db,
                database=self.gpkg,
                run_id=self.run_id,
                source="clusters",
                layer_name="poi_clusters_pothole_360",
                replace=True,
            )
        )

        self.assertEqual(result["source"], "clusters")
        self.assertEqual(result["feature_count"], 1)

        conn = sqlite3.connect(self.gpkg)
        try:
            row = conn.execute(
                """
                SELECT geom, record_type, candidate_id, cluster_id,
                       representative_candidate_id, observation_count,
                       semantic_class, target_yaw, target_pitch
                FROM poi_clusters_pothole_360
                """
            ).fetchone()
        finally:
            conn.close()

        x, y = decode_gpkg_point(row[0])
        self.assertAlmostEqual(x, 135.000003, places=5)
        self.assertAlmostEqual(y, 35.000003, places=5)
        self.assertEqual(row[1], "poi_cluster")
        self.assertEqual(row[2], row[3])
        self.assertEqual(row[4], "cand_b")
        self.assertEqual(row[5], 2)
        self.assertEqual(row[6], "pothole")
        self.assertAlmostEqual(row[7], 14.0)
        self.assertAlmostEqual(row[8], -14.0)

    def test_direction_only_candidates_use_direction_radius_and_ray_center(self):
        """固定距離で流れた空中物は観測レイと専用半径で束ねる。"""
        camera_a = projection.GeoPoint(lat=35.0, lon=135.0)
        camera_b = projection.destination_point(camera_a.lat, camera_a.lon, 0.0, 10.0)
        true_object = projection.destination_point(camera_b.lat, camera_b.lon, 90.0, 10.0)
        fixed_a = projection.destination_point(camera_a.lat, camera_a.lon, 45.0, 10.0)
        fixed_b = projection.destination_point(camera_b.lat, camera_b.lon, 90.0, 10.0)

        self.insert_target("target_e", 20, 45.0, -5.0, "Speed Limit 40")
        self.insert_target("target_f", 21, 90.0, -5.0, "Speed Limit 40")
        self.insert_candidate(
            "cand_e",
            "target_e",
            20,
            "Speed Limit 40",
            0.88,
            fixed_a.lat,
            fixed_a.lon,
            "front",
            camera_lat=camera_a.lat,
            camera_lon=camera_a.lon,
            bearing_deg=45.0,
            model_name="traffic_sign_detector",
            model_run_id="model_traffic",
            projection="elevated_object",
            quality="direction_only",
            position_method="fixed_distance_bearing",
            distance_method="fixed_distance_for_direction_only",
            distance_m=10.0,
        )
        self.insert_candidate(
            "cand_f",
            "target_f",
            21,
            "Speed Limit 40",
            0.89,
            fixed_b.lat,
            fixed_b.lon,
            "front",
            camera_lat=camera_b.lat,
            camera_lon=camera_b.lon,
            bearing_deg=90.0,
            model_name="traffic_sign_detector",
            model_run_id="model_traffic",
            projection="elevated_object",
            quality="direction_only",
            position_method="fixed_distance_bearing",
            distance_method="fixed_distance_for_direction_only",
            distance_m=10.0,
        )
        self.conn.commit()

        result = poi_cluster.generate_poi_clusters(
            poi_cluster.PoiClusterConfig(
                work_db=self.work_db,
                run_id=self.run_id,
                cluster_radius_m=1.0,
                direction_cluster_radius_m=5.0,
                classes=("Speed Limit 40",),
                clear_existing=True,
            )
        )

        self.assertEqual(result["cluster_count"], 1)
        rows = sqlite_io.fetch_rows(self.conn, schema.POI_CLUSTERS_TABLE)
        cluster = rows[0]
        self.assertEqual(cluster["observation_count"], 2)
        self.assertEqual(cluster["cluster_radius_m"], 5.0)
        self.assertLess(
            projection.distance_between_points_m(
                true_object.lat,
                true_object.lon,
                cluster["object_lat"],
                cluster["object_lon"],
            ),
            0.5,
        )

    def test_representative_member_uses_face_time_movement_policy(self):
        """faceごとの移動方向ルールで代表観測を選ぶ。"""
        front_members = [
            {
                "candidate_id": "front_early",
                "frame_index": 10,
                "evidence_face": "front",
                "_score": 1.0,
                "confidence": 0.8,
                "distance_m": 4.0,
                "target_payload_json": json.dumps({"bbox": [0, 0, 20, 20]}),
            },
            {
                "candidate_id": "front_late",
                "frame_index": 20,
                "evidence_face": "front",
                "_score": 1.0,
                "confidence": 0.8,
                "distance_m": 4.0,
                "target_payload_json": json.dumps({"bbox": [0, 0, 40, 40]}),
            },
        ]
        front_cluster = poi_cluster.WorkingCluster(key=("", ""), members=front_members)
        self.assertEqual(poi_cluster.representative_member(front_cluster)["candidate_id"], "front_late")

        back_members = [
            {
                "candidate_id": "back_early",
                "frame_index": 10,
                "evidence_face": "back",
                "_score": 1.0,
                "confidence": 0.8,
                "distance_m": 4.0,
                "target_payload_json": json.dumps({"bbox": [0, 0, 40, 40]}),
            },
            {
                "candidate_id": "back_late",
                "frame_index": 20,
                "evidence_face": "back",
                "_score": 1.0,
                "confidence": 0.8,
                "distance_m": 4.0,
                "target_payload_json": json.dumps({"bbox": [0, 0, 20, 20]}),
            },
        ]
        back_cluster = poi_cluster.WorkingCluster(key=("", ""), members=back_members)
        self.assertEqual(poi_cluster.representative_member(back_cluster)["candidate_id"], "back_early")

        down_members = [
            {"candidate_id": "down_early", "frame_index": 10, "evidence_face": "down", "_score": 1.0},
            {"candidate_id": "down_center", "frame_index": 20, "evidence_face": "down", "_score": 1.0},
            {"candidate_id": "down_late", "frame_index": 30, "evidence_face": "down", "_score": 1.0},
        ]
        down_cluster = poi_cluster.WorkingCluster(key=("", ""), members=down_members)
        self.assertEqual(poi_cluster.representative_member(down_cluster)["candidate_id"], "down_center")


if __name__ == "__main__":
    unittest.main()
