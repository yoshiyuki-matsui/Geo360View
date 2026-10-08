# QGIS 4.2.2対応と応答停止の調査

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
