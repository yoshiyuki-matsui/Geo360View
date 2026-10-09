# OpenCV 4.6 / FFmpeg 6 スレッド数比較

動画のSHA256、OpenCV版、Video I/O情報が一致する会社Ubuntu（CPU数8）と自宅Ubuntu（CPU数20）で、9571番へのシーク結果が異なるための診断です。CPU数が原因と確定したわけではありません。

この3ファイルを同じフォルダに置き、Ubuntuの通常端末から実行します。QGISのPythonコンソールでは実行しません。

```bash
python3 diagnose_video_threads.py "/home/y-matsui/work/nexco/hokuriku/04_VID_20160212_022025_20250711112746_8K.mp4"
```

Python側のOpenCVと、Cコンパイラ`cc`または`gcc`が必要です。スクリプトはパッケージを自動インストールしません。対象は動的リンクされたFFmpeg 6の`libavcodec.so.60`です。

既定、8、16、20スレッドで各々新しいPythonプロセス・VideoCaptureを使い、同じ9571番を読みます。既定テストが自宅QGISと同じ巨大な負数になるか、最初に確認してください。異なる場合、QGIS内との実行環境差が残っているため結果をそのまま同一視しません。

`/tmp/geo360-threads-...`へ結果と縮小JPEGを保存します。各JPEGの中身も確認してください。正常な位置情報だけでは正しい場面の保証にはなりません。測定はopen/seek/readに分けていますが、キャッシュや初回処理による変動があるため、1回で性能を断定しません。

診断用Cライブラリを一時的にコンパイルし、指定した子プロセスでだけ`avcodec_open2`の直前に公開AVOption APIでスレッド数を設定します。次のログが出ることを確認してください。

```text
geo360 probe: threads before=20 requested=8 actual=8 open_result=0
```

`actual`が要求と一致しない、ログが出ない、ライブラリを解決できない場合は、そのテストでスレッド数を変更できたとは扱いません。インストール済みOpenCV・FFmpeg、QGIS設定、CPU設定は変更しません。診断用LD_PRELOADをQGISや通常起動設定へ追加しないでください。比較結果を回収したら一時フォルダは削除できます。

この方式は原因を調べるためのもので、Geo360Viewへ組み込む対策ではありません。

参考: [OpenCV 4.6実装](https://github.com/opencv/opencv/blob/4.6.0/modules/videoio/src/cap_ffmpeg_impl.hpp)、[OpenCV 4.8実装](https://github.com/opencv/opencv/blob/4.8.0/modules/videoio/src/cap_ffmpeg_impl.hpp)、[FFmpeg 6.1 AVOption](https://github.com/FFmpeg/FFmpeg/blob/n6.1/libavcodec/options_table.h)。
