# QGIS 4.2.2対応と応答停止の調査

最新の結果は[0.5.6環境別動作検証記録](runtime_validation.ja.md)を参照してください。本書は調査途中の記録を含みます。途中で試したFFmpeg自動フォールバックは、最終候補の対話操作では無効です。

## 対象と現状

- Windows導入先: `C:\Users\ns0521\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\Geo360View`
- 調査開始時点の導入版は0.5.1、開発リポジトリは0.5.4。今回の対応版は0.5.5。
- 利用者報告: QGIS 4.2.2では互換バージョン表記を変更するとパネルは起動するが、ボタン操作で応答しなくなる。同じ4.2.2の別PCでは動作する場合がある。
- 実機での停止箇所は未特定。Python単体テストの成功はQGIS実機での動作保証を意味しない。

### 0.5.4のQGIS 4.2.2確認

利用者が0.5.4をインストールし、パネル表示と操作が可能であることを確認した。ただし地図クリックで`'QgsMapMouseEvent' object has no attribute 'x'`が発生した。これはフレーム抽出より前のクリック座標取得で発生するAPI互換エラーで、表示メッセージの動画コーデック案内はこの例外の原因を示していない。

`map_tools.py`の`event.x()` / `event.y()`を`event.originalPixelPoint()`から取得する座標へ変更した。このQGIS APIは元の未スナップの画面ピクセル座標を返す。QGIS 3系との共通APIを使い、Qt6形式で`x()` / `y()`のないイベントの回帰テストを追加した。

### 0.5.5のQGIS 4.2.2確認（2026-10-08）

利用者が`Geo360View-0.5.5.zip`をZIPインストールし、WindowsのQGIS 4.2.2で動作したことを報告した。0.5.5をQGIS 4対応版として扱い、対応上限を検証済みの4.2.2とする。個別の操作項目別の検証結果は、以下の実機チェックを使用して追加記録する。

利用者による追加の操作確認:

| 操作 | 確認結果 |
| --- | --- |
| GPX・MP4の選択と位置合わせ | 動作確認済み |
| Markingの実行と保存 | 動作確認済み |
| 視点復元 | 動作確認済み |
| 静止画スナップショット保存 | 動作確認済み |
| 位置合わせ後、プラグイン終了時のtmp.gpkg作成・保存 | 動作確認済み |
| QGIS再起動後のtmp.gpkg再読み込み | 結果未記録 |

この記録は利用者の実機報告に基づく。利用者はQGIS 3.40でも0.5.5の動作を確認し、デグレードは見られないと報告した。両環境での確認を受け、0.5.5は`experimental=False`の通常リリースとして準備する。GitHubおよびQGISプラグインリポジトリへの公開は別途行う。

### Markingナビゲーション中のNaN警告

追加検証で`cannot convert float NaN to integer`を伴うフレーム抽出警告が報告された。実機のスタックは未取得のため、具体的な失敗箇所は未確定。ただし緯度がNaNのGPS EXIF生成で同じ例外を再現した。

- `_parse_float`でNaN・無限大を欠損扱いにし、0は有効な値として保持する。
- EXIFへ渡すGPS座標を有限値と緯度経度の範囲で検証する。不正値はGPSタグを省略し、JPEGとその他のEXIFタグは保存する。
- 不正な補正後座標は元の撮影点座標へフォールバックする。
- 抽出エラーには動画オープン・フレーム読み込み・JPEG保存の処理段階を表示し、完全なスタックをログへ出力する。
- Marking終端の高速移動は`no_picked_frame`を通知して表示処理を呼ばない。通常の1フレーム移動はMarkingの有無にかかわらず次の動画フレームへ進む。

NaN座標を持つ地物でもJPEGを保存できることと、Marking終端での停止処理を含め、56件の単体テストが通過した。追加修正後、利用者は実機でコーデックの案内と`cannot convert float NaN to integer`の両方が出なくなったことを確認した。

参考: [QgsMapMouseEvent API](https://qgis.org/pyqgis/master/gui/QgsMapMouseEvent.html)。

### Ubuntu / QGIS 3.44でのロード時クラッシュ（2026-10-08）

Windowsでの検証後、利用者からUbuntuベアメタルのQGIS 3.44で0.5.5をロードするとQGISが即終了するとの報告を受けた。原因は未特定で、Ubuntu版・QGISのパッチ版・終了直前のログは未取得。Windowsの動作確認をUbuntuでの確認として扱わない。

プラグインのimport、コンストラクタ、`initGui`ではOpenCVの動画処理を開始しない。まずUbuntuの端末から`PYTHONFAULTHANDLER=1 qgis --noplugins 2>&1 | tee ~/geo360view-crash.log`で起動し、プラグイン管理画面からGeo360Viewを有効化して終了時の出力を記録する。必要に応じて新規プロファイルで比較する。

公開済み0.5.5のZIPとSHA256は変更しない。修正が必要な場合は次版として扱う。

追加報告ではプラグインは起動し、通常操作も可能に見えるが、ナビゲーションからの360表示ができない状態。端末にはブラウザのSandboxおよびlibEGL警告が出たが、Pythonのクラッシュスタックは取得されていない。

`http://127.0.0.1:8181/api/health`は`status=ok`を返したものの、`config`は`/home/y-matsui/.local/share/QGIS/QGIS3/profiles/default/python/plugins/GPXVideoProcessor/360viewer/viewer_config.qgis_runtime.json`だった。応答しているサーバはGeo360View自身の設定を使っていない。両プラグインの既定ポートは8181で、Geo360Viewの`viewerHealth`は`app=360viewer`だけを確認するため、別プラグインのサーバを再利用し得る。旧サーバの停止後、Geo360Viewのみで再確認する必要がある。最初の即終了報告とこの接続先の問題が同じ原因かは未確定。

GPXVideoProcessorを無効化し、Geo360Viewを8182番で使用した後も画像更新に問題があった。8182番のhealthはGeo360Viewの設定パスを返し、QGIS操作でcommandのframeが50071から50671へ更新され、viewer-stateのframeとapplied_command_idも一致した。50671のJPEG直表示は成功した。一方、53671ではPSVのfetchがHTTP 422となり、JPEGの直表示でも`Failed to read frame_index=53671`が確認された。動画オープン後のOpenCVフレーム読み取りが失敗している。総フレーム数とシーク・デコードの確認が必要。

`psv_viewer.js`の`loadFrame`は画像読込前にstateとapplied_command_idを書き換えるため、viewer-stateのID一致だけでは表示成功を判定できない。この挙動と古い画像のフォールバック表示は改善候補だが、実際のフレーム読み取り失敗の原因とは分けて扱う。

実機診断はOpenCV 4.6.0 / FFMPEG、総フレーム数53497、FPS約29.97、53671へのseek=True、read=Falseだった。53671は有効範囲0～53496を超えている。0.5.6候補ではフレーム移動を最終フレームに制限し、終端での追加移動を止める。直接の範囲外表示・抽出も止め、HTTP側は範囲外を明示する。フレーム数は動画パス・サイズ・更新時刻をキーにキャッシュする。単体テスト65件が通過。UbuntuとWindowsでの修正後の実機確認は未完了。

さらに利用者は先頭を選択した場合にもナビゲーションが効かないと報告した。終端超過だけでは全症状を説明できない。50671のJPEGはサーバの既存キャッシュから返された可能性があり、新規デコード成功は未確認。範囲内の複数フレームをOpenCVで直接読み取り、ブラウザの画像切り替え問題とデコード失敗を分けて確認する。

利用者は0.5.4の動作については薄い記憶、0.5.2については動いていたはずと報告した。確定した比較結果ではない。Gitタグv0.5.2・v0.5.4から各版のbuild_plugin_zip.pyで比較用ZIPを作成し、同梱全ファイルが各タグと一致することを検証した。保存先は`dist/ubuntu-baselines/`。公開0.5.5のコミット934e767とv0.5.2の比較でも、`360viewer/app.py`・`360viewer/static/psv_viewer.js`・`viewer_controller.py`・`processor.py`に差分はない。同じUbuntu・動画・範囲内フレームで版を比較し、他の変更の影響と環境・残存サーバ・キャッシュの影響を切り分ける。

その後、問題のマシンはTigerVNC接続と判明した。通常起動のFirefoxと`glxinfo -B`はMesa llvmpipeを使い、Accelerated=noだった。NVIDIAカーネルドライバは有効で、`vglrun glxinfo -B`および`vglrun firefox`で起動したFirefoxのWebGL 1ではRTX 2080 Tiが確認できた。GPU有効化後のナビゲーション復旧については結果未記録。表示用画像の縮小を試すため、このマシンの`viewer_config.json`だけで`viewer_max_width=1536`へ変更する手順を案内した。縮小設定の適用・効果は未確認。

利用者は別のUbuntuベアメタルマシンで0.5.5の動作検証ができたと報告した。こちらの正確なQGISバージョンと操作別の結果は未記録。Ubuntu全体で0.5.5が動かないという状況ではない。最初のマシンの症状と終端超過の修正は、別途継続して確認する。

動作した別マシンでは物理ディスプレイの画面をVNCで共有し、問題の自宅マシンは物理ディスプレイのないヘッドレス構成で変則的な仮想画面へVNC接続していた。利用者はその後、自宅マシンでWebGLがGPUを使う状態になっても従来のナビゲーションができないと報告した。ソフトウェア描画は確認済みの環境差だが、全症状の原因と断定しない。GPU有効化後の範囲内フレーム取得、PSVエラー、WebGL 2の状態を追加確認する。

続いてWebGL 2もNVIDIAになったことを確認したが、Loadingのまま画像が変わらないとの報告が続いた。ブラウザのソースマップ404は配布されていない`.js.map`の参照であり、画像取得の失敗とは区別する。1793のJPEG要求はHTTP 200、X-Frame-Source=decodeだった。ただしHTTP成功は画像内容の正しさを保証しない。利用者はその後、imagesとviewer_cacheのフレーム9571のJPEGは名前と内容が両保存先で整合するものの、軌跡途中を選択しても起点の場面が写っていると報告した。実動画の参照先とOpenCVのシーク・実フレーム内容をキャッシュを介さず比較する必要がある。

プラグインとキャッシュを介さないOpenCV診断でも、9571として抽出された画像は起点の場面だった。実動画は`/home/y-matsui/work/nexco/hokuriku/04_VID_20160212_022025_20250711112746_8K.mp4`。0へのseek=True、before=0、after=0、time_ms=0、read=False。9571へのseek=True、before=-3071382977204209、after=-3071382977204208、time_ms=0、read=Trueだった。巨大な負の読み取り位置は異常で、読み取り成功フラグだけで正しい画像と扱えない。OpenCV 4.6.0 / FFmpegのシーク・タイムスタンプ処理と実動画をFFmpeg単体で比較する。特定の既知バグや原因はまだ確定していない。

APT版FFmpegを導入後、利用者は319.35秒付近のFFmpeg単体抽出画像が正しいと報告した。この環境と動画ではOpenCV経由のシークが有力な問題箇所。0.5.6候補は共通の`video_frames.py`でシーク前後の位置を検証し、異常位置・読み取り失敗時はFFmpeg CLIへフォールバックする。FFmpegへ渡す時刻はフレーム/FPS換算（固定FPSを前提とする従来のGPX同期と同じ前提）で、丸めによる次フレームへの飛び越しを避けるため対象時刻の直前へシークする。可変FPS動画の厳密なフレーム番号一致は保証しない。元動画は変更しない。

FFmpegは任意の外部実行ファイルで、正常なOpenCV読み取りには不要。フォールバックが必要なのに未導入ならエラーを表示し、不正画像は保存しない。QGIS側の旧imagesはEXIFの読み取り世代タグがない場合に再生成し、viewer_cacheは`seek-v2`を含む別名を使う。公開0.5.5のZIPは変更しない。候補の実機確認は未完了。

## 互換修正

`QgsField`への型指定を`QVariant`から`QMetaType`へ変更する。geometry enumは`Qgis.GeometryType`を優先し、旧APIへのフォールバックを残す。

初期調査で作成したWindows 0.5.1用の差分では、キーイベント、地図Identify、レーダ、プロセス状態、GeoPackage writerの旧enum参照も互換定数へ移した。この差分用ZIPはQGISの「ZIPからインストール」には使用しない。

正式な今回の対応版は`version=0.5.5`、`qgisMinimumVersion=3.40`、`qgisMaximumVersion=4.2.2`とする。配布ファイルは`Geo360View-0.5.5.zip`で、トップレベルの`Geo360View/`に`__init__.py`と`metadata.txt`を含む。QGISの「ZIPからインストール」で適用して再起動し、地図クリックを再確認する。公開リポジトリへのアップロードは別途行う。

参考: [公式移行案内](https://plugins.qgis.org/docs/migrate-qgis4)、[QgsField API](https://qgis.org/pyqgis/master/core/QgsField.html)。

## 停止箇所の記録

QGISのPythonコンソールで、診断スクリプトのWindowsから参照できるパスを指定する。

```python
import runpy
geo360_diag = runpy.run_path(r"C:\作業フォルダー\diagnose_qgis4.py")
geo360_diag["start_diagnostics"]()
```

停止する操作を再現し、15秒以上待つ。表示された一時ログには環境情報と全Pythonスレッドのスタックが記録される。復帰後は次を実行する。

```python
geo360_diag["stop_diagnostics"]()
```

応答しない状態でもログは外部から読み取れる。ログの個人パスや動画名は共有前に確認する。既存の`faulthandler.dump_traceback_later`を使う診断とは同時に実行しない。

## 切り分けと実機チェック

1. 空のジョブでGPX/動画/出力フォルダーの選択とキャンセルを試す。ファイル選択で停止する場合は、背面のダイアログ、Windows標準ダイアログ、保存済み開始フォルダーを調べる。パネルは常に最前面に設定されている。
2. ローカルの短いMP4で選択・フレーム表示を試す。動画サイズ取得とフレーム抽出はUIスレッド上でOpenCVを呼ぶため、デコードやI/O待ちのスタックを確認する。
3. Process、Open Viewer、New Jobを個別に試す。viewerのHTTP通信、プロセス起動待ち、worker終了待ちを確認する。
4. 正常PCと問題PCのPython/Qt/OpenCV/NumPy、環境変数、QGISプロファイルを比較する。新しいQGISプロファイルでも再現するか確認する。
5. GPX/MP4処理、地図クリック、レーダ、Marking、GPKG保存と再読込をQGIS 4.2.2で確認し、QGIS 3.40系でも回帰確認する。

停止ボタンとスタックの証拠に基づき、非同期化やダイアログ変更の対象を決める。
