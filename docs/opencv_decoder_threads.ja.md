# OpenCVデコードスレッド数の設定と検証

## 推奨環境と適用範囲

OpenCV 4.8以上でFFmpegバックエンドが利用できる環境を推奨します。
開発版では、動画を開く時点で`CAP_PROP_N_THREADS=8`を指定します。
対象はパネルのプレビュー、動画フレーム数・寸法・FPS取得、Webビューアの画像抽出です。
公開済み0.5.5にはこの変更は含まれません。

実際のデコーダが使うスレッド数はコーデックによって8未満になることもあります。
開いた後の報告値が1〜8の範囲にあることを確認し、開けない場合や制限を確認できない場合はエラーにします。
スレッド指定を外した再試行や、FFmpeg CLIへの自動切り替えは行いません。

OpenCV 4.6ではこのAPIが使えないため、警告を出して従来の読み出しを続けます。
異常なシーク位置の検出は継続しますが、8スレッドへの制限は保証できません。
`cv2.setNumThreads(8)`は動画デコーダのスレッド数を設定する代替手段ではありません。

## 使用環境の確認

QGISのPythonコンソールで確認します。

```python
import cv2
print(cv2.__version__, cv2.__file__)
print("Thread API:", hasattr(cv2, "CAP_PROP_N_THREADS"))
```

Windowsの導入手順は[README](../README_ja.md)を参照してください。
Ubuntuのディストリビューション版OpenCVが4.6の場合、推奨条件を満たすには別の対応ビルドが必要です。
通常のPythonや仮想環境だけを更新しても、QGISが読み込む`cv2`やビューア起動用Pythonが切り替わるとは限りません。
環境更新の際はQGIS/GDALが利用するNumPyとの整合も確認し、更新後に実際の`cv2.__file__`を再確認します。

QGISと既存のビューアサーバを終了し、更新した環境で再起動します。
古いサーバの残存確認は[回収手順](viewer_server_recovery.ja.md)を参照してください。

## 動画での確認

APIが利用できる環境で、問題が再現した動画を指定します。

```python
cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 8])
try:
    print("Opened:", cap.isOpened())
    if cap.isOpened():
        print("Backend:", cap.getBackendName())
        print("Threads:", cap.get(cv2.CAP_PROP_N_THREADS))
        print("Seek:", cap.set(cv2.CAP_PROP_POS_FRAMES, 9571))
        print("Before:", cap.get(cv2.CAP_PROP_POS_FRAMES))
        ok, image = cap.read()
        print("Read:", ok, "After:", cap.get(cv2.CAP_PROP_POS_FRAMES))
finally:
    cap.release()
```

要求9571なら位置は読み出し前9571、後9572が期待値です。
画像内容も確認し、複数の途中フレームと先頭・終端でパネルとWeb表示を比較してください。
2026-10-09、自宅Ubuntu（CPU20、QGIS 3.44.7）でOpenCV 4.8.1を使い、
診断用`LD_PRELOAD`なしで0.5.6の正常動作をユーザが確認しました。
QGISとWebサーバの両方が同じ専用ディレクトリから4.8.1を読み込んでいます。
この配布ビルドでは内蔵FFmpegの版も変わるため、旧4.6との差をスレッド設定だけに帰属させないでください。

## Ubuntuで確認した専用ディレクトリ方式

システムのOpenCV 4.6とNumPy 1.26.4を残し、検証用OpenCVだけを追加しました。
`/usr/bin/python3`にpipがない場合は、先に`sudo apt install python3-pip`を実行します。

```bash
geo360_cv_dir="$HOME/.local/share/Geo360View/opencv-4.8.1"
/usr/bin/python3 -m pip install --target "$geo360_cv_dir" \
  --no-deps --only-binary=:all: "opencv-python-headless==4.8.1.78"
```

既存のQGISとWebサーバを終了してから、同じ端末で次を実行します。

```bash
env -u LD_PRELOAD -u GEO360_PROBE_THREADS \
  PYTHONPATH="$geo360_cv_dir${PYTHONPATH:+:$PYTHONPATH}" qgis
```

これは、この起動に対して新しいOpenCVを選ぶ方法です。通常のランチャーからの起動まで変更するものではありません。
新しい端末では`geo360_cv_dir`の定義も必要です。
この特定ビルドの検証条件はNumPy 1.26.4です。別のNumPy版への互換性を保証する導入手順ではありません。
バージョンと読み込み元は[環境診断](environment_diagnostics.ja.md)で確認してください。

APIの仕様は[OpenCV 4.8公式資料](https://docs.opencv.org/4.8.0/d4/d15/group__videoio__flags__base.html)を参照してください。
