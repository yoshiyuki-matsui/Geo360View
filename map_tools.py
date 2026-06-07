"""QGIS地図クリックでフレームを選択するMapTool。"""

from qgis.PyQt import QtGui
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsWkbTypes
from qgis.gui import QgsMapToolIdentifyFeature, QgsRubberBand

class FrameIdentifyTool(QgsMapToolIdentifyFeature):
    """`Video GPX Points` をクリックし、対応フレームをプラグインへ通知する。"""

    def __init__(self, canvas, layer, plugin):
        """対象canvas/layerと呼び戻し先pluginを保持する。"""
        super().__init__(canvas)
        self.canvas = canvas
        self.layer = layer
        self.plugin = plugin
        self.setLayer(layer)
        self.rubber_band = None

    def canvasReleaseEvent(self, event):
        """クリック位置の最前面フレーム点を検索し、ビューア表示を更新する。"""
        try:
            results = self.identify(
                event.x(),
                event.y(),
                [self.layer],
                QgsMapToolIdentifyFeature.TopDownStopAtFirst
            )
            if not results:
                self.plugin.notifyWarning("no_frame_point_found")
                return

            feature = results[0].mFeature
            frame = feature["frame"]
            if frame is None:
                self.plugin.notifyWarning("selected_layer_no_frame")
                return

            self.highlightFeature(feature)
            frame_num = int(frame)
            self.plugin.displayFrame(frame_num, feature=feature)
        except Exception as e:
            self.plugin.notifyWarning("frame_extract_failed", error=e)

    def keyPressEvent(self, event):
        """クリックモード中のキーボードナビゲーションを処理する。"""
        if event.key() == Qt.Key_Escape:
            self.plugin.deactivateClickMode()
            return
        if event.key() == Qt.Key_Left:
            self.plugin.navigateRelative(-1, fast=bool(event.modifiers() & Qt.ShiftModifier))
            return
        if event.key() == Qt.Key_Right:
            self.plugin.navigateRelative(1, fast=bool(event.modifiers() & Qt.ShiftModifier))
            return
        if event.key() == Qt.Key_Space:
            self.plugin.displayCurrentFrame()
            return

    def highlightFeature(self, feature):
        """クリックまたはナビゲーションで選ばれた点を一時強調表示する。"""
        self.clearHighlight()
        geom_type = QgsWkbTypes.geometryType(self.layer.wkbType())
        self.rubber_band = QgsRubberBand(self.canvas, geom_type)
        self.rubber_band.setColor(QtGui.QColor(255, 80, 0, 180))
        self.rubber_band.setWidth(3)
        self.rubber_band.setToGeometry(feature.geometry(), self.layer)
        self.rubber_band.show()

    def clearHighlight(self):
        """既存の一時強調表示を削除する。"""
        if self.rubber_band:
            self.canvas.scene().removeItem(self.rubber_band)
            self.rubber_band = None

    def deactivate(self):
        """QGISのmap tool解除時に強調表示も確実に消す。"""
        self.clearHighlight()
        super().deactivate()
