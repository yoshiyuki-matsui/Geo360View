"""QGISがGeo360 Viewプラグインをロードするためのパッケージ入口。"""

from .main import GPXVideoPlugin

def classFactory(iface):
    """QGIS Plugin Managerから呼ばれるファクトリ関数。"""
    return GPXVideoPlugin(iface)
