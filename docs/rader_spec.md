# レーダ表示 実寸準拠仕様

更新日: 2026-06-04

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
- 動的距離: 直近の移動量から求める扇形の奥行き

FOVは扇形の広がりだけに使います。扇形の奥行きには使いません。

## 入力データ

### QGIS側

QGIS側で必要な情報:

- 現在フレーム番号
- フレーム番号ごとの緯度経度
- UIの `Range`
- UIの `Scale`
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
- `updated_at`

QGIS側はこのJSONを500ms間隔でポーリングします。

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

扇形、direction線、先端垂線の奥行きを調整する倍率です。

現在の既定値:

```text
1.0 x
```

扇形奥行き:

```text
sector_radius_m = trajectory_distance_m * Scale
```

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

## 動的距離

扇形の奥行きは、heading算出に使った区間の移動距離を基準にします。

```text
trajectory_distance_m = sqrt(dx^2 + dy^2)
sector_radius_m = trajectory_distance_m * Scale
```

このため、速度が速い区間では扇形が長くなり、停止に近い区間では短くなります。

## フォールバック

GNSSの暴れや停止時にレーダが不自然に跳ねないよう、前回値を使うフォールバックを行います。

### heading急変

近傍フレーム更新で、算出headingが前回headingから45度を超えて変化した場合は、GNSSの暴れとして扱います。

```text
abs_delta_heading > 45 degrees
```

この場合:

- headingは前回値を維持
- 扇形奥行きは算出距離を維持しつつ、最小値を下回らないようにする

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
- 扇形奥行きは最小1.0m

レーダが完全に消えるとUIが不安定に見えるため、停止時でも最小表示を残します。

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

FOVは扇形の左右方向の広がりだけに使います。扇形の奥行きは `sector_radius_m` で決まります。

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

### 扇形

中心点を撮影点とし、`viewer_bearing ± fov / 2` の範囲を `sector_radius_m` まで伸ばします。

扇形の分割数:

```text
segment_count = max(8, int(fov / 4))
```

### direction線

撮影点から `viewer_bearing` 方向へ `sector_radius_m` だけ伸ばす線です。

### 先端垂線

direction線の先端を中心に、`viewer_bearing ± 90度` 方向へ短い線を描きます。

現在の長さ:

```text
perpendicular_half_m = sector_radius_m * 0.3
```

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

- 扇形奥行きに上限値はまだ設定していません。
- `yaw_to_camera_heading` のGIS方位変換は、実データで視覚確認しながら必要に応じて調整します。
- heading算出はローカルなメートル換算であり、短距離移動を前提にしています。
- `Range`, `Scale`, `Offset` の既定値は暫定です。

## 確認観点

QGIS上で確認する項目:

- `Range=5m` のとき、5m円と10m円が描かれる。
- 速度がある区間では扇形が進行方向へ伸びる。
- 停止に近い区間でも、扇形が完全には消えない。
- 連続フレーム移動時に、GNSSノイズでheadingが大きく跳ねない。
- 地図クリックで離れたフレームへ移動した場合、新しい場所のheadingが採用される。
- ビューアでyawを変えると、扇形の向きが追従する。
- zoomを変えると、扇形の幅だけが変わり、奥行きは変わらない。
- 動画正面が進行方向とずれている場合、`Offset=0/90/180/270deg` で期待方向に合わせられる。

## 将来の検討

- 扇形奥行きの最大値をUIまたは定数で設定する。
- `Range` の2本表示を、任意本数・任意距離へ拡張する。
- レーダON/OFF、色、透過率をUI設定化する。
- heading算出に使うフレーム窓幅をUI設定化する。
- 実データで `yaw_to_camera_heading` の方位変換が逆向きに見える場合、変換式を切り替えられるようにする。
- 動画素材メタデータや処理設定から `Offset` を自動適用できるようにする。
