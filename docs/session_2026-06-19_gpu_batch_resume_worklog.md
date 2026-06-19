# 2026-06-19 YOLO GPU batch/resume 作業ログ

このメモは、8K/11K 360 CubeMap に対する YOLO 推論を、夜間バッチとして安全に回すために
今日入れた変更と、実行時に見えた GPU 周りの調整方針を残すものです。

主眼は最高速ではなく、次の3点です。

- 落ちても失わない。
- 再開できる。
- 処理時間とGPU負荷を読みやすくする。

## 1. 背景

`--batch auto` でポットホールモデルを走らせていたところ、途中 checkpoint commit 時に
SQLite の `database is locked` が発生しました。

この時点での状況は次の通りです。

- `semantic_work.sqlite` に対して長時間 YOLO 推論中。
- CubeMap/YOLO/report/DB確認など、複数プロセスが同じ作業DBを参照する可能性があった。
- YOLO は 8000/53200 image planes まで処理済み。
- その後、同じ `model_run_id` と `--resume` で再開した。

長時間処理では、途中停止そのものよりも「どこまで終わっていたかを失う」ことが損失になります。
そのため、checkpoint と resume の扱いを優先して改善しました。

## 2. SQLite commit の lock 耐性

`TenkakuNinja/sqlite_io.py` に次を追加しました。

- `connect(path, timeout=60.0)`
- `PRAGMA busy_timeout`
- `is_lock_error()`
- `commit_with_retry()`

`commit_with_retry()` は、`database is locked` / `database is busy` のような一時的な lock に対して、
transaction を捨てずに commit を再試行します。既定では最大6回、5秒を基準に段階的に待ちます。

この commit retry を次へ適用しました。

- `sqlite_io.open_work_db()`
- `sqlite_io.initialize()`
- `yolo_detect.py` の auto batch metadata 保存
- `yolo_detect.py` の YOLO checkpoint 保存
- `cubemap.py` の初期化 commit
- `cubemap.py` の CubeMap checkpoint 保存

注意点として、これは「SQLite に対して複数プロセスが自由に同時書き込みしてよい」という意味ではありません。
書き込みはできるだけ短くし、長時間の読み取りやレポート生成は live DB ではなく snapshot/backup 側で行う方が安全です。

## 3. YOLO resume の改善

以前の resume は、既に `yolo_detections_raw` に検出がある `plane_id` をスキップしていました。
この方式では、検出0件だった画像面を「処理済み」と判定できず、再開時に余計な再処理が発生します。

今回の変更後は、`metadata(scope='model_run', key='yolo_detection_checkpoint')` の
`processed_plane_count` を優先して使います。

これにより、checkpoint 済みであれば検出0件だった plane も再処理対象から外れます。

再開時の指定は引き続き明示的に行います。

```bash
python TenkakuNinja/yolo_detect.py \
  --work-db /path/to/semantic_work.sqlite \
  --model /path/to/model.pt \
  --model-name pothole_detector \
  --model-run-id model_yyyyMMddTHHmmss_xxxxxxxx \
  --faces front down \
  --device 0 \
  --conf 0.25 \
  --batch auto \
  --resume
```

`--model-run-id` だけを指定して `--resume` を付けない場合は、誤って同じ model run に追記しないように
エラーにします。

## 4. auto batch の調整

YOLO 側には `--batch auto` を追加済みです。

主な引数は次の通りです。

- `--auto-batch-candidates`
  - 既定値は `16,32,64`
- `--auto-batch-probe-images`
  - 既定値は `256`
- `--auto-batch-target-vram-fraction`
  - 既定値は `0.85`
- `--auto-batch-safety-margin`
  - 既定値は `0.40`

auto batch は、候補 batch を短く試運転し、throughput、VRAM使用増分、budget内かどうかを見ます。
そのうえで、最速候補そのものではなく、safety margin を差し引いた batch ceiling 以下から選びます。

今日の実行では、たとえば次のような挙動でした。

```text
YOLO auto batch started: candidates=[16, 32, 64] target_vram=0.85 used=1.32GB free=14.60GB budget=12.21GB safety_margin=0.40
YOLO auto batch candidate=16 throughput=2.22 img/s reserved_delta=7.10GB within_budget=True
YOLO auto batch candidate=32 throughput=30.46 img/s reserved_delta=11.29GB within_budget=True
YOLO auto batch candidate=64 throughput=1.23 img/s reserved_delta=26.47GB within_budget=False
YOLO auto batch selected: batch=16 best_batch=32 best_throughput=30.46 img/s batch_ceiling=19
```

`best_batch=32` でも、`safety_margin=0.40` のため `batch_ceiling=19` となり、実際には `batch=16` を選びます。

CubeMap変換、YOLO、モデル作成などが並行する可能性がある場合は、最高速の batch よりも安定した batch を優先します。
今回のGPUでは、試食・運用候補として次が扱いやすそうです。

```bash
--batch auto \
--auto-batch-candidates 16,24,32,48 \
--auto-batch-safety-margin 0.25
```

ただし本処理で安定性を優先するなら、結果として `batch=16` が選ばれることは自然です。

## 5. 今日の実行結果

ポットホールモデルの最終実行は完了しました。

```text
Image planes: 53200
Processed image planes: 53200
Skipped existing planes: 8000
Batch: 16
Auto batch: complete selected=16 best=24
Detections: 2554
Status: complete
Done in 2946.58s
```

後段処理の結果は次の通りです。

```text
semantic_targets:
  Detections: 2554
  Processed detections: 2520
  Large bbox skipped: 34
  Targets: 2520

georeference:
  Targets: 2520
  POI candidates: 2343
  ground distance: 2099
  fixed distance: 244
  Skipped: 177

gpkg_merge:
  Layer: poi_candidates_pothole_360
  Features: 2343
```

## 6. QGIS NAVモードの標準化

`gpkg_merge.py` で `--layer-name poi_candidates_pothole_360` のようなモデル別レイヤ名を指定すると、
従来の QGIS 側 DetectionCheck/Nav は標準名 `poi_candidates_360` 前提に寄りすぎていました。

今回、`main.py` 側を調整し、GeoPackage 内の `poi_candidates...` 系 features layer を候補として拾えるようにしました。

NAVモードの標準は次のように整理します。

- 標準候補レイヤ名は `poi_candidates_360` とする。
- モデル別に分ける場合は `poi_candidates_{model_slug}_360` とする。
- GPKG読込時は、まず `poi_candidates_360` を優先して読む。
- 標準レイヤがない場合は、`gpkg_contents` から `poi_candidates...` 系 features layer を探す。
- QGIS上では候補レイヤを `360 Detection Candidates` のメモリレイヤとして読み、NAVの `Detection check` 対象にする。
- `Detection check` は、候補が存在するframeだけを辿り、同じframeの候補を360ビューアへ `targets` として送る。

これにより、たとえば次のレイヤ名も NAV 対象の候補レイヤとして扱えます。

- `poi_candidates_360`
- `poi_candidates_pothole_360`
- `poi_candidates_traffic_sign_360`

今後のGPKG出力では、モデル別レイヤを作る場合も `poi_candidates_` prefix を維持します。
`DetectionCheck` のような任意名は人間には分かりやすい一方で、自動認識の規約から外れるため、
標準運用では使わない方針です。

## 7. 検証

実行済みの確認は次の通りです。

```bash
python -m py_compile TenkakuNinja/sqlite_io.py TenkakuNinja/yolo_detect.py TenkakuNinja/cubemap.py
python -m py_compile main.py
python -m unittest discover -s tests -p 'test_tenkaku_yolo_detect.py'
python -m unittest discover -s tests -p 'test_tenkaku_cubemap.py'
```

結果:

- `test_tenkaku_yolo_detect.py`: 16 tests OK
- `test_tenkaku_cubemap.py`: 7 tests OK
- `pytest` は現在の venv に入っていないため未実行

## 8. 運用メモ

長時間GPU処理では、次を標準作法にします。

- `--model-run-id` を残す。
- 再開時は同じ `--model-run-id` と `--resume` を使う。
- `--batch auto` は最高速ではなく安定火力として扱う。
- CubeMap/YOLO/学習を並行させるときは safety margin を厚めにする。
- live DB に対する長時間の読み取りやレポート生成は避け、必要なら snapshot/backup を使う。
- checkpoint/progress/ETA を見て、翌朝までに終わる処理時間を読めるようにする。

今後の拡張候補:

- `poi doctor` で GPU/CUDA/PyTorch/NAS/DB 書き込みを自己診断する。
- job DB を持ち、CubeMap/YOLO/学習/merge/report の依存関係とリソースを管理する。
- auto batch を YOLO 専用ではなく、重いタスク共通の resource tuner に寄せる。
- YAML オーケストレータで、モデル別の faces/conf/batch 候補/safety margin を管理する。
