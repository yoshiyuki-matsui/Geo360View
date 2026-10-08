"""Map-click regressions without requiring a QGIS installation."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


def load_map_tools():
    package = ModuleType("map_tools_test_package")
    package.__path__ = []
    qt_gui = ModuleType("qgis.PyQt")
    qt_gui.QtGui = SimpleNamespace()
    core = ModuleType("qgis.core")
    core.QgsWkbTypes = SimpleNamespace()
    gui = ModuleType("qgis.gui")
    gui.QgsMapToolIdentifyFeature = type("IdentifyBase", (), {
        "__init__": lambda self, canvas: None,
        "setLayer": lambda self, layer: None,
    })
    gui.QgsRubberBand = Mock()
    compat = ModuleType("map_tools_test_package.qt_compat")
    for index, name in enumerate((
        "QGIS_IDENTIFY_TOP_DOWN_STOP_AT_FIRST", "QT_KEY_ESCAPE", "QT_KEY_LEFT",
        "QT_KEY_RIGHT", "QT_KEY_SPACE", "QT_SHIFT_MODIFIER",
    )):
        setattr(compat, name, index)
    path = Path(__file__).resolve().parents[1] / "map_tools.py"
    spec = importlib.util.spec_from_file_location("map_tools_test_package.map_tools", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "map_tools_test_package": package,
        "map_tools_test_package.qt_compat": compat,
        "qgis": ModuleType("qgis"), "qgis.PyQt": qt_gui,
        "qgis.core": core, "qgis.gui": gui,
    }):
        spec.loader.exec_module(module)
    return module


class FrameIdentifyToolTests(unittest.TestCase):
    def setUp(self):
        self.module = load_map_tools()
        self.plugin = Mock()
        self.layer = object()
        self.tool = self.module.FrameIdentifyTool(object(), self.layer, self.plugin)
        self.tool.highlightFeature = Mock()
        # QgsMapMouseEvent in Qt6 has no x()/y() shortcuts. The integer point
        # supplies unsnapped screen coordinates; map coordinates are irrelevant.
        self.event = SimpleNamespace(originalPixelPoint=lambda: SimpleNamespace(
            x=lambda: 123, y=lambda: 456,
        ))

    def test_qt6_map_click_displays_identified_frame(self):
        feature = {"frame": "42"}
        self.tool.identify = Mock(return_value=[SimpleNamespace(mFeature=feature)])
        self.tool.canvasReleaseEvent(self.event)
        self.tool.identify.assert_called_once_with(
            123, 456, [self.layer], self.module.QGIS_IDENTIFY_TOP_DOWN_STOP_AT_FIRST,
        )
        self.tool.highlightFeature.assert_called_once_with(feature)
        self.plugin.displayFrame.assert_called_once_with(42, feature=feature)
        self.plugin.notifyWarning.assert_not_called()

    def test_empty_click_warns_without_extracting_frame(self):
        self.tool.identify = Mock(return_value=[])
        self.tool.canvasReleaseEvent(self.event)
        self.plugin.notifyWarning.assert_called_once_with("no_frame_point_found")
        self.plugin.displayFrame.assert_not_called()

    def test_missing_frame_warns_without_highlight(self):
        self.tool.identify = Mock(return_value=[SimpleNamespace(mFeature={"frame": None})])
        self.tool.canvasReleaseEvent(self.event)
        self.plugin.notifyWarning.assert_called_once_with("selected_layer_no_frame")
        self.tool.highlightFeature.assert_not_called()
        self.plugin.displayFrame.assert_not_called()


if __name__ == "__main__":
    unittest.main()
