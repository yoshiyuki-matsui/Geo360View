"""TenkakuNinja Exporterの単体CLI入口。

このファイルを含む `TenkakuNinja` フォルダは、QGISプラグイン外へコピーしても
`python main.py ...` で証跡フレームExporterとして動作する。
"""

try:
    from .exporter import main
except ImportError:
    from exporter import main


if __name__ == "__main__":
    raise SystemExit(main())
