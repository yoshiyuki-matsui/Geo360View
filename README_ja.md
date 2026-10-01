# Geo360 View

[English README](README.md)

Geo360 Viewは、GPXと同期した360度動画および通常画角動画を、QGISの地図上から確認し、360空間上の気になる位置をMarkingとして残せるQGISプラグインです。

## 動作報告を募集しています

Geo360 Viewは現在、試験公開版です。

お手元の360動画＋GPXで試していただけた場合は、「カメラ機種」「GPXの出どころ」「動いた／動かなかった」を教えていただけると助かります。

- 動作報告: [GitHub Issues - 動作報告](https://github.com/yoshiyuki-matsui/Geo360View/issues/new?template=operation-report.yml)
- 不具合報告: [GitHub Issues - 不具合報告](https://github.com/yoshiyuki-matsui/Geo360View/issues/new?template=bug-report.yml)
- 質問・使い方の相談・活用アイデア: [GitHub Discussions](https://github.com/yoshiyuki-matsui/Geo360View/discussions)

サポートは原則として日本語で行います。英語での報告も歓迎しますが、回答は日本語、または機械翻訳を併記した形になる場合があります。

MP4動画とGPX軌跡を同期し、フレームごとの撮影点を生成します。地図上の撮影点を選ぶと、対応するフレームをブラウザビューアで確認できます。ビューア上で気になる対象をダブルクリックすると、そのフレーム、視線方向、画角をMarkingとして保存できます。任意の参照点CSVを指定すると、KP、電柱、橋梁、施設、点検対象点などのマスタ情報を撮影点に最近接マッチングし、実写と属性を重ねて確認できます。

Geo360 Viewは単なる再生ビューアではありません。撮影点GeoPackage、Markingレイヤ、フレームCSV、参照点マッチCSV、閲覧用キャッシュ画像、GPS EXIF付きスナップショットなど、GISで再利用できる中間成果物を生成します。

![Geo360 View Geo360View](docs/images/Geo360Viewe.png)
### 概要
![Geo360 View 概要](docs/images/overview.gif)
### 操作パネル
![Geo360 View 操作パネル](docs/images/panel_0.png)
### 撮影点
![Geo360 View 撮影点](docs/images/point.png)
### ビューア表示
![Geo360 View ビューア表示](docs/images/viewer.png)
### スナップショット保存
![Geo360 View スナップショット保存](docs/images/capture.png)
### EXIFタグ
![Geo360 View EXIF GPS](docs/images/exif.png)


## できること

- GPX軌跡を読み込み、MP4のフレーム番号へ撮影位置を補間します。
- フレームシフトを指定して、映像フレームとGNSS位置のずれを調整できます。
- QGIS上に`Video GPX Points`レイヤを生成します。
- KP、電柱、橋梁、施設マスタなどの参照点CSVと最近接マッチングできます。
- QGISからローカルブラウザビューアを開けます。
- 360度/equirectangular画像と通常画角画像を表示できます。
- 動画全体を静止画化せず、必要なフレームだけをオンザフライで表示します。
- フレーム移動時にyaw、pitch、zoomを保持できます。
- 360空間上にMarkingを置き、あとから同じフレーム・視点・画角を再現できます。
- Markingは`geo360_markings`レイヤとしてGeoPackageへ保存され、`frame`でスナップショットや撮影点と対応付けできます。
- 地図側とビューア側にHUD、同心円、視点ロック補助を表示できます。
- マッチした参照点の日本語属性をビューア上にオーバーレイ表示できます。
- HUDや参照点情報を重ねたGPS EXIF付きスナップショットを保存できます。
- 作業中のGeoPackageを保存・復元できます。

## ビューア

Geo360 Viewは2つのビューア経路を持っています。

- `psv`: Photo Sphere Viewer + MarkersPlugin。公開版の主経路です。
- `krpano`: 既存互換確認用のローカル経路です。

Photo Sphere Viewer経路は、既存のローカルHTTP API、画像キャッシュ、`viewer_session.json`を再利用します。QGIS側の処理はビューア実装から疎結合になっています。

## Marking

Markingは、360空間上の「しおり」です。ビューア上で気になる対象をダブルクリックすると、現在の動画名、`frame`、クリックした視線方向、クリック時のビューア中心視点、`zoom`を保存します。

保存したMarkingは、Navの`Marking`モードで辿ることができます。対象フレームへ戻るだけでなく、保存時の視点と画角も復元されるため、あとから同じ対象を確認し直せます。スナップショットにもMarkingマーカーが写るため、GPKG内のMarkingレコードと証跡画像を`frame`で対応付けできます。

Markingは位置確認や申し送りのためのブックマークであり、成果品POIや測量成果ではありません。新規Markingは視点復元用の非geometryレコードとして保存され、対象物の正式位置を主張するものではありません。分類、属性管理、品質管理、正式なPOI化などの業務処理は本リポジトリの範囲外です。

## 公開版の範囲

この公開版は、動画とGPXの同期、撮影点レイヤ生成、参照点CSVとのマッチング、ブラウザビューアでの目視確認に範囲を絞っています。

以下は本リポジトリの対象外です。

- 自動物体検出
- YOLO/RF-DETRなどのモデル実行
- POI候補生成、集約、管理、正式なPOI化
- semantic classに基づく候補レイヤ表示
- モデル比較、検出結果レビュー
- 帳票生成などの業務ワークフロー

これらの高度な業務処理は、GPXVideoProcessorおよび関連商用サービス側の領域です。

## セキュリティとプライバシー

Geo360 Viewは、ユーザのPC上でローカルに動作するQGISプラグインです。MP4、GPX、CSV、Marking、スナップショットを外部サーバへ送信することは意図していません。

ただし、360度動画、GPX、参照点CSV、GeoPackage、GPS EXIF付きスナップショットには、人物、車両、住所、施設、移動経路などの機微情報が含まれる可能性があります。公開、共有、Issue添付、サンプル化を行う前に、必ず内容を確認してください。

ローカルビューアは通常 `localhost` で利用する前提です。ローカルHTTPビューアのポートを、信頼できないネットワークへ公開しないでください。

配布ZIPはGitHub Releasesから取得してください。出所不明のZIPをQGISへインストールしないでください。

脆弱性やプライバシー上の懸念を報告する場合は、公開Issueに詳細な個人情報や位置情報を貼らず、[SECURITY.md](SECURITY.md) の案内に従ってください。

## 必要環境

- QGIS 3.40以降
- QGISが使用するPython環境でOpenCV、つまり`cv2`が利用できること
- ローカルビューアを開けるブラウザ。EdgeまたはChromeを推奨します

## インストール

通常は、GitHub Releasesで配布しているZIPを使ってインストールしてください。

1. [GitHub Releases](https://github.com/yoshiyuki-matsui/Geo360View/releases) から `Geo360View-0.5.0.zip` などの配布ZIPをダウンロードします。
2. QGISを起動します。
3. `プラグイン` → `プラグインの管理とインストール` を開きます。
4. `ZIPからインストール` を選び、ダウンロードしたZIPを指定します。
5. インストール後、QGISを再起動します。

GitHubの `Code > Download ZIP` で取得したソースZIPは、フォルダ名や階層がQGISプラグイン配布ZIPと異なる場合があります。通常利用ではReleasesの配布ZIPを使ってください。

開発版を手動配置する場合は、プラグインディレクトリをQGISのPythonプラグインフォルダへ配置し、QGISを再起動してください。

Windowsの標準的な配置先は以下です。

```text
C:\Users\<user>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\Geo360View
```

### OpenCV / cv2 のセットアップ

QGISで`cv2`が見つからない場合は、通常のWindows PythonやCondaではなく、QGISが使っているPython環境にOpenCVを入れてください。

WindowsのOSGeo4W/QGIS環境では、スタートメニューから **OSGeo4W Shell** を起動して、次の順に実行します。

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install --upgrade --only-binary=:all: "opencv-python>=4.8"
python -m pip check
python -c "import cv2; print(cv2.__version__)"
```

`cv2`のバージョンが表示されれば、OSGeo4W Shell側のPythonではOpenCVを読み込めています。

その後、**QGISを完全に終了してから再起動**してください。QGIS起動中にOSGeo4W ShellでPythonライブラリを追加した場合、起動中のQGISプロセスには反映されません。プラグイン画面だけを閉じても反映されない場合があります。

トラブル確認用:

```bash
python -c "import sys; print(sys.executable)"
python -c "import numpy; print('numpy', numpy.__version__)"
python -c "import cv2; print('opencv', cv2.__version__)"
```

注意:

- `pip install --upgrade numpy` は最終手段にしてください。QGIS/GDAL/OSGeo4WのPython環境では、`numpy`を不用意に上げると他のライブラリと不整合になることがあります。
- まずは `opencv-python` を入れ、`python -m pip check` で不整合が残っていないか確認してください。
- インストール前の状態を残したい場合は、次のコマンドでパッケージ一覧を保存できます。

```bash
python -m pip freeze > qgis_python_packages_before.txt
```

## 入力データ

- 同一路線・同一走行で撮影したMP4動画
- 同じ走行時に取得したGPX軌跡
- 任意の参照点CSV

サンプルMP4/GPXは同梱していません。360度動画は容量が大きく、人物・車両・周辺環境などのプライバシー情報を含む可能性があるためです。まずは、お手元のInsta360、RICOH THETA、GoPro MAXなどで撮影したMP4と、同じ移動時に取得したGPXでお試しください。

実用上は、MP4動画をローカルSSDなどのローカルディスクへコピーしてから処理することを推奨します。NAS、SMB/NFS共有、クラウド同期フォルダ、VPN越しのストレージ上にある大容量MP4を直接読むと、フレーム抽出やビューア上のフレーム移動が非常に遅くなる場合があります。

参照点CSVはUTF-8で保存してください。Excelで編集する場合は「CSV UTF-8（コンマ区切り）（*.csv）」を選択してください。日本語が文字化けする場合は、Sakura EditorやVS Codeなどで開き、UTF-8で保存し直してください。

最小構成の参照点CSV例:

```csv
id,name,latitude,longitude
1991,北陸道上り KP:1991,35.97173562,136.2038756
2034,北陸道上り KP:2034,35.97156058,136.2037934
```

`name`列がある場合、ビューア上の表示ラベルとして使われます。マッチング結果には`reference_id`、`reference_name`、`reference_label`も出力されます。

## 出力されるもの

Geo360 Viewは元動画を正として保持し、作業結果として以下の中間成果物を出力します。

- `Video GPX Points` QGISレイヤ
- フレーム位置CSV
- 参照点マッチCSV
- ローカルビューア用のナビゲーションJSON
- `geo360_markings` Markingレイヤ
- オンザフライ表示用のキャッシュ画像
- HUDや参照点情報を含むGPS EXIF付きスナップショット

360度動画の場合、キャッシュ画像はequirectangular形式の中間画像です。スナップショットは、現在の視点方向から生成される、人が見て分かる通常の静止画です。

## 既知の制限

- 360度動画は大容量で、プライバシー情報を含む可能性があるため、現時点ではサンプル動画を同梱していません。
- ネットワークストレージやVPN越しのMP4アクセスは、ローカルディスクより大幅に遅くなる場合があります。動画ファイルはローカルへ置いて実行することを推奨します。
- QGIS 4/Qt 6対応は実験的です。
- 表示画質やスナップショット画質は、元動画、キャッシュ画像解像度、ビューア描画、JPEG圧縮の影響を受けます。
- krpano経路はローカル互換確認用です。公開配布の主経路はPhoto Sphere Viewerです。


## ライセンス

Geo360 Viewは、QGISプラグイン配布要件に合わせてGPL-2.0-or-laterで提供します。

同梱するブラウザ側OSSコンポーネントは、それぞれのライセンスに従います。

- Photo Sphere Viewer core: MIT
- Photo Sphere Viewer MarkersPlugin: MIT
- three.js: MIT

krpanoは同梱しません。ローカルで旧krpano経路を使う場合は、krpanoのライセンスに従って利用者自身のランタイムを配置してください。

## ドキュメント

- [DESIGN.ja.md](DESIGN.ja.md): 日本語設計メモ
- [DESIGN.md](DESIGN.md): 英語設計メモ
- [CHANGELOG.md](CHANGELOG.md): 変更履歴
- [samples/README.md](samples/README.md): サンプルデータ方針と入力データメモ


## 問い合わせ

動作報告・不具合報告はGitHub Issuesへお願いします:
https://github.com/yoshiyuki-matsui/Geo360View/issues

質問、使い方の相談、活用アイデアはGitHub Discussionsへお願いします:
https://github.com/yoshiyuki-matsui/Geo360View/discussions

業務フローへの組み込み、自動POI生成、物体・損傷検出モデル、検出結果レイヤ出力、レイヤスタイル適用、報告書生成などのご依頼は下記までご連絡ください:
rdcenter.nakashacreative@gmail.com
