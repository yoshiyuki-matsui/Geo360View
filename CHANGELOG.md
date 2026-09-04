# Changelog

このファイルは、Geo360View の主要な仕様変更、実装変更、運用上の意味を記録します。

## 0.3.0 - 2026-09-04

### Added

- 360ViewerにPhoto Sphere Viewer + MarkersPluginベースの代替表示エンジンを追加した。
- `engine=psv` を指定した場合に、既存のJSON、画像キャッシュ、`viewer_session.json`、HTTP APIを流用してPhoto Sphere Viewer経路を起動できるようにした。
- Photo Sphere Viewer経路で、ターゲットマーカー、クラス名/信頼度ラベル、HUD連動の表示/非表示、Lock時の視線レイを表示できるようにした。
- Photo Sphere Viewer経路で、360画像だけでなく通常画角画像も同じ画面内の2D fallbackビューアとして表示できるようにした。
- 通常画角画像のPhoto Sphere Viewer fallbackで、マウスホイールズーム、ドラッグPAN、ターゲットマーカー追従、Lock時の視線レイ表示に対応した。
- Photo Sphere Viewer本体、MarkersPlugin、three.jsのESM/CSSをローカルvendor配下から配信する構成を追加した。
- Photo Sphere Viewer用FOV設定として `viewer_psv_min_fov_deg` / `viewer_psv_max_fov_deg` を追加した。

### Changed

- 360ViewerのHTML生成をビューアエンジン選択式にし、既存krpano経路とPhoto Sphere Viewer経路を並走できる構成にした。
- QGIS側のビューアURL/API payload/runtime configにPhoto Sphere Viewer用FOV設定を伝搬するようにした。
- Photo Sphere Viewer経路では、保存状態は既存krpano互換のyaw/pitch/zoomのまま維持し、PSV境界でのみpitch符号差を吸収するようにした。
- 通常画角画像はPhoto Sphere Viewerへパノラマとして渡さず、2D fallbackで扱うようにした。

### Notes

- Photo Sphere Viewer経路は、krpano配布ライセンス課題を切り分けるための代替ビューア検証です。現時点では機能互換を優先しており、フレーム切替時の描画性能はkrpano経路との差があります。
- 地表同心円は360画像でのみ表示します。通常画角画像では3D球面投影を前提にできないため非表示です。
- `viewer_psv_max_fov_deg` はPhoto Sphere Viewer側の制約に合わせて `1..179` に丸めます。広角側を最大に近づけたい場合は `179` を指定します。

## 0.2.2 - 2026-07-29

### Added

- MP4選択時に動画の幅/高さを読み取り、縦横比から `360 / Equirectangular` または `Flat / Normal FOV` の初期候補を提示するようにした。
- Loadタブに `Projection` 選択を追加し、自動推定結果をユーザが手動上書きできるようにした。
- Loadタブに `New Job` を追加し、プラグインをリロードせずに前回のGPX/MP4/KP/Output/GPKG選択をクリアして新規ジョブを開始できるようにした。
- 選択した `viewer_projection`、flat表示用FOV、推定理由を `viewer_session.json`、360Viewer runtime config、`tmp.gpkg` の `gpx_video_processor_job_metadata` に保存・復元するようにした。
- 古いGPKGなど投影メタデータが無い場合は、復元したMP4の縦横比から再推定するようにした。
- `styles/default_style.qml` のカテゴリラベルを読み取り、内部の `semantic_class` は英語キーのまま、QGISレイヤ/凡例表示だけ日本語などの表示名へ置き換えられるようにした。

### Changed

- 通常の撮影点ナビゲーションでも、選択中の `viewer_projection` を360Viewer URL/API payloadへ渡すようにした。これにより、4K通常画角やcrop動画を初期位置合わせ段階からflat表示できる。
- `target_source = yolo_pinhole` の検出候補を表示する場合は、従来通りflat表示を強制しつつ、flat FOVもpayloadへ渡すようにした。
- `終了` 後のパネルリセットで、前回ジョブのKP CSVやOutput指定を次ジョブへ持ち越さないようにした。
- Process開始時、Output内に既存の `tmp.gpkg`、frames CSV、navigation JSON、matched CSVがある場合は上書き確認を出すようにした。
- `all_poi.gpkg` などの候補/クラスタレイヤのスタイル同期を、`All_Classes` レイヤ名依存から `semantic_class` フィールド基準へ変更した。複数クラスレイヤは `semantic_class` で分類表示し、カテゴリ順はクラス名文字列昇順にする。
- POIクラスタレイヤのQGIS表示prefixを `360 POI Clusters:` から `POI:` に短縮した。単一クラスレイヤを日本語表示しても、保存時の内部レイヤ名は `semantic_class` を優先する。
- GPKG内の候補レイヤ群の `model_name` が1種類に決まる場合は `styles/<model_name>.qml` を優先して読み込み、存在しない場合は `styles/default_style.qml` へフォールバックするようにした。

### Notes

- 縦横比判定は最終決定ではなく初期提案です。`width / height` が2.0付近なら360/equirectangular、それ以外ならflatを提案しますが、crop動画、特殊な360投影、再エンコード済み動画ではユーザ確認と手動上書きを前提にします。

## 0.2.1 - 2026-07-01

### Added

- `styles/default_style.qml` をプラグイン配下の正本スタイルとして読み込み、`All_Classes` の分類スタイルを起点に class 別レイヤへ単一シンボルを同期するようにした。
- `all_poi.gpkg` 読み込み時に `Session` と `All_POIs` のレイヤグループを自動生成し、終了時には空グループを自動削除するようにした。
- `All_Classes` を中心に、class 別レイヤをレイヤツリー上の凡例として扱えるようにした。

### Changed

- `tmp.gpkg` は Geo360View の位置合わせ済み入力、`all_poi.gpkg` は conductor の出力、という役割分担を明確化した。
- `all_poi.gpkg` を開いた後の Nav は、QGIS のレイヤ選択と scope に追従する前提へ整理した。
- `Session` / `All_POIs` グループは、レイヤがなくなれば残さないようにした。

### Fixed

- `all_poi.gpkg` を読み込んだときに、class 別レイヤのアイコンや表示が `All_Classes` と一致しない問題を修正した。
- プラグイン終了後に空の `Session` / `All_POIs` グループだけがレイヤパネルに残る問題を修正した。

## 0.2.0 - 2026-06-12

### Added

- MP4名を既定出力フォルダ名にし、動画ごとの成果物が混在しないようにした。
- パネルにGPKG読込を追加し、`tmp.gpkg` から作業状態を復元できるようにした。
- GPKG保存時の内部レイヤ名を `video_gpx_points` / `click_targets_360` に固定した。
- GPKG内に `gpx_video_processor_job_metadata` を保存し、元MP4/GPX/KP CSV、出力先、`Shift`、`KP tol`、`Range`、`Scale`、`Offset`、`CalFOV`、`CalDist`、`CamH`、`Follow` などを復元できるようにした。
- 360ビューアのダブルクリックで複数のクリック点を保存し、QGIS地図上の `360 Click Targets` へ緯度経度付きで記録できるようにした。
- 保存済みクリック点を360ビューア上に復元表示できるようにした。
- `Picked point` ナビゲーションモードを追加し、クリック点があるフレームだけをブックマークのように巡回できるようにした。
- `Picked point` 移動時は保存済みの `view_yaw` / `view_pitch` / `view_zoom` を再現するようにした。
- 360ビューアとQGIS地図上に、1m間隔の補助グリッド/補助円を追加した。
- `HUD` 切替で、360ビューア上の主円、1m補助グリッド、距離HUDをまとめて表示/非表示にするようにした。
- カメラ高さ `CamH` をジョブ個別条件としてパネル入力、`viewer_session.json`、GPKGメタデータへ保存するようにした。
- GPX / MP4 / KP CSV / Output / GPKG のファイル選択ダイアログで、前回選択フォルダを記憶するようにした。
- Edge/Chromeが利用できる場合、360ビューアを通常タブではなく専用アプリウィンドウで開くようにした。
- GPKG読込時、クリック点がある場合は既定ナビゲーションモードを `Picked point` にするようにした。
- GPKG読込後は復元作業モードとして、GPX/MP4/KP/Output再選択、`Shift`、`KP tol`、`全件処理`、別GPKG読込を無効化するようにした。
- 2026-06-12時点のResume/Picker設計判断を `docs/session_2026-06-12_resume_picker_notes.md` に記録した。

### Changed

- GPKG読込時、MP4はファイル実体が存在する場合だけ動画パスとして復元し、GPX/KP CSVはファイルが無くても由来情報として復元するようにした。
- 360クリック点は正式な地物レイヤではなく、地物登録前段の仮メモレイヤとして扱う方針に整理した。
- 1m補助グリッドは地表面上の距離目安であり、標識板、壁面、電線など高さを持つ対象物の測距には使わない方針を明文化した。
- 360ビューア起動時、フレーム付き `/viewer?...` が作れない場合は `http://127.0.0.1:8181` の初期画面を開かず、サーバ起動だけにした。
- レーダ・クリック投影・ビューアHUDの仕様を、QGIS側とWEB側の整合を重視する方向へ整理した。

### Fixed

- QGISプロジェクト内にラスタレイヤがある場合、クリック点レイヤ判定で `fields()` を呼んでクラッシュする問題を修正した。
- GPKG読込時にOGR由来の `fid` / `ogc_fid` がメモリレイヤへ混入し、新規クリック点追加時に属性がずれる問題を修正した。
- GPKG保存時に既存ファイル全体を再作成せず、内部レイヤ単位で上書き保存するようにした。
- 360ビューア専用アプリウィンドウ起動時に、通常の `127.0.0.1` 初期画面が併発する経路を抑制した。

### Known Limitations

- 360単眼画像から任意対象物までの距離を厳密に測るものではない。
- 距離目安は地表面上の点を対象にする。標識や電柱は根元、人物は足元を基準にする。
- カメラ高さ、pitch、レンズガード、スティッチ、FlowState、実写画角の影響は今後の実測確認が必要。
- `tmp.gpkg` は作業状態の復元用中間DBであり、納品DBとして扱う場合は別途成果品チェックが必要。
- 通常画角カメラ画像はflat表示として扱えるが、距離精度はカメラ高、実効FOV、crop条件、軌跡方位に依存する。投影方式は自動推定だけに任せず、ジョブごとに確認する。

## 0.1 - 2026-06-07

### Added

- GPXとMP4からフレーム単位の撮影位置を生成するQGISプラグイン初期実装。
- `Video GPX Points` メモリレイヤ生成。
- フレームシフト対応。
- KP CSV最近接マッチングとマッチ済みナビゲーションCSV/JSON出力。
- Flask非依存のローカル360Viewer。
- krpanoによる360画像表示と、QGIS側フレーム選択からのHTTP連携。
- `viewer_session.json` を介したyaw/pitch/zoomの疎連携。
- QGIS地図上の一時レーダ表示。
- `CalFOV` / `CalDist` / `Scale` / `Offset` による距離目安の校正。
- QGISパネルの日本語UI、tooltip、手動チェックリスト、品質保証メモ。
