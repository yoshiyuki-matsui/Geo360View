"""Exercise plugin import and field schemas without legacy Qt6 enum aliases."""

import ast
from enum import IntEnum
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def enum_owner(group, names, scoped):
    values = IntEnum(group, {name: index for index, name in enumerate(names)})
    return SimpleNamespace(**({group: values} if scoped else dict(values.__members__)))


def load_compat(scoped):
    modules = {name: ModuleType(name) for name in (
        "qgis", "qgis.PyQt", "qgis.PyQt.QtCore", "qgis.PyQt.QtWidgets",
        "qgis.core", "qgis.gui",
    )}
    qt = SimpleNamespace()
    for group, names in {
        "FocusReason": ["ActiveWindowFocusReason"],
        "AlignmentFlag": ["AlignCenter"],
        "ItemDataRole": ["DisplayRole", "EditRole", "UserRole"],
        "PenStyle": ["DotLine"],
        "Key": ["Key_Escape", "Key_Left", "Key_Right", "Key_Space"],
        "AspectRatioMode": ["KeepAspectRatio"],
        "KeyboardModifier": ["ShiftModifier"],
        "TransformationMode": ["SmoothTransformation"],
        "TextInteractionFlag": ["TextSelectableByMouse"],
        "TimeSpec": ["UTC"],
        "WindowType": ["WindowStaysOnTopHint"],
    }.items():
        qt.__dict__.update(enum_owner(group, names, scoped).__dict__)
    core = modules["qgis.PyQt.QtCore"]
    core.Qt = qt
    core.QEvent = enum_owner("Type", ["KeyPress"], scoped)
    core.QProcess = enum_owner("ProcessState", ["NotRunning"], scoped)
    core.QMetaType = enum_owner("Type", ["QString", "Int", "Double", "QDateTime"], scoped)
    widgets = modules["qgis.PyQt.QtWidgets"]
    widgets.QMessageBox = enum_owner("StandardButton", ["No", "Yes"], scoped)
    widgets.QSizePolicy = enum_owner("Policy", ["Ignored", "Preferred"], scoped)
    qgis_core = modules["qgis.core"]
    qgis_core.Qgis = enum_owner("GeometryType", ["Point", "Line", "Polygon"], True) if scoped else SimpleNamespace()
    # Qt6 fixture intentionally omits every old QgsWkbTypes geometry alias.
    qgis_core.QgsWkbTypes = SimpleNamespace() if scoped else enum_owner(
        "GeometryType", ["PointGeometry", "LineGeometry", "PolygonGeometry"], False,
    )
    qgis_core.QgsVectorFileWriter = enum_owner("WriterError", ["NoError"], scoped)
    modules["qgis.gui"].QgsMapToolIdentifyFeature = enum_owner(
        "IdentifyMode", ["TopDownStopAtFirst"], scoped,
    )
    spec = importlib.util.spec_from_file_location("qt_compat_under_test", ROOT / "qt_compat.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module, core.QMetaType, qgis_core


class QtCompatibilityTests(unittest.TestCase):
    def test_event_filter_handles_mouse_and_key_events_on_qt6(self):
        module, _, _ = load_compat(True)
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name == "GPXVideoPlugin")
        method = next(node for node in plugin.body if isinstance(node, ast.FunctionDef)
                      and node.name == "eventFilter")

        class BaseFilter:
            def eventFilter(self, watched, event):
                return False

        extracted = ast.Module(body=[ast.ClassDef(
            name="FilterUnderTest", bases=[ast.Name(id="BaseFilter", ctx=ast.Load())],
            keywords=[], body=[method], decorator_list=[],
        )], type_ignores=[])
        namespace = dict(vars(module), BaseFilter=BaseFilter)
        exec(compile(ast.fix_missing_locations(extracted), "main.py", "exec"), namespace)
        target = namespace["FilterUnderTest"]()
        moves = []
        target.frameKeyboardNavigationActive = lambda: True
        target.shouldIgnoreNavigationKeyTarget = lambda: False
        target.navigateRelative = lambda direction, fast: moves.append((direction, fast))
        mouse_event = SimpleNamespace(type=lambda: 999)
        self.assertFalse(target.eventFilter(None, mouse_event))
        key_event = SimpleNamespace(type=lambda: module.QT_EVENT_KEY_PRESS,
                                    key=lambda: module.QT_KEY_LEFT, modifiers=lambda: 0)
        self.assertTrue(target.eventFilter(None, key_event))
        self.assertEqual(moves, [(-1, False)])

    def test_qt6_import_and_geometry_without_legacy_aliases(self):
        module, meta, core = load_compat(True)
        self.assertEqual(module.QT_FIELD_STRING, meta.Type.QString)
        self.assertEqual(module.QT_FIELD_DATETIME, meta.Type.QDateTime)
        self.assertEqual(module.QGIS_WKB_POINT_GEOMETRY, core.Qgis.GeometryType.Point)
        self.assertEqual(module.QGIS_WKB_LINE_GEOMETRY, core.Qgis.GeometryType.Line)
        self.assertEqual(module.QGIS_WKB_POLYGON_GEOMETRY, core.Qgis.GeometryType.Polygon)

    def test_qt5_unscoped_fallback(self):
        module, meta, core = load_compat(False)
        self.assertEqual(module.QT_FIELD_INT, meta.Int)
        self.assertEqual(module.QGIS_WKB_LINE_GEOMETRY, core.QgsWkbTypes.LineGeometry)

    def test_marking_schema_uses_supported_field_types(self):
        module, meta, _ = load_compat(True)
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name)
                                  and target.id == "VIEWER_TARGET_FIELD_DEFS"
                                  for target in node.targets))
        definitions = eval(compile(ast.Expression(assignment.value), "main.py", "eval"), vars(module))
        fields = dict(definitions)
        self.assertEqual(fields["video"], meta.Type.QString)
        self.assertEqual(fields["frame"], meta.Type.Int)
        self.assertEqual(fields["target_yaw"], meta.Type.Double)


if __name__ == "__main__":
    unittest.main()
