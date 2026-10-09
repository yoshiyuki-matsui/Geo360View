# 環境診断の実行と報告

開発版0.5.6では、Geo360Viewを有効にしてQGISのPythonコンソールから次の1行を実行できます。
公開済み0.5.5にはこのコマンドは含まれません。

```python
from Geo360View.environment_diagnostics import print_environment_report; print_environment_report()
```

出力の`## Geo360View environment diagnostic`から末尾までをコピーして、IssueやDiscussionに貼り付けてください。
表示されるPython実行ファイルやライブラリのパスにはユーザ名などが含まれる場合があります。
公開したくない部分は伏せ字にしてください。

## 取得する情報

- プラグイン、QGIS、Qt、Python、OpenCVのバージョンと読み込み元
- CPU数、OpenCVのVideo I/Oビルド情報（FFmpegと関連ライブラリ）、並列処理方式
- デコードスレッド指定APIの有無と、開発版で指定する上限
- Linuxで実際に読み込まれている動画関連ライブラリのパス
- スレッド・ライブラリ・ディスプレイに関係する限定した環境変数
- FFmpegコマンドの配置先（OpenCVが使うFFmpegライブラリとは別）

QGIS側は`current_process`、起動中のWebサーバ側は`viewer`に分けて表示します。
サーバは診断のために自動起動しません。未起動・旧版・到達不能の場合は取得できない理由を表示します。
サーバ側の診断APIを使うには、新しいコードでサーバを再起動してください。

Windows起動調査用候補では、`viewer.startup`に管理中のPID、Python起動コマンド、
プラグインのhealth判定、プロキシなしの直接health応答、起動元識別子の一致結果も表示します。
識別子そのものは出力しません。Qtの`process_error`が`Unknown error`の場合、
その文字列だけで起動失敗と判断しないでください。

この診断では動画を開かず、シークや画像生成も行いません。
スレッド上限は設定方針の情報であり、動作中のデコーダの実測値ではありません。
`opencv_processing_threads`は別の並列処理の値なので、デコーダのスレッド数と比較しないでください。
ビルド情報や登録済みバックエンドだけでは、その動画を正常に読み出せることは証明できません。

## 不具合報告に添える情報

環境診断に加え、次を記載してください。

- 直前の操作、再現頻度、警告全文
- パネルとWebビューアそれぞれのフレーム番号と画像内容が正しいか
- 動画の解像度、FPS、保存場所の種類（ローカル／NAS）、可能ならSHA256
- 物理画面／仮想画面、VNCやVirtualGLの利用有無

動画ファイル名や位置情報は診断に自動収集しません。
画像の切り分けは[誤画像の確認手順](wrong_image_triage.ja.md)を参照してください。

QGISを起動できない場合は、配置されたプラグインの`environment_diagnostics.py`を
`python3 environment_diagnostics.py`で実行できます。ただし、得られるのはそのPython環境の情報であり、
QGISが使っている環境と一致するとは限りません。
