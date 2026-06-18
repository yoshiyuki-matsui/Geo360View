# TenkakuNinja Standalone Exporter

GPXVideoProcessorが生成したGeoPackageと元MP4から、条件に合うフレーム画像を証跡用JPEGとして一括抽出する単体Exporterです。

このフォルダは、QGISプラグイン外へコピーして単体利用できます。

## Documents

- [semantic_360_pipeline.md](semantic_360_pipeline.md): 360動画をCubeMap化し、YOLO結果をクリック点互換の `semantic_targets_360` へ加工するCLIパイプライン設計。
- [semantic_360_py_reference.md](semantic_360_py_reference.md): 追加した各pyの入出力、主要パラメータ、内部処理、チェックポイント仕様。
- [env_notes.md](env_notes.md): `venv_yolo`, `venv310_yolo_gpu` などPython環境の役割と確認コマンド。
- [../docs/session_2026-06-18_semantic_360_auto_candidate.md](../docs/session_2026-06-18_semantic_360_auto_candidate.md): CubeMap/YOLO/POI候補化/360視点復元まで到達した日のR&D経緯メモ。

## Install

```bash
pip install -r requirements.txt
```

## CLI

既存の証跡フレームExporter:

このフォルダ内で実行する場合:

```bash
python main.py --database path/to/tmp.gpkg --video path/to/movie.mp4
```

プラグインルートから実行する場合:

```bash
python TenkakuNinja/main.py --database path/to/tmp.gpkg --video path/to/movie.mp4
```

360 semantic pipeline用のCubeMap生成:

```bash
python TenkakuNinja/cubemap.py \
  --database path/to/tmp.gpkg \
  --video path/to/movie.mp4 \
  --work-db path/to/work/semantic_work.sqlite \
  --faces all \
  --checkpoint-interval 100
```

CubeMap生成は既定で `front/right/back/left/up/down` の6面を作り、生成した面を
`semantic_work.sqlite` の `image_planes` に登録します。YOLOにかける面は後段の
`yolo_detect.py` 側で絞ります。
CubeMap生成はチェックポイントごとに `image_planes` とmetadataをcommitします。
途中で止めても、同じ `--run-id` で再実行すれば既存画像を使いながら不足分を続行できます。

CubeMap画像にYOLOをかける場合:

```bash
python TenkakuNinja/yolo_detect.py \
  --work-db path/to/work/semantic_work.sqlite \
  --model path/to/model.pt \
  --faces front left right \
  --conf 0.35 \
  --chunk-size 100
```

YOLO検出結果は `semantic_work.sqlite` の `model_runs` と `yolo_detections_raw` に保存します。
同じ `run_id` に対して複数回実行でき、モデルごとに別の `model_run_id` として追記します。
YOLOはchunkごとにcommitし、`model_run` metadataへcheckpointを保存します。
明示 `--model-run-id` を指定した再開では、`--resume` を付けると既存検出がある画像面を
スキップします。

```bash
python TenkakuNinja/yolo_detect.py \
  --work-db path/to/work/semantic_work.sqlite \
  --model path/to/traffic_sign.pt \
  --model-name traffic_sign_detector \
  --faces front left right

python TenkakuNinja/yolo_detect.py \
  --work-db path/to/work/semantic_work.sqlite \
  --model path/to/pothole.pt \
  --model-name pothole_detector \
  --faces down
```

前方・左方向の標識、下方の路面標示、後方の標識裏錆など、用途が違う検出も同じDBへ
追記します。後段では `model_name`, `model_run_id`, `face_name`, `class_name` で
レポートやGPKGレイヤを切り分けます。

YOLO検出結果を目視確認するレポートを作る場合:

```bash
python TenkakuNinja/yolo_report.py \
  --work-db path/to/work/semantic_work.sqlite
```

既定では `runs.work_dir/yolo_report/` に `summary.txt`, `summary.json`, CSV、
`index.html`、検出枠付き画像を出力します。`semantic_targets_360` 作成後に実行すると、
`detections.csv` にyaw/pitchやprojection/qualityも併記されます。
大きすぎるbboxを確認対象から外す場合は `--max-bbox-area-ratio 0.30` を指定します。
特定モデルだけ見る場合は `--model-names pothole_detector` または
`--model-run-ids model_...` を指定します。

YOLO検出結果を360クリック点互換targetへ加工する場合:

```bash
python TenkakuNinja/semantic_targets.py \
  --work-db path/to/work/semantic_work.sqlite \
  --camera-height-m 2.0 \
  --hud-height-scale 1.0 \
  --max-bbox-area-ratio 0.30 \
  --clear-existing
```

この段階では緯度経度は作らず、`semantic_targets_360` に
`target_yaw_to_camera_heading`、`target_pitch_deg`、`ground_distance_m` などを保存します。
地面に接しているとみなせるクラスだけ `ground_plane` とし、標識や信号のような高さのある
対象は `elevated_object` または `direction_only` として扱います。
`--max-bbox-area-ratio` を指定すると、画面に対して大きすぎるbboxはtarget化しません。
`--model-names` や `--model-run-ids` を指定して `--clear-existing` した場合は、
指定モデル由来のtargetだけを削除・再生成します。

semantic targetを地図上のPOI候補へ変換する場合:

```bash
python TenkakuNinja/georeference.py \
  --work-db path/to/work/semantic_work.sqlite \
  --database path/to/tmp.gpkg \
  --fallback-distance-m 10 \
  --max-ground-distance-m 10 \
  --clear-existing
```

`ground_plane` のtargetは `ground_distance_m` を使い、`elevated_object` や
`direction_only` は方角だけ信じて `--fallback-distance-m` の外円上に置きます。
結果は `semantic_work.sqlite` の `poi_candidates_360` に保存します。
動画正面と進行方向にずれがある場合は `--video-front-offset-deg` で補正します。

POI候補をQGISで扱う `tmp.gpkg` へ集約する場合:

```bash
python TenkakuNinja/gpkg_merge.py \
  --work-db path/to/work/semantic_work.sqlite \
  --database path/to/tmp.gpkg \
  --replace
```

`semantic_work.sqlite` は処理途中の内部DBです。ユーザがQGISで開いて操作する成果物は
`tmp.gpkg` とし、YOLO由来候補は `poi_candidates_360` レイヤへ出力します。
手動クリック点の `click_targets_360` とは別レイヤなので、候補点と手動点を混同しません。
`poi_candidates_360` には `target_yaw`, `target_pitch`, `evidence_bbox_json`,
`bbox_anchor`, `anchor_x_px/y_px`, `cubemap_u/v`, `semantic_class`, `confidence` も出力するため、
地図上の候補点から360ビューア上の検出方向へ点マーカーを復元できます。

## Examples

KPマッチ済みフレームだけ抽出:

```bash
python main.py \
  --database path/to/tmp.gpkg \
  --video path/to/movie.mp4 \
  --matched-only
```

範囲、縮尺、JPEG品質を指定:

```bash
python main.py \
  --database path/to/tmp.gpkg \
  --video path/to/movie.mp4 \
  --start 10000 \
  --end 12000 \
  --scale 0.5 \
  --jpeg-quality 75 \
  --progressive-jpeg
```

軽量参照用:

```bash
python main.py \
  --database path/to/tmp.gpkg \
  --video path/to/movie.mp4 \
  --scale 0.5 \
  --jpeg-quality 70 \
  --progressive-jpeg
```

YOLO/CubeMap用の原寸高品質:

```bash
python main.py \
  --database path/to/tmp.gpkg \
  --video path/to/movie.mp4 \
  --scale 1.0 \
  --jpeg-quality 95
```

## Output Rule

TenkakuNinjaCore由来の保存規則を維持します。

```text
images/
  0000/
    frame_0000000.jpg
  0001/
    frame_0001000.jpg
```

```text
subfolder = frame // 1000
filename = frame_{frame:07d}.jpg
```

## Notes

- OpenCV出力を正とします。
- 現行出力はJPEGです。JPEG品質100でも厳密な非圧縮・ロスレスではありません。
- ffmpegは高速ですが、YOLO結果差分が出る場合があるため標準抽出方式にはしません。
- QGISプラグイン本体の依存関係とは分離します。
