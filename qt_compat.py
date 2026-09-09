"""Qt5/Qt6で移動したenum値を吸収する互換定義。"""

from qgis.PyQt.QtCore import Qt


def qt_enum(group_name, name):
    """Qt6のenum groupを優先し、Qt5のQt直下定義へフォールバックする。"""
    group = getattr(Qt, group_name, None)
    if group is not None:
        value = getattr(group, name, None)
        if value is not None:
            return value
    return getattr(Qt, name)


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
QT_USER_ROLE = qt_enum("ItemDataRole", "UserRole")
QT_WINDOW_STAYS_ON_TOP_HINT = qt_enum("WindowType", "WindowStaysOnTopHint")
