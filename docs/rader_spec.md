# レーダ表示 実寸準拠仕様

更新日: 2026-06-06

この文書は、GPXVideoProcessor のQGIS地図上レーダ表示について、実寸準拠の考え方と現在の実装仕様をまとめるものです。

特定案件、特定路線、特定データ形式に依存する注意点や運用ルールは、この文書へ混ぜず、別途 `docs/*.md` として残します。

## 対象ファイル

主な実装箇所:

- `radar.py`: レーダ計算、`viewer_session.json` ポーリング、QGIS地図上の描画
- `main.py`: レーダUI、フレーム位置キャッシュ、レーダ状態管理
- `360viewer/static/viewer.js`: ビューア側の `yaw_to_camera_heading`, `pitch`, `zoom` 更新
- `360viewer/app.py`: ビューア状態API、`viewer_session.json` 出力

関連ドキュメント:

- `DESIGN.ja.md`
- `realize_rader.md`
- `docs/yolo_georeference_spec.md`

## 目的

レーダ表示は、WEBビューアで見ている360画像の視線方向を、QGIS地図上の撮影点へ補助表示する機能です。

主な目的:

- 撮影位置周辺の距離感を、地図上で実寸として把握する。
- 360ビューアで見ている方向を、地図上の方向と対応付ける。
- 地物登録時に、撮影点、視線方向、対象物のおおまかな距離感を同時に確認できるようにする。
- 既存の地物登録プラグインのレイヤ選択や編集ツールを奪わない。

## 基本方針

レーダは、以下の2種類の距離を分離して扱います。

- 絶対距離: 地図上の固定距離を表す同心円
- 校正距離: 人間が地図上の計測値に合わせた基準距離から求める扇形と距離線の奥行き

headingは±10フレームの移動軌跡から推定します。一方で、扇形、direction線、先端垂線の奥行きは移動速度からは決めず、`CalFOV`、`CalDist`、`Scale`、現在FOVから求めます。5m/10mの同心円は固定実距離の基準線として維持します。

## 入力データ

### QGIS側

QGIS側で必要な情報:

- 現在フレーム番号
- フレーム番号ごとの緯度経度
- UIの `Range`
- UIの `Scale`
- UIの `CalFOV`
- UIの `CalDist`
- UIの `Offset`

フレーム位置は、`Process` 実行後に `main.py` の `frame_position_by_frame` へ辞書化されます。

```text
frame_position_by_frame[frame] = (latitude, longitude)
```

これにより、レーダ更新時に `last_rows` を毎回線形探索せず、±10フレームの位置を高速に取得できます。

### WEBビューア側

WEBビューアは `viewer_session.json` へ現在状態を書き出します。

主なフィールド:

- `video`
- `frame_index`
- `yaw_to_camera_heading`
- `pitch`
- `zoom`
- `viewer_camera_height_m`
- `radar`
- `target`
- `targets`
- `updated_at`

QGIS側はこのJSONを500ms間隔でポーリングします。

QGIS側からフレーム移動を通知する場合、`radar` にはWEBビューアHUD用の距離補助値が入ります。

```text
radar.range_m
radar.outer_range_m
radar.base_sector_radius_m
radar.calibration_fov_deg
radar.calibration_distance_m
radar.manual_scale
radar.min_sector_radius_m
radar.min_zoom_multiplier
radar.max_zoom_multiplier
```

ブラウザ側の視点更新POSTでは、同一フレームの `radar` 値を維持します。

360ビューア上で画像をクリックした場合、`target` にはクリック点の投影補助値が入ります。ダブルクリックした場合は、クリック順の複数点として `targets` 配列にも追加します。`target` は互換用に最後の選択点を保持します。

```text
target.x_ratio
target.y_ratio
target.yaw_delta_deg
target.pitch_delta_deg
target.target_yaw_to_camera_heading
target.target_pitch_deg
target.view_yaw_to_camera_heading
target.view_pitch
target.view_zoom
target.projection
```

`targets` の各要素も同じ値を持ち、追加で `id` と `order` を持ちます。`id` / `order` はダブルクリックした順番の管理用です。

`target_yaw_to_camera_heading` は、動画正面を基準にしたクリック点の絶対yawです。`target_pitch_deg` は、クリック点の360球面上の絶対pitchです。`yaw_delta_deg` は、クリック時点のビューア中心から見た相対yawです。クリック後にビューア視点を動かしても、地図投影点が一緒に回らないよう、クリック時点の絶対yaw/pitchとview条件を保存します。

## UIパラメータ

### `Range`

固定距離円の基準距離です。

現在の既定値:

```text
5.0 m
```

描画される同心円:

- `Range`
- `Range * 2`

既定では、5m円と10m円を表示します。

### `Scale`

校正済み距離へ掛ける手動倍率です。

現在の既定値:

```text
1.0 x
```

`Scale` は、人間が現地の見え方と地図計測を見比べて微調整するための値です。通常は `1.0` から始めます。

### `CamH`

このジョブの地面からカメラ中心までの高さです。

現在の既定値:

```text
1.5 m
```

`CamH` は `viewer_session.json` の `viewer_camera_height_m` として保存します。WEBビューア上の5m/10m地面範囲円は、この高さを使ってカメラから見た地面上の円を画面へ投影します。車両、治具、カメラ取り付け位置が変わると変わるため、全体プロファイルではなくジョブ個別条件として扱います。

### `CalFOV`

距離校正時のWEBビューアFOVです。

現在の既定値:

```text
90.0 deg
```

`Use FOV` ボタンを押すと、現在ビューアに表示されているFOVを `CalFOV` へ反映します。

### `CalDist`

`CalFOV` の状態で、ビューア中心線に対応すると人間が判断した地図上距離です。

現在の既定値:

```text
5.0 m
```

たとえば `CalFOV=90deg` で、ビューア中心が地図上の5m地点に対応すると判断した場合、`CalDist=5.0m` とします。

既知の視野幅から設定する場合は、水平FOV内の幅 `width_m` と中心距離 `distance_m` の関係を次のように扱えます。

```text
width_m = 2 * distance_m * tan(FOV / 2)
distance_m = (width_m / 2) / tan(FOV / 2)
```

FOVが90度の場合、`tan(45deg)=1` なので、視野幅10mを基準にするなら中心距離は5mです。

### `Offset`

360映像の正面方向と進行方向が一致しない場合の方位補正です。

選択肢:

- `0deg`
- `90deg`
- `180deg`
- `270deg`

`Offset` は、移動軌跡から求めた進行方向に対して、動画の正面方向が時計回りに何度ずれているかを表します。

例:

- 動画の正面が進行方向そのもの: `0deg`
- 地図レーダが期待方向より90度左を向く: `90deg`
- 動画の正面が進行方向の後ろ向き: `180deg`

将来的に「進行方向=動画正面」を保証した素材だけを扱う場合は、`0deg` を標準値として使います。

## heading算出

headingはGPXの `direction` 属性や地物属性から取得せず、フレーム前後の移動軌跡から推定します。

対象フレームを `i` とします。

基本計算:

```text
before = position(i - 10)
after  = position(i + 10)
```

緯度経度差をローカルなメートル座標差に変換します。

```text
dx = east_m
dy = north_m
```

headingは、北=0度、時計回りのGIS方位です。

```text
heading = (atan2(dx, dy) * 180 / pi + 360) % 360
```

### 端部フォールバック

動画の先頭・末尾などで `i - 10` と `i + 10` の両方が取得できない場合は、取得可能な範囲で代替します。

優先順:

1. `i - offset` と `i + offset` の両方がある最大offset
2. 中心フレーム `i` から `i + offset`
3. `i - offset` から中心フレーム `i`

offsetは10から1まで順に探します。

## 校正距離

扇形、direction線、先端垂線の奥行きは、人間が校正した `CalFOV` と `CalDist` を基準にし、現在FOVとの半角正接比から求めます。

```text
current_fov = 90 / zoom
fov_ratio = tan(current_fov / 2) / tan(CalFOV / 2)
sector_radius_m = max(1.0, CalDist * Scale * fov_ratio)
```

現在FOVが `CalFOV` と同じで `Scale=1.0` の場合、扇形奥行きは `CalDist` と一致します。zoomを上げると現在FOVが狭くなるため、`fov_ratio` は小さくなり、距離線は手前へ寄ります。zoomを下げると現在FOVが広がるため、距離線は奥へ伸びます。

この方式は単眼360画像から距離を自動推定するものではありません。人間が「このFOV、この見え方なら中心線は地図上の何mに相当する」と校正し、その設定をQGIS地図上の垂線とWEBビューアHUDへ同期して表示するためのものです。

## フォールバック

GNSSの暴れや停止時にレーダが不自然に跳ねないよう、前回値を使うフォールバックを行います。

### heading急変

近傍フレーム更新で、算出headingが前回headingから45度を超えて変化した場合は、GNSSの暴れとして扱います。

```text
abs_delta_heading > 45 degrees
```

この場合:

- headingは前回値を維持
- 扇形奥行きは校正距離で再計算し、最小値を下回らないようにする

ただし、地図クリックやナビゲーションで離れたフレームへジャンプした場合は、このheading急変フォールバックを適用しません。離れた場所では進行方向が変わっていて自然だからです。

近傍判定:

```text
abs(current_frame - previous_radar_frame) <= 10
```

### 移動量が小さすぎる場合

±10フレーム相当の移動距離が0.5m未満の場合、停止またはノイズとして扱います。

```text
trajectory_distance_m < 0.5
```

この場合:

- headingは前回値を維持
- 扇形奥行きは校正距離で再計算し、最小1.0mを下回らないようにする

レーダが完全に消えるとUIが不安定に見えるため、停止時でも最小表示を残します。停止時でも距離線は速度ではなく校正値から決まります。

### 計算不能な場合

前後フレーム位置も中心位置も取得できない場合:

- 前回headingがあれば前回headingを使う
- 前回headingがなければ0度を使う
- 前回扇形奥行きがあればそれを使う
- なければ最小1.0mを使う

## viewerBearing

WEBビューアの `yaw_to_camera_heading` は、動画正面からのビューア相対角として扱います。

`Offset` は「進行方向から動画正面までの時計回り角度」、`yaw_to_camera_heading` は「動画正面から現在視線までの時計回り角度」です。この2つを移動軌跡headingへ加算して、地図上の視線方位を求めます。

```text
viewer_bearing = (heading + Offset + yaw_to_camera_heading) % 360
```

`viewer_bearing` は、地図上で扇形中心線、direction線、先端垂線を描画する方向です。

例:

- 進行方向=動画正面、正面を見ている: `Offset=0`, `yaw=0` -> `heading`
- 動画正面が真後ろ、正面を見ている: `Offset=180`, `yaw=0` -> `heading + 180`
- 動画正面が真後ろ、進行方向左を見ている: `Offset=180`, `yaw=90` -> `heading + 270`

## FOV

FOVはWEBビューアの `zoom` から求めます。

```text
fov = 90 / zoom
```

制限:

```text
1.0 <= fov <= 179.0
```

FOVは扇形の左右方向の広がりと、校正距離の倍率計算に使います。奥行きは `CalFOV` と現在FOVの半角正接比で求めた `sector_radius_m` で決まります。

## 描画要素

QGIS上の描画は `QgsRubberBand` による一時描画です。レイヤとして追加しないため、地物登録プラグインの編集レイヤやmap toolを奪いません。

### 固定距離円

2本描画します。

- 内側円: `Range`
- 外側円: `Range * 2`

円は8度刻みの点列からポリゴンとして作成します。

```text
angle = 0, 8, 16, ..., 360
```

### 1m補助グリッド

WEBビューア上の1m破線補助グリッドと同じ距離目安として、QGIS地図上にも1m間隔の補助円を一時描画します。内側円 `Range` と外側円 `Range * 2` は主円として強調するため、補助円からは除外します。

補助円はレーダ表示の一部として扱い、主円と同じタイミングで表示/消去します。個別のON/OFFは持たせません。

### 扇形

中心点を撮影点とし、`viewer_bearing ± fov / 2` の範囲を、校正距離から求めた `sector_radius_m` まで伸ばします。

扇形の分割数:

```text
segment_count = max(8, int(fov / 4))
```

### direction線

撮影点から `viewer_bearing` 方向へ `sector_radius_m` だけ伸ばす線です。

### 先端垂線

direction線の先端を中心に、`viewer_bearing ± 90度` 方向へ短い線を描きます。この線は、現在FOVと校正値から求めた中心距離線です。

現在の長さ:

```text
perpendicular_half_m = sector_radius_m * 0.3
```

## WEBビューアHUD

WEBビューアは、QGIS側から渡された `radar` 補助値と `viewer_camera_height_m` を使い、画面下部に小さな距離HUDと地面範囲円を表示します。

表示要素:

- `Range` 相当の内側目盛り
- `Range * 2` 相当の外側目盛り
- 1m間隔の薄い破線補助グリッド
- QGIS側の先端垂線に対応する校正距離線

破線補助グリッドは常に1mを最小単位にします。たとえば `Range=10m` の場合、主円は10m/20mのまま維持し、1mごとの補助円を薄く描きます。1m線は測量精度を保証するものではなく、距離感を目視で把握するための最小目盛りです。

このHUDは単眼360画像から距離を厳密に復元するものではありません。QGIS地図上の先端垂線と、WEBビューア上の距離線が同じ「現在見ている方向の目安」を示していればよいという扱いです。ユーザは主円と1m補助グリッドの比較から、目測で地物までの距離感を判断します。

HUD表示はWEBビューアの `HUD` ボタンで切り替えます。`HUD` OFF時は主円、1m補助グリッド、校正距離線をまとめて非表示にします。

### 1m補助グリッドの意図

1m補助グリッドは、`Range` 主円だけでは読みにくい「この辺」という距離感を、WEBビューア上で目視しやすくするための補助表示です。`Range=5m` の場合は主円を5m/10mとして強調し、1m、2m、3m、4m、6m、7m、8m、9mを破線で薄く表示します。`Range=10m` の場合も主円は10m/20mで、補助線は1m間隔のままです。

この表示は、標識板、人物の胴体、壁面、電線など高さを持つ対象物の距離を測るものではありません。地表面上の点、たとえば人や標識柱の足元、路面標示、縁石、マンホールなどと比較して使います。高さを持つ対象物を見る場合は、その対象物の地表面上の接地点または根元を基準にします。

実装上は、地表面上の円を360画像へ投影するため、krpanoが利用できる場合は `spacetosphere` と `spheretoscreen` による座標変換を優先します。これにより、WEBビューアでpitchやyawを変えた時の見え方をkrpano本体の球面投影へ寄せます。krpanoがないフォールバック表示では、従来の近似透視投影を使います。

線の色、太さ、破線間隔は成果物データではなく見た目の調整値です。運用中の視認性調整は `360viewer/static/viewer.css` の `.ground-ring-grid`, `.ground-ring-inner`, `.ground-ring-outer` で行います。

## 360クリック点の平面投影

WEBビューア上のクリック点を、撮影中心から見た地図平面上の仮想点として描画できます。

クリック点は、WEBビューア側でHUD範囲円と同じ地面投影から推定した `ground_distance_m` を優先して地図平面へ投影します。これは単眼360画像から任意対象物までの実距離を自動復元するものではなく、地表面上の点、たとえばコーン接地点、標識柱の根元、路面標示、縁石、マンホールなどをクリックする前提の補助投影です。`ground_distance_m` が無い古いセッションや、推定に失敗したクリックだけ、保存した球面pitchと `CamH * HudH` の実効カメラ高から地面平面との交点を求めます。pitchが水平線以上、または地面交差に使えない場合だけ、従来の中心距離平面投影へフォールバックします。

単クリックは従来互換の単一 `target` を更新します。ダブルクリックは複数メモ点として `targets` に追加し、QGIS側は `targets` がある場合に全点を緑の仮点・仮線として描画します。`targets` がない場合だけ、従来の単一 `target` を描画します。WEBビューア上のマーカーは保存時の画面座標ではなく、保存した絶対yaw/pitchを現在視点へ再投影して表示します。

クリック時に保存する主な値:

- `target_yaw_to_camera_heading`: 動画正面からクリック点までの絶対yaw
- `target_pitch_deg`: クリック点の360球面上の絶対pitch
- `view_yaw_to_camera_heading`: クリック時のビューア中心yaw
- `yaw_delta_deg`: クリック点の中心視線からの相対yaw
- `view_zoom`: クリック時のzoom
- `ground_distance_m`: HUD範囲円と同じ投影から推定した撮影点からの水平距離

QGIS側では、通常はWEBビューアが送った `ground_distance_m` をそのまま撮影点からの水平距離として使います。

```text
target_distance_m = target.ground_distance_m
```

`ground_distance_m` が無い場合は、クリック点の絶対pitchから地面上の水平距離を求めます。

```text
effective_camera_height_m = CamH * HudH
target_distance_m = effective_camera_height_m / tan(target_pitch_deg)
```

地面交差に使えないクリック点では、クリック時zoomからクリック時FOVを復元し、`CalFOV` / `CalDist` / `Scale` による中心前方距離へ戻します。クリック点が中心から `yaw_delta_deg` だけ左右にずれている場合、従来どおり視線に垂直な平面上の斜距離を求めます。

```text
click_fov = 90 / target.view_zoom
forward_distance_m = max(1.0, CalDist * Scale * tan(click_fov / 2) / tan(CalFOV / 2))
target_distance_m = forward_distance_m / cos(yaw_delta_deg)
```

地図上の方位は、移動軌跡heading、動画offset、クリック点絶対yawから求めます。

```text
target_bearing = (heading + Offset + target_yaw_to_camera_heading) % 360
```

最後に、撮影点から `target_bearing` 方向へ `target_distance_m` だけ方位距離投影し、QGIS上に一時RubberBandとして線と点を描きます。複数点の場合は、それぞれのクリック点について同じ計算を行い、1つのMultiLine/MultiPoint RubberBandとしてまとめて描画します。

クリック点には距離帯による運用品質を付与します。5m以内は `trusted`、5m超から10m以内は `usable`、10m超は `far` です。オンザフライ表示では `trusted` を緑、`usable` を黄、`far` を赤系のRubberBandへ分けます。保存レイヤにも `quality` 属性として残します。

### クリック投影点の保存レイヤ

QGIS側は、WEBビューアの `targets` を読んで地図平面へ投影できた点を、`360 Click Targets` という自前のメモリポイントレイヤへ追記します。このレイヤは「この辺にこれがあった」という作業メモの保存先であり、最終的な地物台帳レイヤではありません。単クリックの `target` は互換用の一時表示として扱い、保存対象にはしません。

現在の `viewer_session.json` にあるダブルクリック点を、QGIS側ポーリング時に地図平面へ投影し、緯度経度geometryと属性テーブルへ保存します。

同一 `video` / `frame` / `target_id` の点は重複登録しません。視点移動によって `viewer_session.json` が更新された場合でも、既に登録済みのクリック点は増殖しない扱いです。

主な属性:

- `video`, `frame`, `target_id`, `target_order`
- `latitude`, `longitude`
- `distance_m`, `forward_m`, `bearing_deg`
- `yaw_delta`, `target_yaw`, `target_pitch`
- `view_yaw`, `view_pitch`, `view_zoom`
- `source_lat`, `source_lon`
- `projection`, `quality`, `created_at`

セッション終了時は、既存の生成メモリレイヤと同じく `tmp.gpkg` へ保存します。GeoPackage内では、撮影点レイヤを `video_gpx_points`、クリック点レイヤを `click_targets_360` という固定レイヤ名で保存します。`tmp.gpkg` は退避ファイル名であり、内部レイヤ名には使いません。

### クリック投影点の復元表示

QGIS側でフレームを表示する際、`360 Click Targets` または読み戻した `click_targets_360` 相当レイヤに同じ `video` / `frame` のレコードがあれば、保存済み属性から `targets` を再構成してWEBビューアへ渡します。WEBビューアのPrev/Nextだけでフレーム移動した場合も、QGIS側ポーリング時に現在sessionへ点が無ければ同じ復元処理で `viewer_session.json` へ補完します。

復元参照先は、プロジェクト上の全レイヤをスキーマだけで無条件に拾うのではなく、以下に限定します。

- 現在セッションで作成した自前メモリレイヤ `360 Click Targets`
- 現在動画の出力フォルダにある `tmp.gpkg` の `click_targets_360`
- レイヤ名またはsourceが `click_targets_360` 相当で、かつ `video` 属性が現在のMP4名と一致するレイヤ

新規クリック点の書き込み先は自前メモリレイヤのみです。読み戻したGPKGレイヤへ直接追記しないことで、復元参照用レイヤと作業中の一時レイヤを混同しないようにします。

復元に使う主な属性:

- `target_id`, `target_order`
- `target_yaw`, `target_pitch`
- `view_yaw`, `view_pitch`, `view_zoom`
- `yaw_delta`, `projection`

WEBビューア側は、保存時の画面座標ではなく `target_yaw` / `target_pitch` を現在の視点へ再投影してマーカーを表示します。この復元は「どの画像上のどの方向へ点を置いたか」を確認するための作業継続表示であり、厳密な画像計測結果の再現ではありません。

### GPKGからの作業状態読込

パネルのGPKG読込では、GeoPackage内の `video_gpx_points` と `click_targets_360` を直接編集せず、標準のメモリレイヤへコピーします。

- `video_gpx_points` -> `Video GPX Points`
- `click_targets_360` -> `360 Click Targets`

読込後は、プラグイン内部のフレーム参照レイヤを読み込んだ `Video GPX Points` へ、クリック点保存レイヤを読み込んだ `360 Click Targets` へ差し替えます。作業中の追加クリック点もメモリレイヤへ追記し、終了時に `tmp.gpkg` の同じ内部レイヤ名へ保存します。

`tmp.gpkg` にはプラグイン専用のジョブメタデータテーブル `gpx_video_processor_job_metadata` も保存します。ここには、元MP4、元GPX、KP CSV、`Shift`、`KP tol`、`Range`、`Scale`、`Offset`、`CalFOV`、`CalDist`、`CamH` など、作業状態の復元と由来確認に必要な値をkey/valueとして記録します。MP4はビューア表示に実体が必要なため、読込時にファイルが存在する場合だけパネルへ復元します。GPXとKP CSVは、同期済み座標やKP結果がすでにGPKG内にあるため、ファイルが存在しなくても由来の参照情報としてパネルへ復元します。

GPKG読込後は復元作業モードとして扱い、GPX/MP4/KP/Outputの再選択、`Shift`、`KP tol`、`全件処理`、別GPKG読込を無効化します。撮影条件や入力データを差し替える場合は段取り替えとして一度セッションを終了します。

クリック点があるGPKGを読んだ場合、ナビゲーションモードは `Picked point` を既定にします。このモードでは `360 Click Targets` の `frame` だけを前後移動し、ブックマークのように地物を置いたフレームだけを見直せます。移動時は現在ユーザが見ている視点ではなく、保存済みの `view_yaw` / `view_pitch` / `view_zoom` を再現します。同一フレームに複数点がある場合は、クリック順で最後の点を代表視点として使います。

この段階ではGPKGを本体DBとして直接編集するのではなく、GPKGは作業状態の読込元・終了時バックアップ先として扱います。

この投影は以下の検証用です。

- 校正した中心距離とクリック角だけで、地図上の目標位置が直感と合うか確認する。
- 360ビューア上のクリック点と、QGIS地図上の地物位置の対応を目視確認する。
- 将来のYOLO矩形中心の地図投影で使う方位・距離モデルの妥当性を検討する。

制約:

- 奥行きは人間が与えた校正距離に依存します。
- 対象物がクリック時視線に垂直な平面上にあるという近似です。
- 現在のWEBビューア側クリック角は、画面座標とFOVから求める近似です。将来的にはkrpanoの球面座標APIを使い、より正確なクリックyaw/pitchへ置き換える余地があります。

## 座標計算

距離・方位から緯度経度点を求める処理は、WGS84球面近似で行います。

使用半径:

```text
earth_radius_m = 6378137.0
```

描画前に、EPSG:4326の点を現在のQGIS canvas CRSへ変換します。

## 状態管理

レーダ描画では以下の前回値を保持します。

- `last_radar_heading`
- `last_radar_sector_radius_m`
- `last_radar_frame_index`

これらは以下のタイミングでクリアします。

- `clearRadar()`
- セッション終了
- レーダ描画アイテム削除

## 現在の制約

- 扇形奥行きは最小1.0mです。
- `CalFOV` は1度から179度に制限しています。
- `yaw_to_camera_heading` のGIS方位変換は、実データで視覚確認しながら必要に応じて調整します。
- heading算出はローカルなメートル換算であり、短距離移動を前提にしています。
- `Range`, `Scale`, `CalFOV`, `CalDist`, `Offset` の既定値は暫定です。

## 確認観点

QGIS上で確認する項目:

- `Range=5m` のとき、5m円と10m円が描かれる。
- `Range=10m` のとき、主円は10m/20mで、1m間隔の破線補助グリッドが表示される。
- 速度がある区間では扇形が進行方向へ向く。
- 停止に近い区間でも、扇形が完全には消えない。
- 連続フレーム移動時に、GNSSノイズでheadingが大きく跳ねない。
- 地図クリックで離れたフレームへ移動した場合、新しい場所のheadingが採用される。
- ビューアでyawを変えると、扇形の向きが追従する。
- zoomを変えると、扇形の幅が変わり、`CalFOV` / `CalDist` 基準で扇形奥行きと先端距離線も連動して伸縮する。
- `Use FOV` で現在FOVを校正基準へ取り込み、`CalDist` / `Scale` を変えるとQGIS側垂線とWEBビューアHUDが同じ距離へ動く。
- 動画正面が進行方向とずれている場合、`Offset=0/90/180/270deg` で期待方向に合わせられる。

## 将来の検討

- 扇形奥行きの最大値をUIまたは定数で設定する。
- `Range` の2本表示を、任意本数・任意距離へ拡張する。
- レーダON/OFF、色、透過率をUI設定化する。
- heading算出に使うフレーム窓幅をUI設定化する。
- 実データで `yaw_to_camera_heading` の方位変換が逆向きに見える場合、変換式を切り替えられるようにする。
- 動画素材メタデータや処理設定から `Offset` を自動適用できるようにする。
