# 依存関係・ライセンス確認メモ

作成日: 2026-09-07

Geo360Viewを公開リポジトリまたはQGIS Plugin Repositoryへ出す前の、依存関係と同梱OSSの確認メモです。

## Python実行時依存

### QGIS / PyQt

- 種別: QGISプラグイン実行環境
- 利用箇所: `qgis.core`, `qgis.gui`, `qgis.PyQt`
- 配布形態: Geo360Viewには同梱しない。ユーザのQGIS環境に依存する。
- 備考: QGIS Plugin Repositoryへ登録する場合、プラグインのライセンスはGPLv2 or later互換であることが要求される。

### OpenCV

- 種別: Python外部依存
- requirements: `360viewer/requirements.txt`
- 現在指定: `opencv-python>=4.8`
- 利用箇所:
  - 動画FPS/フレーム数の取得
  - 指定フレームの抽出
  - JPEGエンコード
  - 通常画角/360画像のビューア用キャッシュ生成
- 配布形態: Geo360Viewには同梱しない。ユーザのQGIS Pythonへ別途導入する。
- ライセンス: OpenCV 4.5.0以降はApache License 2.0。

### Python標準ライブラリ

追加インストール不要です。主な利用モジュールは以下です。

- `csv`
- `datetime`
- `http.server`
- `json`
- `math`
- `mimetypes`
- `os`
- `pathlib`
- `re`
- `sqlite3`
- `struct`
- `threading` 系は現状直接利用なし
- `time`
- `urllib`
- `uuid`
- `xml.etree.ElementTree`
- `xml.sax.saxutils`

## ブラウザ側同梱OSS

### Photo Sphere Viewer

- 同梱場所: `360viewer/static/vendor/photo-sphere-viewer/core/`
- バージョン: `5.15.1`
- ライセンス: MIT
- 用途: 360/equirectangular画像の表示
- 備考: `LICENSE` と `package.json` を同梱済み。

### Photo Sphere Viewer MarkersPlugin

- 同梱場所: `360viewer/static/vendor/photo-sphere-viewer/markers-plugin/`
- バージョン: `5.15.1`
- ライセンス: MIT
- 用途: ターゲットマーカー、ラベル等の表示
- 備考: `LICENSE` と `package.json` を同梱済み。

### three.js

- 同梱場所: `360viewer/static/vendor/photo-sphere-viewer/three/`
- バージョン: `0.185.1`
- ライセンス: MIT
- 用途: Photo Sphere Viewerの描画基盤
- 備考: `LICENSE` と `package.json` を同梱済み。`three.module.js` が `./three.core.js` をimportするため、両方を同じ階層に置く必要がある。

## krpano

- 現在の配置: 公開リポジトリからは削除済み。
- ローカル配置候補: `360viewer/static/vendor/krpano/`
- 用途: 既存互換確認用のローカルビューア経路
- 注意点:
  - krpanoは商用ライセンス製品であり、Geo360Viewの公開配布物へ同梱しない方針が安全。
  - QGIS Plugin Repositoryはバイナリ同梱を避ける要求があるため、`.swf` などを公開パッケージへ含めない。
  - 公開版ではPhoto Sphere Viewerを主経路にし、krpanoは「各ユーザがライセンスに従ってローカル配置する任意経路」として文書化するのがよい。

## 現時点のrequirements評価

`360viewer/requirements.txt` の `opencv-python>=4.8` だけで、Python外部依存としては概ね足りています。

ただし、公開向けには次の補足が必要です。

- QGIS本体とQGIS Python/PyQtは前提環境であり、pip依存ではないことをREADMEに明記する。
- OpenCVをQGIS Pythonへ入れる必要があることを、Windows向けに特に明記する。
- Photo Sphere Viewer/threeはnpm実行時依存ではなく、同梱済みvendorファイルとして扱うことを明記する。
- krpanoは同梱しない。ローカル利用する場合は、ユーザがライセンスに従って配置する。

## ライセンス上の要確認事項

### プラグイン本体ライセンス

現在の方針は `GPL-2.0-or-later` です。`metadata.txt` の `license` も同じ値に揃えます。

QGIS Plugin Repositoryの公開要件には、プラグインライセンスがGPLv2 or later互換であることが含まれます。Geo360ViewはQGISプラグインとしての配布を見据え、プラグイン本体をGPL-2.0-or-laterへ変更します。

Apache License 2.0はGPLv3とは互換ですが、GPLv2-onlyとは互換ではないため、QGIS公式リポジトリ向けのプラグイン本体ライセンスとしては採用しません。

商用・特許関連機能は、公開版Geo360Viewへ含めず、GPXVideoProcessor側または別サービス側で扱います。

### 同梱OSSのNOTICE

MITライセンスのPhoto Sphere Viewer、MarkersPlugin、three.jsは、著作権表示とライセンス文を保持する必要があります。現状は各vendorディレクトリに `LICENSE` があるため、公開パッケージ作成時にこれらを削除しないことが必要です。

## 公開前TODO

- `360viewer/static/vendor/krpano/` が公開パッケージへ入らないことを確認する。
- `README.md` にOpenCV導入、QGIS前提、Photo Sphere Viewer同梱、krpano非同梱方針を追記する。
- `metadata.txt` の `about`, `homepage`, `tracker`, `repository` を公開方針に合わせて見直す。
