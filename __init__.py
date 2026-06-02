from .main import GPXVideoPlugin

def classFactory(iface):
    return GPXVideoPlugin(iface)