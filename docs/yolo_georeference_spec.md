# YOLO検出結果の緯度経度化 将来仕様メモ

更新日: 2026-06-04

この文書は、360画像またはCubeMap平面画像でYOLOが検出した物体位置を、将来的に緯度経度空間の絶対座標へ変換するための座標系と処理順を整理するものです。

現時点では未実装です。GPXVideoProcessor本体の現在機能は、フレーム位置同期、360Viewer表示、レーダ表示までです。

## 目的

最終的な目的は、YOLOの検出結果を地図上の地物候補として扱える形に変換することです。

目標とする処理:

```text
YOLO検出矩形
-> 画像内2D座標
-> 360画像空間の方位角・仰角
-> 動画正面からの相対yaw/pitch
-> 移動軌跡headingと動画正面Offsetによる地図方位
-> 距離推定
-> 撮影点から方位・距離投影
-> 緯度経度
```

## 関連仕様

- `docs/rader_spec.md`
- `DESIGN.ja.md`

レーダ表示で使っている以下の定義を、この仕様でも継承します。

```text
map_bearing_deg = (trajectory_heading_deg + video_front_offset_deg + camera_relative_yaw_deg) % 360
```

## 非対象

この文書では、以下はまだ確定しません。

- YOLOモデルの種類、学習データ、推論環境
- CubeMap生成ツールの具体実装
- 検出物までの距離推定方式
- 複数フレームにまたがる同一物体トラッキング
- QGIS地物レイヤへの登録UI

これらは後続設計で別途確定します。

## 座標系

将来の混乱を避けるため、同じ「角度」でも座標系ごとに名前を分けます。

### 画像座標

YOLOが直接返す座標です。

```text
image_x_px
image_y_px
bbox_left_px
bbox_top_px
bbox_width_px
bbox_height_px
```

原点は画像左上、xは右向き、yは下向きです。

検出方向の代表点は、原則として矩形重心を使います。

```text
bbox_center_x_px = bbox_left_px + bbox_width_px / 2
bbox_center_y_px = bbox_top_px + bbox_height_px / 2
```

ただし、標識ポールや道路付属物など、地物登録点を矩形重心に置くと不自然な対象があります。最終的には対象クラスごとに「矩形重心」「下端中央」「ポール基部」などを選べる余地を残します。

### CubeMap面座標

CubeMapで推論する場合は、YOLO検出元の面を必ず保持します。

```text
cubemap_face
cubemap_u
cubemap_v
```

`cubemap_face` の候補例:

```text
front
right
back
left
up
down
```

`cubemap_u`, `cubemap_v` は、各面内の正規化座標として扱います。

```text
-1.0 <= cubemap_u <= 1.0
-1.0 <= cubemap_v <= 1.0
```

`u` は面画像の右方向、`v` は面画像の下方向を基本とします。ただし、CubeMap生成ライブラリによって面の回転や並びが異なるため、実装時には `face_uv_to_camera_ray()` の変換表を固定し、検証画像で確認します。

### カメラローカル3D方向

CubeMap面座標から、動画正面を基準とする3D方向ベクトルへ変換します。

本仕様でのカメラローカル軸:

```text
+X: 動画正面から見て右
+Y: 上
+Z: 動画正面
```

方向ベクトル:

```text
camera_ray_x
camera_ray_y
camera_ray_z
```

このベクトルから、動画正面基準のyaw/pitchを求めます。

```text
camera_relative_yaw_deg = normalize360(atan2(camera_ray_x, camera_ray_z) * 180 / pi)
camera_pitch_deg = atan2(camera_ray_y, sqrt(camera_ray_x^2 + camera_ray_z^2)) * 180 / pi
```

`camera_relative_yaw_deg` は、動画正面から右回りを正とします。

例:

- 正面: `0deg`
- 右: `90deg`
- 後ろ: `180deg`
- 左: `270deg` または signed表現で `-90deg`

### 360画像空間

エクイレクタングラー画像へ戻す場合は、360画像空間の水平角も保持します。

本プロジェクトの暫定規約:

```text
pano_longitude_deg = 0..360
正面中心 = 180deg
正面左45deg = 135deg
正面右45deg = 225deg
```

この規約では、動画正面基準yawへの変換は以下です。

```text
camera_relative_yaw_deg = normalize360(pano_longitude_deg - 180)
```

例:

```text
pano_longitude_deg = 135
camera_relative_yaw_deg = 315  # signed表現では -45
```

注意:

エクイレクタングラー画像のseam位置やCubeMap変換ツールによって、正面中心が `0deg` 扱いになることがあります。その場合でも、外部出力をこの規約へ正規化してから後続処理へ渡します。

### 地図方位

地図方位はQGIS/GISで扱いやすい方位角です。

```text
0deg: 北
90deg: 東
180deg: 南
270deg: 西
```

角度は時計回りに増加します。

## headingとOffset

`trajectory_heading_deg` は、フレーム前後の移動軌跡から求める進行方向です。

`video_front_offset_deg` は、進行方向から動画正面までの時計回り角度です。

例:

- 動画正面が進行方向: `0deg`
- 動画正面が進行方向右: `90deg`
- 動画正面が進行方向後ろ: `180deg`
- 動画正面が進行方向左: `270deg`

検出物の地図方位:

```text
map_bearing_deg = normalize360(
    trajectory_heading_deg
    + video_front_offset_deg
    + camera_relative_yaw_deg
)
```

この式は、現在のレーダ表示で使っている `viewer_bearing` と同じ考え方です。

## 単眼スケール投影の考え方

この仕様でまず想定する方式は、カメラベクトルやdepthを使った三次元復元ではありません。

360空間上の角度と撮影点の緯度経度を使い、現地スケールを人間または設定値として与えて地図へ投影する近似です。

```text
360空間上の角度
+ 撮影点緯度経度
+ trajectory_heading_deg
+ video_front_offset_deg
+ 現地スケール仮定
= 地図上の推定位置
```

この方式では、検出物までの絶対距離は画像だけから自動的には決まりません。`reference_fov_deg` と `reference_width_m` のようなリファレンスを置く場合、それは「指定した視野角を現地の何m幅として解釈するか」を与えていることになります。

例:

```text
reference_fov_deg = 90
reference_width_m = 20
reference_plane_distance_m = reference_width_m / (2 * tan(reference_fov_deg / 2))
```

これは「90度視野の幅を20m相当とみなし、正面10m先の仮想面へ投影する」近似です。測量的な正解ではなく、地物候補を地図上へ落とすための作業用推定位置として扱います。

出力には必ず、投影方式と品質情報を残します。

```text
distance_method
scale_reference_fov_deg
scale_reference_width_m
quality_flag
```

## 精度の考え方

緯度経度化の誤差は、方位誤差と距離誤差に分けて考えます。

方位側は、以下の式で管理できます。

```text
trajectory_heading_deg
+ video_front_offset_deg
+ camera_relative_yaw_deg
= map_bearing_deg
```

一方、最終的な平面位置の誤差は距離に比例して増えます。

```text
position_error_m ~= object_distance_m * angle_error_rad
```

同じ角度誤差でも、近い対象ほど位置ずれは小さく、遠い対象ほど大きくなります。

例:

```text
angle_error = 1deg
distance = 5m  -> lateral_error ~= 0.09m
distance = 20m -> lateral_error ~= 0.35m
distance = 50m -> lateral_error ~= 0.87m
```

YOLOの矩形についても、近い対象ほど有利です。

- bboxが大きい。
- 中心点のピクセル誤差が角度誤差へ変換されにくい。
- 検出confidenceが安定しやすい。
- 実寸と矩形サイズの対応を取りやすい。
- 撮影点から対象までの距離が短く、方位誤差が位置誤差として増幅されにくい。

遠い対象は逆に、bboxが小さく、1pxのずれやbboxの揺れが大きな角度誤差になりやすいです。単眼360 + YOLO bboxだけで現実的な精度を狙う場合、近接で大きく写っている検出を優先することが重要です。

## 代表検出の選び方

同一対象が複数フレームに写る場合、すべての検出を同じ重みで扱わない方がよいです。

代表検出の候補優先度:

1. 対象が大きく写っている検出
2. 推定距離が近い検出
3. confidenceが高い検出
4. bboxの角度幅が十分にある検出
5. 連続フレームで方位変化が安定している検出
6. CubeMap面の端やseamから離れている検出

保持したい品質指標:

```text
bbox_area_px
bbox_angular_width_deg
bbox_angular_height_deg
estimated_distance_m
detection_confidence
view_edge_margin_deg
frame_to_object_angle_stability_deg
```

特に `bbox_angular_width_deg` は、画像解像度やCubeMap解像度が変わっても比較しやすいため、代表検出選択の基準として有用です。

最初の実装では、完全自動で確定地物を作るよりも、代表検出から推定位置を作り、QGIS上で人間が確認・補正できる運用を前提にします。

## 目的別の座標化方式

360空間上の角度とスケール仮定から直接緯度経度へ投影する方式だけが正解ではありません。対象物の性質や撮影条件によって、より精度を説明しやすい方式を選びます。

### 360空間スケール投影方式

対象物が進行方向前方、斜め前、遠方などに写り、真横を通過するとは限らない場合の汎用方式です。

使う情報:

- `camera_relative_yaw_deg`
- `map_bearing_deg`
- `object_distance_m` またはスケールリファレンス

この方式では、撮影点から `map_bearing_deg` 方向へ `object_distance_m` だけ投影して地物候補点を作ります。

長所:

- 対象が任意方向に写っていても処理できる。
- 360画像空間の方位情報を直接利用できる。

短所:

- 距離推定が弱いと、最終緯度経度の精度も弱くなる。
- 単眼画像だけでは絶対距離が一意に決まらない。

### 真横代表フレーム方式

道路標識や道路付属物のように、走行に伴って対象物が左右を横切ることが期待できる場合は、画像から無理に距離を推定しない方が堅いことがあります。

この方式では、対象物が最も真横に近く、かつ大きく写っているフレームを代表フレームとして選びます。

真横判定の例:

```text
right_side_score = abs(normalize180(camera_relative_yaw_deg - 90))
left_side_score  = abs(normalize180(camera_relative_yaw_deg - 270))
side_angle_error_deg = min(right_side_score, left_side_score)
```

`side_angle_error_deg` が小さいほど、対象物は進行方向に対して真横に近いとみなします。

代表フレーム選択の指標:

- `side_angle_error_deg` が小さい。
- `bbox_angular_width_deg` が大きい。
- `bbox_area_px` が大きい。
- `detection_confidence` が高い。
- 連続フレームで同一対象として追跡できる。

代表フレームの緯度経度化:

```text
object_lat/lon ~= representative_camera_lat/lon
```

必要に応じて、道路端側への固定オフセットや既存道路/KP/地物レイヤへのスナップを後段で加えます。

長所:

- 距離推定を画像から無理に出さなくてよい。
- フレーム間移動量が1m程度なら、代表撮影点ベースで1m粒度の説明がしやすい。
- 対象物が近接して大きく写る検出を使いやすい。

短所:

- 対象が必ず左右を横切る運用でないと使えない。
- 撮影点そのものは道路中心や車両位置であり、標識設置位置とは横断方向にずれる。
- 左右どちら側の対象かを別途判定し、必要なら道路端方向へ補正する必要がある。

この方式における360空間変換の主な役割は、緯度経度を直接出すことではなく、真横に近い代表フレームを選ぶことです。

### 使い分け

```text
対象が左右を横切る:
  真横代表フレーム方式を優先候補にする。

対象が前方・斜め・遠方にあり、横切り前提がない:
  360空間スケール投影方式を使う。

高精度な確定座標が必要:
  QGIS上で人間が確認・補正する。
```

## 距離推定

単一の360画像とYOLO矩形だけでは、対象物までの絶対距離は一意に決まりません。

緯度経度へ変換するには、少なくとも水平距離が必要です。

```text
object_distance_m
```

候補となる距離推定方式:

- 手動指定距離
- 地図上クリックによる補正距離
- 対象クラスごとの既知寸法を使う単眼推定
- カメラ高とpitchから地面との交点を求める地面平面交差
- 複数フレームの同一物体追跡による三角測量
- 深度推定モデル
- 道路中心線、KP、既存地物レイヤへの拘束

距離推定方式が確定するまでは、検出方位だけを信頼し、絶対緯度経度は仮値または未出力として扱います。

## 緯度経度投影

撮影点、地図方位、距離がそろった場合、WGS84上の方位距離投影で地物候補点を作ります。

入力:

```text
camera_lat
camera_lon
map_bearing_deg
object_distance_m
```

出力:

```text
object_lat
object_lon
```

計算は、レーダ表示の `destinationPoint()` と同じ球面近似を使えます。

## pitchと高さ

`camera_pitch_deg` は、地物の高さや地面交差を扱う場合に必要です。

ただし、地図上の2D点だけを作る場合は、まず水平方位 `map_bearing_deg` と水平距離 `object_distance_m` を優先します。

将来的に高さを扱う場合の追加候補:

```text
camera_height_m
object_height_m
object_vertical_angle_deg
object_ground_contact_assumption
```

標識の矩形重心は標識板の中心を指すため、地図登録点としては支柱位置や路側位置とはずれる可能性があります。

## 推奨列名

将来のCSV、GeoPackage、DBでは、曖昧な `yaw` や `angle` だけの列名を避けます。

最低限保持したい列:

```text
video_name
frame_index
camera_lat
camera_lon
trajectory_heading_deg
video_front_offset_deg

detection_class
detection_confidence
bbox_left_px
bbox_top_px
bbox_width_px
bbox_height_px
bbox_center_x_px
bbox_center_y_px
bbox_area_px
bbox_angular_width_deg
bbox_angular_height_deg
side_angle_error_deg

cubemap_face
cubemap_u
cubemap_v
pano_longitude_deg
camera_relative_yaw_deg
camera_relative_yaw_signed_deg
camera_pitch_deg

map_bearing_deg
object_distance_m
distance_method
scale_reference_fov_deg
scale_reference_width_m
position_method
representative_frame_index
representative_camera_lat
representative_camera_lon
object_lat
object_lon
quality_flag
```

`frame_index` は、GPX同期、画像抽出、YOLO結果、地図登録結果を結ぶ不変キーとして扱います。フレームシフト後も、元動画上のフレーム番号として保持します。

## 角度正規化

角度処理は、丸め誤差や0/360境界で破綻しやすいため、関数名を明示します。

```text
normalize360(deg) = deg % 360
normalize180(deg) = ((deg + 180) % 360) - 180
```

内部処理では `0..360` の unsigned表現を基本とし、ログや人間向け表示では `-180..180` の signed表現を併記してもよいです。

## 検証方針

実装前に、座標変換だけを検証する小さなテストデータを作ります。

### 合成360画像

以下の位置に文字やマーカーを置いた合成エクイレクタングラー画像を用意します。

- 正面中心
- 正面左45度
- 正面右45度
- 右90度
- 後ろ180度
- 左90度
- 上下方向

期待値例:

```text
正面左45度:
  pano_longitude_deg = 135
  camera_relative_yaw_deg = 315
  camera_relative_yaw_signed_deg = -45
```

### CubeMap往復確認

同じ合成画像をCubeMapへ変換し、各面のマーカーが期待する `camera_relative_yaw_deg` / `camera_pitch_deg` へ戻ることを確認します。

この確認により、CubeMap生成ツールのface順、face回転、seam位置を固定します。

### レーダとの整合

ビューア中心に置いた対象物の `camera_relative_yaw_deg` が、現在のレーダ中心線と一致することを確認します。

確認例:

- `Offset=0`, 正面対象: 進行方向へ出る
- `Offset=180`, 正面対象: 進行方向後ろへ出る
- `Offset=180`, 動画正面から右90度対象: 進行方向左へ出る

### 真横代表フレーム方式の確認

同一対象が連続フレームに写るサンプルで、以下を確認します。

- `camera_relative_yaw_deg` が90度または270度へ最も近いフレームが選ばれる。
- その近傍で `bbox_angular_width_deg` または `bbox_area_px` が大きい検出が優先される。
- `representative_frame_index` の撮影点が、対象物の最接近位置として説明可能である。
- `position_method=side_view_representative_frame` として、360空間スケール投影方式と区別される。

## 現在のリスク

- CubeMap変換ツールごとにfaceの向きが異なる。
- 360画像の正面中心が `180deg` か `0deg` かで式が変わる。
- YOLO矩形重心が地物登録点を表すとは限らない。
- 単一フレームだけでは距離が決まらない。
- 動画正面Offsetが素材ごとに違う場合、推論結果の地図方位が一括でずれる。
- 移動軌跡headingはGNSSノイズや停止時に不安定になる。
- 真横代表フレーム方式は、対象物が左右を横切らない場合には使えない。

## 実装時の原則

- `yaw` だけの変数名を使わない。
- 画像空間、カメラ相対角、地図方位、緯度経度を同じ列へ混ぜない。
- CubeMap変換は、face名、u/v、変換後ray、yaw/pitchをすべてログまたは中間CSVに残す。
- 距離推定方式を `distance_method` として明示する。
- 緯度経度化方式を `position_method` として明示する。
- 絶対座標の信頼度を `quality_flag` として残す。
- 合成画像で角度変換を検証してから、実動画へ適用する。
