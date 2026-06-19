# 360 Semantic Pipeline 設計メモ

更新日: 2026-06-18

この文書は、360動画をCubeMap化し、YOLO物体検出結果をクリック点互換の
`semantic_targets_360` へ加工し、最終的に地図上のPOI候補へ変換するための
CLIパイプライン設計メモです。

当初の設計メモです。現時点では主要CLIをGPXVideoProcessor内の
`TenkakuNinja/` 配下で単体CLIとして動かし、将来的に
`tenkaku_ninja_core` へ合流できる構成にします。

## 位置づけ

本処理はQGISプラグイン本体の機能ではなく、TenkakuNinjaCore側に近い
データ処理工場です。

```text
QGISプラグイン
  360ビューア、手動クリック、確認、GPKG表示

TenkakuNinja CLI
  フレーム抽出、CubeMap生成、YOLO推論、中間DB生成、POI候補化

venv_yolo
  opencv-python, py360convert, ultralytics などの重い依存
```

QGIS Python環境へYOLOやpy360convertを混ぜないことを原則にします。プラグインは
生成済みのSQLite/GPKGを受け取り、表示・確認・補正だけを担当します。

## 目的

目的は、YOLO検出結果を直接緯度経度化することではありません。

まず、CubeMap上のYOLO bboxを、人が360ビューア上でクリックした点と同じ意味の
中間データへ変換します。

```text
YOLO bbox
-> CubeMap face内の代表点
-> cubemap u/v
-> camera ray
-> target_yaw_to_camera_heading
-> target_pitch_deg
-> semantic_targets_360
```

その後、既存のクリック点投影ロジックと同じ考え方で、撮影点、trajectory heading、
video front offset、CamH/HudH、ground distanceから地図上のPOI候補を作ります。

```text
semantic_targets_360
+ video_gpx_points
+ job metadata
= poi_candidates_360
```

## 基本原則

- QGIS APIに依存しないCLIとして作る。
- `frame_index` を全工程の不変キーにする。
- 中間DBの正本は、まず `semantic_work.sqlite` とする。
- Core合流時にはParquetへ寄せられるように、表形式・run_id中心で設計する。
- YOLO結果をいきなり地物点にしない。
- `semantic_targets_360` をクリック点互換インタフェースとする。
- CubeMap変換ツールは交換可能にし、後段ではface規約を正規化して扱う。
- 出自、モデル、設定、face規約、anchor policyをメタデータとして残す。
- 浮いている対象を無理に地面点へしない。`direction_only` や `elevated_object` として扱う。
- 同じ `run_id` に複数のYOLOモデル実行を追記できるようにする。
- 長時間処理はAll-or-Nothingにしない。チェックポイントごとにDBへcommitし、途中停止後も
  既存成果を再利用できるようにする。

## 全体フロー

```text
tmp.gpkg + source.mp4
  |
  | 1. export-frames
  v
images/
  0000/frame_0000030.jpg
  |
  | 2. cubemap
  v
work/cubemap/
  0000/frame_0000030_front.jpg
  0000/frame_0000030_right.jpg
  0000/frame_0000030_back.jpg
  0000/frame_0000030_left.jpg
  0000/frame_0000030_up.jpg
  0000/frame_0000030_down.jpg
  |
  | 3. yolo-detect
  v
semantic_work.sqlite
  image_planes
  model_runs
  yolo_detections_raw
  |
  | 3.5 yolo-report
  v
yolo_report/
  summary.txt
  detections.csv
  annotated/0000/frame_0000030_front_annotated.jpg
  |
  | 4. build-targets
  v
semantic_work.sqlite
  semantic_targets_360
  |
  | 5. georef-targets
  v
semantic_work.sqlite
  poi_candidates_360
  |
  | 6. merge-gpkg
  v
tmp.gpkg
  yolo_observations_360
  semantic_targets_360
  poi_candidates_360
```

最初の実装では、CubeMap生成、YOLO推論、`semantic_targets_360` 作成までを
優先します。緯度経度化は既存クリック点投影の純粋関数化と合わせて後段で実装します。

## venv_yolo

想定する実行環境です。

```bash
python -m venv venv_yolo
source venv_yolo/bin/activate
pip install opencv-python py360convert ultralytics numpy
```

Windows/WSL混在運用では、動画パス、GPKGパス、出力先をすべてCLI引数で明示します。

## CLI構想

既存の `TenkakuNinja/main.py` はExporter入口です。将来的にはサブコマンド化します。

```bash
python -m TenkakuNinja.cli export-frames \
  --database tmp.gpkg \
  --video source.mp4 \
  --frames 30,60,90

python -m TenkakuNinja.cli cubemap \
  --database tmp.gpkg \
  --video source.mp4 \
  --size 1024 \
  --work-db work/semantic_work.sqlite

python -m TenkakuNinja.cli yolo-detect \
  --work-db work/semantic_work.sqlite \
  --model models/assets.pt \
  --model-name traffic_sign_detector \
  --faces front left right \
  --conf 0.35

python -m TenkakuNinja.cli yolo-detect \
  --work-db work/semantic_work.sqlite \
  --model models/pothole.pt \
  --model-name pothole_detector \
  --faces down \
  --conf 0.35

python -m TenkakuNinja.cli build-targets \
  --work-db work/semantic_work.sqlite

python -m TenkakuNinja.cli georef-targets \
  --work-db work/semantic_work.sqlite \
  --database tmp.gpkg

python -m TenkakuNinja.cli merge-gpkg \
  --work-db work/semantic_work.sqlite \
  --database tmp.gpkg
```

最終的にはまとめ実行も用意します。

```bash
python -m TenkakuNinja.cli pipeline \
  --database tmp.gpkg \
  --video source.mp4 \
  --model models/assets.pt \
  --cubemap-faces all \
  --yolo-faces front left right
```

## ディレクトリ構成案

```text
TenkakuNinja/
  README.md
  semantic_360_pipeline.md
  main.py
  exporter.py
  geo_util.py
  beat_utils.py

  cli.py                 # planned: サブコマンド入口
  schema.py              # SQLiteスキーマ定義
  sqlite_io.py           # semantic_work.sqlite IO
  cubemap.py             # equirectangular -> CubeMap
  yolo_detect.py         # YOLO推論
  yolo_report.py         # YOLO結果のサマリー・注釈画像
  semantic_targets.py    # bbox -> クリック点互換target
  georeference.py        # semantic target -> POI候補
  gpkg_merge.py          # 中間DB -> tmp.gpkg
  projection.py          # QGIS非依存の方位・距離・WGS84投影
```

## 各pyの責務

### `main.py`

現状のExporter CLI入口です。

- `python TenkakuNinja/main.py ...` で単体実行できる。
- 現在は `exporter.py` の `main()` を呼ぶだけの薄い入口。
- 将来サブコマンド化する場合も、既存Exporter互換の入口は維持します。

### `exporter.py`

既存のequirectangular静止画Exporterです。

- `tmp.gpkg` と元MP4を読み、条件に合うフレームをOpenCVで抽出する。
- `images/{frame//1000:04d}/frame_{frame:07d}.jpg` の保存規則を維持する。
- OpenCV抽出を正とし、ffmpeg抽出とは混ぜない。
- 将来的には `--cubemap` オプションでCubeMap生成を同時実行してもよい。

ただし、責務を膨らませすぎないため、CubeMap生成本体は `cubemap.py` に分離します。

### `geo_util.py`

GPX同期・時刻解釈・フレーム補間の補助関数です。

- QGIS非依存で使える。
- `frame_index` と緯度経度の対応を作る処理で再利用できます。
- 今回の360 semantic pipelineでは、`tmp.gpkg` に `video_gpx_points` がない場合の
  補助経路として使う候補です。

### `beat_utils.py`

音声ビート同期の旧ユーティリティです。

- 今回の360 semantic pipelineの主処理では使わない。
- 音声同期方式を戻す場合の候補として残します。

### `cli.py` planned

新しいサブコマンド入口です。

- `export-frames`
- `cubemap`
- `yolo-detect`
- `build-targets`
- `georef-targets`
- `merge-gpkg`
- `pipeline`

を束ねます。

### `schema.py`

`semantic_work.sqlite` のテーブル定義、スキーマバージョン、列名定数を持ちます。

- テーブル定義をコード内に散らさない。
- Core合流時にParquetスキーマへ写せる粒度で定義する。
- `schema_version` を `runs` と `metadata` に残します。

### `sqlite_io.py`

SQLite中間DBの読み書きを担当します。

- `semantic_work.sqlite` を作成する。
- `runs`, `image_planes`, `model_runs`, `yolo_detections_raw`,
  `semantic_targets_360`, `poi_candidates_360` を読み書きする。
- `run_id` 単位で追記できるようにする。

### `cubemap.py`

equirectangular静止画またはOpenCVで読んだ動画フレームからCubeMap面を生成します。

想定変換エンジン:

- `py360convert`
- custom OpenCV/NumPy remap
- krpanotools fallback

後段には必ず共通規約で渡します。

```text
face_name: front / right / back / left / up / down
face_convention: normalized_f_r_b_l_u_d_v1
```

CubeMap生成段階では、既定で6面すべてを書き出します。

```text
front, right, back, left, up, down
```

これは、後段のYOLO対象面を変えても同じ派生画像セットを再利用できるようにするためです。

現在の単体CLI:

```bash
python TenkakuNinja/cubemap.py \
  --database tmp.gpkg \
  --video source.mp4 \
  --work-db work/semantic_work.sqlite \
  --faces all \
  --size 1024 \
  --checkpoint-interval 100
```

出力規則:

```text
work/cubemap/{frame//1000:04d}/frame_{frame:07d}_{face}.jpg
```

CubeMap生成は `--checkpoint-interval` ごとに、生成済み・既存画像の `image_planes` 登録と
`metadata(scope='run', key='cubemap_checkpoint')` をcommitします。Ctrl+Cで中断した場合も、
直前checkpointまでのDB登録は残ります。同じ `--run-id` で再実行すると、既存JPEGは
`existing` として登録更新され、不足分だけ生成されます。`--overwrite` を付けた場合は
画像を再生成します。

### `yolo_detect.py`

CubeMap画像面にYOLOモデルを実行し、生の検出結果を保存します。

- 入力は `image_planes`。
- `image_planes` には6面すべてが入っていてよい。
- YOLOを実行する面は `--faces` または設定ファイルで明示する。
- 出力は `model_runs` と `yolo_detections_raw`。
- bboxは画像座標のまま保存する。
- この段階ではyaw/pitchや緯度経度を作らない。

現在の単体CLI:

```bash
python TenkakuNinja/yolo_detect.py \
  --work-db work/semantic_work.sqlite \
  --model models/assets.pt \
  --model-name traffic_sign_detector \
  --faces front left right \
  --conf 0.35 \
  --chunk-size 100
```

`image_planes.image_path` は `runs.work_dir` からの相対パスとして解決します。

同じ `run_id` へ複数回実行できます。たとえば標識モデルを `front/left/right`、
ポットホールモデルを `down` にかける場合、`model_runs` に2行、
`yolo_detections_raw` にそれぞれの `model_run_id` 付き検出結果が追記されます。
SQLiteの同時書き込みは避け、CLIをモデルごとに順番に実行する運用を標準とします。

YOLO推論は `--chunk-size` ごとに `yolo_detections_raw` と
`metadata(scope='model_run', key='yolo_detection_checkpoint')` をcommitします。
Ctrl+Cで中断しても、完了済みchunkの検出結果はDBに残ります。再開する場合は、
同じ `--model-run-id` と `--resume` を指定します。

```bash
python TenkakuNinja/yolo_detect.py \
  --work-db work/semantic_work.sqlite \
  --run-id run_xxx \
  --model models/traffic_sign.pt \
  --model-run-id model_xxx \
  --faces front left \
  --resume
```

resume時は、`metadata(scope='model_run', key='yolo_detection_checkpoint')` の
`processed_plane_count` を優先し、checkpoint済みの画像面をスキップします。
検出0件だった面も、checkpoint済みであれば再処理対象から外れます。
古いDBなどcheckpointがない場合は、既に1件以上の検出がある `plane_id` もスキップ候補として扱います。

GPU推論では `--batch auto` を指定できます。候補batchを短く試運転し、throughputとVRAM使用量を見たうえで、
最速候補から `--auto-batch-safety-margin` 分の余裕を取ったbatchを選択します。

```bash
python TenkakuNinja/yolo_detect.py \
  --work-db work/semantic_work.sqlite \
  --model models/pothole.pt \
  --model-name pothole_detector \
  --faces front down \
  --device 0 \
  --conf 0.25 \
  --batch auto \
  --auto-batch-candidates 16,24,32,48 \
  --auto-batch-safety-margin 0.25
```

長時間運用では最高速batchよりも、GPUメモリと他ジョブに余裕を残す安定batchを優先します。

想定例:

```bash
python TenkakuNinja/yolo_detect.py \
  --work-db work/semantic_work.sqlite \
  --model models/traffic_sign.pt \
  --model-name traffic_sign_detector \
  --faces front left

python TenkakuNinja/yolo_detect.py \
  --work-db work/semantic_work.sqlite \
  --model models/road_marking.pt \
  --model-name road_marking_detector \
  --faces down

python TenkakuNinja/yolo_detect.py \
  --work-db work/semantic_work.sqlite \
  --model models/sign_back_rust.pt \
  --model-name sign_back_rust_detector \
  --faces back
```

この場合でも、抽出DBは分けません。`yolo_detections_raw` と `semantic_targets_360` は
全部入りの観測ログとして保持し、表示・GPKG merge・QGISレイヤ化の段階で
`model_name`, `model_run_id`, `face_name`, `class_name`, `projection` によって
切り分けます。

### `yolo_report.py`

YOLO検出結果を人が確認するためのファイル一式を生成します。

- `summary.txt`: 件数、クラス別件数、面別件数の短いログ。
- `summary.json`: 同じ内容の機械処理用JSON。
- `detections.csv`: 検出ごとのbbox、bbox面積率、信頼度、元画像、注釈画像、semantic target情報。
- `class_summary.csv`: クラス別サマリー。
- `face_summary.csv`: face別サマリー。
- `index.html`: 注釈画像を信頼度順にざっと見るHTMLギャラリー。
- `annotated/`: 元CubeMap画像にbboxとラベルを描いた確認用JPEG。

現在の単体CLI:

```bash
python TenkakuNinja/yolo_report.py \
  --work-db work/semantic_work.sqlite
```

必要に応じて対象を絞れます。

```bash
python TenkakuNinja/yolo_report.py \
  --work-db work/semantic_work.sqlite \
  --faces front left right \
  --model-names traffic_sign_detector \
  --classes Stop "Speed Limit 40" \
  --min-conf 0.5 \
  --max-bbox-area-ratio 0.30 \
  --max-images 200
```

この工程は地図座標を作りません。モデルの誤検出、誤分類、bboxの当たり方を確認するための
検査出口です。`semantic_targets_360` 作成後に実行すると、`detections.csv` に
`target_yaw_to_camera_heading`, `target_pitch_deg`, `projection`, `quality` も併記します。

`--max-bbox-area-ratio` は、生の `yolo_detections_raw` を消さずにレポート対象だけを
絞るためのフィルタです。標識や信号のような小物体で、CubeMap面の3割以上をbboxが
占める検出は誤検出候補として扱えます。

複数モデルが同じDBに入っている場合は、`--model-names` または `--model-run-ids` で
確認対象を切り出します。`model_run_summary.csv` にはモデル実行単位の件数を出力します。

### `semantic_targets.py`

このパイプラインの肝です。

YOLO bboxをクリック点互換の `semantic_targets_360` に変換します。

```text
cubemap_face + bbox_anchor
-> cubemap_u/v
-> camera_ray
-> target_yaw_to_camera_heading
-> target_pitch_deg
```

ここで作るtargetはまだ地物ではありません。360空間上の意味付きターゲットです。

現在の単体CLI:

```bash
python TenkakuNinja/semantic_targets.py \
  --work-db work/semantic_work.sqlite \
  --camera-height-m 2.0 \
  --hud-height-scale 1.0 \
  --model-names traffic_sign_detector \
  --max-bbox-area-ratio 0.30 \
  --clear-existing
```

`target_pitch_deg` は既存360ビューアと同じく下向きを正とします。CubeMap rayは
+Yを上として計算するため、rayからpitchを作る時点で上下符号を反転します。

`ground_distance_m` は、クラス別policyが `ground_plane` で、かつpitchが地面交差に
使える場合だけ作ります。標識板や信号機のように地面上の点とは限らない対象は、
初期実装では `elevated_object` または `direction_only` にします。

`--max-bbox-area-ratio` を指定した場合、bbox面積が画像面積に対して閾値を超える検出は
`semantic_targets_360` に進めません。YOLOの生検出は `yolo_detections_raw` に残るため、
閾値を変えて再生成できます。

`--model-names` または `--model-run-ids` を指定した場合は、そのモデル由来の検出だけを
target化します。`--clear-existing` と併用しても、指定モデル由来の既存targetだけを
削除するため、別モデルのtargetを巻き込みません。

### `projection.py`

QGIS非依存の投影コアです。

`radar.py` と同じ方位・距離・WGS84投影の数式をCLI側で使うための純粋関数群です。

```text
destination_point(lat, lon, bearing_deg, distance_m)
local_vector_meters(lat1, lon1, lat2, lon2)
heading_from_vector(dx, dy)
trajectory_heading(positions_by_frame, frame_index, window_frames)
```

### `georeference.py`

`semantic_targets_360` を読み、`poi_candidates_360` を作ります。

- `video_gpx_points` から撮影点を取得する。
- trajectory headingを計算する。
- `projection.py` で `object_lat/lon` を作る。
- `quality`, `position_method`, `distance_method` を保存する。
- `ground_plane` は `ground_distance_m`、`elevated_object` と `direction_only` は
  `--fallback-distance-m` の固定外円を使う。

### `gpkg_merge.py`

中間DBの結果を `tmp.gpkg` へ別レイヤとして追加します。

現在の実装レイヤ:

- `poi_candidates_360`

手動クリック点の `click_targets_360` とは分けます。`semantic_work.sqlite` は処理途中の
内部DB、ユーザがQGISで開いて操作する対象は `tmp.gpkg` です。

NAVモードで自動認識できるように、GPKGへ出す候補レイヤ名は標準化します。

- 汎用候補レイヤ: `poi_candidates_360`
- モデル別候補レイヤ: `poi_candidates_{model_slug}_360`

QGISプラグインは、GPKG読込時にまず `poi_candidates_360` を探します。
存在しない場合は、`gpkg_contents` のfeatures layerから `poi_candidates...` 系レイヤを探し、
`360 Detection Candidates` の一時メモリレイヤとして読み込みます。
このレイヤがNavの `Detection check` 対象になります。

`DetectionCheck` など任意のレイヤ名は標準運用では使わず、モデル別に分けたい場合も
`poi_candidates_` prefix を維持します。

属性には次を持たせます。

- `record_type = yolo_candidate`
- `review_status = unreviewed`
- `semantic_class`
- `model_name`
- `position_method`
- `distance_method`
- `quality`
- `target_yaw`
- `target_pitch`
- `evidence_bbox_json`
- `anchor_x_px / anchor_y_px`
- `cubemap_u / cubemap_v`
- `payload_json`

将来、必要に応じて `yolo_observations_360` や `semantic_targets_360` も別レイヤとして
出力します。

360ビューア上の確認では、CubeMap矩形をequirectangularへ戻すことを基本にしません。
`target_yaw/target_pitch` の点マーカーを表示し、必要に応じて
`evidence_bbox_json` と注釈画像レポートでYOLO矩形の根拠を確認します。

## SQLite中間DB

当面の正本は `semantic_work.sqlite` とします。

Core合流時には、同じ内容をParquetへ出力する可能性があります。ただし本件では
SQLiteを正本とし、プラグインはSQLiteまたはGPKGだけを受け取ります。

### `runs`

1回の処理単位です。自己記述型データの入口になります。

```text
run_id TEXT PRIMARY KEY
schema_version INTEGER
created_at TEXT
updated_at TEXT
status TEXT
source_video TEXT
source_gpkg TEXT
work_dir TEXT
config_json TEXT
notes TEXT
```

### `source_frames`

`tmp.gpkg` の `video_gpx_points` から読み取った撮影点スナップショットです。

```text
run_id TEXT
frame_index INTEGER
source_frame INTEGER
frame_shift INTEGER
timestamp TEXT
camera_lat REAL
camera_lon REAL
aligned_latitude REAL
aligned_longitude REAL
kp TEXT
kp_distance_m REAL
image_path TEXT
PRIMARY KEY (run_id, frame_index)
```

`tmp.gpkg` を毎回読む実装でも構いませんが、長い処理では中間DB側にスナップショットを
持たせる方が再現しやすくなります。

### `image_planes`

YOLOが処理する画像面です。通常画角4K、CubeMap、将来のマルチカメラを同じ概念で扱います。

CubeMap生成段階では6面すべてを登録します。YOLO実行段階では、この表から指定面だけを
選択して `yolo_detections_raw` を作ります。

```text
plane_id TEXT PRIMARY KEY
run_id TEXT
frame_index INTEGER
source_type TEXT          -- equirectangular_360 / normal_camera / cubemap_face
projection_type TEXT      -- equirectangular / pinhole / cubemap_face
plane_name TEXT           -- front / left / right / camera_01
face_name TEXT            -- front / right / back / left / up / down
image_path TEXT
parent_image_path TEXT
width_px INTEGER
height_px INTEGER
converter TEXT            -- py360convert / krpanotools / opencv_remap
converter_version TEXT
face_convention TEXT
transform_json TEXT
created_at TEXT
```

### `model_runs`

YOLOモデル実行単位です。

```text
model_run_id TEXT PRIMARY KEY
run_id TEXT
model_name TEXT
model_path TEXT
model_version TEXT
ultralytics_version TEXT
conf REAL
imgsz INTEGER
device TEXT
classes_json TEXT
params_json TEXT
created_at TEXT
```

### `yolo_detections_raw`

YOLOの生検出結果です。ここでは地図座標を作りません。

```text
detection_id TEXT PRIMARY KEY
run_id TEXT
model_run_id TEXT
plane_id TEXT
frame_index INTEGER
class_id INTEGER
class_name TEXT
confidence REAL
bbox_x1 REAL
bbox_y1 REAL
bbox_x2 REAL
bbox_y2 REAL
bbox_width REAL
bbox_height REAL
bbox_area REAL
bbox_anchor_default TEXT
raw_json TEXT
created_at TEXT
```

### `semantic_targets_360`

クリック点互換インタフェースです。ここが本件の中核です。

```text
target_id TEXT PRIMARY KEY
run_id TEXT
detection_id TEXT
frame_index INTEGER
target_source TEXT        -- yolo_cubemap / manual_click / external
semantic_class TEXT
confidence REAL

target_yaw_to_camera_heading REAL
target_pitch_deg REAL
ground_distance_m REAL
projection TEXT           -- ground_plane / direction_only / elevated_object
quality TEXT              -- trusted / usable / far / unknown

evidence_plane_id TEXT
evidence_image_path TEXT
evidence_face TEXT
evidence_bbox_json TEXT
bbox_anchor TEXT
payload_json TEXT
created_at TEXT
```

クリック点投影ロジックに渡す最小payloadは次です。

```json
{
  "target_yaw_to_camera_heading": 92.4,
  "target_pitch_deg": 18.7,
  "ground_distance_m": 5.8,
  "projection": "ground_plane",
  "quality": "usable"
}
```

YOLO由来の場合は、根拠を `payload_json` または evidence列に残します。

```json
{
  "source": "yolo_cubemap",
  "face": "right",
  "bbox": [120.0, 80.0, 260.0, 340.0],
  "bbox_anchor": "bottom_center",
  "class_name": "traffic_cone",
  "confidence": 0.86
}
```

### `poi_candidates_360`

地図上に落としたPOI候補です。これは `semantic_targets_360` の後段成果です。

```text
candidate_id TEXT PRIMARY KEY
run_id TEXT
target_id TEXT
frame_index INTEGER
target_source TEXT
semantic_class TEXT
confidence REAL
projection TEXT
model_run_id TEXT
model_name TEXT
evidence_face TEXT
camera_lat REAL
camera_lon REAL
object_lat REAL
object_lon REAL
bearing_deg REAL
distance_m REAL
position_method TEXT      -- ground_plane_bearing / fixed_distance_bearing
distance_method TEXT
quality TEXT
payload_json TEXT
created_at TEXT
```

### `metadata`

任意の自己記述メタデータです。

```text
scope TEXT                -- database / run / table / model / converter
scope_id TEXT
key TEXT
value_json TEXT
PRIMARY KEY (scope, scope_id, key)
```

## CubeMap face規約

後段のyaw/pitch変換は、face規約に強く依存します。

初期規約:

```text
camera axes:
  +X = 動画正面から見て右
  +Y = 上
  +Z = 動画正面

face_name:
  front = +Z
  right = +X
  back  = -Z
  left  = -X
  up    = +Y
  down  = -Y
```

CubeMap面内の正規化座標:

```text
-1.0 <= cubemap_u <= 1.0
-1.0 <= cubemap_v <= 1.0
u = 画像右方向
v = 画像下方向
```

YOLO bboxの代表点から以下を作ります。

```text
bbox_anchor_x/y
-> cubemap_u/v
-> camera_ray_x/y/z
-> target_yaw_to_camera_heading
-> target_pitch_deg
```

py360convert、krpanotools、custom remapのどれを使っても、DBに入れる前にこの規約へ
正規化します。

## bbox anchor policy

bbox中心が地物登録点とは限りません。

初期実装のpolicy:

```text
road_surface_damage: center        + ground_plane
road_damage:         center        + ground_plane
pothole:             center        + ground_plane
crack:               center        + ground_plane
manhole:             center        + ground_plane
traffic_cone:        bottom_center + ground_plane
pole:                bottom_center + ground_plane
utility_pole:        bottom_center + ground_plane
sign_post:           bottom_center + ground_plane
road_marking:        center        + ground_plane
pavement_marking:    center        + ground_plane
lane_marking:        center        + ground_plane
crosswalk:           center        + ground_plane
traffic_sign:        center        + elevated_object
signal:              center        + elevated_object
traffic_light:       center        + elevated_object
unknown:             center        + direction_only
```

標識板や信号機のbbox中心は地面点ではないため、初期状態では無理に
`ground_plane` にしません。根元推定やクラス別anchor policyが整うまでは
`direction_only` または `elevated_object` として扱います。

`ground_plane` policyでも、bbox代表点が水平線より上にあり地面交差距離を作れない場合は、
保存時の `projection` を `direction_only` に落とします。意図したpolicyは
`payload_json.policy.requested_projection` に残します。

## georeferenceの考え方

YOLO専用の緯度経度変換を別に作りません。

`semantic_targets_360` をクリック点互換payloadにして、既存のクリック点投影と同じ
数式へ渡します。

必要入力:

```text
frame_index
camera_lat/lon
trajectory_heading_deg
video_front_offset_deg
target_yaw_to_camera_heading
ground_distance_m   -- ground_planeのみ。CamH/HudHはsemantic_targets.py側で反映済み
fallback_distance_m -- elevated_object/direction_only用の仮距離
```

出力:

```text
object_lat/lon
bearing_deg
distance_m
quality
position_method
```

距離はここで新たに画像から推定しません。地面対象は `semantic_targets.py` が作った
`ground_distance_m` を使い、高さがある対象は方角だけを信用して固定距離へ置きます。

## tmp.gpkgへのマージ

`tmp.gpkg` は最終確認・QGIS表示用です。中間DBの全情報を無理に詰め込まず、
用途別に別レイヤ化します。

ユーザが操作すべき成果物は `tmp.gpkg` です。`semantic_work.sqlite` はCubeMap生成、
YOLO検出、target化、候補点化の途中成果と監査情報を保持する内部DBとして扱います。

候補:

```text
yolo_observations_360
  YOLO生検出を確認するための観測レイヤ

semantic_targets_360
  クリック点互換targetを確認するための中間レイヤ

poi_candidates_360
  地図上POI候補レイヤ
```

QGISプラグインは、この結果を読み、色分け、根拠画像、quality、確認ステータスを扱います。

## 将来のCore統合

Core合流後は、入力が通常画角4Kでも360動画でも同じ「画像面」単位で扱います。

```text
source
  -> frame
    -> image_plane
      -> model_run
        -> detection
          -> semantic_observation
```

360の場合だけ、CubeMap faceを通じてクリック点互換targetへ変換できます。

通常4Kの場合:

```text
projection_type = pinhole
semantic_observation = image-plane detection
```

360の場合:

```text
projection_type = cubemap_face
semantic_observation
-> semantic_targets_360
```

このため、最初のSQLite設計でも `image_planes` と `model_runs` を分けておきます。

## 未決事項

- CubeMap変換の標準エンジンを `py360convert` にするか、custom OpenCV remapにするか。
- face回転・u/v方向の検証画像をどう作るか。
- YAML設定ファイルをいつ導入するか。
- `semantic_work.sqlite` からParquetへ書き出すタイミング。
- QGISプラグインがSQLiteを直接読むか、GPKGへマージしたものだけ読むか。
- クラス別anchor policyをYAML等の外部設定に出すタイミング。
- 浮いている対象の根元推定を初期実装に入れるか。

## 最初の実装範囲

まずは以下を小さく実装します。1から5までは初期CLIとして実装済みです。

1. `schema.py`
2. `sqlite_io.py`
3. `cubemap.py`
4. `yolo_detect.py`
5. `semantic_targets.py`

最初の到達点:

```text
tmp.gpkg + mp4
-> six CubeMap face images
-> selected-face YOLO raw detections
-> semantic_targets_360
```

この時点では緯度経度化しなくてよいです。クリック点互換payloadが正しく作れることが
最重要です。
