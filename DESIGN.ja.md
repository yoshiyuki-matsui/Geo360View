# GPXVideoProcessor 設計メモ

更新日: 2026-06-04

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
├── main.py                      QGISプラグインUI/全体制御
├── constants.py                 プラグイン共通定数
├── common.py                    CSV/文字列/日時などの共通ヘルパー
├── processor.py                 GPXとMP4からフレーム位置を生成するQThread
├── viewer_controller.py         360Viewer起動・HTTP連携・QProcess制御
├── frame_extract.py             静止画抽出・EXIF付与・QGISプレビュー表示
├── map_tools.py                 地図クリック用MapTool
├── radar.py                     viewer_session.json監視とレーダ描画
├── exporter.py                  TenkakuNinja Exporter互換CLIラッパー
├── kp.py                        KP CSV読込・最近接マッチング
├── exif_utils.py                JPEG EXIF生成
├── TenkakuNinja/
│   ├── main.py                  単体Exporter CLI入口
│   ├── exporter.py              GeoPackage条件指定型の証跡フレームExporter
│   ├── requirements.txt         単体Exporter用依存関係
│   ├── README.md                単体Exporter利用方法
│   └── geo_util.py              GPX読込・補間処理
├── 360viewer/
│   ├── app.py                   ローカルHTTPビューア
│   ├── static/viewer.js         ブラウザ側同期処理
│   ├── static/viewer.css        ビューア画面レイアウト
│   ├── static/vendor/krpano/    krpano配置場所
│   ├── viewer_config.json       ビューア既定設定
│   └── requirements.txt         OpenCVのみ
├── docs/
│   ├── exporter_spec.md         フレーム画像Exporter仕様
│   ├── rader_spec.md            レーダ表示の実寸準拠仕様
│   └── yolo_georeference_spec.md YOLO検出結果の緯度経度化 将来仕様メモ
├── metadata.txt                 QGISプラグイン定義
├── README.md
├── DESIGN.md                    英語版設計メモ
└── DESIGN.ja.md                 日本語版設計メモ
```

QGISプラグインとWEBビューアは疎結合です。QGIS側はローカルHTTPサーバを起動し、フレーム移動をHTTP APIで通知します。WEBビューア側は現在のフレームや視線方向をJSONへ書き出します。

## Pythonモジュール分割方針

`main.py` はQGISプラグインのエントリポイント、メニュー、パネルUI、全体の状態管理を担当します。肥大化を避けるため、機能単位で比較的大きなまとまりを別モジュールへ分離しています。

現在の主な責務分担:

- `processor.py`: GPXと動画FPSから全フレーム位置を生成するバックグラウンド処理。
- `kp.py`: KP CSVの列自動判定、空間インデックス、許容距離内の最近接マッチング。
- `viewer_controller.py`: 360Viewerの設定ファイル生成、QProcess起動/停止、HTTPヘルスチェック、ブラウザ起動。
- `frame_extract.py`: OpenCVによる単一フレーム抽出、JPEG/EXIF保存、QGISパネル内プレビュー表示。
- `radar.py`: `viewer_session.json` のポーリング、視線方向の計算、QGIS地図上の一時レーダ描画。
- `map_tools.py`: `Video GPX Points` の地図クリック待ち受け、ハイライト、キーボードナビゲーション。
- `common.py`: ファイル名、CSV、数値、日時などの共通ヘルパー。
- `constants.py`: プラグイン名や出力ファイル接尾辞などの共通定数。
- `exif_utils.py`: JPEG EXIFセグメント生成と挿入。

細かすぎる分割は避け、処理の流れを `main.py` から追える状態を維持します。QGIS GUIに強く依存する配置やボタン接続は `main.py` 側に残し、外部プロセス制御、画像生成、レーダ描画のように機能境界が明確なものだけをMixin/補助モジュールへ分けています。

## 現在の実装・確認状況

2026-06-04時点で、以下を実装・動作確認済みです。

- 非標準GPXの時刻を読み取り、MP4フレームへ位置情報を補間できる。
- フレーム番号を不変キーとして扱い、指定フレーム数のシフトを反映できる。
- KP CSVを指定した場合、許容距離内の最近接KPへマッチングし、結果CSVを出力できる。
- `360ViewerOpen` でQGISからローカルWEBビューアを起動できる。
- QGIS地図上の撮影点クリックにより、該当フレームの360画像をブラウザへ表示できる。
- ブラウザ側はフレーム切替時にページ全体を再読み込みせず、krpanoの `loadpano()` で画像を差し替える。
- フレーム切替後も、直前の `yaw_to_camera_heading`, `pitch`, `zoom` を継承できる。
- WEBビューアの視点状態を `viewer_session.json` へ書き出し、QGIS側が500ms間隔でポーリングできる。
- QGIS地図上に、固定距離の同心円、視野角の扇形、direction線、direction線先端の垂線を一時レーダとして表示できる。
- レーダ表示は `QgsRubberBand` による一時描画であり、地物登録プラグイン側の選択レイヤやmap toolを奪わない。
- `main.py` から処理系、ビューア制御、フレーム抽出、レーダ描画、KP処理を分離し、Pythonファイルの責務を整理した。
- プラグインパネルをタブUIへ変更し、ロード/全件処理と制御/プレビューを分離した。
- レーダheadingをGPX属性値ではなく、±10フレームの移動軌跡から推定できる。
- レーダ扇形の奥行きを、±10フレームの移動距離とUIの `Scale` に連動できる。

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

## プラグインパネルUI

縦方向に大きくなりすぎないよう、パネルは2タブ構成にしています。

### `Load / Process`

上から順に、全件処理までの実行順に並べています。

- GPXファイル選択
- MP4動画ファイル選択
- KP CSV選択
- 出力先ディレクトリ選択
- `Shift` と `KP tol`
- `Process` と進捗バー

ファイル選択は、ラベル、現在のファイル名、`Browse` ボタンを1行に収めます。表示はファイル名だけにし、フルパスはツールチップで確認します。長いファイル名でパネル幅が広がりすぎないよう、ラベルは1行表示でクリップされます。

### `Control / Preview`

単一フレーム確認、地図クリック、ナビゲーション、プレビューをまとめています。

- `Frame` 番号指定と `Extract`
- `Click Layer` / `Stop Click`
- 現在フレーム、ナビゲーションモード、通常移動量、早送り/早戻し量、レーダ `Range` / `Scale` / `Offset`
- QGIS側プレビュー情報
- QGIS側プレビュー画像
- `<<`, `<`, `>`, `>>` の移動ボタン

当初は1画面内に全UIを縦積みしていましたが、QGIS上でパネルが画面をはみ出すため、ロード設定と制御系を分けました。意味的に一連の操作は同一行にまとめ、ボタン文言も短くしています。

## フレームナビゲーション

プラグインパネルには、現在フレームを基準に前後へ移動するナビゲーションUIがあります。

ボタン:

- `<<`: 大きく戻る
- `<`: 戻る
- `>`: 送る
- `>>`: 大きく進む

設定:

- `Navigation mode`
- `Step`
- `Fast`

`Step` は通常移動量、`Fast` は大きく戻る/進む時の移動量です。既定では `Step=1`, `Fast=30` です。30フレーム動画では、`Fast=30` が約1秒移動に相当します。

ナビゲーションモード:

- `Frame step`: 現在フレーム番号に対して `±Step` / `±Fast` する。
- `Layer point`: 選択中またはクリックモード中の `Video GPX Points` レイヤを `frame` 順に移動する。
- `KP matched CSV`: `<video_stem>_matched_frames.csv` の `frame_index` 順に移動する。

クリックモード中はキーボードでも操作できます。

- `←` / `→`: 通常移動
- `Shift + ←` / `Shift + →`: 大きく戻る/進む
- `Space`: 現在フレームを再表示
- `Esc`: クリックモード解除

ナビゲーションはQGIS地図側を主導にしています。WEBビューアのPrev/Nextは補助機能であり、通常運用ではQGIS地図クリックまたはQGIS側ナビゲーションからフレームを指定します。

## 基本操作フロー

1. `Load / Process` タブでGPXファイルを選択する。
2. MP4動画を選択する。
3. 必要に応じてKP CSVを選択する。
4. 出力先、フレームシフト量、KP許容距離を指定する。
5. `Process` を実行する。
6. `Video GPX Points` レイヤがQGISに追加される。
7. CSV/JSONが出力される。
8. `Control / Preview` タブで `Click Layer` を有効にする。
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

QGIS側はこのJSONを500ms間隔でポーリングし、地図上に視線方向レーダを描画します。

レーダ表示:

- 撮影点を中心にした固定距離の同心円
- WEBビューアの視野角に対応する扇形
- direction線
- direction線の先端に置く垂線

レーダは「絶対距離」と「動的距離」を分けて扱います。

### 絶対距離

プラグインパネルの `Range` は、地図上へ描く固定距離円です。既定値は5mです。

描画する円:

- `Range`
- `Range * 2`

既定では5m円と10m円になります。この2本を目視距離の基準線として使います。

### 動的距離

扇形、direction線、先端の垂線の奥行きは、±10フレームの移動距離から求めます。

```text
sector_radius_m = distance_m * Scale
```

`Scale` の既定値は `1.0` です。速度が速い区間では扇形が伸び、停止に近い区間では短くなります。

### 方位補正

360映像の正面方向と進行方向が一致しない場合は、プラグインパネルの `Offset` で補正します。

`Offset` は、移動軌跡から求めた進行方向に対して、動画の正面方向が時計回りに何度ずれているかを表します。

選択肢:

- `0deg`
- `90deg`
- `180deg`
- `270deg`

将来的に「進行方向=動画正面」を保証した素材を使う場合は、`0deg` を標準値として扱います。

### heading算出

対象フレームを `i` とし、`i - 10` と `i + 10` の位置から移動ベクトルを作ります。緯度経度差はローカルなメートル座標差へ変換します。

```text
dx = east_m
dy = north_m
heading = (atan2(dx, dy) * 180 / pi + 360) % 360
```

`heading` は北=0度、時計回りのGIS方位です。

端部などで±10フレームがそろわない場合は、取得できる範囲で前後差または中心フレームから片側差を使います。

### フォールバック

GNSSの暴れや停止時にレーダが飛ばないよう、以下のフォールバックを行います。

- 近傍フレーム更新でheadingが前回値から45度を超えて急変した場合、前回headingを維持する。
- ±10フレームの移動距離が0.5m未満の場合、停止またはノイズとして前回headingを維持する。
- 停止時でも扇形が完全に消えないよう、扇形奥行きは最小1.0mにする。
- 地図クリックなどで離れたフレームへジャンプした場合は、前回heading固定を適用せず、新しい軌跡headingを採用する。

### 視線方向とFOV

WEBビューアの `yaw_to_camera_heading` は、動画正面から現在視線までの時計回り相対角として扱います。

```text
viewer_bearing = (heading + Offset + yaw_to_camera_heading) % 360
```

視野角はWEBビューアの `zoom` から算出します。

```text
fov = 90 / zoom
```

FOVは扇形の広がりにのみ使います。扇形の奥行きには使いません。

画像を別フレームへ切り替える場合、WEBビューアは切替直前の `yaw_to_camera_heading`, `pitch`, `zoom` を新しいフレームへ継承します。

### `images/0000/frame_0000000.jpg`

QGIS側プレビュー画像です。

Exporterと同じく、1000フレームごとのサブフォルダと `frame_{frame:07d}.jpg` の命名規則で保存します。`*_frames.csv` と `*_matched_frames.csv` の `image_path` 列も、この階層付きパスをCSVからの相対パスとして記録します。全フレームCSVの `image_path` は、未抽出フレームでもExporterが生成する予定位置を示します。

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

ブラウザ側は初回表示後、QGISクリックのたびにページ全体を再読み込みしません。セッション状態をポーリングし、krpanoの `loadpano()` でシーンだけ差し替えます。

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

- 実データで `yaw_to_camera_heading` の方位変換、`Range`、`Scale`、`Offset` の初期値を調整する。
- レーダの扇形奥行きに対して、速度が高すぎる場合の上限値を設定するか検討する。
- レーダ表示のON/OFFや色・透過率を設定できるようにする。
- 証跡用Exporterを別途実装する。
- OpenCV/ffmpegのフレーム一致検証をraw pixel hashで行う。
- QGIS Python向け固定wheel配布手順を整備する。
