# 2026-06-18 Semantic 360 実装ワークログ

このメモは、Semantic 360 Auto Candidate の実装中に節目ごとに確認したこと、
その時点の判断、次に入れた実装を時系列で追えるようにした作業ログです。

設計思想や事業上の意味は
`docs/session_2026-06-18_semantic_360_auto_candidate.md` にまとめています。
この文書は、ログを追わなくても「どういう順序で形になったか」を確認するためのメモです。

## 0. 開始時点の前提

開始時点では、360ビューアと手動Pickerは既に動いていました。

- `video_gpx_points` で撮影点を管理する。
- `click_targets_360` に手動クリック点を保存する。
- クリック点は `target_yaw`, `target_pitch`, `view_yaw`, `view_pitch`, `view_zoom` を持つ。
- クリック点はQGIS地図上の候補点として投影できる。
- 360ビューアでは保存済みクリック点の視点復元ができる。

今日の目的は、手動クリック点と同じ考え方で、YOLO検出結果を360空間上の候補点として扱うことでした。

```text
YOLO bbox
  -> クリック点互換target
  -> 地図上の候補点
  -> 360ビューア上の確認マーカー
```

## 1. まず設計を分離した

最初に決めたことは、QGISプラグイン本体へYOLOやCubeMap変換の依存を入れないことです。

理由は単純で、QGIS Python環境に `ultralytics`, `torch`, `py360convert` を混ぜると壊れやすく、
将来 `tenkaku_ninja_core` に合流しにくくなるためです。

この時点で役割を分けました。

```text
TenkakuNinja CLI
  重い処理を担当する。
  CubeMap生成、YOLO推論、中間DB、POI候補生成。

semantic_work.sqlite
  長時間処理の中間DB。
  途中停止、再実行、複数モデル追記に耐える。

tmp.gpkg
  QGISでユーザが見る成果DB。
  クリック点とYOLO候補点を別レイヤで持つ。

QGISプラグイン
  表示、確認、視点復元、採否判断の入口。
```

ここで `semantic_targets_360` を中間インタフェースにする方針を固定しました。
YOLO結果をいきなり緯度経度へ落とさず、まず手動クリック点互換の `target_yaw/target_pitch`
へ変換する設計です。

## 2. CubeMap生成をCLI化した

次に、既存のExporterから派生して、CubeMap生成をCLI化しました。

この段階での判断は次の通りです。

- 既定では `front/right/back/left/up/down` の6面を必ず作る。
- YOLOにかける面は後段で選ぶ。
- 生成画像は `frame_0000123_front.jpg` のような名前にする。
- 1000フレーム単位のフォルダで一覧性を保つ。
- `semantic_work.sqlite` の `image_planes` に生成面を登録する。
- checkpointごとにDB commitし、途中停止しても再開できるようにする。

ファイル名を `frame番号 + face名` にしたのは、Explorerのサムネイル表示で
フレーム順・面順の確認がしやすかったためです。これは実務上かなり効きました。

## 3. py360convertの環境確認をした

`py360convert` は `e2c(..., cube_format="dict")` で次の6キーを返すことを確認しました。

```text
F, R, B, L, U, D
```

これを内部規約へ変換しました。

```text
F -> front
R -> right
B -> back
L -> left
U -> up
D -> down
```

ここで重要だったのは、CubeMapのface規約を早い段階で固定したことです。
後段のYOLO bboxからyaw/pitchへ戻す処理は、この規約に依存します。

## 4. YOLO検出結果をSQLiteへ保存した

次に、CubeMap画像にYOLOをかけ、結果を `yolo_detections_raw` へ保存しました。

この段階では、地図や360ビューアへはまだ戻していません。
まずは「どのモデルで、どの面の、どの画像から、どんなbboxが出たか」を正規化して残すことを優先しました。

主な判断は次の通りです。

- `runs` は処理全体の単位。
- `image_planes` はCubeMap各面の画像。
- `model_runs` はモデル実行単位。
- `yolo_detections_raw` は生の検出結果。
- 同じ `run_id` に複数モデルの検出を追記できる。
- 同じDBに、標識モデル、ポットホールモデル、路面標示モデルなどを混在できる。
- `--model-name`, `--faces`, `--conf`, `--chunk-size` をCLI引数にする。

この時点で、将来の運用は「face別・モデル別に複数回detectをかけ、同じDBに追記する」
という形に寄せました。

## 5. レポートとアノテーション画像を作った

YOLO結果をDBに入れても、何を拾ったかが分からないと評価できません。
そこで `yolo_report.py` を作り、summary、CSV、HTML、注釈画像を出すようにしました。

この段階で見えたことは、誤検出がかなり多いことです。
ただし誤検出も、モデルの癖を読む材料として有用でした。

ここで入れた判断です。

- HTMLギャラリーはconfidence順ではなくframe番号順に並べる。
- `bbox_area_ratio` を出す。
- 大きすぎるbboxを除外できるようにする。
- face/class/modelで絞り込めるようにする。
- `semantic_targets_360` 作成後はyaw/pitchやprojectionもCSVへ併記する。

「でかすぎるbboxは怪しい」という判断がここで入っています。

## 6. bboxをsemantic targetへ変換した

次の肝は、YOLOのbboxを `semantic_targets_360` へ変換することでした。

ここでやっていることは、検出矩形の代表点をCubeMap面内のu/vへ変換し、
カメラローカルrayへ戻し、そこから `target_yaw` と `target_pitch` を作ることです。

```text
bbox anchor
  -> cubemap_u / cubemap_v
  -> camera ray
  -> target_yaw_to_camera_heading
  -> target_pitch_deg
  -> semantic_targets_360
```

主な判断は次の通りです。

- bbox代表点はclassごとに変えられるようにする。
- 標識などは基本的に空中物として扱う。
- 路面標示やポットホールは地面対象として扱う。
- 地面対象は `ground_plane` とし、`ground_distance_m` を持てる。
- 空中物は `elevated_object` または `direction_only` として扱う。
- `max_bbox_area_ratio` で巨大誤検出をtarget化しない。

この時点では、まだ緯度経度は作らず、360空間上の方向だけを正規化していました。

## 7. semantic targetをPOI候補へ変換した

次に、`semantic_targets_360` と `video_gpx_points` を使って `poi_candidates_360` を生成しました。

ここでの考え方は、手動Pickerの投影と同じです。

- 撮影点の緯度経度を取る。
- フレーム前後の軌跡からheadingを出す。
- `target_yaw` と動画正面offsetを足して地図方位を出す。
- 地面対象なら `ground_distance_m` を使う。
- 空中物なら方角だけ信じ、固定距離の外円上へ仮置きする。

この段階で、空中物の地図位置は粗いことを明示的に受け入れました。
標識などは、正確な緯度経度よりも360ビューア上で「あれを拾った」と確認できることを重視します。

## 8. tmp.gpkgへmergeした

`semantic_work.sqlite` は内部DBなので、QGISで扱う正本は `tmp.gpkg` としました。

`gpkg_merge.py` では、`poi_candidates_360` をGPKGのPOINTレイヤとして出力します。

このとき、単なる地図点だけではなく、360ビューア復元に必要な証跡も一緒に出すようにしました。

主な列です。

```text
target_yaw
target_pitch
ground_distance_m
semantic_class
confidence
evidence_face
evidence_image_path
evidence_bbox_json
bbox_anchor
anchor_x_px
anchor_y_px
cubemap_u
cubemap_v
viewer_marker
```

この判断により、QGIS上の候補点から、360ビューア上の検出方向へ戻せるようになりました。

## 9. QGISプラグインにpoi_candidates_360を読ませた

最初は `tmp.gpkg` に `poi_candidates_360` が入っても、
プラグイン側は `video_gpx_points` と `click_targets_360` しか読んでいませんでした。

そこで、GPKG読込時に `poi_candidates_360` を `360 Detection Candidates` として
メモリレイヤへ読み込むようにしました。

この段階で注意したのは、`poi_candidates_360` も `frame`, `target_id`, `target_yaw`
を持つため、既存のクリック点レイヤ判定に引っかかることです。

対策として、候補レイヤを明示的に判定し、`click_targets_360` とは別扱いにしました。

```text
click_targets_360
  手動クリック点。
  正式POI候補へ育てやすい。

poi_candidates_360
  YOLO候補点。
  確認用。手動点とは混ぜない。
```

## 10. Detection checkナビを追加した

Navに `Detection check` を追加しました。

このモードでは、YOLO候補があるframeだけを辿ります。
frame移動時には、そのframeの候補点をビューアの `targets` として送ります。

```text
viewerDetectionTargetsForFrame(frame)
  -> target_yaw / target_pitch
  -> semantic_class / confidence
  -> target_source=yolo_candidate
  -> viewer_session targets
```

同じframeに複数候補がある場合は、confidenceが高い候補を優先して視点を合わせます。
候補マーカーは最大100件まで送る設計です。

この実装で、YOLO検出結果が360ビューア上にマーカーとして復元されました。

## 11. YOLO候補を手動クリック点として保存しないようにした

ビューアへ `targets` として送ると、既存のレーダ監視処理がそれをクリック点として解釈し、
`click_targets_360` へ保存する可能性がありました。

これは避ける必要がありました。

そこで、YOLO候補には次を持たせました。

```text
target_source = yolo_candidate
viewer_marker = target_point
```

`radar.py` ではこの由来情報をprojectionまで引き継ぎ、
`storeViewerTargetProjections()` では `target_source=yolo_candidate` を保存対象から除外しました。

これにより、YOLO候補は地図上に一時表示され、360ビューアにも出ますが、
手動クリック点レイヤを汚しません。

## 12. 360viewer側で候補メタデータを保持した

ビューアAPIの `validate_target_payload()` は、これまで未知の属性を落としていました。

YOLO候補では `semantic_class`, `confidence`, `candidate_id`, `review_status` が重要なので、
これらを検証済みpayloadとして残すようにしました。

また、`projection=direction_only` と `quality=direction_only` も受け付けるようにしました。

ビューア上のマーカーは、手動クリック点と区別するため別色にしました。
titleにはclassとconfidenceを出します。

## 13. hidden columnsを候補レイヤにも適用した

`poi_candidates_360` は証跡列が多く、そのまま属性テーブルに出すと情報量が多すぎます。

そこで、QGIS側では候補レイヤにもhidden columnsを設定しました。
普段はclass、confidence、quality、位置などを見る想定で、bbox JSONや内部IDなどは隠します。

これは、データを捨てるのではなく、普段のUIでは奥ゆかしく隠すという設計です。

## 14. 実データで確認した

実データ `VID_20260605_140303_00_001_2` では、`poi_candidates_360` が869件生成されました。

確認したことです。

- `target_yaw` が埋まっている。
- `target_pitch` が埋まっている。
- `semantic_class` と `confidence` がある。
- `evidence_bbox_json` がある。
- `anchor_x_px/y_px` と `cubemap_u/v` がある。
- QGISで `poi_candidates_360` をPOINTレイヤとして参照できる。
- `Detection check` で候補frameへ移動できる。
- 360ビューア上にYOLO候補マーカーが出る。

地図位置は荒れるものの、360ビューア上では標識にマーカーが乗るケースがありました。
これにより、CubeMap検出位置とkrpano表示座標系が噛み合っていることを確認できました。

## 15. テストを追加した

実装に合わせて純Pythonテストを追加・更新しました。

主な観点です。

- WGS84投影とheading計算。
- `semantic_targets_360` から `poi_candidates_360` への変換。
- GPKGへの `poi_candidates_360` 出力。
- `detect` ナビモードのconfig検証。
- 360viewer APIがYOLO候補メタデータを保持すること。
- schema v2の列追加。

最終確認では次を通しました。

```bash
python3 -m py_compile main.py viewer_controller.py radar.py config.py messages.py 360viewer/app.py
python3 -m unittest discover -s tests -v
```

結果は76 tests OKでした。

## 16. 最終的な到達点

今日の到達点は次です。

```text
CubeMap生成
  OK

YOLO検出
  OK

検出結果の可視化レポート
  OK

semantic_targets_360
  OK

poi_candidates_360
  OK

tmp.gpkgへのmerge
  OK

QGISで候補レイヤ表示
  OK

360ビューアで候補マーカー復元
  OK

Detection checkナビ
  OK
```

残っている課題は次です。

- 空中物の緯度経度は粗い。
- 誤検出は多い。
- 採用/棄却UIは未実装。
- `review_status` の運用はこれから。
- ground対象とdirection_only対象で評価方法を分ける必要がある。
- 高速道路データでface別・モデル別の実検証が必要。

## 17. 今日の実装の意味

今日の実装により、YOLO結果は「画像上のbbox」から
「360空間上の意味付き方向」へ昇格しました。

地図上では候補アイコン、360ビューア上では根拠方向として扱えます。

これは完成した自動地物登録ではありません。
むしろ、現場や顧客に対して「これを拾っています。これは見たいものですか」と聞くための
Auto Candidate基盤です。

誤検出も含めて、現場の判断基準を引き出すための材料になります。

## 18. 明日の入り方

明日は、CubeMap生成が終わった高速道路データに対して、次を行う想定です。

- 標識モデルを `front/left/right/up` などにかける。
- ポットホールまたは路面系モデルを `down` にかける。
- 同じ `semantic_work.sqlite` に複数model_runとして追記する。
- `semantic_targets_360` を再生成する。
- `poi_candidates_360` を生成する。
- `tmp.gpkg` へmergeする。
- QGISと360ビューアで `Detection check` を確認する。
- 誤検出、正解例、地図上の荒れ方を分けて見る。
