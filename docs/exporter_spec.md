# フレーム画像 Exporter 仕様

更新日: 2026-06-04

この文書は、GPXVideoProcessorで同期済みのGeoPackage/動画から、証跡用静止画を一括抽出するExporterの仕様をまとめるものです。

## 目的

QGISプラグイン本体は、目視確認のために必要なフレームをオンザフライ抽出します。

一方、証跡用の大量画像出力は処理が重いため、別バッチのExporterとして扱います。

```text
同期済みGeoPackage
+ 元MP4
+ 抽出条件
+ 画質設定
= 証跡用JPEG群
```

## 実装ファイル

- `TenkakuNinja/exporter.py`
- `TenkakuNinja/main.py`
- `TenkakuNinja/requirements.txt`
- `TenkakuNinja/README.md`
- `exporter.py`: 後方互換用の薄いCLIラッパー

`main.py` 側では、`tmp.gpkg` へ保存される `Video GPX Points` レイヤに、Exporterで条件指定しやすいKP関連列を追加します。

追加列:

```text
aligned_latitude
aligned_longitude
kp
kp_distance_m
kp_latitude
kp_longitude
kp_match
```

## 基本方針

TenkakuNinjaCoreの既存ルールを継承します。

- Exporter本体はTenkakuNinja由来であることを明確にするため、`TenkakuNinja/` 配下に置く。
- `TenkakuNinja/` フォルダは、単体で別環境へコピー移植して動作できる構成にする。
- ExporterはQGISプラグイン本体から独立した単体Pythonプログラムとして扱う。
- QGISプラグインの依存関係へ、Exporter用ライブラリを混ぜない。
- QGIS UIから起動する場合も、将来的にはQProcessで外部プロセスとして起動する。
- 抽出方式はOpenCVを正とする。
- 1000フレームごとにサブフォルダを分ける。
- ファイル名はDB上のフレーム番号と一致させる。
- QGISプラグイン側のオンザフライ抽出画像も同じ相対パス規則に揃える。
- ナビゲーション用CSV/JSONには、Exporter出力を参照できる `image_path` を記録する。
- 既存ファイルは既定でスキップする。
- 再生成したい場合だけ `--overwrite` を使う。

出力パス:

```text
images/
  0000/
    frame_0000000.jpg
    frame_0000001.jpg
  0001/
    frame_0001000.jpg
```

サブフォルダ番号:

```text
folder = frame // 1000
```

ファイル名:

```text
frame_{frame:07d}.jpg
```

CSV/JSON内の画像参照:

```text
image_path = images/{folder}/frame_{frame:07d}.jpg
```

`image_path` はCSV/JSONファイルから見た相対パスです。通常の `360view_output` 配下では `images/0000/frame_0000000.jpg` になります。動画フォルダ側へ複製する `*_matched_frames.csv` では、そのCSV位置から見た相対パスになります。

全フレームCSVでは、`image_path` は実体ファイルの存在保証ではなく、QGISオンザフライ抽出またはExporterが生成する予定位置を示します。

`viewer_cache/` はWEBビューアがオンザフライ表示のために生成する軽量JPEGキャッシュであり、この証跡用パス規則とは分離します。

## 実行環境

ExporterはQGIS同梱Pythonではなく、通常のPython環境で実行する前提です。

依存関係:

```bash
cd TenkakuNinja
pip install -r requirements.txt
```

現時点の外部依存:

```text
opencv-python
```

YAML設定ファイル対応は未実装です。PyYAMLのような標準外依存を増やす前に、まずはCLI引数とJSON/CSV出力だけで運用します。

8K 360動画を長時間書き出す場合、処理時間は数時間規模になる可能性があります。QGISプロセスを占有しないためにも、Exporterはプラグイン本体から分離して実行します。

ffmpegはOpenCVより高速な場合がありますが、過去比較でYOLO検出結果に1割以上の差が出たため、標準抽出方式にはしません。色空間、color range、color matrix、chroma補間、リサイズ補間、シーク位置などの差がYOLO結果へ影響する可能性があります。

このため、証跡画像・学習画像・推論画像はOpenCV抽出で統一することを原則とします。

## 入力

### GeoPackage

既定値:

```text
tmp.gpkg
```

任意のGeoPackageも指定できます。

```bash
python TenkakuNinja/main.py --database path/to/tmp.gpkg --video path/to/movie.mp4
```

対象レイヤを省略した場合は、GeoPackage内の最初のfeature layerを使います。

明示する場合:

```bash
--layer video_gpx_points
```

### フレーム列

既定では以下を自動判定します。

```text
frame
frame_number
frame_index
```

明示する場合:

```bash
--frame-column frame
```

## 抽出条件

### フレーム範囲

両端を含む範囲指定です。

```bash
--start 1000 --end 2000
```

互換オプションとして `--frame-start` / `--frame-end` も利用できます。

### フレーム番号リスト

明示フレームだけを抽出できます。

```bash
--frames 100,200,300
```

### KPマッチ済みのみ

`kp_match` 列がある場合は `kp_match=1` を使います。

```bash
--matched-only
```

`kp_match` がなく `kp` 列がある場合は、`kp` が空でない行をマッチ済みとして扱います。

### 汎用列条件

単純な列条件を繰り返し指定できます。

```bash
--condition kp_match=1
--condition kp_distance_m<=5
```

対応演算子:

```text
=
!=
>
>=
<
<=
```

より複雑な条件は `--where` でSQLiteのWHERE断片として指定できます。

```bash
--where "kp_match = 1 AND frame % 30 = 0"
```

## 出力プロファイル

Exporterは用途ごとに `--scale` と `--jpeg-quality` を切り替えて使います。

### 参照・納品確認用

顧客確認、顧客の顧客への参照提出、WEBビューアでの軽量閲覧を想定します。

```bash
--scale 0.5 --jpeg-quality 70 --progressive-jpeg
```

実測例:

```text
8K 360動画
scale=0.5
jpeg-quality=70
1000 frames / 50.30 sec = 約19.9 FPS
```

軽量参照用は、表示速度、転送量、保管容量を優先します。YOLO推論や最終検証の正規入力にはしません。

### YOLO・CubeMap変換用

YOLO推論、CubeMap変換、証跡検証の基準データを想定します。

```bash
--scale 1.0 --jpeg-quality 95
```

または、JPEG品質を最大に寄せる場合:

```bash
--scale 1.0 --jpeg-quality 100
```

現行Exporterの出力形式はJPEGです。JPEGは品質100でも厳密には非圧縮・ロスレスではありません。完全ロスレスが必要になった場合は、PNG/TIFFなどの出力形式対応を別途追加します。

### 用途ごとの整理

```text
参照用:
  小さく、軽く、速く表示できることを優先
  例: scale=0.5, jpeg-quality=70

YOLO/CubeMap用:
  元動画に近い画素情報を維持することを優先
  例: scale=1.0, jpeg-quality=95..100

WEBビューアcache:
  削除可能な一時派生物
  images/成果品とは分ける
```

## 画質設定

### scale

元動画サイズに対する倍率です。

```bash
--scale 0.5
```

例:

```text
7680 x 3840, scale=0.5 -> 3840 x 1920
```

### JPEG品質

```bash
--jpeg-quality 75
```

範囲:

```text
1..100
```

### Progressive JPEG

OpenCVが対応している場合、Progressive JPEGを指定できます。

```bash
--progressive-jpeg
```

## EXIF

既定では最小EXIFを付与します。

入る情報:

- ImageDescription
- Software
- DateTime
- GPS

GPSは以下の順に探します。

```text
aligned_latitude / aligned_longitude
kp_latitude / kp_longitude
latitude / longitude
lat / lon
```

EXIFを入れない場合:

```bash
--no-exif
```

## 出力補助ファイル

画像出力ディレクトリに以下を生成します。

```text
export_manifest.csv
export_summary.json
```

`export_manifest.csv`:

```text
frame,status,path,message
```

`status`:

```text
exported
skipped
error
```

`export_summary.json` には、入力DB、対象レイヤ、動画、scale、JPEG品質、出力件数などを記録します。

## 出力検証

### ファイル欠損確認

範囲指定のみで抽出する場合、期待件数は両端を含みます。

```text
expected = end - start + 1
```

例:

```bash
--start 0 --end 999
```

期待件数:

```text
1000 files
```

実行ログの `Selected frames` と完了時の `Counts` を確認します。

```text
Selected frames: 1000
Done in 50.30s. Counts: {'exported': 1000}
```

`export_manifest.csv` では、全対象フレームが `exported` または既存再利用の `skipped` になっていることを確認します。`error` がある場合は欠損または抽出失敗として扱います。

### フレーム同期精度確認

後ろのフレームへ進むほど位置がずれていないかを確認します。特に29.97fps系動画では、フレーム番号生成時の丸めやドロップフレーム相当の扱いで、長時間動画ほど同期ずれが累積する可能性があります。

確認手順:

1. QGISプラグインで `tmp.gpkg` とフレームCSVを作成する。
2. ExporterでEXIF付き画像を書き出す。
3. EXIFをインポートできるGISプラグインで画像位置を読み込む。
4. 動画前半、中盤、後半の撮影点を地図上で比較する。
5. 地図背景、道路中心、交差点、KP位置と360画像内の地物位置を目視確認する。

この検証により、フレームシフト設定、GPX補間、FPS処理、EXIF書き込み位置の妥当性を確認します。

## 実行例

### tmp.gpkgから全件抽出

```bash
python TenkakuNinja/main.py ^
  --database W:/workshop/nexco/360view_output/tmp.gpkg ^
  --video W:/workshop/nexco/VID_20250324_135428_00_033_rot170.mp4
```

### KPマッチ済みだけ抽出

```bash
python TenkakuNinja/main.py ^
  --database W:/workshop/nexco/360view_output/tmp.gpkg ^
  --video W:/workshop/nexco/VID_20250324_135428_00_033_rot170.mp4 ^
  --matched-only
```

### 範囲と画質を指定

```bash
python TenkakuNinja/main.py ^
  --database W:/workshop/nexco/360view_output/tmp.gpkg ^
  --video W:/workshop/nexco/VID_20250324_135428_00_033_rot170.mp4 ^
  --start 10000 ^
  --end 12000 ^
  --scale 0.5 ^
  --jpeg-quality 75 ^
  --progressive-jpeg ^
  --overwrite
```

## 現在の制約

- 最初の実装ではOpenCVで抽出します。
- ffmpegによる高速連続抽出や欠損補完は未実装です。OpenCV出力との一致検証が済むまで標準にはしません。
- GeoPackageのgeometryは読まず、属性列からフレーム番号とGPSを取得します。
- `--where` は高度な利用者向けで、SQL断片をそのまま渡します。
- QGIS UIからの起動ボタンは未実装です。
- YAML設定ファイルは未実装です。

## 今後の候補

- QGISプラグインメニューまたはパネルからExporterを起動する。
- QProcessで外部バッチとして実行し、進捗ログをQGISへ表示する。
- ffmpeg rawvideoによる連続抽出モードを追加する。
- 出力プロファイルを保存する。
- 依存関係を増やす場合は、プラグイン本体ではなくExporter単体環境のrequirementsへ閉じ込める。
- YAML設定は、運用が固まってからPyYAMLをExporter専用依存として追加するか検討する。
- JPEG以外の形式や、証跡用フル解像度/閲覧用縮小版の同時出力に対応する。
