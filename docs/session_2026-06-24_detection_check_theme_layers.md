# 2026-06-24 Detection Check 主題レイヤ運用メモ

## 背景

`tenkaku_ninja_poi` で生成した `poi_clusters_road_360` を
GPXVideoProcessor の `Detection check` で巡回し、CubeMap 検出由来の POI を
元の 360 動画視点で確認できることを確認しました。

当日の実データでは以下の規模でした。

```text
約 53,000 フレーム
-> 269,600 CubeMap image planes
-> 約 45 万 YOLO 検出
-> 370,371 POI candidates
-> 8,071 POI clusters
```

## QGIS フィルタの注意点

QGIS 属性テーブル内のフィルタ欄で式を入れて `適用` しても、
レイヤの `subsetString()` は設定されません。
そのため、GPXVideoProcessor の `Detection check` から見ると全件が対象になります。

Nav に効くのは、レイヤ本体の subset filter です。

確認:

```python
layer = iface.activeLayer()
print(layer.subsetString())
print(layer.featureCount())
```

例:

```python
layer = iface.activeLayer()
layer.setSubsetString("\"semantic_class\" = '01:road_pothole'")
layer.triggerRepaint()
```

この状態で `featureCount()` が 104 になり、`Detection check / Active layer`
で pothole 候補だけを巡回できました。

## 実装修正

`main.py` の候補 feature 読み取りで、候補レイヤの `subsetString()` を
`QgsFeatureRequest().setFilterExpression(...)` へ明示的に反映するようにしました。

対象:

- `candidateFeatureRequest(layer)`
- `candidateFeatures(layer, selected_only=False)`

これにより、レイヤ本体の subset filter は Detection check の Nav 対象へ反映されます。

## 主題レイヤ運用

ユーザ向けには、subset filter を直接使わせるより、
目的別レイヤを GPKG にあらかじめ用意する方が分かりやすいと判断しました。

例:

```text
全体俯瞰:
  poi_clusters_road_360

目的別レビュー:
  poi_clusters_road_pothole_360
  poi_clusters_road_kilometer_marker_360
  poi_clusters_road_snow_pole_360
  poi_clusters_road_posts_markers_360
  poi_clusters_road_damage_360
```

操作:

```text
単一テーマ:
  対象主題レイヤをアクティブ
  Nav mode = Detection check
  Scope = Active layer

複数テーマ:
  見たい主題レイヤだけ表示 ON
  Nav mode = Detection check
  Scope = Visible layers
```

QGIS のレイヤツリーを「見たいクラスのチェックボックス」として使えるため、
独自のクラス選択 UI を作らずに済みます。

## 意味づけ

今回の価値は、AI が最終判定することではなく、広い 360 動画から
「人が見るべき候補」へ主題別に案内することです。

```text
YOLO evidence
-> POI candidate
-> cluster representative
-> thematic layer
-> 360Viewer review
```

特に pothole や KP 標のように、テーマ別に巡回するだけで実務点検に近い価値があります。
