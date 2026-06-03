import json
import math
import os

from qgis.PyQt import QtGui
from qgis.PyQt.QtCore import QTimer
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


class RadarMixin:
    def startViewerSessionPolling(self):
        if self.viewer_session_timer is None:
            self.viewer_session_timer = QTimer(self)
            self.viewer_session_timer.timeout.connect(self.pollViewerSession)
        if not self.viewer_session_timer.isActive():
            self.viewer_session_timer.start(500)

    def stopViewerSessionPolling(self):
        if self.viewer_session_timer is not None and self.viewer_session_timer.isActive():
            self.viewer_session_timer.stop()

    def pollViewerSession(self):
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

        yaw = _parse_float(state.get("yaw_to_camera_heading"))
        pitch = _parse_float(state.get("pitch"))
        zoom = _parse_float(state.get("zoom"))
        signature = (
            state.get("video"),
            frame_index,
            round(yaw or 0.0, 3),
            round(pitch or 0.0, 3),
            round(zoom or 1.0, 3),
            state.get("updated_at"),
        )
        if signature == self.last_viewer_session_signature:
            return

        self.last_viewer_session_signature = signature
        try:
            self.renderViewerRadar(state)
        except Exception as e:
            print(f"Viewer radar update failed: {e}")

    def sessionFrameIndex(self, state):
        value = _parse_float(state.get("frame_index"))
        if value is None:
            return None
        return int(value)

    def framePosition(self, frame_num):
        feature = self.findFeatureByFrame(frame_num)
        if feature is not None:
            gps = self.featureGps(feature)
            if gps:
                return gps["lat"], gps["lon"], feature

        target = int(frame_num)
        for row in self.last_rows:
            try:
                frame_value, _source_frame, _time_value, lat, lon = row
            except ValueError:
                continue
            if int(frame_value) == target:
                return float(lat), float(lon), None

        return None, None, None

    def cameraHeadingForFeature(self, feature):
        if feature is None:
            return None

        for field_name in ("camera_heading", "heading", "direction", "bearing", "azimuth", "yaw"):
            if feature.fields().indexFromName(field_name) < 0:
                continue
            value = _parse_float(feature[field_name])
            if value is not None:
                return value % 360.0
        return None

    def viewerBearing(self, state, feature=None):
        yaw = _parse_float(state.get("yaw_to_camera_heading"))
        yaw = (yaw or 0.0) % 360.0
        camera_heading = self.cameraHeadingForFeature(feature)
        if camera_heading is None:
            return yaw
        return (camera_heading + yaw) % 360.0

    def viewerFov(self, state):
        zoom = _parse_float(state.get("zoom"))
        zoom = max(zoom or 1.0, 0.01)
        return max(1.0, min(179.0, 90.0 / zoom))

    def destinationPoint(self, lat, lon, bearing_deg, distance_m):
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

    def ensureRadarBands(self):
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
                self.radar_circle_band.setFillColor(QtGui.QColor(0, 190, 255, 20))
            self.radar_circle_band.setWidth(1)

        if self.radar_direction_band is None:
            self.radar_direction_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
            self.radar_direction_band.setColor(QtGui.QColor(255, 70, 40, 230))
            self.radar_direction_band.setWidth(3)

        if self.radar_perpendicular_band is None:
            self.radar_perpendicular_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
            self.radar_perpendicular_band.setColor(QtGui.QColor(255, 255, 255, 230))
            self.radar_perpendicular_band.setWidth(2)

    def setRadarPolygon(self, rubber_band, points):
        transformed = [self.canvasPoint(point.x(), point.y()) for point in points]
        rubber_band.setToGeometry(QgsGeometry.fromPolygonXY([transformed]), None)
        rubber_band.show()

    def setRadarLine(self, rubber_band, points):
        transformed = [self.canvasPoint(point.x(), point.y()) for point in points]
        rubber_band.setToGeometry(QgsGeometry.fromPolylineXY(transformed), None)
        rubber_band.show()

    def renderViewerRadar(self, state):
        frame_index = self.sessionFrameIndex(state)
        if frame_index is None:
            return

        lat, lon, feature = self.framePosition(frame_index)
        if lat is None or lon is None:
            self.clearRadar()
            return

        self.setCurrentFrame(frame_index)
        radius_m = float(self.radar_radius.value())
        bearing = self.viewerBearing(state, feature=feature)
        fov = self.viewerFov(state)
        center = QgsPointXY(float(lon), float(lat))

        circle_points = [
            self.destinationPoint(lat, lon, angle, radius_m)
            for angle in range(0, 361, 8)
        ]

        start_angle = bearing - (fov / 2.0)
        end_angle = bearing + (fov / 2.0)
        segment_count = max(8, int(fov / 4.0))
        sector_points = [center]
        for index in range(segment_count + 1):
            ratio = index / float(segment_count)
            angle = start_angle + (end_angle - start_angle) * ratio
            sector_points.append(self.destinationPoint(lat, lon, angle, radius_m))
        sector_points.append(center)

        direction_end = self.destinationPoint(lat, lon, bearing, radius_m)
        perpendicular_center = self.destinationPoint(lat, lon, bearing, radius_m)
        perpendicular_half_m = radius_m * 0.3
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

        self.ensureRadarBands()
        self.setRadarPolygon(self.radar_circle_band, circle_points)
        self.setRadarPolygon(self.radar_sector_band, sector_points)
        self.setRadarLine(self.radar_direction_band, [center, direction_end])
        self.setRadarLine(self.radar_perpendicular_band, [perpendicular_start, perpendicular_end])

    def clearRadar(self):
        canvas = self.iface.mapCanvas()
        for attr_name in (
            "radar_circle_band",
            "radar_sector_band",
            "radar_direction_band",
            "radar_perpendicular_band",
        ):
            rubber_band = getattr(self, attr_name, None)
            if rubber_band is not None:
                try:
                    canvas.scene().removeItem(rubber_band)
                except Exception:
                    pass
                setattr(self, attr_name, None)
        self.last_viewer_session_signature = None
