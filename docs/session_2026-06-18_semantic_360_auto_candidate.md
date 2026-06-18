# 2026-06-18 Semantic 360 Auto Candidate 経緯メモ

このメモは、360ビューアが手動Pickerを経て、YOLO由来の自動候補点を地図と360ビューへ戻す
`Auto Candidate Picker` へ拡張された経緯と、現時点の設計判断を残すものです。

## 一言でいうと

360動画からCubeMapを生成し、YOLOで検出したbboxを360球面上の `target_yaw/target_pitch`
へ戻し、QGIS上の候補アイコンと360ビューア上の確認マーカーとして復元できるようになりました。

これは測量成果として正確な緯度経度を作る機能ではありません。目的は、
「このフレーム、この方向に、この意味を持つ候補がある」を地図と360ビューに接続し、
現場確認や正式POI化の入口を作ることです。

## 背景

当初の360ビューアは、GPX/MP4同期済みの撮影点から、該当フレームの360映像を見るためのUIでした。

その後、手動クリック点を地図上へ投影するPickerへ拡張しました。校正画像を使って、
カメラ高、HUD高さ倍率、範囲円、地図上の投影点を合わせ込み、5m程度の近接範囲では
実用的な候補点を落とせることを確認しました。

この時点で重要だった判断は、地図上の点を全て等価に扱わないことです。距離や投影条件から
`quality` を持たせ、近接で信頼できる点と、遠方で怪しい点を分けて扱う設計にしました。

## 今日できたこと

今日の主な進捗は、YOLO検出結果を手動クリック点互換の中間表現に乗せ、
地図と360ビューアへ戻す経路が通ったことです。

処理の流れは次の通りです。

```text
MP4 / tmp.gpkg
  -> CubeMap 6面生成
  -> YOLO検出
  -> yolo_detections_raw
  -> semantic_targets_360
  -> poi_candidates_360
  -> tmp.gpkg
  -> QGIS候補レイヤ
  -> 360Viewer Detection check
```

実装上は、QGISプラグイン本体にYOLOやpy360convertを混ぜず、
`TenkakuNinja/` 配下のCLIで `semantic_work.sqlite` を生成します。
QGISプラグインは成果物である `tmp.gpkg` を読み、確認UIとして振る舞います。

## 重要な確認結果

最も大きい確認結果は、py360convertで作ったCubeMap上のYOLO検出位置が、
krpanoの360ビューア上の球面位置へ正しく戻せることです。

標識の検出では、地図上の緯度経度は粗くても、360ビューア上では検出対象の標識に
マーカーがほぼ乗るケースを確認しました。

これは次の規約が噛み合っていることを意味します。

- CubeMapの `front/right/back/left/up/down` 面の向き
- 各面のu/v座標
- CubeMap上のbbox代表点からカメラローカルrayへの変換
- rayから `target_yaw/target_pitch` への変換
- krpano上で同じyaw/pitchへマーカーを置く表示経路

この一致により、YOLO検出結果は単なる画像上の矩形ではなく、
360空間上の意味付き方向として扱えるようになりました。

## レイヤとデータの役割

`tmp.gpkg` では、手動点と自動候補を混ぜません。

```text
video_gpx_points
  撮影点。frameと位置の基準。

click_targets_360
  人が360ビューアでクリックした点。
  近接・地面対象で正式POI候補へ育てやすい。

poi_candidates_360
  YOLO由来の自動候補点。
  semantic_class, confidence, evidence, target_yaw/target_pitchを持つ。
  現時点では確認用候補であり、正式点とは別扱い。
```

`poi_candidates_360` は地図上にもPOINTとして表示できますが、特に標識などの空中物では
緯度経度を信用しすぎない前提です。価値の中心は、地図上の概略候補と、
360ビューア上で「あれを拾った」と確認できる視線復元です。

## Detection check

QGISプラグインのNavに `Detection check` を追加しました。

このモードでは、`poi_candidates_360` が存在するframeだけを辿ります。
対象frameへ移動すると、同じframeのYOLO候補が360ビューアへ `targets` として送られます。

候補マーカーは手動クリック点と区別するため、ビューア上では別色で表示します。
`semantic_class` と `confidence` もsessionに残すため、ブラウザのtitleや後続処理で参照できます。

また、YOLO候補には `target_source=yolo_candidate` を持たせています。
これによりレーダ描画はできますが、手動クリック点として `click_targets_360` へ保存されることはありません。

## 精度と期待値

現時点の整理は次の通りです。

- 地面上の近接対象は、手動Pickerと同じ考え方で比較的扱いやすい。
- 標識などの空中物は、単眼360画像だけでは奥行きが分からない。
- 空中物の地図位置は、方角を信じた仮置き候補として扱う。
- 360ビューア上の方向復元はかなり有効で、検出対象の再発見に使える。
- 地図上の点は測量成果ではなく、候補アイコンである。
- 正式な位置は、近接フレームでの手動クリック、現地確認、台帳照合、測量などで確定する。

このため、営業・顧客説明では「緯度経度を正確に出す」ではなく、
「走行映像から沿線候補を拾い、地図と360ビューで根拠確認できる」と表現するのが安全です。

## 今日の設計判断

主な判断は次の通りです。

- YOLO結果を直接正式POIにしない。
- まず `semantic_targets_360` でクリック点互換のyaw/pitch表現へ変換する。
- 地図上の自動候補は `poi_candidates_360` に分ける。
- 手動クリック点 `click_targets_360` とは混ぜない。
- `semantic_work.sqlite` は内部DB、`tmp.gpkg` はユーザがQGISで扱う成果DBとする。
- 複数モデル、複数faceを同じDBに追記できるようにする。
- CubeMap生成、YOLO検出、レポート生成はチェックポイント型にする。
- QGIS側では候補レイヤの証跡列をhidden columnsにして、普段は見せすぎない。

## 事業・R&D上の意味

今日の成果は、単なる360ビューアの機能追加ではありません。

360映像から意味候補を抽出し、位置、根拠画像、360視点へ接続する入口ができました。
これは、インフラが自分の状態を語る世界、つまりInfraGenom構想へ向かう部品です。

今後の顧客との会話では、モデル精度そのものよりも次の問いが重要になります。

- 欲しいものが見えているか。
- 現場では何を異常と呼ぶか。
- これは見るべき候補か、無視してよい誤検出か。
- どの粒度で地図にアイコンがあれば業務に使えるか。
- 候補を採用・棄却・正式POI化する運用はどうあるべきか。

誤検出も、顧客に「では何を見ていますか」と聞き返す材料になります。
この意味で、Auto Candidateは完成品ではなく、現場の判断基準を引き出すR&D営業の道具です。

## 次にやること

明日の想定作業です。

- CubeMap生成が終わった高速道路データへYOLO検出を実行する。
- face別、model別に検出を追加し、同じ `semantic_work.sqlite` に追記する。
- `semantic_targets_360` と `poi_candidates_360` を生成する。
- `tmp.gpkg` へmergeし、QGIS上で候補分布を確認する。
- `Detection check` で360ビュー上の視点復元を確認する。
- 地面対象、標識、路面対象で地図位置の荒れ方を比較する。
- 採用/棄却の `review_status` 運用を検討する。

## 参照

- `TenkakuNinja/semantic_360_pipeline.md`
- `TenkakuNinja/semantic_360_py_reference.md`
- `TenkakuNinja/env_notes.md`
- `docs/yolo_georeference_spec.md`
- `docs/qgis_manual_test_checklist.md`
