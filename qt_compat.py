"""Qt5/Qt6で移動したenum値を吸収する互換定義。"""

from qgis.PyQt.QtCore import QEvent, QMetaType, QProcess, Qt
from qgis.PyQt.QtWidgets import QMessageBox, QSizePolicy
from qgis.core import Qgis, QgsVectorFileWriter, QgsWkbTypes
from qgis.gui import QgsMapToolIdentifyFeature


def qt_enum(group_name, name):
    """Qt6のenum groupを優先し、Qt5のQt直下定義へフォールバックする。"""
    group = getattr(Qt, group_name, None)
    if group is not None:
        value = getattr(group, name, None)
        if value is not None:
            return value
    return getattr(Qt, name)


def widget_enum(widget_class, group_name, name):
    """Qt6のWidgets enum groupを優先し、Qt5のclass直下定義へフォールバックする。"""
    group = getattr(widget_class, group_name, None)
    if group is not None:
        value = getattr(group, name, None)
        if value is not None:
            return value
    return getattr(widget_class, name)


def object_enum(owner, group_name, name):
    """Qt6/QGIS4形式のenum groupを優先し、Qt5/QGIS3の直下定義へフォールバックする。"""
    group = getattr(owner, group_name, None)
    if group is not None:
        value = getattr(group, name, None)
        if value is not None:
            return value
    return getattr(owner, name)


def geometry_enum(name):
    """Qgis.GeometryTypeを優先し、旧QgsWkbTypesへフォールバックする。"""
    group = getattr(Qgis, "GeometryType", None)
    if group is not None:
        return getattr(group, name)
    return object_enum(QgsWkbTypes, "GeometryType", name + "Geometry")


QT_FIELD_STRING = object_enum(QMetaType, "Type", "QString")
QT_FIELD_INT = object_enum(QMetaType, "Type", "Int")
QT_FIELD_DOUBLE = object_enum(QMetaType, "Type", "Double")
QT_FIELD_DATETIME = object_enum(QMetaType, "Type", "QDateTime")


QT_ACTIVE_WINDOW_FOCUS_REASON = qt_enum("FocusReason", "ActiveWindowFocusReason")
QT_ALIGN_CENTER = qt_enum("AlignmentFlag", "AlignCenter")
QT_DISPLAY_ROLE = qt_enum("ItemDataRole", "DisplayRole")
QT_DOT_LINE = qt_enum("PenStyle", "DotLine")
QT_EDIT_ROLE = qt_enum("ItemDataRole", "EditRole")
QT_KEY_ESCAPE = qt_enum("Key", "Key_Escape")
QT_KEY_LEFT = qt_enum("Key", "Key_Left")
QT_KEY_RIGHT = qt_enum("Key", "Key_Right")
QT_KEY_SPACE = qt_enum("Key", "Key_Space")
QT_KEEP_ASPECT_RATIO = qt_enum("AspectRatioMode", "KeepAspectRatio")
QT_SHIFT_MODIFIER = qt_enum("KeyboardModifier", "ShiftModifier")
QT_SMOOTH_TRANSFORMATION = qt_enum("TransformationMode", "SmoothTransformation")
QT_TEXT_SELECTABLE_BY_MOUSE = qt_enum("TextInteractionFlag", "TextSelectableByMouse")
QT_UTC = qt_enum("TimeSpec", "UTC")
QT_USER_ROLE = qt_enum("ItemDataRole", "UserRole")
QT_WINDOW_STAYS_ON_TOP_HINT = qt_enum("WindowType", "WindowStaysOnTopHint")

QT_EVENT_KEY_PRESS = object_enum(QEvent, "Type", "KeyPress")
QT_MESSAGE_BOX_NO = widget_enum(QMessageBox, "StandardButton", "No")
QT_MESSAGE_BOX_YES = widget_enum(QMessageBox, "StandardButton", "Yes")
QT_PROCESS_NOT_RUNNING = object_enum(QProcess, "ProcessState", "NotRunning")
QT_SIZE_POLICY_IGNORED = widget_enum(QSizePolicy, "Policy", "Ignored")
QT_SIZE_POLICY_PREFERRED = widget_enum(QSizePolicy, "Policy", "Preferred")

QGIS_IDENTIFY_TOP_DOWN_STOP_AT_FIRST = object_enum(
    QgsMapToolIdentifyFeature,
    "IdentifyMode",
    "TopDownStopAtFirst",
)
QGIS_WKB_LINE_GEOMETRY = geometry_enum("Line")
QGIS_WKB_POINT_GEOMETRY = geometry_enum("Point")
QGIS_WKB_POLYGON_GEOMETRY = geometry_enum("Polygon")
QGIS_VECTOR_WRITER_NO_ERROR = object_enum(QgsVectorFileWriter, "WriterError", "NoError")
