# TenkakuNinja Exporter 運用ノウハウ

更新日: 2026-06-04

この文書は、GPXVideoProcessorの `TenkakuNinja/` Exporterに反映している大量JPEG処理の運用ノウハウ、ベンチ結果、禁止事項をまとめるものです。

`TenkakuNinja/` にExporterを置く理由は、TenkakuNinjaCore由来の大量フレーム抽出・大量JPEG運用の経験則を、QGISプラグイン本体から分離して再利用するためです。

## 基本方針

```text
GPKG + MP4 = 同期済みフレーム画像を書き出せる最小入力
```

QGISプラグインは、即時確認と地物入力支援を担当します。

Exporterは、時間のかかる大量静止画生成をQGIS外で実行します。

```text
QGISプラグイン:
  同期確認
  フレームシフト調整
  KPマッチ
  地物入力支援
  必要フレームだけオンザフライ抽出

TenkakuNinja Exporter:
  tmp.gpkg / 任意GPKG
  元MP4
  条件指定
  EXIF付きJPEG大量出力
  manifest / summary 作成

NAS Docker / tenkaku_ninja_core:
  管理フォルダWatch
  YAML/JSONジョブ設定読込
  入力ファイル存在確認
  自動バッチ実行
  状態管理
```

QGISからHTTPストリームで大容量コンテンツを渡すのではなく、QGISは同期済みデータを作り、WEBビューアやExporterはジョブ成果品を読む構成にします。

## フレーム番号の不変条件

`frame` は最重要の不変キーです。

```text
frame = 元MP4の0始まりフレーム番号
```

この値は、どの処理系でも変更してはいけません。

```text
GPKG
CSV
JSON
JPEGファイル名
EXIF
WEBビューア
YOLO結果
CubeMap結果
```

すべて `frame` を共通キーとして扱います。

同期に関係する値は以下のように分けます。

```text
frame:
  元MP4から実際に抽出する0-based frame number
  ファイル名にも使う不変キー

source_frame:
  GPX補間上の参照フレーム番号
  frame_shift適用前の同期元

frame_shift:
  frame = source_frame + frame_shift
```

禁止事項:

```text
source_frameを画像ファイル名に使う
シフト後/シフト前の意味を入れ替える
1始まりへ変換する
欠番補完時に別番号を振る
ffmpegとOpenCVでフレーム番号基準を変える
```

ここが崩れると、位置、EXIF、YOLO検出結果、地物登録位置がすべてずれるため重大事故になります。

## 出力フォルダ規則

大量JPEGは1000ファイル単位でサブフォルダへ分けます。

```text
images/
  0000/
    frame_0000000.jpg
    frame_0000001.jpg
  0001/
    frame_0001000.jpg
```

```text
folder = frame // 1000
filename = frame_{frame:07d}.jpg
```

この規則は速度、欠損確認、人間の確認、NAS運用のバランスを取るためのものです。

1フォルダに数万から数十万JPEGを平置きする構成は採用しません。

理由:

```text
ディレクトリ一覧が遅くなる
Explorerやファイルブラウザが固まる
NAS/SMB/NFSのメタデータアクセスが重くなる
欠損確認が難しい
部分再実行や部分削除が扱いにくい
```

## manifestを正とする

大量ファイル環境では、実ファイルを毎回スキャンしません。

遅い方法:

```text
images/** をglobする
全ファイルへstatする
Explorerで全体確認する
NAS越しにディレクトリを総なめする
```

速く安定する方法:

```text
export_manifest.csv を読む
export_summary.json を読む
DB/CSVのframe列とmanifestを突合する
```

ファイル実体は成果物、一覧と状態確認はmanifestを正とします。

## OpenCV運用

OpenCVによる動画抽出は逐次処理を原則とします。

採用する方針:

```text
1プロセス
1 VideoCapture
1スレッド
直列読み
1フレーム読んで1フレーム書く
大きなフレームをキューに溜めない
atomic write
manifestへ結果記録
```

採用しない方針:

```text
複数スレッドで同じ動画を読む
大量フレームをキューへ先読みする
複数VideoCaptureで同一動画へ同時アクセスする
QGISプロセス内で大量OpenCVバッチを実行する
```

過去にマルチスレッド抽出を試した際、逐次書き込みより遅くなり、スレッドキュー詰まり、欠損、OpenCVハングが発生しました。

OpenCVの動画デコードはネイティブ側で落ちることがあり、Python例外として安全に捕捉できない場合があります。QGISプロセス内で大量処理を実行すると、QGIS本体、未保存編集、レイヤ状態を巻き込むため避けます。

## ffmpegを標準にしない理由

ffmpegはOpenCVより高速な場合があります。

ただし過去比較で、OpenCV抽出画像とffmpeg抽出画像をYOLOへ入力した際、検出結果に1割以上の差が出ました。

想定される差分要因:

```text
色空間
color range
color matrix
chroma補間
リサイズ補間
シーク位置
フレーム番号基準
```

このため、YOLO、CubeMap、証跡画像の標準抽出方式はOpenCVとします。ffmpegはOpenCV出力との一致検証が済むまで標準化しません。

## ベンチマーク結果

検証環境:

```text
8K 360 MP4
NFSマウントNAS出力
Core Ultra 7環境
OpenCV逐次処理
EXIF付きJPEG
```

確認された傾向:

```text
1000ファイルより10000ファイルバッチの方が約2割効率が良い
JPEG品質70は高品質設定より約2割速い
4K相当(scale=0.5)は8K原寸(scale=1.0)より大きく速い
```

代表値:

```text
4K Q70:
  約24 FPS
  参照用・WEB閲覧用として最速

4K Q100:
  約19.6 FPS
  8K Q70より速い

8K Q70:
  約13 FPS

4K Q70 実測:
  1000 frames / 50.30 sec = 約19.9 FPS
```

ファイルサイズ例:

```text
8K Q70:
  約2.4 MB/file

4K Q100:
  約1.6 MB/file
```

この結果から、CPU処理よりも出力ファイルサイズとI/Oが支配的である可能性が高いと判断しています。

4K Q70が最速だったため、軽量参照用・WEBビューア用プロファイルとして有力です。

## 出力プロファイル

### 軽量参照用

顧客確認、顧客の顧客への参照提出、WEBビューアでの軽量閲覧を想定します。

```bash
--scale 0.5 --jpeg-quality 70 --progressive-jpeg
```

特徴:

```text
軽い
速い
保管容量が小さい
ブラウザ表示に向く
YOLOの正規入力にはしない
```

### YOLO / CubeMap / 検証用

解析、CubeMap変換、YOLO推論、証跡検証を想定します。

```bash
--scale 1.0 --jpeg-quality 95
```

または:

```bash
--scale 1.0 --jpeg-quality 100
```

現行ExporterはJPEG出力です。JPEG品質100でも厳密な非圧縮・ロスレスではありません。完全ロスレスが必要になった場合はPNG/TIFF対応を別途検討します。

## NAS / WSL / Docker運用

大量JPEG処理では、処理そのものよりファイルI/O経路が支配的になることがあります。

過去実績:

```text
Windows + SMB -> NAS:
  約11時間

WSL + NFS -> NAS:
  約3時間

NAS上Docker:
  さらに高速
```

推奨順:

```text
大量・長時間・数十万JPEG:
  NAS上Docker / tenkaku_ninja_core

通常規模:
  WSL + NFS

避けたい構成:
  Windows + SMBで大量小ファイルを直接処理
```

基本原則:

```text
データがある場所の近くで処理する
ネットワーク越し小ファイルI/Oを減らす
Windows GUI作業端末を長時間バッチで占有しない
```

## QGISとバッチの分離

10から20 FPS程度で8K 360動画を書き出す場合、30fps動画に対して処理時間は概ね動画実時間の1.5倍から3倍になります。

このため、即時性が必要なQGIS作業と、時間のかかる静止画書き出しは分けます。

```text
QGIS:
  GPKG + MP4で即時確認
  必要フレームだけオンザフライ抽出
  目視同期
  地物入力

NAS Docker / Exporter:
  GPKG + MP4から大量JPEG生成
  夜間または別端末で実行
  manifest / summaryで検証
```

大量処理で行き詰まった場合は、Dockerを稼働できるNAS上で `gpkg + mp4` から静止画を書き出す運用を推奨します。

## tenkaku_ninja_coreとの関係

`tenkaku_ninja_core on Docker` は管理フォルダをWatchし、YAML/JSON設定を読み、必要ファイルの存在を確認して自動実行する「自動工場」として設計されています。

今回のExporterは、その1工程として組み込めるようにCLI中心で実装しています。

分担:

```text
tenkaku_ninja_core:
  Watch
  ジョブ検出
  YAML/JSON設定読込
  入力ファイル存在確認
  実行順序制御
  状態管理
  ログ/通知
  再実行制御

TenkakuNinja Exporter:
  GeoPackageから対象frameを抽出
  MP4からフレームJPEGを書き出す
  EXIFを付与
  manifest / summaryを出す
```

Exporter本体へYAML/JSON設定読込を急いで入れず、CLI APIを安定させておく方が、QGIS単体利用とDocker自動工場の両方へ流用しやすいです。

## EXIF方針

全体共通情報は `export_summary.json` を正とします。

EXIFには、画像単体になったときにフレームを識別・検証できる情報だけを入れます。

候補:

```text
frame
source_frame
frame_shift
timestamp
GPSLatitude / GPSLongitude
gps_source
kp
kp_distance_m
```

詳細な属性一覧はDB/CSV/manifestを正とします。EXIFへ過剰に詰め込みません。

GPSは以下の優先順位で決めます。

```text
aligned_latitude / aligned_longitude
kp_latitude / kp_longitude
latitude / longitude
lat / lon
```

KP CSVを与えていない場合、`aligned_latitude/aligned_longitude` は元の `latitude/longitude` と同じ値になるため、EXIF GPSも元GPX由来の座標になります。

KP寄せした座標をEXIFへ入れる場合は、KPマッチ済みGPKGを使います。

## 検証観点

### 欠損確認

`--start 0 --end 999` のように範囲指定した場合、期待件数は両端を含みます。

```text
expected = end - start + 1
```

確認対象:

```text
Selected frames
Counts
export_manifest.csv
export_summary.json
```

`export_manifest.csv` に `error` がある場合は、欠損または抽出失敗として扱います。

### 同期精度確認

DBを使って元MP4からEXIF付きフレームを書き出せるようになったため、EXIFをGISへインポートして同期精度を検証できます。

確認すること:

```text
動画前半・中盤・後半で位置ずれが増えていないか
固定ずれか累積ずれか
交差点や道路形状と360画像内の見え方が合うか
ドロップフレーム相当のズレが出ていないか
```

代表フレーム:

```text
0%
25%
50%
75%
100%近傍
```

固定ずれであれば `frame_shift` の調整対象です。

後半ほどずれる場合は、FPS解釈、GPX補間、動画実時間、総フレーム数、OpenCVが返すFPSを再確認します。

## 禁止事項まとめ

```text
frame番号の意味を変えない
source_frameで画像を書き出さない
1フォルダへ数万JPEGを平置きしない
OpenCV大量抽出をQGISプロセス内で実行しない
OpenCV抽出を安易にマルチスレッド化しない
8Kフレームをキューへ大量に溜めない
manifestを使わずに毎回glob/statで全体確認しない
ffmpegをOpenCVの代替として無検証で標準化しない
Windows + SMB経由の大量小ファイル処理を標準運用にしない
```

この文書の失敗例・禁止事項は、今後の最適化で同じ罠を踏まないための設計制約として扱います。
