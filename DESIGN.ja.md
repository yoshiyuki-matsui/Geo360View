# GPXVideoProcessor 設計メモ

更新日: 2026-06-02

## 目的

GPXVideoProcessor は、360度MP4動画のフレーム番号と、GPXから得られる撮影位置を同期するためのQGISプラグインです。

主な目的は以下です。

- GPXとMP4からフレーム単位の位置情報を生成する。
- フレームシフトを適用して、映像と位置を同期する。
- 必要に応じてKPマスタCSVへ最近接マッチングする。
- QGIS地図上の撮影点をクリックし、対応する360静止画をブラウザで確認する。
- 既存の地物登録プラグインを邪魔せず、目視確認用の補助ビューアとして動かす。

全フレームの証跡画像を最終出力する処理は、このプラグインではなく別バッチの Exporter で行う想定です。

## 全体構成

```text
GPXVideoProcessor/
├── main.py                      QGISプラグイン本体
├── TenkakuNinja/
│   └── geo_util.py              GPX読込・補間処理
├── 360viewer/
│   ├── app.py                   ローカルHTTPビューア
│   ├── static/viewer.js         ブラウザ側同期処理
│   ├── static/viewer.css        ビューア画面レイアウト
│   ├── static/vendor/krpano/    krpano配置場所
│   ├── viewer_config.json       ビューア既定設定
│   └── requirements.txt         OpenCVのみ
├── metadata.txt                 QGISプラグイン定義
├── README.md
├── DESIGN.md                    英語版設計メモ
└── DESIGN.ja.md                 日本語版設計メモ
```

QGISプラグインとWEBビューアは疎結合です。QGIS側はローカルHTTPサーバを起動し、フレーム移動をHTTP APIで通知します。WEBビューア側は現在のフレームや視線方向をJSONへ書き出します。

## 実行環境

### QGIS

- `metadata.txt` 上の最小QGISバージョンは `3.40`。
- QGIS同梱Python上で動作する。
- 別venvは使わない方針。

### Python依存

必要:

- `cv2` / OpenCV

不要:

- Flask
- pandas
- scipy

360ViewerはFlask非依存です。現在はPython標準ライブラリの `http.server.ThreadingHTTPServer` で動作します。

### krpano

360パノラマ表示には、ライセンス済みの `krpano.js` を以下へ配置します。

```text
GPXVideoProcessor/360viewer/static/vendor/krpano/krpano.js
```

未配置の場合は通常のエクイレクタングラー静止画表示にフォールバックします。

## プラグインメニュー

現在のメニュー/ツールバーは以下です。

- `360ViewerOpen`
- `Start`
- `Exit`

### 360ViewerOpen

ローカルHTTPビューアを起動し、外部ブラウザを開きます。

QGIS環境では `sys.executable` が `qgis.exe` や `qgis-bin.exe` を指す場合があります。そのまま起動するとQGISが二重起動するため、プラグイン側で `python.exe` / `python3.exe` / `python-qgis.bat` を探索して起動します。

### Start

同期処理用のパネルを開きます。あわせて360Viewerが起動済みかどうかをQGISのmessageBarへ表示します。

### Exit

現在の作業セッションを終了します。

実行内容:

- クリックモード解除
- プラグインが起動した360Viewerプロセス停止
- 生成済みメモリレイヤを `tmp.gpkg` に保存
- 生成済みレイヤをQGISから削除
- パネルを閉じる
- プレビューや進捗などの状態をリセット

削除対象は、このプラグインが生成してIDを記録しているレイヤだけです。同名の手作業レイヤは削除しません。

## 基本操作フロー

1. GPXファイルを選択する。
2. MP4動画を選択する。
3. 必要に応じてKP CSVを選択する。
4. KP許容距離とフレームシフト量を指定する。
5. `Process` を実行する。
6. `Video GPX Points` レイヤがQGISに追加される。
7. CSV/JSONが出力される。
8. `Click Current Layer` を有効にする。
9. `Video GPX Points` 上の点をクリックする。
10. ブラウザ側360Viewerが該当フレームを表示する。
11. QGIS側にもプレビューJPEGが保存/表示される。

## フレーム番号の考え方

動画側のフレーム番号を不変キーとして扱います。

- `frame`: 動画上の0始まりフレーム番号
- `source_frame`: シフト適用後に位置情報へ対応させる元フレーム
- `frame_shift`: 指定したシフト量

シフト処理:

```text
source_frame = frame - frame_shift
```

シフトしても `frame` は変えません。OpenCVやffmpegで元MP4から証跡画像を取り出す際のキーになるためです。

## GPX読込

`TenkakuNinja/geo_util.py` がGPXを読み込みます。

対応している時刻例:

- `2025-03-24T13:08:49.000Z`
- `+09:00` 付きISO8601
- `UTC` / `GMT` / `JST` サフィックス
- 一部のコンパクトな日時表現
- 名前空間あり/なしのGPX要素

処理には少なくとも2点以上の時刻付きGPXポイントが必要です。

## KPマッチング

KP CSVは任意です。

緯度経度列は以下のような列名から自動検出します。

- `lat`, `latitude`, `gps_lat`, `y`, `緯度`
- `lon`, `lng`, `longitude`, `gps_lon`, `gps_lng`, `x`, `経度`

KP識別子は以下のような列名から自動検出します。

- `kp`, `kilopost`, `kilo_post`, `name`, `id`, `point`, `測点`, `キロポスト`

処理内容:

- `QgsSpatialIndex` で最近接候補を検索
- `QgsDistanceArea` + WGS84で距離計測
- UIで指定した許容距離以内ならマッチ
- マッチした場合は `aligned_latitude` / `aligned_longitude` をKP座標へ寄せる

例:

- KPが10m間隔
- 許容距離5m

この場合、道路中心のKPへ近い撮影点だけをマッチ対象にできます。

## QGIS生成レイヤ

レイヤ名:

```text
Video GPX Points
```

ジオメトリ:

```text
Point, EPSG:4326
```

フィールド:

- `frame`
- `source_frame`
- `frame_shift`
- `timestamp`
- `latitude`
- `longitude`

`Exit` 時に以下へ保存します。

```text
<output_dir>/tmp.gpkg
```

保存に失敗した場合は、安全側でレイヤ削除を行いません。

## 出力ファイル

標準出力先:

```text
<video_dir>/360view_output
```

主な出力:

```text
<video_stem>_frames.csv
<video_stem>_navigation.json
<video_stem>_matched_frames.csv
tmp.gpkg
viewer_session.json
viewer_cache/
images/
```

### `<video_stem>_frames.csv`

全フレーム同期結果です。

主な列:

- `frame`
- `source_frame`
- `frame_shift`
- `timestamp`
- `latitude`
- `longitude`
- `aligned_latitude`
- `aligned_longitude`
- `kp`
- `kp_distance_m`
- `kp_latitude`
- `kp_longitude`
- `kp_match`

### `<video_stem>_matched_frames.csv`

WEBビューアのPrev/Nextナビゲーション用CSVです。KPマッチング時に生成されます。

最低限必要な列:

```csv
frame_index
```

KPなしでこのCSVが存在しない場合、ブラウザに以下が表示されます。

```text
Matched frames CSV is not found. Prev/Next navigation is disabled.
```

これはPrev/Nextが無効という意味で、QGISクリックによる直接表示には影響しません。

### `viewer_session.json`

WEBビューアの現在状態です。

- `video`
- `frame_index`
- `yaw_to_camera_heading`
- `pitch`
- `zoom`
- `updated_at`

将来的にQGIS側でこのJSONを監視し、地図上に視線方向レーダを描画する想定です。

### `images/frames_******.jpg`

QGIS側プレビュー画像です。

クリックした地物から緯度経度を取得できる場合、GPS EXIFも付与します。これは確認用キャッシュであり、最終証跡画像ではありません。

### `viewer_cache/`

WEBビューア専用の軽量JPEGキャッシュです。

現在の既定値:

```json
{
  "viewer_jpeg_quality": 70,
  "viewer_progressive_jpeg": true,
  "viewer_max_width": 3072
}
```

8Kフレームはブラウザ表示用に縮小してからJPEG化します。QGIS側プレビューや将来の証跡Exporterには影響しません。

## 360Viewer

ローカルサーバ:

```text
http://127.0.0.1:8181
```

主要エンドポイント:

```text
GET  /api/health
GET  /viewer?video=<file.mp4>&frame_index=<frame>
GET  /krpano-scene.xml?video=<file.mp4>&frame_index=<frame>
GET  /frames/<file.mp4>/<frame>.jpg
GET  /api/session/viewer-state
POST /api/session/viewer-state
POST /api/session/navigate
```

ブラウザ側は初回表示後、QGISクリックのたびにページ全体を再読み込みしません。`session.json` をポーリングし、krpanoの `loadpano()` でシーンだけ差し替えます。

## パフォーマンス調整

開発中の体感値:

- 初期状態では8Kフレーム表示に4〜5秒程度。
- JPEG品質70、縮小、キャッシュ、`loadpano()` 化により、おおむね3秒程度まで改善。

現在の主な高速化:

- WEBビューアJPEG品質: `70`
- progressive JPEG有効
- WEBビューア最大幅: `3072`
- WEBビューアJPEGキャッシュ
- QGISクリック時は先にWEBビューアへ通知し、その後QGISプレビュー保存を開始
- フォールバック画像は必要時のみlazy load
- ブラウザ全体リロードではなく `loadpano()` でフレーム切替

追加で検討できる高速化:

- `viewer_max_width` を `2048` へ下げる
- QGIS側プレビュー保存をクリック時は任意にする
- 近傍フレームをプリフェッチする
- QGIS側の `VideoCapture` を毎回開かず保持する
- 証跡画像は別Exporterで一括生成する

## 現時点の制約

- QGISの `Exit` はローカルサーバを止めるが、外部ブラウザのタブ自体は閉じない。
- `matched_frames.csv` はKPマッチング出力がある場合だけ生成される。
- krpanoはライセンス物のため同梱しない。
- `viewer_cache` は目視確認用であり証跡用ではない。
- OpenCVとffmpegで同じフレーム番号が同じ画像になることは、証跡運用前に検証が必要。

## 次の実装候補

- QGIS側で `viewer_session.json` を監視する。
- 現在フレーム位置と `yaw_to_camera_heading` から地図上にレーダ表示する。
- レーダ表示は地物登録プラグインの選択レイヤ・map toolを奪わない方式にする。
- 証跡用Exporterを別途実装する。
- OpenCV/ffmpegのフレーム一致検証をraw pixel hashで行う。
- QGIS Python向け固定wheel配布手順を整備する。
