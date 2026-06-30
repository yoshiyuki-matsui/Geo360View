# tenkaku_ninja_poi 方向性メモ

このメモは、GPXVideoProcessor内で育ってきた360 semantic pipelineを、
将来的に `tenkaku_ninja_poi` として専用特化させるための役割定義と接続方針を整理するものです。

結論から言うと、これはQGISプラグインの1機能ではなく、360動画/GNSS/AI検出から
POI候補を生産する独立した処理ラインです。QGISプラグインは成果を確認・レビューする作業台、
coreは案件投入と全体管理、modelはモデル工房として分けます。

## 1. 役割定義

```text
tenkaku_ninja_core
  受付、フォルダ監視、ジョブ投入、状態管理、成果物管理、通知。
  工程の中身は深く知らず、規約化されたpipeline/jobを呼ぶ。

tenkaku_ninja_model
  dataset作成、dig、自動アノテーション、学習、評価、モデル改善。
  モデルを作り、poi pipelineへ供給する。

tenkaku_ninja_poi
  360動画/GNSS/YOLO/model runからPOI候補を生産する処理ライン。
  CubeMap、YOLO、Report、semantic_targets、georeference、gpkg_mergeを担う。

GPXVideoProcessor / QGIS Plugin
  GPKG、地図、360証跡、NAV、採否判断のUI。
  重いGPU処理や長時間バッチは抱え込まない。

POI Center
  これらを現場サービスとして提供する運用/事業上の名前。
```

`tenkaku_ninja_poi` は、地図を作るシステムではありません。
巨大な360視覚情報から、現場が確認・判断するための軽量な意味情報を抽出するPOI生成エンジンです。

## 2. 境界線

### tenkaku_ninja_poi が持つもの

- `semantic_work.sqlite`
- CubeMap生成
- YOLO推論
- auto batch / GPU負荷調整
- checkpoint / resume
- YOLOレポート
- bboxから360 targetへの変換
- 360 targetからPOI候補への変換
- GPKG/CSV/HTML/JSON出力
- 停止フレーム、巨大bbox、対象class、faceなどの非破壊フィルタ
- モデル別/メニュー別レイヤ出力

### tenkaku_ninja_poi が持たないもの

- QGIS上の地物編集UI
- 公式台帳の主管
- 基幹GISやArcGISの置き換え
- NAS/PC/GPU/ネットワークの一次保守
- 詳細測量成果そのもの
- 補修優先度や現場判断の最終決定

### QGIS Plugin が持つもの

- `tmp.gpkg` の読み込み
- `poi_candidates_360` / `poi_candidates_{model_slug}_360` のNAV確認
- 360ビューアでの証跡確認
- 採用/除外/保留のレビューUI
- 手動Pickerとの相互運用

QGISは食べる場所、`tenkaku_ninja_poi` は厨房です。
この分離を守ると、QGIS Python環境、GPU依存、長時間ジョブ、DB lock、UI固まりが絡みにくくなります。

`tmp.gpkg` は GPXVideoProcessor が位置合わせまで終えた入力です。
`gpkg_merge.py` が書き出す `auto_poi.gpkg` は conductor の出力です。
つまり、conductor の入力は `tmp.gpkg`、出力は `auto_poi.gpkg` です。

## 3. 現在のpipeline

現在の処理ラインは次の形です。

```text
video_gpx_points / MP4
  -> cubemap.py
  -> yolo_detect.py
  -> yolo_report.py
  -> semantic_targets.py
  -> georeference.py
  -> gpkg_merge.py
  -> QGIS / NAV / 360 review
```

各工程の現在の役割:

| stage | 役割 | 主な成果 |
| --- | --- | --- |
| `cubemap` | 360動画からCubeMap各面を生成 | `image_planes`, JPEG |
| `yolo` | CubeMap画像にモデルを適用 | `yolo_detections_raw`, `model_run_id` |
| `report` | 検出結果を人が味見する | `summary.json`, `summary.txt`, HTML, CSV, annotated images |
| `targets` | bboxを360クリック点互換targetへ変換 | `semantic_targets_360` |
| `georef` | targetを地図上の候補点へ変換 | `poi_candidates_360` |
| `cluster` | 複数観測を束ねて代表POIを作る | `poi_clusters_360`, `poi_cluster_members_360` |
| `merge` | QGISで開くGPKGへ出荷 | `auto_poi.gpkg` 内の `poi_candidates_{model_slug}_360`, `All_Classes`, `poi_clusters_<class>` |

重要なのは、`yolo_detections_raw` を原観測として残すことです。
停止中の重複、誤検出、大きすぎるbbox、海外モデルの癖も、まずは観測ログとして残します。
業務候補として見る段階で、レポートやPOI候補化のフィルタを使って圧縮します。
さらに `poi_cluster.py` で同一POIらしい候補を束ねます。代表点はクラスタ中心、
代表観測はfaceごとの移動ルールで選びます。`front/left/right` は後半、
`back` は前半、`up/down` は中央の観測を優先し、bboxサイズも加点します。
空中物は10mなどの固定距離に仮置きした点ではなく、撮影点と方位から作る観測レイで
中心を推定し、`direction_cluster_radius_m` で地面系とは別に集約幅を持たせます。

## 4. core との共通規約

今すぐcoreへ混ぜ込むのではなく、coreが呼べる外部pipelineとして規約を揃えます。

### 入力規約

将来的な入力は `pipeline.yml` に寄せます。

```yaml
project_id: VID_20250324_135428_033_rot170
video: /mnt/d/nexco/VID_20250324_135428_00_033_rot170.mp4
gpkg: /mnt/d/nexco/VID_20250324_135428_033_rot170/tmp.gpkg
work_db: /mnt/d/nexco/VID_20250324_135428_033_rot170/semantic_work.sqlite
work_dir: /mnt/d/nexco/VID_20250324_135428_033_rot170

detectors:
  - name: pothole_detector
    model: /mnt/nfs/WatchFolder/Models/pothole_yolo8m.pt
    classes: [pothole]
    faces: [front, down]
    conf: 0.25
    layer_name: poi_candidates_pothole_360
    batch: auto
    auto_batch_candidates: [16, 24, 32, 48]
    auto_batch_safety_margin: 0.25

  - name: traffic_sign_detector
    model: /mnt/nfs/WatchFolder/Models/traffic_sign_detector.pt
    faces: [front, back, left, right, up]
    conf: 0.25
    layer_name: poi_candidates_traffic_sign_360

filters:
  max_bbox_area_ratio: 0.30
  exclude_stationary: true
  stationary_distance_m: 0.5
```

### 実行規約

coreから見える実行単位は、stageとjobです。

```text
stage:
  cubemap
  yolo
  report
  targets
  georef
  merge

job status:
  pending
  running
  complete
  failed
  interrupted
  skipped
```

CLIの入口イメージ:

```bash
tenkaku-ninja-poi run pipeline.yml
tenkaku-ninja-poi run pipeline.yml --stages yolo report
tenkaku-ninja-poi resume pipeline.yml
tenkaku-ninja-poi status --job-id job_...
```

### 成果物規約

coreが知ればよい成果は、工程の中身ではなく成果物と状態です。

```text
semantic_work.sqlite
logs/{stage}.log
summaries/{stage}.summary.json
reports/{model_name}/index.html
tmp.gpkg
poi_candidates_{model_slug}_360
```

各stageは最後に `summary.json` を出します。
stdoutは人間向けログ、`summary.json` はcore/GUI/ダッシュボード向けの正本にします。

共通summaryの最小形:

```json
{
  "job_id": "job_...",
  "stage": "yolo",
  "status": "complete",
  "run_id": "run_...",
  "model_run_id": "model_...",
  "started_at": "2026-06-20T01:36:11Z",
  "finished_at": "2026-06-20T01:57:57Z",
  "elapsed_seconds": 1305.94,
  "input_count": 66500,
  "output_count": 7737,
  "skipped_count": 0,
  "artifacts": {
    "work_db": "/path/to/semantic_work.sqlite",
    "report_dir": "/path/to/yolo_report",
    "gpkg": "/path/to/tmp.gpkg"
  }
}
```

## 5. GUIの方向性

GUIは重い処理を抱え込まず、pipeline操作盤にします。

主な画面:

| view | 役割 |
| --- | --- |
| Jobs | 案件一覧、stage状態、ETA、失敗/再開 |
| CubeMap | 生成枚数、skip数、checkpoint、ログ |
| YOLO | model_run_id、auto batch、detections、img/s |
| Report | class summary、HTMLリンク、annotated画像数 |
| POI | targets、georef、skip理由、layer名 |
| GPU | nvitop相当、VRAM、実行中プロセス |

大事なのは、全ログを1つの画面に押し込まないことです。
工程ごとに最新summaryをカード表示し、必要なときだけ詳細ログを開きます。

開発中のterminal運用も、この設計に近いです。

```text
CubeMap tab
YOLO tab
Report tab
POI tab
nvitop tab
```

GUI化しても、この工程別の見通しを保ちます。

## 6. 停止時間と重複観測の扱い

車両や列車の実撮影では、停車時間が無視できません。
信号待ち、渋滞、駅停車、SA/PA滞在により、同じ対象を大量に検出します。
極端な場合、ローカル線などでは撮影時間の1/3が停止または低速区間になることもあります。

方針:

- YOLO raw検出は全件残す。
- レポートでは `--exclude-stationary` で確認対象から外せる。
- POI候補化では `georeference.py --exclude-stationary` で `stationary_camera` としてskipできる。
- 将来的にはYOLO前に、停止区間を代表フレームだけに間引く前段フィルタを検討する。

rawを消さないのは、後から別モデル、別閾値、別クラスタリング方針で再評価できるようにするためです。
捨てるのではなく、業務候補へ出す段階で圧縮します。

## 7. 近い実装目標

### Phase 1: CLI資産の整理

- `tenkaku_ninja_poi` へ移す対象moduleを明確化する。
- 各CLIに `--summary-json` を追加する。
- stage名、status、artifact名を揃える。
- `yolo_report.py` のような読み取り専用工程はDBへ書き戻さない。
- model別レイヤ名は `poi_candidates_{model_slug}_360` に統一する。

### Phase 2: pipeline.yml

- 1案件1YAMLで、video/gpkg/work_db/models/layers/filterを定義する。
- `--dry-run` で実行予定コマンドを表示する。
- `--stages` で部分実行する。
- `--resume` でcheckpoint済み工程を継続する。

### Phase 3: job/orchestrator

- `jobs.sqlite` またはjob JSONで状態管理する。
- stageごとに `logs/{stage}.log` と `summary.json` を残す。
- 失敗時にresume可能かを表示する。
- GPU/CPU/I/O heavyなど、resource profileを持たせる。

### Phase 4: GUI

- pipeline.ymlを編集/生成する。
- stageごとの最新summaryを表示する。
- HTMLレポート、GPKG、ログ、QGISを開く導線を作る。
- 重い処理はサブプロセスで走らせ、GUIは状態監視に徹する。

### Phase 5: core連携

- coreは `tenkaku-ninja-poi run pipeline.yml` をジョブとして呼ぶ。
- coreはstage summaryとartifactだけを見る。
- coreはPOI生成の内部実装を知らない。
- 監視、通知、成果管理、ダッシュボードへ集約する。

## 8. Docker/エッジ運用

将来的な量産ラインでは、次の構成を目指します。

```text
Linux host
  NVIDIA Driver
  NVIDIA Container Toolkit
  Docker Engine
  NAS mount

tenkaku_ninja_poi containers
  worker
  orchestrator
  api/review
  doctor/benchmark
```

巨大な360動画やCubeMap画像は現場NASに置き、GPU処理もデータの近くで行います。
中央やAWSへ送るのは、採用済みPOI、候補サマリ、レビュー状態、軽量な証跡リンクです。

考え方:

```text
生データは現場。
意味情報は共有。
```

これはクラウド否定ではありません。
TB級の生映像処理はエッジで行い、全社ダッシュボード/API/集計はクラウドや既存基盤へつなぎます。

## 9. 事業上の位置づけ

`tenkaku_ninja_poi` は、POI Centerの厨房/データ工場です。

GIS屋、分析屋、コンサル、全社ダッシュボードは、POIを使って価値を出します。
`tenkaku_ninja_poi` は、その前段で現場由来の新鮮なPOIを継続生産します。

```text
現場には厨房として寄り添う。
全社にはPOIデータ工場として供給する。
```

標準メニューは用意しますが、本質は現場の「それ見たい」に対して、
まず試作品を出し、使えるものを定番化することです。

## 10. 当面の判断

- `tenkaku_ninja_poi` は独立プロジェクト名として妥当。
- 現在の `TenkakuNinja/` 内semantic系CLIは、将来的にpoi側へ切り出す候補。
- coreとの統合は、コード統合ではなく規約統合から始める。
- `pipeline.yml` と `summary.json` を接続の重心にする。
- QGISプラグインは重い処理を持たず、確認・レビューの作業台に寄せる。
- raw検出は消さず、レポート/POI候補化/クラスタリングで業務候補へ圧縮する。

この方針なら、世界が膨張しても、core/model/poi/QGISの責任境界を保ったまま自然に収束できます。
