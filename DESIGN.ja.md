# GPXVideoProcessor 設計メモ

更新日: 2026-06-07

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
├── config.py                    UI入力Configと純Python validation
├── common.py                    CSV/文字列/日時などの共通ヘルパー
├── processor.py                 GPXとMP4からフレーム位置を生成するQThread
├── viewer_controller.py         360Viewer起動・HTTP連携・QProcess制御
├── frame_extract.py             静止画抽出・EXIF付与・QGISプレビュー表示
├── map_tools.py                 地図クリック用MapTool
├── messages.py                  ユーザ向けメッセージテンプレートとlocale切替
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
│   ├── quality_assurance.md     品質保証方針・退行テスト・手動確認観点
│   ├── qgis_manual_test_checklist.md QGIS実機の機能別手動テスト項目
│   ├── rader_spec.md            レーダ表示の実寸準拠仕様
│   ├── tenkaku_ninja_operations.md TenkakuNinja由来の大量JPEG運用ノウハウ
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
- `config.py`: UI入力を機能単位のConfigへ束ね、処理前に検証する純Python層。
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

2026-06-07時点で、以下を実装・動作確認済みです。

- 非標準GPXの時刻を読み取り、MP4フレームへ位置情報を補間できる。
- フレーム番号を不変キーとして扱い、指定フレーム数のシフトを反映できる。
- KP CSVを指定した場合、許容距離内の最近接KPへマッチングし、結果CSVを出力できる。
- `360Viewer起動` でQGISからローカルWEBビューアを起動できる。
- QGIS地図上の撮影点クリックにより、該当フレームの360画像をブラウザへ表示できる。
- ブラウザ側はフレーム切替時にページ全体を再読み込みせず、krpanoの `loadpano()` で画像を差し替える。
- フレーム切替後も、直前の `yaw_to_camera_heading`, `pitch`, `zoom` を継承できる。
- WEBビューアの視点状態を `viewer_session.json` へ書き出し、QGIS側が500ms間隔でポーリングできる。
- QGIS地図上に、固定距離の同心円、視野角の扇形、direction線、direction線先端の垂線を一時レーダとして表示できる。
- レーダ表示は `QgsRubberBand` による一時描画であり、地物登録プラグイン側の選択レイヤやmap toolを奪わない。
- `main.py` から処理系、ビューア制御、フレーム抽出、レーダ描画、KP処理を分離し、Pythonファイルの責務を整理した。
- プラグインパネルをタブUIへ変更し、ロード/全件処理と制御/プレビューを分離した。
- レーダheadingをGPX属性値ではなく、±10フレームの移動軌跡から推定できる。
- レーダ扇形の奥行きと先端距離線を、`CalFOV` / `CalDist` / `Scale` と現在FOVから校正距離として表示できる。
- WEBビューア上でクリックした360空間上の点を、校正距離とクリック角から地図平面へ一時投影できる。
- Insta360 X4 + スマホリモコン/GNSSで撮影したH.265 MP4と、Insta360書き出しGPXをそのまま読み込めることを実機確認した。
- `config.py` により、Process、単体フレーム抽出、ナビゲーション、レーダ、360Viewer起動設定の入力検証をQGIS非依存のユニットテスト対象にした。
- QGIS実機で確認すべき操作を `docs/qgis_manual_test_checklist.md` に機能単位で整理した。
- 主要UIを日本語化し、技術ラベルはtooltipで補足するハイブリッドUIにした。
- プレビュー領域で、QGIS側 `images/` 抽出とWEBビューア側 `viewer_cache/` の責任分界を確認できる。

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

H.265 MP4を扱う場合は、QGIS同梱PythonのOpenCVが当該コーデックを読める環境であることが前提です。開発環境ではInsta360 X4由来のH.265 MP4を読み込めることを確認済みです。

### krpano

360パノラマ表示には、ライセンス済みの `krpano.js` を以下へ配置します。

```text
GPXVideoProcessor/360viewer/static/vendor/krpano/krpano.js
```

未配置の場合は通常のエクイレクタングラー静止画表示にフォールバックします。

## プラグインメニュー

現在のメニュー/ツールバーは以下です。

- `360Viewer起動`
- `操作パネル`
- `終了`

### 360Viewer起動

ローカルHTTPビューアを起動し、外部ブラウザを開きます。

QGIS環境では `sys.executable` が `qgis.exe` や `qgis-bin.exe` を指す場合があります。そのまま起動するとQGISが二重起動するため、プラグイン側で `python.exe` / `python3.exe` / `python-qgis.bat` を探索して起動します。

### 操作パネル

同期処理用のパネルを開きます。あわせて360Viewerが起動済みかどうかをQGISのmessageBarへ表示します。

### 終了

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

UIは、マニュアルレスで触り始められることと、パネルのコンパクトさを両立するため、ハイブリッド日本語化とします。

- メニュー、タブ、主要ボタン、チェックボックスは日本語表示にする。
- `Shift`、`KP tol`、`CamH`、`CalFOV`、`CalDist`、`Scale`、`Offset` などの短い技術ラベルは英語/略称のまま維持する。
- 技術ラベルの意味、運用上の注意、成果品ではなくキャッシュであることなどはtooltip/What's Thisで日本語説明する。
- UI文言はmessageBarと同じlocale設定を使い、`messages.py` の `UI_TEXTS` で管理する。

### `Load / Process`

上から順に、全件処理までの実行順に並べています。

- GPXファイル選択
- MP4動画ファイル選択
- KP CSV選択
- 出力先ディレクトリ選択
- `Shift` と `KP tol`
- `全件処理` と進捗バー

ファイル選択は、ラベル、現在のファイル名、`Browse` ボタンを1行に収めます。表示はファイル名だけにし、フルパスはツールチップで確認します。長いファイル名でパネル幅が広がりすぎないよう、ラベルは1行表示でクリップされます。

### `Control / Preview`

単一フレーム確認、地図クリック、ナビゲーション、プレビューをまとめています。

- `Frame` 番号指定と `抽出`
- `撮影点選択` / `選択解除` / `追従`
- 現在フレーム、ナビゲーションモード、通常移動量、早送り/早戻し量、レーダ `Range` / `Scale` / `CamH` / `CalFOV` / `CalDist` / `Offset`
- QGIS側プレビュー情報
- QGIS側プレビュー画像
- `<<`, `<`, `>`, `>>` の移動ボタン

当初は1画面内に全UIを縦積みしていましたが、QGIS上でパネルが画面をはみ出すため、ロード設定と制御系を分けました。意味的に一連の操作は同一行にまとめ、ボタン文言も短くしています。

プレビュー領域は、フレーム同期確認中の簡易ダッシュボードとしても使います。

- `Frame ... 保存/既存` の行は、QGIS側が `images/` に抽出したJPEGと処理時間を示す。
- 一見すると同じ画像でも、ファイル名とframe番号で表示切替を確認できる。
- プレビュー画像のtooltipは、WEBビューアへ渡る `viewer_cache/` 側の想定ファイル名を示す。
- `viewer_cache/` ファイルが既に生成済みなら、tooltipにファイルサイズも表示する。

操作パネルはQGIS地図操作中も確認しやすいよう、常に前面表示するウィンドウフラグを付けています。

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
- `Layer point`: GPXVideoProcessorが生成・保持している `Video GPX Points` レイヤを `frame` 順に移動する。
- `KP matched CSV`: `<video_stem>_matched_frames.csv` の `frame_index` 順に移動する。

`KP matched CSV` が存在しない、または空の場合は、警告を表示してナビゲーションモードを `Frame step` へ自動的に戻します。KPを指定していない作業でKPモードが残り続けると毎回同じエラーになるため、デフォルト動作へフォールバックします。

`Video GPX Points` は360画像参照用の内部レイヤとして扱います。プラグインは生成したレイヤIDを保持してナビゲーションやクリック待ち受けに使うため、ユーザが地物登録先として別レイヤを選択していても、画像送り側の参照先は変わりません。Process前に既存のframe属性レイヤを手動利用する場合のみ、選択中レイヤを保険として参照します。

クリックモード中、またはGPXVideoProcessor操作パネルにフォーカスがある場合は、キーボードでも操作できます。

- `←` / `→`: 通常移動
- `Shift + ←` / `Shift + →`: 大きく戻る/進む
- `Space`: 現在フレームを再表示
- `Esc`: クリックモード解除

キー入力は地図キャンバスのMapToolに加え、QGISアプリケーション側のイベントフィルタでも補助的に受けます。地物登録ツールなど別MapToolが有効な場合でも、GPXVideoProcessor操作パネルにフォーカスがあればナビゲーションキーを受け付けます。ただし、数値入力やコンボボックス操作中の矢印キーは奪いません。

QGISのMapToolは同時に1つだけ有効になるため、地図クリックは明示切替式です。通常時は地物登録ツールを主とし、GPXVideoProcessorは操作パネル、キーボード、WEBビューア連携で従ツールとして動作します。撮影点を地図上で直接選択したい場合だけ、ユーザが `撮影点選択` を押して一時的にMapToolをGPXVideoProcessorへ切り替えます。

ナビゲーションはQGIS地図側を主導にしています。WEBビューアのPrev/Nextは補助機能であり、通常運用ではQGIS地図クリックまたはQGIS側ナビゲーションからフレームを指定します。

`Follow` をONにすると、地図クリック、ボタン操作、キーボード操作で表示フレームが変わった時に、対応する撮影点をQGIS地図の中心へ移動します。ズーム倍率は変更しません。地図再描画によるレスポンス低下を避けるため、既定ではOFFです。

WEBビューア側でも、ブラウザにフォーカスがある場合は `←` / `→` で `matched_frames.csv` 上のPrev/Nextへ移動できます。

WEBビューアのデバッグログは既定では折り畳み、ツールバーの `Log` ボタンで表示/非表示を切り替えます。

## 基本操作フロー

1. `読込 / 処理` タブでGPXファイルを選択する。
2. MP4動画を選択する。
3. 必要に応じてKP CSVを選択する。
4. 出力先、フレームシフト量、KP許容距離を指定する。
5. `全件処理` を実行する。
6. `Video GPX Points` レイヤがQGISに追加される。
7. CSV/JSONが出力される。
8. `操作 / プレビュー` タブで `撮影点選択` を有効にする。
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

`終了` 時に以下へ保存します。

```text
<output_dir>/tmp.gpkg
```

保存に失敗した場合は、安全側でレイヤ削除を行いません。

## 出力ファイル

標準出力先:

```text
<video_dir>/<video_stem>
```

`video_stem` は選択したMP4ファイル名から拡張子を除き、ファイルシステム上扱いやすいASCII名へ正規化した名前です。例えば `VID_20250324_135428_00_033_rot170.mp4` の既定出力先は `<video_dir>/VID_20250324_135428_00_033_rot170` です。

これにより、出力フォルダ名だけで「どの動画から生成された成果物か」を判別でき、別動画のCSV、GPKG、画像、viewer cacheが同じ `360view_output` に混在する事故を避けます。ユーザが明示的に出力先を選択した場合は、その指定を優先します。

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
- `viewer_camera_height_m`
- `radar`
- `target`
- `updated_at`

QGIS側はこのJSONを500ms間隔でポーリングし、地図上に視線方向レーダを描画します。

レーダ表示:

- 撮影点を中心にした固定距離の同心円
- WEBビューアの視野角に対応する扇形
- direction線
- direction線の先端に置く垂線

レーダは `QgsRubberBand` による一時描画です。`終了` やセッション終了時は、RubberBandを非表示化、形状リセット、QGraphicsSceneから除去し、QGISキャンバスを更新して描画残りを避けます。

レーダは「絶対距離」と「動的距離」を分けて扱います。

### 絶対距離

プラグインパネルの `Range` は、地図上へ描く固定距離円です。既定値は5mです。

描画する円:

- `Range`
- `Range * 2`

既定では5m円と10m円になります。この2本を目視距離の基準線として使います。

### 校正距離

扇形、direction線、先端の垂線の奥行きは、`CalFOV`、`CalDist`、`Scale`、WEBビューアの現在FOVから求めます。先端の垂線は、現在の校正条件で見ている中心距離線として扱います。

```text
current_fov = 90 / zoom
fov_ratio = tan(current_fov / 2) / tan(CalFOV / 2)
sector_radius_m = max(1.0, CalDist * Scale * fov_ratio)
```

`CalFOV` は距離校正時のFOV、`CalDist` はそのFOVでビューア中心線が地図上の何mに相当するかを表す値です。`Use FOV` を押すと、現在ビューアのFOVを `CalFOV` へ取り込めます。`Scale` の既定値は `1.0` で、人間が地図計測と見比べて微調整する倍率です。zoomを上げると視野角が狭くなり、扇形奥行きと先端距離線は手前へ寄ります。

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

FOVは扇形の広がりと、`CalFOV` からの距離倍率計算に使います。現在FOVが `CalFOV` と同じで `Scale=1.0` の場合、奥行きは `CalDist` と一致します。最終表示は最低1.0mを維持します。

WEBビューアにも、`Range` / `Range * 2` 相当の地面範囲円、1m間隔の破線補助グリッド、QGIS側の先端垂線に対応する校正距離線をHUDとして表示します。地面範囲円はジョブ条件 `CamH` / `viewer_camera_height_m` をカメラ中心の地上高として投影します。このHUDは単眼360画像から実距離を厳密に復元するものではなく、QGIS側レーダと同じ距離目安を画像側にも重ね、ユーザが主円と1m補助グリッドの比較で目測できるようにする補助表示です。ツールバーの `HUD` ボタンでHUD全体を、`Grid` ボタンで補助グリッドだけを表示/非表示に切り替えます。

WEBビューア上で画像をクリックすると、クリック時点の360空間上の絶対yaw、ビューア中心からの相対yaw、クリック時zoomを `viewer_session.json` の `target` に保存します。QGIS側は、クリック時FOVから求めた前方距離を `cos(yaw_delta)` で補正し、撮影点から `heading + Offset + target_yaw` 方向へ一時投影点を描きます。これは地物レイヤへ書き込むものではなく、360クリック点と地図平面の対応を試すためのRubberBand表示です。

画像を別フレームへ切り替える場合、WEBビューアは切替直前の `yaw_to_camera_heading`, `pitch`, `zoom` を新しいフレームへ継承します。

### `images/0000/frame_0000000.jpg`

QGIS側プレビュー画像です。

Exporterと同じく、1000フレームごとのサブフォルダと `frame_{frame:07d}.jpg` の命名規則で保存します。`*_frames.csv` と `*_matched_frames.csv` の `image_path` 列も、この階層付きパスをCSVからの相対パスとして記録します。全フレームCSVの `image_path` は、未抽出フレームでもExporterが生成する予定位置を示します。

クリックした地物から緯度経度を取得できる場合、GPS EXIFも付与します。これは確認用キャッシュであり、最終証跡画像ではありません。

プラグインパネルの `Frame ... 保存/既存` 表示はこの `images/` 側を示します。ここで確認できるのは「QGISプラグインがMP4からフレームを抽出し、プレビュー用JPEGを書き出した」ことです。

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

プレビュー画像のtooltipには、360Viewerと同じ命名規則で推定した `viewer_cache/` 側パスを表示します。まだブラウザ側の生成が終わっていない場合でも、同じframeがWEBビューアへ渡る時にどのファイルへ書かれるかを確認できます。ファイルが存在する場合はサイズも表示します。

責任分界:

- `images/`: QGISプラグインが抽出・保存したプレビュー/成果品予定画像。
- `viewer_cache/`: 360Viewerがブラウザ表示用に生成する軽量JPEG。
- ブラウザ表示異常時は、`images/` 表示、`viewer_cache/` tooltip、WEBビューア表示の順に切り分ける。

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

- QGISの `終了` はローカルサーバを止めるが、外部ブラウザのタブ自体は閉じない。
- `matched_frames.csv` はKPマッチング出力がある場合だけ生成される。
- krpanoはライセンス物のため同梱しない。
- `viewer_cache` は目視確認用であり証跡用ではない。
- OpenCVとffmpegで同じフレーム番号が同じ画像になることは、証跡運用前に検証が必要。

## 次の実装候補

- 実データで `yaw_to_camera_heading` の方位変換、`Range`、`Scale`、`Offset` の初期値を調整する。
- Exporter成果品チェックを自動化し、CSV/GPKG/JPEG/EXIF/manifest間のframe対応、欠損、重複、フレーム一致を検査できるようにする。
- WEBビューア上の5m/10m範囲円は、仰角が浅い場合の投影精度がまだ保証できていないため、実測データまたはkrpanoの球面座標APIで検証する。
- レーダの扇形奥行きに対して、速度が高すぎる場合の上限値を設定するか検討する。
- レーダ表示のON/OFFや色・透過率を設定できるようにする。
- 証跡用Exporterを別途実装する。
- OpenCV/ffmpegのフレーム一致検証をraw pixel hashで行う。
- QGIS Python向け固定wheel配布手順を整備する。
