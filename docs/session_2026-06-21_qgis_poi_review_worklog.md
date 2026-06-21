# 2026-06-21 QGIS POIレビューUI 午前作業ログ

このメモは、360全周物体検出POI化パイプラインをQGIS上で確認・精査するために、
午前中に追加したUI/運用仕様をまとめるものです。

## 背景

`semantic_work.sqlite` で検出・POI候補化した結果を `tmp.gpkg` へ出し、
QGISプラグインで360Viewerと連動して確認する運用が実用段階に近づきました。

ポットホールモデルでは、路面上のクラックや側溝蓋などが地図上へ落ち、
`poi_candidates_pothole_360` と `poi_clusters_pothole_360` を比較しながら確認できました。
既存の交通標識モデルでは、高速道路案内標識は拾いにくい一方で、
一般道信号やキロ程標を別クラスとして拾う挙動が確認できました。

この結果から、QGIS側は単なる表示ではなく、
候補レイヤを絞り込み、順に360画像で確認し、不要なものを落とすレビュー台として扱う方針に整理しました。

## 1. 候補レイヤの複数読込

従来は `poi_candidates_360` の標準名に寄りすぎていました。
現在は `gpkg_contents` から以下のfeatures layerを探して読み込みます。

- `poi_candidates_360`
- `poi_candidates_{model_slug}_360`
- `poi_clusters_{model_slug}_360`

QGIS表示名は以下のように元レイヤ名を残します。

- `360 Detection Candidates: poi_candidates_pothole_360`
- `360 POI Clusters: poi_clusters_pothole_360`

これにより、ポットホール候補、交通標識候補、クラスタ代表POIなどを別レイヤとして並べ、
QGISのスタイルやフィルタを使い分けられます。

## 2. Detection check Scope

`Detection check` に `Scope` を追加しました。

- `Active layer`: 現在QGISで選択している候補/クラスタレイヤだけをNav対象にする。
- `All candidates`: 読み込まれている候補/クラスタレイヤ全体をNav対象にする。
- `Selected features`: QGIS上で選択中のfeatureだけをNav対象にする。

QGISのsubset filterは `getFeatures()` に反映されるため、
式ビルダーで `semantic_class`, `model_name`, `confidence`, `evidence_face` などを絞ると、
その表示結果だけを360Viewerで順番に確認できます。

この仕様により、クラス別・レイヤ別・選択済みfeature別のレビューをQGISに委ねます。
プラグイン側に専用検索UIを増やさず、QGISを空間DBの操作UIとして活用する方針です。

## 3. 先頭/最後尾ナビゲーション

Navボタン列に以下を追加しました。

- `|<<`: 現在のNav対象の先頭へ移動
- `>>|`: 現在のNav対象の最後尾へ移動

対象範囲は現在のNav modeに従います。

- `Detection check`: 現在のScopeとQGISフィルタ後の候補frame集合
- `Picked point`: クリック点があるframe集合
- `KP matched CSV`: matched CSV上のframe集合
- `Layer point` / `Frame step`: `Video GPX Points` のframe集合

地物種類やフィルタ条件を変えながら、始点から終点まで何度もレビューする運用を想定しています。

## 4. 360Viewer更新とログ抑制

連続Nav時に、既存ビューアが一時的にbusyだと新しいビューアを開く経路へ落ちることがありました。
既にビューアが開いている場合は、開き直さず `/api/session/navigate` の再送を行うようにしました。
古いリトライが後から戻すことを防ぐため、現在要求中のframeだけを更新するガードも入れています。

また、QGIS messageBar/logへ高頻度ログを流すと連続閲覧のラグになります。
操作パネルに `Log` チェックを追加し、OFF時は以下を抑制します。

- `360Viewer frame updated`
- フレーム保存/キャッシュ命中のINFO
- 一時的なviewer navigation失敗ログ
- 360Viewer HTTPアクセスログ
- ブラウザ内debug logのDOM追加

警告や起動失敗はOFFでも出します。
通常レビューは `Log` OFF、調査時だけONを推奨します。

## 5. 終了時保存の見直し

候補レイヤが増えると、`終了` 時に全メモリレイヤを `tmp.gpkg` へ書き戻す処理が重くなります。
一方で、QGISテーブル上で不要クラスや誤検出を削除し、その結果を書き戻したい運用もあります。

現在の仕様は以下です。

- GPKGから読み込んだ候補/クラスタレイヤは、閲覧だけなら終了時に再保存しない。
- feature追加、削除、属性変更、ジオメトリ変更が入ったレイヤは保存対象に昇格する。
- Processで新規生成した `Video GPX Points` や、新規クリック点レイヤは終了時保存対象にする。
- 既存クリック点レイヤへ手動クリック点を追加した場合も保存対象にする。
- 候補/クラスタレイヤを書き戻す場合は、元の `poi_candidates...` / `poi_clusters...` 名を維持する。

これにより、ただレビューして閉じる場合は軽く、
QGISで削除・編集して閉じる場合はその変更を `tmp.gpkg` へ反映できます。

## 6. 空間インデックス

GPKGからメモリレイヤへ読み替えた候補/クラスタレイヤと、
Processで生成した撮影点レイヤには、可能ならメモリproviderの空間インデックスを作ります。

これは終了時書き戻し自体を速くするものではありません。
地図表示、選択、範囲処理などQGIS側操作の体感改善を狙ったものです。

## 7. 確認

コード側で確認した内容:

```bash
python -m py_compile main.py viewer_controller.py frame_extract.py messages.py 360viewer/app.py
node --check 360viewer/static/viewer.js
python -m unittest discover -s tests
```

最終確認では `95 tests` が通っています。

実機所感:

- `Log` OFFと既存Viewer更新リトライにより、連続Nav中のもたつきとViewer新規起動は再発していない。
- 地図追従が速くなり、それに引きずられるように360Viewer表示も速く感じる。
- 全体として、地物種類やフィルタを変えながら始点から終点へレビューする体感が向上している。

この体感向上は、QGISログ抑制、Viewer開き直し回避、メモリレイヤ空間インデックス、
高頻度書き戻し抑制が複合的に効いている可能性があります。
ただし個別寄与は未計測のため、現時点では運用所感として扱います。

## 次に見ること

- QGIS実機で、未編集GPKG読込後の `終了` が軽くなっていること。
- 候補レイヤでfeature削除後、`終了` で同じレイヤ名へ書き戻ること。
- `Detection check` の `Active layer` / `All candidates` / `Selected features` が、
  QGIS subset filterと組み合わせて期待通りにNav対象を変えること。
- `Log` OFFで連続Nav中にビューア新規起動やログ由来のもたつきが再発しないこと。
