# TenkakuNinja Standalone Exporter

GPXVideoProcessorが生成したGeoPackageと元MP4から、条件に合うフレーム画像を証跡用JPEGとして一括抽出する単体Exporterです。

このフォルダは、QGISプラグイン外へコピーして単体利用できます。

## Install

```bash
pip install -r requirements.txt
```

## CLI

このフォルダ内で実行する場合:

```bash
python main.py --database path/to/tmp.gpkg --video path/to/movie.mp4
```

プラグインルートから実行する場合:

```bash
python TenkakuNinja/main.py --database path/to/tmp.gpkg --video path/to/movie.mp4
```

## Examples

KPマッチ済みフレームだけ抽出:

```bash
python main.py \
  --database path/to/tmp.gpkg \
  --video path/to/movie.mp4 \
  --matched-only
```

範囲、縮尺、JPEG品質を指定:

```bash
python main.py \
  --database path/to/tmp.gpkg \
  --video path/to/movie.mp4 \
  --start 10000 \
  --end 12000 \
  --scale 0.5 \
  --jpeg-quality 75 \
  --progressive-jpeg
```

軽量参照用:

```bash
python main.py \
  --database path/to/tmp.gpkg \
  --video path/to/movie.mp4 \
  --scale 0.5 \
  --jpeg-quality 70 \
  --progressive-jpeg
```

YOLO/CubeMap用の原寸高品質:

```bash
python main.py \
  --database path/to/tmp.gpkg \
  --video path/to/movie.mp4 \
  --scale 1.0 \
  --jpeg-quality 95
```

## Output Rule

TenkakuNinjaCore由来の保存規則を維持します。

```text
images/
  0000/
    frame_0000000.jpg
  0001/
    frame_0001000.jpg
```

```text
subfolder = frame // 1000
filename = frame_{frame:07d}.jpg
```

## Notes

- OpenCV出力を正とします。
- 現行出力はJPEGです。JPEG品質100でも厳密な非圧縮・ロスレスではありません。
- ffmpegは高速ですが、YOLO結果差分が出る場合があるため標準抽出方式にはしません。
- QGISプラグイン本体の依存関係とは分離します。
