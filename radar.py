"""WEBビューアの視点状態をQGIS地図上の実寸レーダとして描画する。"""

import json
import math
import os

from qgis.PyQt import QtGui
from qgis.PyQt.QtCore import QTimer, Qt
try:
    from qgis.PyQt import sip
except ImportError:  # pragma: no cover - QGIS配布差異への保険
    sip = None
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsWkbTypes,
)
from qgis.gui import QgsRubberBand

from .common import _parse_float


RADAR_TRAJECTORY_WINDOW_FRAMES = 10
RADAR_HEADING_JUMP_THRESHOLD_DEG = 45.0
RADAR_MIN_DISTANCE_M = 0.5
RADAR_MIN_SECTOR_RADIUS_M = 1.0
RADAR_MIN_ZOOM_DISTANCE_MULTIPLIER = 0.25
RADAR_MAX_ZOOM_DISTANCE_MULTIPLIER = 8.0
RADAR_GRID_STEP_M = 1.0
RADAR_GRID_MAX_RINGS = 250
RADAR_TARGET_TRUSTED_DISTANCE_M = 5.0
RADAR_TARGET_USABLE_DISTANCE_M = 10.0
RADAR_TARGET_QUALITY_ORDER = ("trusted", "usable", "far")


class RadarMixin:
    """viewer_session.jsonを監視し、撮影点周辺へ一時レーダを描くMixin。"""

    def startViewerSessionPolling(self):
        """WEBビューア状態JSONの定期監視を開始する。"""
        if self.viewer_session_timer is None:
            self.viewer_session_timer = QTimer(self)
            self.viewer_session_timer.timeout.connect(self.pollViewerSession)
        if not self.viewer_session_timer.isActive():
            self.viewer_session_timer.start(500)

    def stopViewerSessionPolling(self):
        """WEBビューア状態JSONの定期監視を停止する。"""
        if self.viewer_session_timer is not None and self.viewer_session_timer.isActive():
            self.viewer_session_timer.stop()

    def pollViewerSession(self):
        """viewer_session.jsonを読み、変化がある場合だけレーダを更新する。"""
        path = self.viewerSessionPath()
        if not os.path.isfile(path):
            return

        try:
            with open(path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return

        if not isinstance(state, dict):
            return

        frame_index = self.sessionFrameIndex(state)
        if frame_index is None:
            return

        try:
            self.storeViewerTargetsFromSessionState(state, frame_index)
        except Exception as e:
            self.reportViewerTargetStoreStatus(f"failed: {e}", warning=True)

        yaw = _parse_float(state.get("yaw_to_camera_heading"))
        pitch = _parse_float(state.get("pitch"))
        zoom = _parse_float(state.get("zoom"))
        target = state.get("target") if isinstance(state.get("target"), dict) else {}
        targets = state.get("targets") if isinstance(state.get("targets"), list) else []
        targets_signature = tuple(
            (
                target_item.get("id"),
                round(_parse_float(target_item.get("target_yaw_to_camera_heading")) or 0.0, 3),
                round(_parse_float(target_item.get("map_bearing_deg")) or 0.0, 3),
                round(_parse_float(target_item.get("yaw_delta_deg")) or 0.0, 3),
                round(_parse_float(target_item.get("target_pitch_deg")) or 0.0, 3),
                round(_parse_float(target_item.get("view_zoom")) or 0.0, 3),
                round(_parse_float(target_item.get("ground_distance_m")) or 0.0, 3),
            )
            for target_item in targets
            if isinstance(target_item, dict)
        )
        radar_config = self.collectRadarConfig(show_errors=False)
        if radar_config is None:
            self.clearRadar()
            return
        range_m = radar_config.range_m
        # 同じ状態を繰り返し描画しないため、表示に関係する値だけで署名を作る。
        signature = (
            state.get("video"),
            frame_index,
            round(yaw or 0.0, 3),
            round(pitch or 0.0, 3),
            round(zoom or 1.0, 3),
            round(_parse_float(state.get("viewer_front_offset_deg")) or 0.0, 3),
            round(_parse_float(target.get("target_yaw_to_camera_heading")) or 0.0, 3),
            round(_parse_float(target.get("yaw_delta_deg")) or 0.0, 3),
            round(_parse_float(target.get("target_pitch_deg")) or 0.0, 3),
            round(_parse_float(target.get("view_zoom")) or 0.0, 3),
            round(_parse_float(target.get("ground_distance_m")) or 0.0, 3),
            targets_signature,
            round(range_m, 3),
            round(radar_config.scale, 3),
            round(radar_config.cal_fov_deg, 3),
            round(radar_config.cal_dist_m, 3),
            round(radar_config.offset_deg, 3),
            round(_parse_float(state.get("viewer_camera_height_m")) or 0.0, 3),
            round(_parse_float(state.get("viewer_hud_height_scale")) or 0.0, 3),
            state.get("updated_at"),
        )
        if signature == self.last_viewer_session_signature:
            return

        self.last_viewer_session_signature = signature
        try:
            self.renderViewerRadar(state)
        except Exception as e:
            print(f"Viewer radar update failed: {e}")

    def storeViewerTargetsFromSessionState(self, state, frame_index):
        """viewer_session.jsonの手動クリック点を、レーダ描画とは独立してレイヤへ保存する。"""
        if not self.viewerTargetPayloads(state):
            return
        lat, lon, _feature = self.framePosition(frame_index)
        if lat is None or lon is None:
            self.reportViewerTargetStoreStatus(f"skipped: no frame position for frame {frame_index}", warning=True)
            return
        heading, _trajectory_radius_m = self.radarHeadingAndRadius(frame_index)
        state = self.persistViewerBearingOffsetForState(heading, state)
        target_projections = self.viewerTargetProjections(lat, lon, heading, state)
        if not target_projections:
            self.reportViewerTargetStoreStatus(f"skipped: no projection for frame {frame_index}", warning=True)
            return
        store_targets = getattr(self, "storeViewerTargetProjections", None)
        if callable(store_targets):
            store_targets(state, lat, lon, target_projections)

    def reportViewerTargetStoreStatus(self, message, warning=False):
        """クリック点保存の診断を同じ内容で連発しないように表示する。"""
        key = (str(message), bool(warning))
        if getattr(self, "last_viewer_target_store_status", None) == key:
            return
        self.last_viewer_target_store_status = key
        notifier_name = "notifyWarningText" if warning else "notifyInfoText"
        notifier = getattr(self, notifier_name, None)
        text = f"Viewer target store {message}"
        if callable(notifier):
            notifier(text)
        else:
            print(text)

    def sessionFrameIndex(self, state):
        """ビューア状態から整数フレーム番号を取り出す。"""
        value = _parse_float(state.get("frame_index"))
        if value is None:
            return None
        return int(value)

    def framePosition(self, frame_num, prefer_feature=True):
        """フレーム番号に対応する緯度経度を取得する。

        通常描画はクリック地物を優先し、軌跡計算では処理済みキャッシュを優先する。
        """
        target = int(frame_num)
        if prefer_feature:
            feature = self.findFeatureByFrame(target)
            if feature is not None:
                gps = self.featureGps(feature)
                if gps:
                    return gps["lat"], gps["lon"], feature

        cached_position = getattr(self, "frame_position_by_frame", {}).get(target)
        if cached_position is not None:
            lat, lon = cached_position
            return lat, lon, None

        for row in self.last_rows:
            try:
                frame_value, _source_frame, _time_value, lat, lon = row
            except ValueError:
                continue
            if int(frame_value) == target:
                return float(lat), float(lon), None

        return None, None, None

    def viewerBearing(self, heading, state):
        """移動軌跡heading、ビューアyaw、動画固有offsetから地図上の視線方位を求める。"""
        yaw = _parse_float(state.get("yaw_to_camera_heading"))
        yaw = (yaw or 0.0) % 360.0
        # yawは動画正面からのビューア相対角として扱う。
        return (heading + self.viewerBearingOffsetForState(heading, state) + yaw) % 360.0

    def viewerBearingOffsetForState(self, heading, state):
        """Return the video-front offset for the current viewer state.

        Detection-check targets can come from CubeMap images whose front face was
        yaw-corrected before YOLO.  In that case the restored viewer yaw is in
        the original MP4 coordinate system, while map POI coordinates already
        carry their absolute bearing.  Prefer the target-derived offset so the
        radar sector follows the original MP4 view without shifting the POI.
        """

        state_offset = self.viewerBearingOffsetFromState(state)
        if state_offset is not None:
            return state_offset
        target_offset = self.viewerBearingOffsetFromTargets(heading, state)
        if target_offset is not None:
            return target_offset
        return self.radarBearingOffsetValue()

    def viewerBearingOffsetFromState(self, state):
        """Return the persisted video-front offset from viewer_session.json."""

        if not isinstance(state, dict):
            return None
        offset = _parse_float(state.get("viewer_front_offset_deg"))
        if offset is None:
            return None
        return self.signedAngleDelta(0.0, offset)

    def viewerBearingOffsetFromTargets(self, heading, state):
        """Derive original video-front offset from detection target payload."""

        for target in self.viewerTargetPayloads(state):
            if not isinstance(target, dict):
                continue
            map_bearing = _parse_float(target.get("map_bearing_deg"))
            target_yaw = _parse_float(target.get("target_yaw_to_camera_heading"))
            if map_bearing is None or target_yaw is None:
                continue
            return self.signedAngleDelta(0.0, float(map_bearing) - float(heading) - float(target_yaw))
        return None

    def persistViewerBearingOffsetForState(self, heading, state):
        """Persist a target-derived video-front offset so manual picks reuse it."""

        if not isinstance(state, dict):
            return state
        target_offset = self.viewerBearingOffsetFromTargets(heading, state)
        if target_offset is None:
            return state

        state_offset = self.viewerBearingOffsetFromState(state)
        if state_offset is not None and self.headingDelta(state_offset, target_offset) < 0.01:
            return state

        updated_state = dict(state)
        updated_state["viewer_front_offset_deg"] = self.signedAngleDelta(0.0, target_offset)
        write_state = getattr(self, "writeViewerSessionState", None)
        if callable(write_state):
            written_state = write_state(updated_state)
            if isinstance(written_state, dict):
                return written_state
        return updated_state

    def viewerFov(self, state):
        """ビューアzoomから扇形の水平視野角を求める。"""
        zoom = _parse_float(state.get("zoom"))
        zoom = max(zoom or 1.0, 0.01)
        return max(1.0, min(179.0, 90.0 / zoom))

    def viewerDistanceMultiplier(self, state):
        """ビューアzoomからレーダ奥行き用の距離倍率を求める。"""
        zoom = _parse_float(state.get("zoom"))
        zoom = max(zoom or 1.0, 0.01)
        # ズームインは近い対象を大きく見る操作として扱い、距離線は手前へ寄せる。
        inverse_zoom = 1.0 / zoom
        return max(
            RADAR_MIN_ZOOM_DISTANCE_MULTIPLIER,
            min(RADAR_MAX_ZOOM_DISTANCE_MULTIPLIER, inverse_zoom)
        )

    def radarCalibrationFovValue(self):
        """UIのCalFOV値を取得する。未初期化時は90度を返す。"""
        radar_cal_fov = getattr(self, "radar_cal_fov", None)
        if radar_cal_fov is None:
            return 90.0
        return max(1.0, min(179.0, float(radar_cal_fov.value())))

    def radarCalibrationDistanceValue(self):
        """UIのCalDist値を取得する。未初期化時は5mを返す。"""
        radar_cal_distance = getattr(self, "radar_cal_distance", None)
        if radar_cal_distance is None:
            return 5.0
        return max(0.1, float(radar_cal_distance.value()))

    def calibratedMarkerDistance(self, state):
        """現在FOVと校正値から、地図上へ描く垂線中心距離を求める。"""
        return self.calibratedMarkerDistanceForFov(self.viewerFov(state))

    def calibratedMarkerDistanceForFov(self, fov):
        """指定FOVと校正値から、地図上へ描く中心距離を求める。"""
        cal_fov = self.radarCalibrationFovValue()
        current_half_tan = math.tan(math.radians(float(fov) / 2.0))
        calibration_half_tan = math.tan(math.radians(cal_fov / 2.0))
        if abs(calibration_half_tan) < 1e-9:
            ratio = 1.0
        else:
            ratio = current_half_tan / calibration_half_tan
        return max(
            RADAR_MIN_SECTOR_RADIUS_M,
            self.radarCalibrationDistanceValue() * self.radarScaleValue() * ratio
        )

    def updateRadarCalibrationReadout(self, fov, marker_distance_m):
        """現在FOVと垂線距離を操作パネルへ表示する。"""
        self.current_viewer_fov = float(fov)
        self.current_marker_distance_m = float(marker_distance_m)
        current_fov_label = getattr(self, "current_fov_label", None)
        if current_fov_label is not None:
            current_fov_label.setText(f"FOV: {float(fov):.1f}deg")
        marker_distance_label = getattr(self, "marker_distance_label", None)
        if marker_distance_label is not None:
            marker_distance_label.setText(f"Marker: {float(marker_distance_m):.1f}m")

    def targetDistanceQuality(self, distance_m):
        """クリック点距離から運用品質ラベルを返す。"""
        distance = _parse_float(distance_m)
        if distance is None:
            return "unknown"
        if distance <= RADAR_TARGET_TRUSTED_DISTANCE_M:
            return "trusted"
        if distance <= RADAR_TARGET_USABLE_DISTANCE_M:
            return "usable"
        return "far"

    def updateRadarTargetReadout(self, target_projection):
        """360ビューアクリック投影点の距離と相対角を操作パネルへ表示する。"""
        target_projection_label = getattr(self, "target_projection_label", None)
        if target_projection_label is None:
            return
        if isinstance(target_projection, list):
            projections = target_projection
        else:
            projections = [target_projection] if target_projection else []
        if not projections:
            target_projection_label.setText("Click: -")
            return
        latest_projection = projections[-1]
        distance_m = latest_projection["distance_m"]
        yaw_delta = latest_projection["yaw_delta_deg"]
        quality = latest_projection.get("quality") or self.targetDistanceQuality(distance_m)
        if len(projections) == 1:
            target_projection_label.setText(f"Click: {distance_m:.1f}m {quality} {yaw_delta:+.1f}deg")
        else:
            target_projection_label.setText(f"Click: {len(projections)} pts last {distance_m:.1f}m {quality} {yaw_delta:+.1f}deg")

    def viewerRadarHudPayload(self, frame_index):
        """WEBビューアHUDへ渡すレーダ距離補助値を作る。"""
        radar_config = self.collectRadarConfig(show_errors=False)
        if radar_config is None:
            return None
        fixed_radius_m = radar_config.range_m
        calibration_distance_m = radar_config.cal_dist_m
        manual_scale = radar_config.scale

        return {
            "range_m": fixed_radius_m,
            "outer_range_m": fixed_radius_m * 2.0,
            "base_sector_radius_m": float(calibration_distance_m * manual_scale),
            "calibration_fov_deg": radar_config.cal_fov_deg,
            "calibration_distance_m": calibration_distance_m,
            "manual_scale": manual_scale,
            "min_sector_radius_m": RADAR_MIN_SECTOR_RADIUS_M,
            "min_zoom_multiplier": RADAR_MIN_ZOOM_DISTANCE_MULTIPLIER,
            "max_zoom_multiplier": RADAR_MAX_ZOOM_DISTANCE_MULTIPLIER,
        }

    def destinationPoint(self, lat, lon, bearing_deg, distance_m):
        """緯度経度から指定方位・距離だけ進んだWGS84上の点を返す。"""
        earth_radius_m = 6378137.0
        bearing = math.radians(float(bearing_deg))
        angular_distance = float(distance_m) / earth_radius_m
        lat1 = math.radians(float(lat))
        lon1 = math.radians(float(lon))

        lat2 = math.asin(
            math.sin(lat1) * math.cos(angular_distance)
            + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing)
        )
        lon2 = lon1 + math.atan2(
            math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1),
            math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2)
        )
        return QgsPointXY(math.degrees(lon2), math.degrees(lat2))

    def canvasPoint(self, lon, lat):
        """EPSG:4326の点を現在のQGIS canvas CRSへ変換する。"""
        canvas = self.iface.mapCanvas()
        source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        dest_crs = canvas.mapSettings().destinationCrs()
        point = QgsPointXY(float(lon), float(lat))
        if dest_crs.authid() == source_crs.authid():
            return point

        transform = QgsCoordinateTransform(
            source_crs,
            dest_crs,
            QgsProject.instance().transformContext()
        )
        return transform.transform(point)

    def localVectorMeters(self, lat1, lon1, lat2, lon2):
        """短距離前提で緯度経度差を東西dx・南北dyのメートル差へ近似変換する。"""
        earth_radius_m = 6378137.0
        mean_lat = math.radians((float(lat1) + float(lat2)) / 2.0)
        dx = math.radians(float(lon2) - float(lon1)) * earth_radius_m * math.cos(mean_lat)
        dy = math.radians(float(lat2) - float(lat1)) * earth_radius_m
        return dx, dy

    def headingFromVector(self, dx, dy):
        """東西dx・南北dyから、北0度・時計回りのheadingを算出する。"""
        return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0

    def headingDelta(self, heading_a, heading_b):
        """0/360度境界をまたいでも最小角度差としてheading差を返す。"""
        return abs((float(heading_a) - float(heading_b) + 180.0) % 360.0 - 180.0)

    def signedAngleDelta(self, angle_a, angle_b):
        """angle_aからangle_bへの差を-180..180度の符号付き角度で返す。"""
        return (float(angle_b) - float(angle_a) + 180.0) % 360.0 - 180.0

    def radarScaleValue(self):
        """UIのScale値を取得する。古いUI状態では安全な既定値を返す。"""
        radar_scale = getattr(self, "radar_scale", None)
        if radar_scale is None:
            return 1.0
        return max(0.1, float(radar_scale.value()))

    def radarBearingOffsetValue(self):
        """動画の正面方向ずれを補正する時計回りoffset角を取得する。"""
        radar_offset = getattr(self, "radar_offset", None)
        if radar_offset is None:
            return 0.0
        return float(radar_offset.currentData() or 0.0)

    def trajectoryHeadingAndDistance(self, frame_index):
        """対象フレーム前後の軌跡からheadingと移動距離を求める。"""
        frame_index = int(frame_index)
        prefer_feature_lookup = not bool(getattr(self, "frame_position_by_frame", {})) and not bool(self.last_rows)
        center = self.framePosition(frame_index, prefer_feature=prefer_feature_lookup)
        has_center = center[0] is not None and center[1] is not None

        # まずは仕様通り、前後がそろう最大offsetを使う。
        for offset in range(RADAR_TRAJECTORY_WINDOW_FRAMES, 0, -1):
            before = self.framePosition(frame_index - offset, prefer_feature=prefer_feature_lookup)
            after = self.framePosition(frame_index + offset, prefer_feature=prefer_feature_lookup)
            if before[0] is None or before[1] is None or after[0] is None or after[1] is None:
                continue

            dx, dy = self.localVectorMeters(before[0], before[1], after[0], after[1])
            distance_m = math.hypot(dx, dy)
            return self.headingFromVector(dx, dy), distance_m

        if not has_center:
            return None, None

        # 端部では中心から片側だけを使い、方向が完全に欠落することを避ける。
        center_lat, center_lon, _feature = center
        for offset in range(RADAR_TRAJECTORY_WINDOW_FRAMES, 0, -1):
            after = self.framePosition(frame_index + offset, prefer_feature=prefer_feature_lookup)
            if after[0] is not None and after[1] is not None:
                dx, dy = self.localVectorMeters(center_lat, center_lon, after[0], after[1])
                distance_m = math.hypot(dx, dy)
                return self.headingFromVector(dx, dy), distance_m

            before = self.framePosition(frame_index - offset, prefer_feature=prefer_feature_lookup)
            if before[0] is not None and before[1] is not None:
                dx, dy = self.localVectorMeters(before[0], before[1], center_lat, center_lon)
                distance_m = math.hypot(dx, dy)
                return self.headingFromVector(dx, dy), distance_m

        return None, None

    def radarHeadingAndRadius(self, frame_index):
        """フォールバックを含めた最終headingと扇形奥行きを決定する。"""
        frame_index = int(frame_index)
        computed_heading, distance_m = self.trajectoryHeadingAndDistance(frame_index)
        previous_heading = getattr(self, "last_radar_heading", None)
        previous_frame_index = getattr(self, "last_radar_frame_index", None)
        frame_is_near_previous = (
            previous_frame_index is not None
            and abs(frame_index - int(previous_frame_index)) <= RADAR_TRAJECTORY_WINDOW_FRAMES
        )

        if computed_heading is None or distance_m is None:
            heading = previous_heading if previous_heading is not None else 0.0
            radius_m = getattr(self, "last_radar_sector_radius_m", None) or RADAR_MIN_SECTOR_RADIUS_M
            self.last_radar_heading = heading
            self.last_radar_sector_radius_m = radius_m
            self.last_radar_frame_index = frame_index
            return heading, radius_m

        heading = computed_heading
        radius_m = distance_m * self.radarScaleValue()

        # 離れたフレームへジャンプした場合は、本当に方向が変わった可能性が高い。
        heading_is_unstable = (
            frame_is_near_previous
            and previous_heading is not None
            and self.headingDelta(computed_heading, previous_heading) > RADAR_HEADING_JUMP_THRESHOLD_DEG
        )
        distance_is_too_small = distance_m < RADAR_MIN_DISTANCE_M

        if (heading_is_unstable or distance_is_too_small) and previous_heading is not None:
            heading = previous_heading

        if heading_is_unstable or distance_is_too_small:
            radius_m = max(radius_m, RADAR_MIN_SECTOR_RADIUS_M)

        self.last_radar_heading = heading
        self.last_radar_sector_radius_m = radius_m
        self.last_radar_frame_index = frame_index
        return heading, radius_m

    def ensureRadarBands(self):
        """レーダ描画用のRubberBandを必要に応じて生成する。"""
        canvas = self.iface.mapCanvas()
        if self.radar_sector_band is None:
            self.radar_sector_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
            self.radar_sector_band.setColor(QtGui.QColor(255, 180, 0, 180))
            if hasattr(self.radar_sector_band, "setFillColor"):
                self.radar_sector_band.setFillColor(QtGui.QColor(255, 200, 0, 70))
            self.radar_sector_band.setWidth(2)

        if self.radar_circle_band is None:
            self.radar_circle_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
            self.radar_circle_band.setColor(QtGui.QColor(0, 190, 255, 190))
            if hasattr(self.radar_circle_band, "setFillColor"):
                self.radar_circle_band.setFillColor(QtGui.QColor(0, 190, 255, 0))
            self.radar_circle_band.setWidth(1)

        if self.radar_outer_circle_band is None:
            self.radar_outer_circle_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
            self.radar_outer_circle_band.setColor(QtGui.QColor(0, 130, 255, 160))
            if hasattr(self.radar_outer_circle_band, "setFillColor"):
                self.radar_outer_circle_band.setFillColor(QtGui.QColor(0, 130, 255, 0))
            self.radar_outer_circle_band.setWidth(1)

        if self.radar_grid_band is None:
            self.radar_grid_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
            # RADAR_GRID_STEP_Mごとに描く補助線は、主線より薄い色で点線にする。お好みで調整してください。
            # シアン系
            #self.radar_grid_band.setColor(QtGui.QColor(0, 255, 255, 150))
            # マゼンタ系
            #self.radar_grid_band.setColor(QtGui.QColor(255, 80, 255, 150))
            # 白っぽく濃いめ
            self.radar_grid_band.setColor(QtGui.QColor(255, 255, 255, 180))

            #self.radar_grid_band.setColor(QtGui.QColor(150, 255, 72, 125))
            #線幅
            self.radar_grid_band.setWidth(1)
            if hasattr(self.radar_grid_band, "setLineStyle"):
                self.radar_grid_band.setLineStyle(Qt.DotLine)   #破線

        if self.radar_direction_band is None:
            self.radar_direction_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
            self.radar_direction_band.setColor(QtGui.QColor(255, 70, 40, 230))
            self.radar_direction_band.setWidth(3)

        if self.radar_perpendicular_band is None:
            self.radar_perpendicular_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
            self.radar_perpendicular_band.setColor(QtGui.QColor(255, 255, 255, 230))
            self.radar_perpendicular_band.setWidth(2)

        self.ensureRadarTargetQualityBands()

    def ensureRadarTargetQualityBands(self):
        """信頼度ごとのクリック点RubberBandを生成する。"""
        canvas = self.iface.mapCanvas()
        line_bands = getattr(self, "radar_target_quality_line_bands", None)
        point_bands = getattr(self, "radar_target_quality_point_bands", None)
        if not isinstance(line_bands, dict):
            line_bands = {}
            self.radar_target_quality_line_bands = line_bands
        if not isinstance(point_bands, dict):
            point_bands = {}
            self.radar_target_quality_point_bands = point_bands

        colors = {
            "trusted": QtGui.QColor(70, 255, 130, 240),
            "usable": QtGui.QColor(255, 210, 70, 235),
            "far": QtGui.QColor(255, 80, 80, 235),
        }
        for quality in RADAR_TARGET_QUALITY_ORDER:
            color = colors[quality]
            if line_bands.get(quality) is None:
                line_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
                line_band.setColor(color)
                line_band.setWidth(2)
                line_bands[quality] = line_band
            if point_bands.get(quality) is None:
                point_band = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
                point_band.setColor(color)
                point_band.setWidth(5)
                if hasattr(point_band, "setIconSize"):
                    point_band.setIconSize(10)
                point_bands[quality] = point_band

    def setRadarPolygon(self, rubber_band, points):
        """WGS84点列をcanvas CRSへ変換し、ポリゴンRubberBandへ反映する。"""
        transformed = [self.canvasPoint(point.x(), point.y()) for point in points]
        rubber_band.setToGeometry(QgsGeometry.fromPolygonXY([transformed]), None)
        rubber_band.show()

    def setRadarLine(self, rubber_band, points):
        """WGS84点列をcanvas CRSへ変換し、ラインRubberBandへ反映する。"""
        transformed = [self.canvasPoint(point.x(), point.y()) for point in points]
        rubber_band.setToGeometry(QgsGeometry.fromPolylineXY(transformed), None)
        rubber_band.show()

    def setRadarMultiLine(self, rubber_band, line_points):
        """複数のWGS84ラインを1つのRubberBandへ反映する。"""
        if not line_points:
            rubber_band.hide()
            rubber_band.reset(QgsWkbTypes.LineGeometry)
            return
        transformed = [
            [self.canvasPoint(point.x(), point.y()) for point in points]
            for points in line_points
        ]
        rubber_band.setToGeometry(QgsGeometry.fromMultiPolylineXY(transformed), None)
        rubber_band.show()

    def setRadarPoint(self, rubber_band, point):
        """WGS84点をcanvas CRSへ変換し、ポイントRubberBandへ反映する。"""
        transformed = self.canvasPoint(point.x(), point.y())
        rubber_band.setToGeometry(QgsGeometry.fromPointXY(transformed), None)
        rubber_band.show()

    def setRadarMultiPoint(self, rubber_band, points):
        """複数のWGS84点を1つのPoint RubberBandへ反映する。"""
        if not points:
            rubber_band.hide()
            rubber_band.reset(QgsWkbTypes.PointGeometry)
            return
        transformed = [self.canvasPoint(point.x(), point.y()) for point in points]
        rubber_band.setToGeometry(QgsGeometry.fromMultiPointXY(transformed), None)
        rubber_band.show()

    def setRadarQualityTargets(self, center, target_projections):
        """クリック投影点を距離品質ごとのRubberBandへ反映する。"""
        self.ensureRadarTargetQualityBands()
        line_bands = getattr(self, "radar_target_quality_line_bands", {})
        point_bands = getattr(self, "radar_target_quality_point_bands", {})
        projections_by_quality = {quality: [] for quality in RADAR_TARGET_QUALITY_ORDER}
        for projection in target_projections:
            quality = projection.get("quality") or self.targetDistanceQuality(projection.get("distance_m"))
            if quality not in projections_by_quality:
                quality = "far"
            projections_by_quality[quality].append(projection)

        for quality in RADAR_TARGET_QUALITY_ORDER:
            projections = projections_by_quality[quality]
            line_band = line_bands.get(quality)
            point_band = point_bands.get(quality)
            if line_band is not None:
                self.setRadarMultiLine(
                    line_band,
                    [[center, projection["point"]] for projection in projections]
                )
            if point_band is not None:
                self.setRadarMultiPoint(
                    point_band,
                    [projection["point"] for projection in projections]
                )

    def hideRadarTargetBands(self):
        """クリック投影点がない場合、投影点用RubberBandだけを非表示にする。"""
        for attr_name, geometry_type in (
            ("radar_target_line_band", QgsWkbTypes.LineGeometry),
            ("radar_target_point_band", QgsWkbTypes.PointGeometry),
        ):
            rubber_band = getattr(self, attr_name, None)
            if rubber_band is None:
                continue
            try:
                rubber_band.hide()
                rubber_band.reset(geometry_type)
            except Exception:
                pass
        for bands, geometry_type in (
            (getattr(self, "radar_target_quality_line_bands", {}), QgsWkbTypes.LineGeometry),
            (getattr(self, "radar_target_quality_point_bands", {}), QgsWkbTypes.PointGeometry),
        ):
            if not isinstance(bands, dict):
                continue
            for rubber_band in bands.values():
                if rubber_band is None:
                    continue
                try:
                    rubber_band.hide()
                    rubber_band.reset(geometry_type)
                except Exception:
                    pass

    def viewerTargetPayloads(self, state):
        """複数targetがあれば優先し、なければ従来の単一targetを返す。"""
        targets = state.get("targets")
        if isinstance(targets, list):
            payloads = [target for target in targets if isinstance(target, dict)]
            if payloads:
                return payloads
        target = state.get("target")
        return [target] if isinstance(target, dict) else []

    def viewerGroundProjectionCameraHeight(self, state):
        """クリック点の地面交差投影に使う実効カメラ高を返す。"""
        camera_height = _parse_float(state.get("viewer_camera_height_m"))
        if camera_height is None:
            getter = getattr(self, "viewerCameraHeightValue", None)
            camera_height = getter() if callable(getter) else 1.5

        hud_scale = _parse_float(state.get("viewer_hud_height_scale"))
        if hud_scale is None:
            getter = getattr(self, "viewerHudHeightScaleValue", None)
            hud_scale = getter() if callable(getter) else 1.0

        camera_height = max(0.1, min(20.0, float(camera_height)))
        hud_scale = max(0.1, min(5.0, float(hud_scale)))
        return camera_height * hud_scale

    def groundDistanceFromTargetPitch(self, target_pitch, state):
        """球面pitchから地面平面との水平距離を求める。"""
        if target_pitch is None:
            return None
        pitch = float(target_pitch)
        if pitch <= 0.1 or pitch >= 89.9:
            return None
        tangent = math.tan(math.radians(pitch))
        if abs(tangent) < 1e-9:
            return None
        return self.viewerGroundProjectionCameraHeight(state) / tangent

    def groundDistanceFromTargetPayload(self, target):
        """WEBビューアがHUD投影から推定済みの地面距離を返す。"""
        ground_distance_m = _parse_float(target.get("ground_distance_m"))
        if ground_distance_m is None or ground_distance_m <= 0:
            return None
        return ground_distance_m

    def viewerTargetProjection(self, lat, lon, heading, state, target=None):
        """360ビューアでクリックした球面位置を、撮影点周辺の地図点へ投影する。"""
        if target is None:
            target = state.get("target")
        if not isinstance(target, dict):
            return None

        target_yaw = _parse_float(target.get("target_yaw_to_camera_heading"))
        view_yaw = _parse_float(target.get("view_yaw_to_camera_heading"))
        yaw_delta = _parse_float(target.get("yaw_delta_deg"))
        if target_yaw is None:
            state_yaw = _parse_float(state.get("yaw_to_camera_heading")) or 0.0
            if yaw_delta is None:
                return None
            target_yaw = (state_yaw + yaw_delta) % 360.0
        if view_yaw is None:
            state_yaw = _parse_float(state.get("yaw_to_camera_heading")) or 0.0
            view_yaw = state_yaw
        if yaw_delta is None:
            yaw_delta = self.signedAngleDelta(view_yaw, target_yaw)

        view_pitch = _parse_float(target.get("view_pitch"))
        pitch_delta = _parse_float(target.get("pitch_delta_deg"))
        target_pitch = _parse_float(target.get("target_pitch_deg"))
        if target_pitch is None and view_pitch is not None and pitch_delta is not None:
            target_pitch = max(-90.0, min(90.0, view_pitch + pitch_delta))

        view_zoom = _parse_float(target.get("view_zoom"))
        fov = self.viewerFov({"zoom": view_zoom}) if view_zoom is not None else self.viewerFov(state)
        calibrated_forward_distance_m = self.calibratedMarkerDistanceForFov(fov)

        cos_delta = math.cos(math.radians(yaw_delta))
        if abs(cos_delta) < 0.1:
            cos_delta = 0.1 if cos_delta >= 0 else -0.1

        ground_distance_m = self.groundDistanceFromTargetPayload(target)
        if ground_distance_m is None:
            ground_distance_m = self.groundDistanceFromTargetPitch(target_pitch, state)
        if ground_distance_m is not None:
            distance_m = max(RADAR_MIN_SECTOR_RADIUS_M, ground_distance_m)
            forward_distance_m = abs(distance_m * cos_delta)
            projection_name = "ground_plane"
            projected_ground_distance_m = distance_m
        else:
            # pitchが地面交差に使えない場合だけ、従来の垂直平面投影へ戻す。
            distance_m = max(RADAR_MIN_SECTOR_RADIUS_M, calibrated_forward_distance_m / abs(cos_delta))
            forward_distance_m = calibrated_forward_distance_m
            projection_name = target.get("projection") or "center_plane"
            projected_ground_distance_m = None

        target_bearing = _parse_float(target.get("map_bearing_deg"))
        map_target_yaw = _parse_float(target.get("map_target_yaw_to_camera_heading"))
        if target_bearing is None:
            bearing_yaw = map_target_yaw if map_target_yaw is not None else target_yaw
            target_bearing = (heading + self.viewerBearingOffsetForState(heading, state) + bearing_yaw) % 360.0
        point = self.destinationPoint(lat, lon, target_bearing, distance_m)
        quality = self.targetDistanceQuality(distance_m)
        projection = {
            "point": point,
            "bearing": target_bearing,
            "distance_m": distance_m,
            "forward_distance_m": forward_distance_m,
            "yaw_delta_deg": yaw_delta,
            "target_yaw_to_camera_heading": target_yaw,
            "map_target_yaw_to_camera_heading": map_target_yaw,
            "target_pitch_deg": target_pitch,
            "view_yaw_to_camera_heading": view_yaw,
            "view_pitch": view_pitch,
            "view_zoom": view_zoom,
            "projection": projection_name,
            "quality": quality,
        }
        if projected_ground_distance_m is not None:
            projection["ground_distance_m"] = projected_ground_distance_m
        if target.get("id") is not None:
            projection["id"] = target.get("id")
        if target.get("order") is not None:
            projection["order"] = target.get("order")
        for key in ("target_source", "viewer_marker", "candidate_id", "semantic_class", "confidence", "map_bearing_deg", "x_ratio", "y_ratio"):
            if target.get(key) is not None:
                projection[key] = target.get(key)
        return projection

    def viewerTargetProjections(self, lat, lon, heading, state):
        """viewer_session.json内のクリックターゲットをすべて地図投影する。"""
        projections = []
        for target in self.viewerTargetPayloads(state):
            projection = self.viewerTargetProjection(lat, lon, heading, state, target)
            if projection:
                projections.append(projection)
        return projections

    def radarCirclePoints(self, lat, lon, radius_m):
        """指定半径のWGS84円近似点列を返す。"""
        return [
            self.destinationPoint(lat, lon, angle, radius_m)
            for angle in range(0, 361, 8)
        ]

    def radarGridRadii(self, inner_radius_m, outer_radius_m):
        """WEBビューアの1m補助グリッドに対応する地図側半径一覧を返す。"""
        max_radius_m = int(math.floor(max(0.0, float(outer_radius_m))))
        radii = []
        for radius_m in range(1, max_radius_m + 1):
            if abs(radius_m - float(inner_radius_m)) < 0.001:
                continue
            if abs(radius_m - float(outer_radius_m)) < 0.001:
                continue
            radii.append(float(radius_m))

        # 極端に大きいRangeでQGIS描画を重くしないため、補助線だけ上限を設ける。
        return radii[:RADAR_GRID_MAX_RINGS]

    def renderViewerRadar(self, state):
        """ビューア状態をもとに同心円・扇形・方向線を再描画する。"""
        radar_config = self.collectRadarConfig(show_errors=False)
        if radar_config is None:
            self.clearRadar()
            return

        frame_index = self.sessionFrameIndex(state)
        if frame_index is None:
            return

        lat, lon, feature = self.framePosition(frame_index)
        if lat is None or lon is None:
            self.clearRadar()
            return

        self.setCurrentFrame(frame_index)
        fixed_radius_m = radar_config.range_m
        outer_radius_m = fixed_radius_m * 2.0
        heading, _trajectory_radius_m = self.radarHeadingAndRadius(frame_index)
        state = self.persistViewerBearingOffsetForState(heading, state)
        sector_radius_m = self.calibratedMarkerDistance(state)
        bearing = self.viewerBearing(heading, state)
        fov = self.viewerFov(state)
        self.updateRadarCalibrationReadout(fov, sector_radius_m)
        center = QgsPointXY(float(lon), float(lat))

        # Rangeは絶対距離の基準線。扇形の奥行きとは別扱いにする。
        circle_points = self.radarCirclePoints(lat, lon, fixed_radius_m)
        outer_circle_points = self.radarCirclePoints(lat, lon, outer_radius_m)
        grid_lines = [
            self.radarCirclePoints(lat, lon, radius_m)
            for radius_m in self.radarGridRadii(fixed_radius_m, outer_radius_m)
        ]

        start_angle = bearing - (fov / 2.0)
        end_angle = bearing + (fov / 2.0)
        segment_count = max(8, int(fov / 4.0))
        sector_points = [center]
        for index in range(segment_count + 1):
            ratio = index / float(segment_count)
            angle = start_angle + (end_angle - start_angle) * ratio
            sector_points.append(self.destinationPoint(lat, lon, angle, sector_radius_m))
        sector_points.append(center)

        direction_end = self.destinationPoint(lat, lon, bearing, sector_radius_m)
        perpendicular_center = self.destinationPoint(lat, lon, bearing, sector_radius_m)
        perpendicular_half_m = sector_radius_m * 0.3
        perpendicular_start = self.destinationPoint(
            perpendicular_center.y(),
            perpendicular_center.x(),
            bearing - 90.0,
            perpendicular_half_m
        )
        perpendicular_end = self.destinationPoint(
            perpendicular_center.y(),
            perpendicular_center.x(),
            bearing + 90.0,
            perpendicular_half_m
        )
        target_projections = self.viewerTargetProjections(lat, lon, heading, state)
        store_targets = getattr(self, "storeViewerTargetProjections", None)
        if callable(store_targets):
            store_targets(state, lat, lon, target_projections)

        self.ensureRadarBands()
        self.setRadarMultiLine(self.radar_grid_band, grid_lines)
        self.setRadarPolygon(self.radar_circle_band, circle_points)
        self.setRadarPolygon(self.radar_outer_circle_band, outer_circle_points)
        self.setRadarPolygon(self.radar_sector_band, sector_points)
        self.setRadarLine(self.radar_direction_band, [center, direction_end])
        self.setRadarLine(self.radar_perpendicular_band, [perpendicular_start, perpendicular_end])
        if target_projections:
            self.setRadarQualityTargets(center, target_projections)
        else:
            self.hideRadarTargetBands()
        self.updateRadarTargetReadout(target_projections)

    def clearRadar(self):
        """地図上のレーダRubberBandと前回値をすべて破棄する。"""
        canvas = self.iface.mapCanvas()
        band_types = {
            "radar_grid_band": QgsWkbTypes.LineGeometry,
            "radar_circle_band": QgsWkbTypes.PolygonGeometry,
            "radar_outer_circle_band": QgsWkbTypes.PolygonGeometry,
            "radar_sector_band": QgsWkbTypes.PolygonGeometry,
            "radar_direction_band": QgsWkbTypes.LineGeometry,
            "radar_perpendicular_band": QgsWkbTypes.LineGeometry,
            "radar_target_line_band": QgsWkbTypes.LineGeometry,
            "radar_target_point_band": QgsWkbTypes.PointGeometry,
        }
        removed_any = False
        for attr_name, geometry_type in band_types.items():
            rubber_band = getattr(self, attr_name, None)
            if rubber_band is not None:
                # QGISのRubberBandはMapCanvas上のQGraphicsItemなので、
                # 非表示化、形状リセット、sceneからの除去を順に行い描画残りを避ける。
                try:
                    rubber_band.hide()
                except Exception:
                    pass
                try:
                    rubber_band.reset(geometry_type)
                except Exception:
                    pass
                try:
                    scene = rubber_band.scene() or canvas.scene()
                    scene.removeItem(rubber_band)
                except Exception:
                    pass
                if sip is not None:
                    try:
                        sip.delete(rubber_band)
                    except Exception:
                        pass
                setattr(self, attr_name, None)
                removed_any = True
        for dict_name, geometry_type in (
            ("radar_target_quality_line_bands", QgsWkbTypes.LineGeometry),
            ("radar_target_quality_point_bands", QgsWkbTypes.PointGeometry),
        ):
            bands = getattr(self, dict_name, None)
            if not isinstance(bands, dict):
                continue
            for rubber_band in bands.values():
                if rubber_band is None:
                    continue
                try:
                    rubber_band.hide()
                except Exception:
                    pass
                try:
                    rubber_band.reset(geometry_type)
                except Exception:
                    pass
                try:
                    scene = rubber_band.scene() or canvas.scene()
                    scene.removeItem(rubber_band)
                except Exception:
                    pass
                if sip is not None:
                    try:
                        sip.delete(rubber_band)
                    except Exception:
                        pass
                removed_any = True
            setattr(self, dict_name, {})
        self.last_viewer_session_signature = None
        self.last_radar_heading = None
        self.last_radar_sector_radius_m = None
        self.last_radar_frame_index = None
        self.updateRadarTargetReadout(None)
        if removed_any:
            try:
                canvas.scene().update()
                canvas.refresh()
            except Exception:
                pass
