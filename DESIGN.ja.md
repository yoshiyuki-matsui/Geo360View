# Geo360 View 設計メモ

更新日: 2026-09-04

## 目的

Geo360 View は、MP4動画とGPX軌跡を同期し、QGIS地図上の撮影点から該当フレームを確認するための軽量QGISプラグインです。

公開版の範囲は、動画と位置情報の同期、撮影点レイヤ生成、任意の参照点CSVとの最近接マッチング、ブラウザビューアでの目視確認に限定します。自動物体検出、POI生成、semantic clustering、モデルレビュー機能は本リポジトリの対象外です。

## 全体構成

```text
Geo360View/
├── main.py                      QGISプラグインUI/全体制御
├── constants.py                 プラグイン共通定数
├── config.py                    UI入力Configと純Python validation
├── common.py                    CSV/文字列/日時などの共通ヘルパー
├── processor.py                 GPXとMP4からフレーム位置を生成するQThread
├── viewer_controller.py         360Viewer起動・HTTP連携・QProcess制御
├── frame_extract.py             静止画抽出・EXIF付与・QGISプレビュー表示
├── map_tools.py                 地図クリック用MapTool
├── messages.py                  ユーザ向けメッセージテンプレートとlocale切替
├── radar.py                     viewer_session.json監視とレーダ描画
├── kp.py                        参照点CSV読込・最近接マッチング
├── exif_utils.py                JPEG EXIF生成
├── TenkakuNinja/
│   └── geo_util.py              GPX読込・補間処理
├── 360viewer/
│   ├── app.py                   ローカルHTTPビューア
│   ├── static/viewer.js         krpano互換ビューア制御
│   ├── static/psv_viewer.js     Photo Sphere Viewer制御
│   ├── static/viewer.css        ビューア画面レイアウト
│   ├── static/vendor/           ローカルvendor配置
│   ├── viewer_config.json       ビューア既定設定
│   └── requirements.txt         ビューア側依存
├── docs/                        手動確認・運用メモ
├── tests/                       QGIS非依存ユニットテスト
├── metadata.txt                 QGISプラグイン定義
├── CHANGELOG.md                 主要変更履歴
└── README.md
```

QGIS側とブラウザビューアは疎結合です。QGIS側はローカルHTTPサーバを起動し、フレーム移動をHTTP APIで通知します。ビューア側は現在フレーム、視線方向、HUD状態を `viewer_session.json` に書き出し、QGIS側がそれを読んで地図上の一時レーダを更新します。

## 主な処理

1. ユーザがMP4、GPX、任意の参照点CSV、出力先を指定する。
2. OpenCVで動画FPS/フレーム数を読み取る。
3. GPX時刻を動画フレームへ補間する。
4. 必要に応じてフレームシフトを適用する。
5. QGIS上に `Video GPX Points` レイヤを作成する。
6. 任意で参照点CSVと最近接マッチングし、ナビゲーションCSVを出力する。
7. 撮影点クリックまたはナビゲーション操作で該当フレームをブラウザビューアへ表示する。

## ビューア

ビューアは `engine` 指定で切り替えます。

- `psv`: Photo Sphere Viewer + MarkersPlugin。公開版の主経路。
- `krpano`: 既存互換確認用のローカル経路。配布時はkrpanoライセンスに従って扱います。

Photo Sphere Viewer経路は、既存の画像キャッシュ、HTTP API、`viewer_session.json` を再利用します。QGIS側から見たpayloadの意味を変えず、ブラウザ側でPhoto Sphere Viewerの座標系へ変換します。

## 投影

動画は以下のどちらかとして扱います。

- `sphere`: 360度/equirectangular画像。
- `flat`: 通常画角画像。

MP4の縦横比から初期候補を提示し、ユーザが手動で上書きできます。`flat` の場合はPhoto Sphere Viewerへパノラマとして渡さず、同じビューア画面内の2D fallbackで表示します。

## 公開版の境界

Geo360 Viewでは以下を扱いません。

- 自動物体検出。
- YOLO/RF-DETRなどのモデル実行。
- POI候補生成、集約、管理。
- semantic classに基づく候補レイヤ表示。
- モデル比較・検出結果レビュー。

これらは内部開発版または別製品側で扱います。
