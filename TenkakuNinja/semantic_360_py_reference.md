# 360 Semantic Pipeline Python Reference

更新日: 2026-06-18

この文書は、`TenkakuNinja/` 配下に追加した360 semantic pipeline関連Pythonの
入出力、主要パラメータ、内部処理、チェックポイント仕様をまとめた実装参照です。

次工程は `semantic_targets_360` から `poi_candidates_360` を作る緯度経度変換です。
その前提として、現時点の処理は次の段階まで完了しています。

```text
tmp.gpkg + MP4
  -> cubemap.py
  -> image_planes + CubeMap JPEG
  -> yolo_detect.py
  -> model_runs + yolo_detections_raw
  -> semantic_targets.py
  -> semantic_targets_360
  -> yolo_report.py
  -> summary/CSV/HTML/annotated images
```

## 共通設計

正本DBは `semantic_work.sqlite` です。QGISプラグイン本体へYOLOやCubeMap変換の重い依存を
混ぜないため、これらはQGIS非依存のCLIとして実行します。

重要なキー:

```text
run_id        : 1回の360データ処理単位
frame_index   : 全工程の不変キー
plane_id      : 1つの画像面。CubeMapなら frame + face
model_run_id  : YOLOモデル実行単位
detection_id  : YOLO生検出1件
target_id     : クリック点互換semantic target 1件
candidate_id  : 地図上POI候補 1件 planned
```

複数モデルは同じ `run_id` に追記します。DBは分けません。

例:

```text
front/left/right/up -> traffic_sign_detector
down                -> pothole_detector / road_marking_detector
back                -> sign_back_rust_detector
```

後段では `model_name`, `model_run_id`, `face_name`, `class_name`, `projection`, `quality` で
表示・レポート・GPKGレイヤを切り分けます。

## schema.py

### 役割

`semantic_work.sqlite` のテーブル定義を一元管理します。

### 入力

なし。コード内の `TABLES` 定義がスキーマ正本です。

### 出力

`schema.create_schema(conn)` により、以下のテーブルとindexを作成します。

```text
runs
source_frames
image_planes
model_runs
yolo_detections_raw
semantic_targets_360
poi_candidates_360
metadata
```

### 主なテーブル

`runs`:

```text
run_id
schema_version
source_video
source_gpkg
work_dir
config_json
status
```

`image_planes`:

```text
plane_id
run_id
frame_index
projection_type       -- cubemap_face など
plane_name
face_name             -- front/right/back/left/up/down
image_path
width_px / height_px
converter
face_convention
transform_json
```

`model_runs`:

```text
model_run_id
run_id
model_name
model_path
model_version
ultralytics_version
conf
imgsz
device
classes_json
params_json
```

`yolo_detections_raw`:

```text
detection_id
run_id
model_run_id
plane_id
frame_index
class_id / class_name
confidence
bbox_x1/y1/x2/y2
bbox_width / bbox_height / bbox_area
raw_json
```

`semantic_targets_360`:

```text
target_id
run_id
detection_id
frame_index
target_source          -- yolo_cubemap
semantic_class
confidence
target_yaw_to_camera_heading
target_pitch_deg
ground_distance_m
projection             -- ground_plane / elevated_object / direction_only
quality                -- trusted / usable / far / unknown
evidence_plane_id
evidence_face
evidence_bbox_json
bbox_anchor
payload_json
```

`poi_candidates_360` planned:

```text
candidate_id
run_id
target_id
frame_index
camera_lat / camera_lon
object_lat / object_lon
bearing_deg
distance_m
position_method
distance_method
quality
```

`metadata`:

```text
scope
scope_id
key
value_json
```

チェックポイントやサマリーはここにJSONで保存します。

## sqlite_io.py

### 役割

SQLiteの作成、row dict接続、JSON列のエンコード、各テーブルへの基本insertを担当します。

### 入力

```text
semantic_work.sqlite path
各insert関数の引数
```

### 出力

SQLite接続、または作成されたID:

```text
run_id
plane_id
model_run_id
detection_id
target_id
```

### 主要関数

```text
initialize(path)
connect(path)
create_run(...)
update_run_status(...)
set_metadata(...)
get_metadata(...)
insert_image_plane(...)
insert_model_run(...)
insert_yolo_detection(...)
insert_semantic_target(...)
fetch_rows(...)
```

### 内部処理

- `schema.create_schema()` でスキーマを作成。
- SQLiteの `row_factory` を `sqlite3.Row` にしてdict化しやすくする。
- `*_json` 列は `json.dumps(..., ensure_ascii=False, sort_keys=True)` で保存。
- IDは `prefix_YYYYMMDDTHHMMSS_xxxxxxxx` 形式で生成。

## cubemap.py

### 役割

`tmp.gpkg` のフレーム情報と元MP4から、CubeMap JPEGを生成し、`image_planes` に登録します。

### 入力

```text
tmp.gpkg
MP4 equirectangular 360 video
semantic_work.sqlite
frame selection conditions
```

### 出力

ファイル:

```text
<output_dir>/cubemap/{frame//1000:04d}/frame_{frame:07d}_{face}.jpg
<output_dir>/cubemap_manifest.csv
<output_dir>/cubemap_summary.json
```

DB:

```text
runs
image_planes
metadata(scope='run', key='cubemap_checkpoint')
metadata(scope='run', key='cubemap_summary')
```

### CLI

```bash
python TenkakuNinja/cubemap.py \
  --database tmp.gpkg \
  --layer video_gpx_points \
  --video source.mp4 \
  --work-db work/semantic_work.sqlite \
  --output-dir work \
  --faces all \
  --size 1024 \
  --checkpoint-interval 100
```

### 主要パラメータ

```text
--database             入力GPKG。既定 tmp.gpkg
--video                入力MP4
--work-db              semantic_work.sqlite
--output-dir           CubeMap画像とmanifest出力先
--layer                GPKG layer/table。例 video_gpx_points
--frame-column         frame列名を明示
--frame-start/end      処理フレーム範囲
--frames               カンマ/空白区切りの個別frame
--condition            kp_match=1 などの簡易条件。複数指定可
--where                SQL WHERE断片
--matched-only         kp match系だけ選択
--limit                テスト用件数制限
--faces                all/front/right/back/left/up/down
--size                 CubeMap faceサイズpx。既定1024
--jpeg-quality         1-100。既定92
--overwrite            既存JPEGを上書き
--frames-per-folder    既定1000
--progress-interval    進捗表示間隔
--checkpoint-interval  DB commit/checkpoint間隔
--converter            auto / py360convert / opencv_remap
--run-id               既存runへ追記・再開
```

### 内部処理

1. `exporter.read_frame_records()` でGPKGから対象frame一覧を取得。
2. `runs` を作成、または `--run-id` の既存runを使用。
3. OpenCV `VideoCapture` で対象frameを読む。
4. `py360convert` があれば優先、なければOpenCV remapでCubeMap化。
5. faceごとにJPEGをatomic write。
6. checkpointごとに `image_planes` を登録。
7. `metadata` に進捗・summaryを保存。
8. manifest CSV/JSONを出力。

### 再開・中断仕様

- `--checkpoint-interval` ごとにDB commitします。
- Ctrl+C時も直前checkpointまでの `image_planes` とmetadataは残ります。
- 同じ `--run-id` で再実行すると、既存JPEGは `existing` として扱い、不足分だけ生成します。
- `image_planes` は同じ `run_id + frame_index + face_name` が既にあれば更新し、重複を作りません。
- `--overwrite` を指定すると既存JPEGも再生成します。

## yolo_detect.py

### 役割

`image_planes` から指定faceを選び、Ultralytics YOLOを実行し、生検出を
`yolo_detections_raw` に保存します。

### 入力

```text
semantic_work.sqlite
image_planes
YOLO .pt model
faces
model metadata
```

### 出力

DB:

```text
model_runs
yolo_detections_raw
metadata(scope='model_run', key='yolo_detection_checkpoint')
metadata(scope='model_run', key='yolo_detection_summary')
```

### CLI

```bash
python TenkakuNinja/yolo_detect.py \
  --work-db work/semantic_work.sqlite \
  --run-id run_xxx \
  --model models/traffic_sign.pt \
  --model-name traffic_sign_detector \
  --faces front left right up \
  --conf 0.25 \
  --chunk-size 100 \
  --device cpu
```

ポットホールなど別モデルを同じDBに追記:

```bash
python TenkakuNinja/yolo_detect.py \
  --work-db work/semantic_work.sqlite \
  --run-id run_xxx \
  --model models/pothole.pt \
  --model-name pothole_detector \
  --faces down \
  --conf 0.25 \
  --chunk-size 100
```

再開:

```bash
python TenkakuNinja/yolo_detect.py \
  --work-db work/semantic_work.sqlite \
  --run-id run_xxx \
  --model models/traffic_sign.pt \
  --model-run-id model_xxx \
  --faces front left right up \
  --resume
```

### 主要パラメータ

```text
--work-db           semantic_work.sqlite
--model             YOLO .pt
--run-id            対象run。省略時は最新run
--faces             YOLO対象face。既定 front left right
--conf              confidence閾値。既定0.25
--imgsz             YOLO入力サイズ
--device            cpu/cudaなど
--limit             テスト用image plane件数制限
--model-name        model_runs.model_name
--model-version     model_runs.model_version
--model-run-id      明示model_run_id
--progress-interval 進捗表示間隔
--chunk-size        YOLO predict単位。既定100
--resume            既存model_run_idの再開
```

### 内部処理

1. `runs` と `image_planes` をDBから取得。
2. `faces` に合うCubeMap画像だけ選択。
3. YOLOモデルをロード。
4. `model_runs` を作成。明示 `--model-run-id --resume` の場合は既存行を再利用。
5. `chunk_size` ごとに `model.predict()` 実行。
6. bbox/class/confを正規化して `yolo_detections_raw` にinsert。
7. chunkごとにcheckpoint metadataを保存。

### 再開・中断仕様

- chunkごとにDB commitします。
- Ctrl+C時も完了済みchunkはDBに残ります。
- 既存 `--model-run-id` を使う場合は `--resume` が必須です。指定しない場合は重複防止でエラー。
- resume時は、既に1件以上の検出がある `plane_id` をスキップします。
- 検出0件だった面は現仕様では再処理される可能性があります。完全な0件処理済み管理が必要なら、将来 `processed_planes` 表を追加します。

## semantic_targets.py

### 役割

YOLO bboxを360ビューアの手動クリック点と互換の `semantic_targets_360` に変換します。

ここでは緯度経度を作りません。

### 入力

```text
semantic_work.sqlite
yolo_detections_raw
image_planes
model_runs
camera height / HudH scale
class policy
```

### 出力

DB:

```text
semantic_targets_360
metadata(scope='run', key='semantic_target_summary')
```

### CLI

```bash
python TenkakuNinja/semantic_targets.py \
  --work-db work/semantic_work.sqlite \
  --run-id run_xxx \
  --camera-height-m 2.0 \
  --hud-height-scale 1.0 \
  --max-bbox-area-ratio 0.30 \
  --clear-existing
```

モデルを絞る:

```bash
python TenkakuNinja/semantic_targets.py \
  --work-db work/semantic_work.sqlite \
  --run-id run_xxx \
  --model-names traffic_sign_detector \
  --max-bbox-area-ratio 0.30 \
  --clear-existing
```

### 主要パラメータ

```text
--work-db              semantic_work.sqlite
--run-id               対象run。省略時は最新run
--camera-height-m      実測CamH。既定2.0
--hud-height-scale     HudH係数。既定1.0
--limit                テスト用検出件数制限
--clear-existing       既存yolo_cubemap target削除
--model-run-ids        対象model_run_id
--model-names          対象model_name
--max-bbox-area-ratio  bboxが画面に対して大きすぎる検出を除外。例0.30
```

### 内部処理

1. YOLO検出と画像面情報をjoin。
2. `--model-names` / `--model-run-ids` があれば対象モデルだけ選択。
3. `--max-bbox-area-ratio` を超える検出をtarget化対象から除外。
4. クラス名からanchor/projection policyを決定。
5. bbox代表点をCubeMap面内の `u/v` に変換。
6. CubeMap face規約からcamera rayを作成。
7. rayを `target_yaw_to_camera_heading`, `target_pitch_deg` に変換。
8. `ground_plane` policyの場合だけ `ground_distance_m` を推定。
9. `semantic_targets_360` にinsert。

### class policy

地面上:

```text
road_surface_damage, road_damage, pothole, crack, manhole
road_marking, pavement_marking, lane_marking, crosswalk
traffic_cone, cone, pole, utility_pole, sign_post
```

高さあり:

```text
traffic_sign, sign, signal, traffic_light
Green Light, Red Light, Stop, Speed Limit xx
```

未知:

```text
direction_only
```

### 削除仕様

- `--clear-existing` だけの場合、そのrunの `target_source='yolo_cubemap'` を全削除して再生成。
- `--model-names` / `--model-run-ids` と併用した場合、指定モデル由来の既存targetだけ削除します。
- 別モデルのtargetは残します。

## yolo_report.py

### 役割

YOLO検出結果を人が確認するため、summary/CSV/HTML/注釈付き画像を生成します。

### 入力

```text
semantic_work.sqlite
yolo_detections_raw
image_planes
model_runs
semantic_targets_360 optional
CubeMap JPEG
```

### 出力

既定出力先:

```text
<runs.work_dir>/yolo_report/
```

ファイル:

```text
summary.txt
summary.json
detections.csv
class_summary.csv
face_summary.csv
model_run_summary.csv
index.html
annotated/{bucket}/frame_xxxxxxx_face_annotated.jpg
```

### CLI

```bash
python TenkakuNinja/yolo_report.py \
  --work-db work/semantic_work.sqlite \
  --run-id run_xxx \
  --output-dir work/yolo_report_max030 \
  --max-bbox-area-ratio 0.30
```

モデル別:

```bash
python TenkakuNinja/yolo_report.py \
  --work-db work/semantic_work.sqlite \
  --model-names traffic_sign_detector \
  --output-dir work/yolo_report_signs
```

### 主要パラメータ

```text
--work-db              semantic_work.sqlite
--run-id               対象run。省略時は最新run
--output-dir           レポート出力先
--min-conf             confidence下限
--faces                face filter
--classes              class_name filter
--model-run-ids        model_run_id filter
--model-names          model_name filter
--max-images           注釈画像枚数制限
--no-images            CSV/summaryのみ
--jpeg-quality         注釈画像JPEG品質。既定92
--max-bbox-area-ratio  bbox面積率filter。例0.30
```

### 内部処理

1. `yolo_detections_raw`, `image_planes`, `model_runs`, `semantic_targets_360` をjoin。
2. face/class/model/conf/bbox面積率でfilter。
3. 検出ごとのCSV行を作成。
4. class/face/model_run別summaryを作成。
5. 検出がある画像面ごとにCubeMap JPEGを読み、bboxとlabelを描画。
6. HTML galleryを生成。

### HTML表示順

HTMLは次の順で並びます。

```text
frame_index asc
face order: front, right, back, left, up, down
confidence desc within same frame/face
```

### bbox面積率

`detections.csv` には次を出します。

```text
bbox_area
bbox_area_ratio = bbox_area / (width_px * height_px)
```

標識・信号など小物体検出では、`bbox_area_ratio > 0.30` を巨大誤検出候補として落とす運用が有効です。

## 現時点で未実装の次工程

### projection.py planned

QGIS非依存の測地計算コアにします。

想定入力:

```text
camera_lat/lon
trajectory_heading_deg
video_front_offset_deg
target_yaw_to_camera_heading
distance_m
```

想定出力:

```text
object_lat/lon
bearing_deg
```

### georeference.py planned

`semantic_targets_360` を `poi_candidates_360` に変換します。

最初の方針:

```text
projection = ground_plane:
  ground_distance_m を使う
  max distance 10m程度で制限

projection = elevated_object / direction_only:
  --fallback-distance-m 10 が指定されていれば10m外円上へ方位マーカーとして配置
  position_method = fixed_distance_bearing
  distance_method = fixed_10m_direction_marker
  quality = direction_only
```

### gpkg_merge.py planned

`poi_candidates_360` を `tmp.gpkg` の別レイヤへ出力します。

想定:

```text
yolo_observations_360
semantic_targets_360
poi_candidates_360
direction_markers_360 optional
```

## 推奨実行順

```bash
# 1. CubeMap
python TenkakuNinja/cubemap.py \
  --database tmp.gpkg \
  --layer video_gpx_points \
  --video source.mp4 \
  --work-db work/semantic_work.sqlite \
  --output-dir work \
  --faces all \
  --size 1024 \
  --checkpoint-interval 100

# 2. 標識モデル
python TenkakuNinja/yolo_detect.py \
  --work-db work/semantic_work.sqlite \
  --model models/traffic_sign.pt \
  --model-name traffic_sign_detector \
  --faces front left right up \
  --conf 0.25 \
  --chunk-size 100

# 3. 路面・ポットホールモデル
python TenkakuNinja/yolo_detect.py \
  --work-db work/semantic_work.sqlite \
  --model models/pothole.pt \
  --model-name pothole_detector \
  --faces down \
  --conf 0.25 \
  --chunk-size 100

# 4. semantic target化
python TenkakuNinja/semantic_targets.py \
  --work-db work/semantic_work.sqlite \
  --camera-height-m 2.0 \
  --hud-height-scale 1.0 \
  --max-bbox-area-ratio 0.30 \
  --clear-existing

# 5. レポート
python TenkakuNinja/yolo_report.py \
  --work-db work/semantic_work.sqlite \
  --output-dir work/yolo_report_max030 \
  --max-bbox-area-ratio 0.30
```

