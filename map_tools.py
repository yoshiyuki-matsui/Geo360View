from qgis.PyQt import QtGui
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsWkbTypes
from qgis.gui import QgsMapToolIdentifyFeature, QgsRubberBand

from .constants import PLUGIN_TITLE


class FrameIdentifyTool(QgsMapToolIdentifyFeature):
    def __init__(self, canvas, layer, plugin):
        super().__init__(canvas)
        self.canvas = canvas
        self.layer = layer
        self.plugin = plugin
        self.setLayer(layer)
        self.rubber_band = None

    def canvasReleaseEvent(self, event):
        try:
            results = self.identify(
                event.x(),
                event.y(),
                [self.layer],
                QgsMapToolIdentifyFeature.TopDownStopAtFirst
            )
            if not results:
                self.plugin.iface.messageBar().pushWarning(PLUGIN_TITLE, "No frame point found.")
                return

            feature = results[0].mFeature
            frame = feature["frame"]
            if frame is None:
                self.plugin.iface.messageBar().pushWarning(PLUGIN_TITLE, "Clicked feature has no frame value.")
                return

            self.highlightFeature(feature)
            frame_num = int(frame)
            self.plugin.displayFrame(frame_num, feature=feature)
        except Exception as e:
            self.plugin.iface.messageBar().pushWarning(PLUGIN_TITLE, f"Frame click failed: {e}")

    def keyPressEvent(self, event):
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
        self.clearHighlight()
        geom_type = QgsWkbTypes.geometryType(self.layer.wkbType())
        self.rubber_band = QgsRubberBand(self.canvas, geom_type)
        self.rubber_band.setColor(QtGui.QColor(255, 80, 0, 180))
        self.rubber_band.setWidth(3)
        self.rubber_band.setToGeometry(feature.geometry(), self.layer)
        self.rubber_band.show()

    def clearHighlight(self):
        if self.rubber_band:
            self.canvas.scene().removeItem(self.rubber_band)
            self.rubber_band = None

    def deactivate(self):
        self.clearHighlight()
        super().deactivate()
