# 品質保証方針

更新日: 2026-06-07

この文書は、Geo360View の長時間運用、データ損失防止、将来デグレ防止のための品質保証方針をまとめるものです。

## 基本方針

本プラグインは、QGIS上の対話操作、ローカルWEBビューア、動画フレーム抽出、GeoPackage/CSV/JSON出力をまたぐため、すべてを通常のユニットテストだけで保証することはできません。

そのため、品質保証は以下の層に分けます。

- 純Pythonユニットテスト: QGISなしで検証できる入出力規則、JSON/HTTP入力検証、Exporter抽出条件を守る。
- 構文チェック: QGIS外で読み込めるPython/JavaScriptの構文破綻を検出する。
- QGIS手動チェック: MapTool、RubberBand、レイヤ保存、ブラウザ連携などQGIS実機が必要な挙動を確認する。
- 長時間バッチ確認: OpenCV、NAS/SSD I/O、フレーム欠損、manifest/summaryを確認する。

## 実行コマンド

QGISを起動せずに実行できる基本チェック:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile config.py main.py frame_extract.py radar.py viewer_controller.py messages.py 360viewer/app.py TenkakuNinja/exporter.py tests/test_config_validation.py tests/test_messages.py tests/test_360viewer_app.py tests/test_tenkaku_exporter.py
node --check 360viewer/static/viewer.js
```

`common.py` や `main.py` などQGISモジュールを直接importするファイルは、通常Python環境では完全なユニットテスト対象にしにくいです。純Pythonへ切り出せる処理は、今後小さなヘルパーとして分離し、`tests/` から検証できるようにします。

## 2026-06-07時点の品質・UX補強

この時点で、以下の補強を実装済みです。

- `config.py` に機能単位のConfig/Validationを置き、入力不備や破綻値を処理本体へ渡す前に止める。
- `tests/test_config_validation.py` でProcess、Frame抽出、Navigation、Radar、Viewer設定の境界値を確認する。
- `messages.py` にmessageBar用 `MESSAGES` とUI用 `UI_TEXTS` を置き、英語/日本語のキー対応を `tests/test_messages.py` で確認する。
- プラグインパネルは主要操作を日本語化し、短い技術ラベルは英語/略称のままtooltipで補足する。
- `docs/qgis_manual_test_checklist.md` に、QGIS実機が必要な結合テストシナリオを機能単位で整理する。
- プレビュー領域を簡易ダッシュボード化し、`images/` への抽出状況と `viewer_cache/` 側の想定ファイルを切り分けられるようにする。

ユニットテストは細かい入力規則と退行検知を担当し、QGIS手動チェックはMapTool、RubberBand、外部ブラウザ、実ファイルI/O、既存地物登録ツールとの共存を担当します。

## 現在のユニットテスト対象

### `tests/test_360viewer_app.py`

対象:

- 動画名入力の安全性
- `viewer_session.json` へ保存する視点状態の検証
- 360クリック投影用 `target` / `targets` の正規化
- セッションJSONの原子的書き込み
- QGISナビゲーション時の視点継承

守りたい事故:

- パストラバーサルで任意ファイルを読みに行く
- 壊れた `viewer_session.json` や不正なtarget値でQGIS側レーダが不安定になる
- フレーム移動時にyaw/pitch/zoomが意図せずリセットされる
- セッション書き込み中断で途中JSONを残す

### `tests/test_tenkaku_exporter.py`

対象:

- 1000フレーム単位フォルダと `frame_0000000.jpg` 命名規則
- `--condition` のSQLパラメータ化
- GPKGからのフレーム範囲抽出
- `--matched-only`
- `--frames`
- 同一frameの重複排除

守りたい事故:

- frame番号とファイル名の対応が崩れる
- 1000件サブフォルダ規則が壊れる
- SQL条件の扱いが変わり、想定外のフレームを書き出す
- KPマッチ済みだけ抽出するつもりが未マッチも混ざる
- 重複frameを複数回書き出す

### `tests/test_messages.py`

対象:

- 既定localeメッセージと英語/日本語テンプレートのキー対応
- 既定locale UI文言と英語/日本語UIテンプレートのキー対応
- 未対応localeの既定localeフォールバック
- `ja_JP` / `ja-JP` の日本語locale正規化
- テンプレート変数のformat
- テンプレート変数不足時の安全な表示

守りたい事故:

- 片方のlocaleへ追加したメッセージキーをもう片方へ追加し忘れる
- 片方のlocaleへ追加したUIキーをもう片方へ追加し忘れる
- 日本語運用へ切り替えた時に未知キーやformat例外でUI表示が壊れる
- QGIS messageBarの文型が機能ごとにばらつく

### `tests/test_config_validation.py`

対象:

- `ProcessConfig`: GPX/MP4/KP CSV/出力先/Shift/KP許容距離
- `FrameExtractConfig`: MP4、frame番号、出力先
- `NavigationConfig`: mode、step、fast step、follow
- `RadarConfig`: Range、Scale、CalFOV、CalDist、Offset
- `ViewerConfig`: host、port、動画ディレクトリ、session/cacheパス、JPEG品質、最大幅、カメラ高さ

守りたい事故:

- 必須ファイル未指定や拡張子違いのままworkerやOpenCVへ進む
- 負のframe番号や0ステップなど、処理上意味を持たない値が混入する
- レーダ距離校正に破綻した値が入り、地図上に誤解を招く表示が出る
- 360Viewerのport/JPEG品質/キャッシュ設定が壊れたままQProcessを起動する
- ジョブ固有のカメラ高さが不正なまま地面範囲HUDへ流れる

## 長時間運用で重視する不変条件

### フレーム番号

動画上の0始まり `frame` は不変キーです。

- QGISプラグイン
- `*_frames.csv`
- `tmp.gpkg`
- WEBビューア
- TenkakuNinja Exporter
- EXIF/JPEGファイル名

これらの間で同じframe番号が同じ動画フレームを指すことを最優先で守ります。

### ファイル出力

途中終了やクラッシュ時に壊れた成果を正規ファイルとして残さないことを重視します。

- `viewer_session.json`: 一時ファイルから `os.replace`
- WEBビューアJPEGキャッシュ: 一時ファイルから `os.replace`
- Exporter JPEG: 一時ファイルから `os.replace`

今後、CSV/summary JSONも長時間バッチの成果物として扱う場合は、同様に一時ファイルから置換する方針を検討します。

### キャッシュと成果品

`viewer_cache/` は目視確認用の軽量JPEGキャッシュです。証跡画像ではありません。

`images/0000/frame_0000000.jpg` 形式の画像は、Exporter規則に合わせる成果品または成果品予定パスです。

両者を混同しないようにします。

QGIS操作パネルでは、この責任分界を運用中に確認できるようにします。

- `Frame ... 保存/既存` 表示: QGIS側が `images/` に抽出したJPEGと処理時間。
- プレビュー画像tooltip: 360Viewerが参照する `viewer_cache/` 側の想定ファイル名。生成済みならサイズも表示。
- WEBビューア表示: ブラウザ/krpanoへ渡った最終的な表示結果。

表示異常時は、`images/` への抽出、`viewer_cache/` 生成、ブラウザ表示の順に切り分けます。

### 揮発性データと成果品データ

Geo360Viewには、地物を生成するための揮発性データと、最終的に納品・再検証の対象になる成果品データが混在します。この2つは性質が違うため、品質保証上も分けて考えます。

揮発性データは、QGIS上で地物登録を支援するための一時データです。

- `viewer_cache/`: 高速表示用の軽量JPEG。削除しても再生成できる。
- QGISメモリレイヤ: 作業中の参照用。Exit時に保存・削除する。
- レーダRubberBand: 視点確認用の一時描画。地物や成果品ではない。
- `viewer_session.json`: QGISとWEBビューアの疎連携用状態。最新状態だけが重要。

成果品データは、後段処理、納品、監査、再説明の対象です。

- `tmp.gpkg`: 作業セッション退避または中間DB。
- `*_frames.csv`: フレーム同期結果の基礎データ。
- `*_navigation.json`: WEBビューア等が参照する派生データ。
- `*_matched_frames.csv`: KP単位ナビゲーションや抽出対象の派生データ。
- `images/0000/frame_0000000.jpg`: Exporter規則に従う証跡画像または成果品候補。
- `export_manifest.csv` / `export_summary.json`: Exporterの処理記録。
- 将来の `audit_report.json` / `audit_report.csv`: 成果物監査の記録。

揮発性データでは速度、操作性、再生成可能性を優先します。成果品データでは、欠損しないこと、同じframeが同じ動画フレームを指すこと、CSV/GPKG/JPEG/EXIF/JSONの整合性が最優先です。

重要な設計判断:

- `viewer_cache/` を納品対象にしない。
- QGISメモリレイヤをそのまま成果品と見なさない。
- `tmp.gpkg` は中間成果として扱い、納品用DBにする場合は別途検査する。
- `images/` は成果品候補だが、QGISオンザフライ抽出物とExporter一括抽出物の由来を区別する。
- `frame` はすべての成果物を結び付ける不変キーとして扱う。

## QGIS手動確認チェック

詳細なチェック項目は `docs/qgis_manual_test_checklist.md` に記録します。

QGIS実機で確認する主要観点:

- GPX/MP4を読み込み、`Video GPX Points` が生成される。
- `tmp.gpkg` 保存後にレイヤ削除できる。
- 既存の地物登録プラグインのMapToolを邪魔せず、Geo360View操作パネルにフォーカスがあればキー操作できる。
- `Exit` 後にレーダRubberBandが残らない。
- WEBビューアの画像送りでyaw/pitch/zoomを継承する。
- WEBビューアクリック点がQGIS地図上の緑点として投影される。
- WEBビューアのダブルクリック複数点がQGIS地図上の複数緑点として投影される。
- WEBビューアクリック投影点が `360 Click Targets` レイヤの属性テーブルへ緯度経度付きで保存される。
- `tmp.gpkg` 内部レイヤ名が退避ファイル名 `tmp` ではなく、`video_gpx_points` / `click_targets_360` になる。
- `CalFOV` / `CalDist` / `Scale` を変えた時、QGIS側垂線、クリック投影点、WEB HUDが同じ前提で変化する。
- `CamH` を変えた時、`viewer_session.json` への保存とWEB HUDの地面範囲円が更新される。
- WEB HUDの1m破線補助グリッドが主円と同じHUD表示状態で切り替わり、QGIS地図側にも同じ1m補助円が出る。
- `Follow` ON/OFFで地図再中心化の挙動が切り替わる。
- 操作パネルの主要ボタン、タブ、messageBar、tooltipが同じlocaleで表示される。
- パネル上の `Frame ... 保存/既存` 表示とプレビュー画像tooltipで、`images/` と `viewer_cache/` のどちらを見ているか切り分けられる。

## QGIS UI手動テストの考え方

QGIS UI、MapTool、RubberBand、外部ブラウザ、ローカルHTTPサーバ、OpenCV、実ファイルI/Oをまたぐ動作は、自動UIテストにすると壊れやすく保守コストが高くなります。

そのため、UIを伴う品質確認は、機能ごとのチェックリストとして人が確認する方針にします。

手動チェックの粒度:

- 起動・環境確認
- GPX/MP4読込
- `Process` 実行とレイヤ生成
- CSV/GPKG出力
- 360Viewer起動
- 地図クリック連携
- キーボードナビゲーション
- 他プラグインMapToolとの共存
- レーダ表示
- `CalFOV` / `CalDist` / クリック投影
- `Follow` ON/OFF
- `Exit` 後のレイヤ・レーダ・ビューア終了
- 連続クリック・長時間操作

確認結果は、`OK` / `NG` / `保留` / `メモ` / `証跡フレーム` のような表形式で残すと、将来のデグレ確認に使いやすくなります。

一方で、入力値の例外、境界値、不正値、ファイル名規則、JSON検証などは粒度が細かすぎるため、手動UIテストではなく自動テストへ寄せます。

## Exporter長時間バッチ確認

長時間書き出し後に確認する項目:

- `export_manifest.csv` の対象フレーム数と `export_summary.json` のcountsが一致する。
- `error` がない、またはエラーframeを再抽出できる。
- `frame_start` / `frame_end` 指定が両端を含む。
- 1000件ごとのサブフォルダ数とファイル数が想定通り。
- EXIF GPSが元緯度経度または意図した属性から入っている。
- 動画後半で位置同期が大きくずれていない。

## Config / Validation

UI入力は、処理本体が直接 `self.gpx_file` や `QSpinBox.value()` を読み続けるのではなく、機能単位のConfigへ束ね、処理開始前にvalidationする方針が望ましいです。

現在のConfig:

- `ProcessConfig`: GPX、MP4、KP CSV、出力先、frame shift、KP許容距離
- `ViewerConfig`: host、port、JPEG品質、progressive JPEG、最大幅、cache/sessionパス、カメラ高さ
- `NavigationConfig`: navigation mode、通常step、fast step、follow
- `RadarConfig`: Range、Scale、CalFOV、CalDist、Offset
- `FrameExtractConfig`: MP4、frame番号、出力先

将来追加候補:

- `ExporterConfig`: DB、動画、出力先、frame範囲、matched-only、scale、JPEG品質

目的:

- 不正値を処理本体へ流さない。
- 入力例外をQGISなしの自動テストで検証できる。
- UI変更時に処理本体への影響を小さくする。
- 将来CLIやバッチ処理へ流用しやすくする。

検証したい入力例:

- 必須ファイル未指定
- 拡張子違い
- ファイル存在確認
- 出力先作成可否
- `frame_shift` の範囲
- `kp_tolerance` が負数または非数
- viewer port が範囲外
- JPEG quality が1-100外
- scale が0以下
- `CalFOV` が1-179外
- `CalDist` が0以下
- `Offset` が0/90/180/270以外
- Exporterの `start <= end`

実装は、`config.py` にdataclass定義と `validate_*` 関数を同居させています。規模が大きくなった場合に、`validation.py` へ分離します。

## ユーザ向けメッセージと言語切替

QGIS messageBarは、ユーザが今すぐ判断するための短いメッセージに限定します。

messageBarに出す内容:

- 何が起きたか
- 正常か異常か
- 次に何をすればよいか

messageBarに出しすぎない内容:

- Python traceback
- 内部変数
- HTTPレスポンス全文
- `viewer_session.json` の中身
- Radarの連続計算値
- OpenCVの細かい処理時間

これらはログファイルまたはブラウザ側デバッグログへ出します。

現在、`messages.py` に既定locale・英語/日本語テンプレートのメッセージカタログとUI文言カタログを置いています。messageBar向けは `MESSAGES`、ボタン/タブ/tooltip向けは `UI_TEXTS` で管理します。`tests/test_messages.py` で以下を確認します。

- 英語キーと日本語キーの対応漏れ
- UIラベル/tooltipキーの英語・日本語対応漏れ
- localeフォールバック
- `ja_JP` / `ja-JP` の正規化
- format変数不足時の安全性

将来の方針:

- UI要素追加時は `UI_TEXTS` の英語/日本語両方へ同じキーを追加する。
- messageBar追加時は `MESSAGES` の英語/日本語両方へ同じキーを追加する。
- UIラベルとmessageBarのlocaleを必ず一致させる。
- ログは保守者向けのため、英語固定でもよい。

フォントについては、QGIS/PyQt/OSのフォント解決へ任せます。QGIS本体が日本語表示できる環境なら、プラグインUIの日本語も通常表示できます。Ubuntu等で日本語フォントがない場合は、運用手順として `fonts-noto-cjk` 等の導入を案内します。プラグインへ日本語フォントを同梱する必要は、現時点ではありません。

ただし、将来以下を行う場合は、フォント同梱または明示指定を再検討します。

- グラフ出力
- 帳票/PDF生成
- 画像への日本語文字焼き込み
- OpenCV/Pillow/Matplotlibによる日本語描画

## ログ方針

QGIS messageBarとログは役割を分けます。

想定するログ種別:

- user message: QGIS messageBarに出す短文
- operation log: 実行履歴、入力ファイル、出力先、件数、処理時間、設定値
- debug log: HTTP連携、viewer session、frame抽出、レーダ計算、例外traceback
- batch manifest: Exporterのframe単位status/error/path

QGIS操作パネルの `Log` チェックがOFFの場合、高頻度debug logは出しません。
連続Nav中にmessageBarやHTTPアクセスログが処理遅延の原因になるためです。
OFFでも、起動失敗、保存失敗、入力エラーなどユーザ判断に必要な警告は表示します。

ログに残したい主要イベント:

- 起動時環境
- `Process` 開始/終了
- GPX/MP4/KP/出力先/shift/tolerance
- レイヤ生成件数
- CSV/GPKG出力先
- 360Viewer start/stop/health
- frame抽出のopen/read/save/total時間
- cache hit/miss
- 例外traceback
- `Exit` 時の保存・削除・viewer停止

QGISユーザには短く出し、詳細はログで追える状態を目指します。

終了時保存は、GPKG由来レイヤをすべて無条件に書き戻すのではなく、
読み込み後にfeature追加、削除、属性変更、ジオメトリ変更があったレイヤだけを保存対象にします。
閲覧だけの終了は軽くし、QGISテーブル上で削除・編集した場合は変更を失わないことを確認対象にします。

例:

```text
messageBar:
  Frame extraction failed. Check the video codec or see log file.

log:
  traceback, video path, frame number, OpenCV error, elapsed breakdown
```

## Self Check / Diagnostics

運用後に問題になりやすいのは、ハードウェア/ソフトウェア環境差、処理速度、I/O安定性です。そのため、プラグイン自身が環境を診断し、結果をユーザと保守者へ示せる仕組みが有効です。

想定するSelf Check項目:

- OS
- Python executable/version
- QGIS version
- Qt version
- plugin path
- output_dir
- OpenCV import可否
- OpenCV version
- 対象MP4を開けるか
- frame count / fps / width / height を取得できるか
- H.265等、運用対象コーデックを読めるか
- krpano配置有無
- viewer port使用可否
- viewer health応答
- `viewer_session.json` 書き込み可否
- output_dir書き込み可否
- 空き容量
- 出力先がローカルSSD、NAS、NFS、SMB等の可能性

QGIS messageBarには要約だけ出します。

```text
Self check completed. 2 warning(s). See diagnostics report.
```

詳細はJSONとして保存する想定です。

```text
<output_dir>/diagnostics/environment_report.json
```

## Performance Probe

処理前またはメニュー操作で、軽量な性能測定を行う仕組みです。

測定候補:

- 動画open時間
- 先頭/中間/末尾付近の数フレームread時間
- JPEG encode時間
- 一時ファイルwrite時間
- viewer cache書き込み時間
- HTTP health応答時間
- 実効FPS見積もり

目的:

- NAS/SMB/NFS/ローカルSSDの差を説明できるようにする。
- OpenCV readが異常に遅い環境を検出する。
- 出力先I/Oが詰まっているか切り分ける。
- 顧客環境で「遅い」の原因を感覚ではなく数値で見る。

結果は以下のようなJSONに残す想定です。

```text
<output_dir>/diagnostics/performance_probe.json
```

## Runtime Monitor

実行中に処理速度と異常を観測する仕組みです。

Exporterで記録したい値:

- frames_processed
- fps_recent
- fps_average
- read_error_count
- write_error_count
- slow_frame_count
- disk_free_gb
- eta

QGISオンザフライ抽出で記録したい値:

- open_sec
- seek_read_sec
- save_sec
- total_sec
- cache_hit

異常判定例:

- 直近100件のFPSが基準値の50%未満
- frame read失敗が連続
- disk freeが10GB未満
- save時間が急増
- viewer HTTP応答が遅い
- `viewer_session.json` 更新が止まっている

ユーザ向けには短く出します。

```text
Frame extraction is slower than expected. Check storage or video location.
```

詳細はログまたはdiagnostics JSONへ残します。

## 成果物整合チェック

処理後に、成果物が相互に矛盾していないか検査する小さなコマンドまたはメニューを用意すると安全です。

これは毎回の作業フローに必ず入れる常時チェックではなく、抜き打ち監査、納品前検査、問題発生時の切り分けに使う位置づけです。特に、揮発性データから成果品データへ変換した後に、frame番号を起点として各成果物が同じ対象を指しているかを確認します。

確認候補:

- `tmp.gpkg` に対象レイヤがある
- `*_frames.csv` の件数とGPKGのframe件数が一致する
- `frame` が0始まりで重複していない
- `frame` と `source_frame` の関係が `frame_shift` と一致する
- 緯度経度が空でなく、値域が妥当である
- `image_path` がExporter規則に従っている
- `matched_frames.csv` のframeが `*_frames.csv` に存在する
- `navigation.json` のnode数とmatched CSV件数が一致する
- `navigation.json` の `previous_frame` / `next_frame` が破綻していない
- Exporter `export_manifest.csv` に対象frameがすべて出ている
- `error` statusがない、または再抽出対象として明示されている
- 実画像ファイルが存在する
- 1000件サブフォルダ規則に反していない
- JPEGが0バイトではなく、画像として読める
- EXIFにSoftware/Description/GPSなど期待するタグが入っている
- `viewer_cache/` と `images/` または成果品画像を混同していない

この検査はQGISなしのCLIとしても実装できます。

想定するCLI:

```bash
python tools/validate_outputs.py \
  --output-dir /path/to/VID_20250324_135428_00_033_rot170 \
  --database /path/to/VID_20250324_135428_00_033_rot170/tmp.gpkg \
  --video-name VID_20250324_135428_00_033_rot170.mp4
```

想定する出力:

```text
<output_dir>/audit_report.json
<output_dir>/audit_report.csv
```

監査レポートに残したい内容:

- 検査日時
- 入力パス
- 検査した成果物種別
- 件数サマリ
- 欠損frame一覧
- 重複frame一覧
- 壊れJPEG一覧
- EXIF不足一覧
- CSV/GPKG/JSON間の不整合一覧
- 総合判定 `ok` / `warning` / `error`

将来的に、`validate_outputs.py` はQGISプラグイン本体から切り離した純Python CLIとして実装します。QGISから呼ぶ場合も、内部処理は同じCLI相当の関数を使い、監査結果だけをmessageBarへ短く表示します。

## 今後の改善候補

- `main.py` のCSV/JSON書き出しを一時ファイル置換へ変更する。
- `viewer_controller.py` のruntime config書き込みを一時ファイル置換へ変更する。
- レーダ計算の純Python部分をQGIS非依存関数へ切り出し、FOV/CalDist/クリック投影をユニットテスト化する。
- `common.py` のQGIS依存を薄くし、フレームパス規則やCSV列検出をテスト可能にする。
- Exporterのmanifest/summaryを書き込み途中で失敗した場合の再開方針を明確化する。
- サンプルGPX/CSV/小型MP4を使ったスモークテストを追加する。
- QGIS実機チェックリストをリリース手順へ組み込む。
- `viewer_controller.py` 側のmessageBar呼び出しも `messages.py` 経由へ移行する。
- 将来的にUI設定またはプロジェクト設定から `GPX_VIDEO_PROCESSOR_LOCALE` 相当を選べるようにする。
- `logging_utils.py` を追加し、operation/debugログをファイルへ出す。
- Self Checkメニューを追加し、環境診断JSONを出力する。
- Performance Probeを追加し、動画read/JPEG encode/I/O性能を簡易測定する。
- Runtime Monitorを追加し、長時間バッチ中の速度低下や連続エラーを検知する。
- 成果物整合チェックCLIまたはメニューを追加する。
