# Geo360View調査の再開メモ

更新日: 2026-10-08。ユーザの希望により本日の調査はここで終了。公開、コミット、pushは行わない。

開発リポジトリ: `/home/ns0521/TenkakuNinjaProject/Geo360View`。現在のHEADは`934e767`。ここに残る未コミット変更と未追跡の新規ファイルを保全し、再開時に初期化・上書きしない。

## 公開状況と判断待ち

- 0.5.5のGitHub Release用ZIPは作成済みで、ユーザがReleaseとSHA256を公開した。QGISプラグインリポジトリでは、ユーザの最終報告時点で自動チェック通過・人間の承認待ち。現在の承認状態は未確認。
- 提出用ZIPのmetadataは`version=0.5.5`、`experimental=False`、最小QGIS 3.40、最大4.2.2。実験版の設定ではない。
- 公開前に原因と影響範囲を絞る必要があるとユーザと認識を共有した。公開保留を提案したが、保留手続きやレビュー担当者への連絡はしていない。
- 他の環境で動作することは確認できたが、潜在的な影響範囲は未確定。「自宅固有だから他ユーザには起きない」と扱わない。

## 現在の到達点

- 公開済み0.5.5はWindowsと別のUbuntuベアメタルで動作確認済み。自宅Ubuntuはヘッドレス・TigerVNCの仮想画面構成で、別のUbuntuは物理画面をVNCで共有している。
- 自宅QGISのバックトレースでは3.44.7が確認された。Qt5 / Python 3.12系。
- WebGLはVirtualGL経由でNVIDIA RTX 2080 Tiを利用する状態になったが、それだけでは誤画像は解消しなかった。
- 自宅OpenCV 4.6.0 / FFMPEGバックエンドの単独テストで、9571番へのシーク後の位置が巨大な負数となり、起点の画像を返した。QGIS・ブラウザを介さず再現している。
- 同じ動画をFFmpegコマンドで約319.35秒の位置から抽出すると、ユーザ確認で正しい画像になった。根本原因は未特定。
- QGISクラッシュはメインスレッドの`__dynamic_cast` / QGIS / SIP / アプリ全体イベントフィルタ経路で発生していた。親クラスへの呼び出し変更だけでは改善せず、全体フィルタの登録を外した候補では操作・プラグイン管理画面とも落ちなくなったと報告された。
- その候補でもWeb画像が誤った状態だったが、残存サーバを停止して起動し直すとパネル・Webとも正しく表示された。最初にサーバが残った具体的な終了操作は未特定。
- 「ハードウェア対応時からの問題」という話はGPXVideoProcessorとの取り違え。Geo360Viewの不具合発生時期の根拠には使わない。

## 今日の調査経緯

1. 初期の8181番healthはGPXVideoProcessorの設定を示していた。Geo360Viewの8182番に接続先を分けた。別プラグインのサーバとの混同があった。
2. フレーム53671のHTTP 422は、動画の報告総フレーム数53497（有効範囲0〜53496）を超えていた。終端の範囲チェックを追加。ただし途中の地点でも誤画像があり、終端だけの問題ではなかった。
3. WebGLのllvmpipe状態をVirtualGL/NVIDIAへ変更したが、症状は残った。画像縮小でも改善せず、GPUや8Kの描画負荷だけでは説明できなかった。
4. パネルとWebの番号・指示IDは更新していたが、生成JPEGの内容も起点だった。JavaScriptソースマップの404は、画像取得失敗とは別の警告だった。
5. 単独OpenCVテストでシーク異常を確認。FFmpeg CLIでは正しい場面が抽出された。位置検査とFFmpegフォールバック、旧キャッシュの再生成を候補に追加した。
6. パネルだけ正しくWeb側が誤る状態は、サーバ停止・再起動で改善した。古いコードを保持したプロセスの再利用と整合するが、残存に至った操作は未特定。
7. 0.5.5へ戻した後、画像閲覧・プラグイン管理画面などでクラッシュ。プラグインなし起動では管理画面は落ちなかった。Geo360Viewだけを有効にしてもクラッシュした。
8. GDBで全体イベントフィルタ中のネイティブ型変換を確認。最初の修正（`super().eventFilter`を呼ばない）でも同じ箇所で落ちた。全体フィルタ登録自体を外した候補ではユーザ確認で改善した。
9. サーバ残存対策と復旧手順を作成。その後、オンザフライで数秒という要求を優先し、自動FFmpegフォールバックを最新候補から外した。この最新候補は実機未検証。

### 読み出し異常の具体例

動画: `/home/y-matsui/work/nexco/hokuriku/04_VID_20160212_022025_20250711112746_8K.mp4`

```text
OpenCV: 4.6.0 / Backend: FFMPEG
Frame count: 53497.0 / FPS: 29.970000867778218
Requested: 0    Seek: True Before: 0.0 After: 0.0 Time(ms): 0.0 Read: False
Requested: 9571 Seek: True Before: -3071382977204209.0
After: -3071382977204208.0 Time(ms): 0.0 Read: True
```

9571番の保存画像は起点の内容だった。FFmpeg CLIによる約319.35秒の抽出は正しいとユーザ確認。OpenCVのどの内部処理で誤った値になったかは未特定。タイムスタンプ、ビルド、動画構造などは候補であり、確定原因ではない。

## 候補版を区別する

候補はすべて未公開の0.5.6。同じファイル名なので、格納先で区別する。

| ZIPの格納先（dist配下） | 内容と確認状況 |
| --- | --- |
| `qgis3-no-global-filter/Geo360View-0.5.6.zip` | 全体イベントフィルタ削除、FFmpeg自動フォールバックあり。ユーザが無クラッシュと、サーバ再起動後の正しい画像を確認した候補。 |
| `qgis3-server-lifecycle/Geo360View-0.5.6.zip` | 上記にサーバの所属・コード指紋確認、親入力パイプEOFによる終了、通常終了時の停止を追加。QGIS実機の検証は未実施。 |
| `qgis3-opencv-only/Geo360View-0.5.6.zip` | 最新ソース。対話経路のFFmpeg自動フォールバックを外した。94件のテストが通過。QGIS実機の検証は未実施。 |

最新候補では、異常なOpenCV読み出しはエラーになる。前の候補で表示できたことは、OpenCV自体が修復されたことを意味しない。誤生成した画像は保存しない。FFmpegは明示的な比較診断用の関数にだけ残している。

公開済み`dist/Geo360View-0.5.5.zip`は変更していない。SHA256:

```text
4b3aea41be79ff24de57a1ac960d14e952a3dfa41cdb372cfca01cfde2f785c0
```

## 次に調べること

### 2026-10-09の比較情報

ユーザからQGIS上のVideo I/Oビルド情報を受領した。

| 項目 | 自宅Ubuntu（問題あり） | 会社Windows（動作） |
| --- | --- | --- |
| OpenCV（ユーザ報告） | 4.6 | 5.0 |
| FFMPEG | YES | YES (prebuilt binaries) |
| avcodec | 60.31.102 | 61.19.100 |
| avformat | 60.16.100 | 61.7.100 |
| avutil | 58.29.100 | 59.39.100 |
| swscale | 7.5.100 | 8.3.100 |
| GStreamer | YES (1.24.1) | NO |
| Parallel framework | TBB 2021.11 | Concurrency |

OpenCVとFFmpegライブラリの両方に世代差があると確認できた。ただし、OS・ビルド構成も異なるので、どちらの差が原因かは断定しない。Windowsの「5.0」はユーザ報告の表記で、完全な版文字列と導入パスは未取得。FFmpeg CLIによる抽出が成功した事実も踏まえ、OpenCVとFFmpegの組み合わせ・利用方法を比較する。動作する別Ubuntuの構成を次に比較したい。QGISの既存Python環境へOpenCVを上書きインストールする前に、現状を記録する。

その後、会社の動作したUbuntuのVideo I/O情報も受領。avcodec 60.31.102、avformat 60.16.100、avutil 58.29.100、swscale 7.5.100、GStreamer 1.24.1、TBB 2021.11で、自宅Ubuntuの提示情報と一致する。FFmpeg世代差だけでUbuntu間の動作差を説明する仮説は弱まった。ただし、この出力だけでOpenCV本体・配布パッケージ・実際のリンク先まで同一とは言えない。会社UbuntuのOpenCV版・導入パスと、検証動画が自宅と同一かは未確認。次は入力動画を揃えることを優先する。

さらにユーザ確認: 動画名は同じ。自宅ではダウンロードしたローカルファイル、会社UbuntuではNAS上のファイルを読み出している。バイト単位の同一性は未確認。両方のファイルサイズとSHA256を比較し、一致した場合に会社側でNAS版とローカルコピーを比較する順で切り分ける。NAS/ローカルという保存場所の差だけを原因と断定しない。

両動画のSHA256が一致したとユーザ確認:

```text
174cbda58bbdacaa226875cd5e30cd50fc10c92c4092b41e20676a8559d3049c
自宅: /home/y-matsui/work/nexco/hokuriku/04_VID_20160212_022025_20250711112746_8K.mp4
会社側確認パス: /mnt/nfs/workshop/nexco/hokuriku/04_VID_20160212_022025_20250711112746_8K.mp4
```

動画のバイト内容差を除外できた。会社のハッシュ実行プロンプトは`/mnt/c/Users/ns0521`であり、動作したUbuntuのQGIS環境と同じ実行環境とは確認できない。ハッシュはどの環境でも有効だが、OpenCV比較は実際に動作したUbuntuのQGIS Pythonで行うこと。会社UbuntuのOpenCV版・導入パス、およびプラグインやキャッシュを通さない9571番の新規VideoCapture読み出しが次の確認対象。

会社UbuntuのQGIS Pythonで、同じNAS動画を新規VideoCaptureから9571番へ直接シークした結果を受領:

```text
4.6.0 /usr/lib/python3/dist-packages/cv2.cpython-312-x86_64-linux-gnu.so
Opened: True Count: 53497.0
Seek: True
Before: 9571.0
Read: True After: 9572.0
```

会社UbuntuもOpenCV 4.6.0で、位置情報は期待どおりだった。動画内容・OpenCV版・提示されたVideo I/O欄が一致しても結果に差がある。ただし、このテストで9571番の画像内容を直接確認したわけではない。次は自宅のQGIS内でも同じ新規VideoCapture→9571番の手順でテストし、前回の単独テストとの実行環境・操作手順差を揃える。前の自宅テストには0番でRead=Falseという結果もあり、呼び出し順やキャプチャ再利用の条件は追加確認が必要。パッケージ版、実際のリンク先、環境変数、NAS/ローカルの比較はその後に行う。

自宅QGISでも同じ新規VideoCapture→9571番の手順を実施。最初の入力は拡張子`.mp`の誤記でOpened=Falseだったため比較から除外。`.mp4`へ訂正後、以下を受領:

```text
4.6.0 /usr/lib/python3/dist-packages/cv2.cpython-312-x86_64-linux-gnu.so
Opened: True Count: 53497.0
Seek: True
Before: -3071382977204209.0
Read: True After: -3071382977204208.0
```

同じSHA256の動画、同じOpenCV版とモジュールパス、同じ操作手順をQGIS Pythonで実施しても、自宅では位置情報異常、会社では正常となる。0番読み出しの失敗を先に挟んだことだけが原因という説明は除外できた。Webサーバやプラグインの画像キャッシュを介さず再現。次は両QGISの実ロードされたlibopencv_videoio/libav系ライブラリのパスと、LD_LIBRARY_PATH/LD_PRELOAD/OpenCVのキャプチャ設定を比較する。必要なら実ファイルのハッシュと配布パッケージ版を確認する。

両QGISの実ロードパスも一致した:

```text
/usr/lib/x86_64-linux-gnu/libavcodec.so.60.31.102
/usr/lib/x86_64-linux-gnu/libavformat.so.60.16.100
/usr/lib/x86_64-linux-gnu/libavutil.so.58.29.100
/usr/lib/x86_64-linux-gnu/libopencv_videoio.so.4.6.0
/usr/lib/x86_64-linux-gnu/libswscale.so.7.5.100
```

自宅の環境変数: LD_LIBRARY_PATH=/usr/lib/grass83/lib、LD_PRELOAD=None、OPENCV_FFMPEG_CAPTURE_OPTIONS=None、OPENCV_VIDEOIO_PRIORITY_LIST=None。会社側の環境変数出力はまだ未受領。ライブラリファイルのSHA256も未比較なので、パス一致をバイナリ同一と断定しない。

OpenCV 4.6.0上流ソースを確認すると、LinuxのCPU数をsysconfから取得し、FFmpegのdecoder thread_countに設定している。同じライブラリでもCPU数により実行条件が変わり得るため、両QGISでSC_NPROCESSORS_ONLNを比較する。スレッド数が根本原因とは未確定。4.6上流ソースではcodecを開く際の辞書がNULLなので、未検証の「threads;1」環境変数指定を有効な対策と決めつけない。

CPU数の比較を受領: 会社UbuntuはSC_NPROCESSORS_ONLN=8、自宅Ubuntuは20。4.6上流はこの値をdecoder thread_countに設定する。4.8上流では既定最大16とOPENCV_FFMPEG_THREADS設定があり、比較する価値がある。ただしCPU数との因果は未確定で、4.6へ新しい設定方法が有効と仮定しない。

切り分け用に`scripts/diagnose_video_threads.py`、`scripts/video_threads_probe.c`、`scripts/video_threads_probe_README.ja.md`を作成。配布ZIPは`dist/diagnostics/Geo360View-video-threads-diagnostic.zip`。Ubuntuの単独Python子プロセスで、既定・8・16・20のFFmpegデコーダスレッド設定を比較し、位置、画像、open/seek/read時間を出力する。既存ライブラリやプラグインには組み込まない。FFmpeg 6の公開AVOptionで一時的に設定を変える診断用LD_PRELOADを子プロセスにのみ適用。cc/gccが必要で、自動インストールはしない。切り替えと実FFmpeg呼び出しへの転送は代替FFmpeg APIのCハーネスで8/16/20を確認済み。実OpenCV・動画での検証は未実施。既定の単独テストがQGIS内と同じ症状か、まず確認が必要。会社側環境変数と実ライブラリSHAの比較はまだ未実施。

自宅でスレッド比較診断を実行した結果を受領（2026-10-09）。実際のOpenCV 4.6.0 / FFmpegバックエンドで、主VideoCaptureのdecoder thread_countが要求値へ変わったことをログで確認できた。

| 設定 | seek前後のBefore | read後のAfter | seek秒 | read秒 | 判定 |
| --- | --- | --- | --- | --- | --- |
| default（CPU20） | -3071382977204209 | -3071382977204208 | 3.5566 | 0.2204 | 異常 |
| 8 | 9571 | 9572 | 1.0332 | 0.0551 | 位置情報は正常 |
| 16 | -3071382977204209 | -3071382977204208 | 3.6240 | 0.1647 | 異常 |
| 20 | -3071382977204209 | -3071382977204208 | 3.5494 | 0.1976 | 異常 |

すべてOpened=True、Seek=True、Read=True、総フレーム数53497。主デコーダのログは`threads before=20 requested=8 actual=8 open_result=0`等。事前のストリーム解析で出るbefore=1/actual=1のログと区別する。結果・画像は自宅`/tmp/geo360-threads-dpj2g0cl/`にあり、default.jpg、8.jpg、16.jpg、20.jpg、results.txt。

同一マシンでデコードスレッド設定を変更すると9571番の位置情報が改善する、という実験結果を得た。8.jpgが実際に9571番の場面かは、まだユーザの目視確認が必要。8〜16のどこから異常になるか、複数フレーム・他動画でも成立するか、OpenCV内部の根本原因は未確定。16でも失敗したため「最大16にすれば解決」と扱わない。現状の計測は1回ずつで、恒常的な速度保証には使わない。

次は8.jpgの内容確認を優先し、その後8スレッドで先頭・複数の途中・最終有効フレームを検証する。正式対策は、スレッド数を明示できるOpenCVのAPIを利用するなど、プラグインから適切に制御できる経路を検討する。今回のLD_PRELOAD診断をそのままプラグインに組み込む方針ではない。4.6はスレッド指定APIの対応を別途確認する必要がある。

ユーザが自宅診断の`8.jpg`を目視し、期待した途中の正しい場面と確認した。今回の環境・動画・9571番では、8スレッド指定で位置情報と内容の両方が正常化し、16/20では異常となることを確認できた。ただし、内部でタイムスタンプが壊れる根本原因、境界値、全動画への一般化は未確定。

次の実機確認として、自宅だけで一時的な診断ライブラリをQGIS起動コマンドへ適用する案を提示する。プラグインメニューから終了し、QGISを閉じ、Geo360Viewの待受が残っていないことを確認してから、`env GEO360_PROBE_THREADS=8 LD_PRELOAD=/tmp/geo360-threads-dpj2g0cl/video_threads_probe.so PYTHONFAULTHANDLER=1 qgis`で起動する。親QGISからQProcess環境を継承する新しいWebサーバにも設定が渡る。古いサーバは再利用せず停止が必要。これは診断・自宅限定の暫定起動で、正式配布するプラグインへLD_PRELOADを組み込む対策ではない。8スレッドで先頭・複数の途中・最後の有効フレームを比較する。最新opencv-only候補は未検証で、正常化の確認が先。

続いて、自宅で8スレッドを適用した暫定QGIS起動を試し、ユーザから「正しく指定した画像を表示できるようになりました」と報告を受領。単独診断だけでなくQGISの実操作でも改善を確認できた。各フレーム・別動画の網羅範囲、最新候補へのインストール切替、通常起動との比較回数は未明示なので追加検証が必要。

この実機結果から、自宅のOpenCV/FFmpegシーク不良はデコードスレッド数を減らすことで回避できると確認できた。20/16設定で異常、8で位置と画像が正しい。NAS/ローカル、VNC、GPUだけを根本原因として扱わない。内部タイムスタンプの壊れる機序は未特定。次の実装課題は、診断用LD_PRELOADに依存せず、正式なデコードAPIで適切なスレッド数を設定できる方法の選定と、Windows・正常Ubuntuでの回帰確認。OpenCV 4.6の通常APIではスレッド指定に制約があるため、単に新しいAPI名を追加するだけで全環境対応済みとしない。QGISクラッシュ対策（全体フィルタ削除）とサーバ残存対策は、このシーク対策と別の変更として検証する。

公式ソース上、FFmpeg 6.1のavcodecメジャーは60、7.1は61:
[6.1](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n6.1/libavcodec/version_major.h)、[7.1](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n7.1/libavcodec/version_major.h)。ビルド情報だけでディストリビューション側の修正や実際の全リンク構成まで確定しない。

「画像が違う」報告の確認項目とテンプレートは[画像違いの切り分け](wrong_image_triage.ja.md)に整理済み。要求番号と表示完了番号の区別、診断情報コピーなどのUI改善は未実装。

最優先は、同じ動画・同じプラグインでOpenCVの読み出しに環境差が出る理由を調べること。

1. 動作するUbuntuと問題のUbuntuで同じ動画かSHA256を確認する。
2. パネルのQGIS PythonとWebサーバのPythonそれぞれで、Python実行パス、OpenCV版、`cv2.__file__`、`cv2.getBuildInformation()`を収集する。
3. バックエンドとOpenCVが利用するFFmpeg構成を比較する。FFmpegコマンドの版とOpenCV側のFFmpegは同一とは限らない。
4. 同じフレームを順読みした場合とランダムシークした場合で、返された画像と位置情報を比較する。
5. サーバ残存対策は別件として、終了メニュー、正常なリロード、QGIS通常終了・強制終了、上書き更新の前後でPIDと待受ポートを確認する。

比較前にライブラリを更新すると差異の手がかりが失われるため、まず現状の情報を保存する。QGISのPythonコンソールでは以下を一行ずつ実行して収集できる。

```python
print(__import__("sys").executable)
print(__import__("cv2").__version__)
print(__import__("cv2").__file__)
print(__import__("cv2").getBuildInformation())
```

Webサーバは実際のPIDの実行パス・起動コマンドから使用するPythonを確認する。通常の端末の`python3`で得た情報を、そのままQGISやサーバの情報と同一視しない。

参考としてユーザが挙げた[Qiita記事](https://qiita.com/BUU-SAN/items/3076b8df3f88fd9a7785)は、順読みの途中で`read()`がFalseになる事例。今回の「成功扱いで誤画像・位置が巨大な負数」と同じ原因とは未確認。記事のリカバリ方法をそのまま適用しない。

## 制約と運用

- Geo360Viewの目的は必要なフレームをオンザフライで数秒で取り出すこと。毎回FFmpegプロセスを起動する遅いフォールバックを通常の解決策にしない。
- 環境問題だけとも、プラグイン全般の不具合とも断定しない。位置情報の検査だけで画像内容の完全な正確性を保証できるわけではない。
- 自宅`/home/y-matsui`環境はこの開発シェルから操作できない。実機確認はユーザの作業と結果共有が必要。
- 実装変更はGeo360Viewの作業ツリーに未コミット。公開済み0.5.5やその配布ZIPを上書きしない。
- 復旧手順と条件表は[Webビューアのサーバ残存と復旧](viewer_server_recovery.ja.md)を参照する。無関係なPythonサーバをまとめてkillしない。
- 最新のテスト: `python3 -m unittest discover -s tests -q`、112件通過。親パイプEOFは子プロセスでテストしたが、ネットワーク待受はサンドボックス制限のため代替実装。QGIS・Windows上の終了検証は未実施。

## 2026-10-09: OpenCV 4.8以上の正式APIによるスレッド指定

- ユーザから、診断用ライブラリで8スレッドにしたQGISでは正しい画像を表示でき、以前より速いとの報告があった。
- OpenCV 4.8以上を推奨環境に明記。Windows導入コマンドとビューアrequirementsは元から4.8以上だった。
- `video_frames.open_video_capture`を追加し、プラグインとWebビューアの全5箇所で共通利用。APIがある場合はFFmpegバックエンドを明示して、開く時点で`CAP_PROP_N_THREADS=8`を指定し、報告値が1〜8であることを確認する。
- 指定付きで開けない場合、制限なしの再試行は行わない。Webでは422、プレビューでは既存の抽出警告経路に報告する。
- APIがない4.6などの環境は警告を出して従来処理を継続するため、制限は適用できない。推奨環境と最低動作条件は区別する。
- 新しいテストを含め102件通過、変更Pythonファイルの構文確認と`git diff --check`も通過。ネイティブOpenCV 4.8以上・QGIS上のAPI方式は未検証。
- 検証用ZIP: `dist/opencv-thread-limit/Geo360View-0.5.6.zip`。公開済み0.5.5 ZIPのSHA256は変更なし。環境の確認・再起動・動画検証は[設定手順](opencv_decoder_threads.ja.md)を参照。

## 2026-10-09: 不具合報告用の環境診断

- ユーザの提案に沿い、まずQGIS Pythonコンソールから1行で実行する方式を実装。メニュー項目は追加していない。
- `from Geo360View.environment_diagnostics import print_environment_report; print_environment_report()`でMarkdown形式のレポートを出力する。
- QGISプロセスと起動中Webサーバの実際の環境を分け、OpenCVバージョン・配置先・Video I/Oビルド情報・CPU数・限定した環境変数・Linuxのロード済みライブラリを記録する。画像や動画は読み出さず、サーバも自動起動しない。
- Webサーバに`/api/diagnostics`を追加。旧版サーバや接続不能でも、その理由を表示してQGIS側のレポートは残す。所有トークンとジョブ設定はレポートに含めない。
- 診断レポートの「上限8」は設定方針であり、開いているデコーダの実測値ではない。OpenCVの汎用並列処理スレッド数とは別と明記する。
- 112件の回帰テスト通過。実機コンソール・実際のHTTP待受の確認は未実施。使い方は[診断手順](environment_diagnostics.ja.md)を参照。
- 診断を同梱した検証用ZIPは`dist/environment-diagnostics/Geo360View-0.5.6.zip`。公開済み0.5.5は変更しない。

## 2026-10-09: 実機診断結果とWindows起動比較

- 自宅Ubuntu: QGIS 3.44.7 / Qt 5.15.13 / Python 3.12.3 / OpenCV 4.6.0、CPU20。QGISとWebサーバ双方に診断用`LD_PRELOAD`と`GEO360_PROBE_THREADS=8`が残った状態で最新0.5.6の動作を確認。正式APIは利用されていない。
- 会社Ubuntu: 同じQGIS・Qt・Python・OpenCV版、CPU8。特殊な環境変数なし、FFmpeg CLIなしで正常動作。ユーザによるとソフトウェアWebGLでも実用的な速度。旧サーバを停止した後に診断成功。
- 両Ubuntuのロード済みFFmpegライブラリ版とWebサーバbuildは一致。環境診断のQGIS・Web両プロセス取得を実機確認できた。
- Windows: QGIS 3.40.12 / Qt 5.15.13 / PyQt 5.15.11 / Python 3.12.11 / OpenCV 5.0.0、CPU20。cv2はユーザPython312 site-packages。APIはあるが、Web診断は当初タイムアウト。ブラウザLoading、Windowsの応答低下も報告された。
- QGIS起動のPython PID34404と8182ポートのListen PIDが一致した。その後、プロキシなし直接接続は10061で拒否。時点差があるため、待受が継続していたと断定しない。終了原因ログは取得できていない。
- OSGeo4W Shellから同じPython・app.py・runtime configで手動起動し、`VIEWER_WATCH_STDIN=0`を指定すると、PID33108が起動しQGISからhealth応答`status=ok`を確認。QProcess起動との差があるが、標準入力監視が根本原因と確定したわけではない。
- 比較候補ではQProcess起動時の標準入力監視をWindowsのみ無効化。Linuxは有効。通常Exit/unload/aboutToQuitの停止とterminate/killは維持。Windows強制終了時のサーバ残存は保証できない。
- 検証用ZIP: `dist/windows-no-stdin-watch/Geo360View-0.5.6.zip`。113件通過。手動起動の端末はCtrl+Cで止め、QGISを終了してから比較ZIPをインストールし、再起動して確認する。Windows実機での比較結果は未報告。

- Windows標準入力監視無効版の実機結果: ユーザから「360ビューア起動でブラウザが開かなくなった」と報告。自動停止監視の無効化だけで直ったと扱わない。手動サーバ残存の有無、現在の警告、プロセス・HTTP応答状態は再確認が必要。
- 起動状態診断を追加した候補: `dist/windows-startup-diagnostics/Geo360View-0.5.6.zip`。通常の環境診断1行で管理PID・起動コマンド・プラグインhealth判定・プロキシなし直接health・所有識別子の一致を記録。サーバの起動動作は直前の比較版と同じで、原因の決め打ち修正を追加したものではない。
- 115件の回帰テスト通過。比較用ZIPを増やしたため、最新候補のディレクトリ名を必ず区別する。公開済み0.5.5は変更しない。

## 2026-10-09: Windows正常終了と自宅Ubuntu正式API構成の検証成功

- Windowsで正常動作をユーザが確認。その後QGIS 4.2.2でも0.5.6を確認。プラグインの「終了」と、プラグインを終了しないままQGISを通常終了する両経路でHTTPサーバが消えることを確認した。強制終了・クラッシュ時は別の未検証条件。
- 「360Viewer起動」を押すたびブラウザ窓が開くが、画像切替では窓が増えないと確認。この分岐は0.5.5にも存在し、サーバの毎回再起動を意味しないため修正していない。
- 自宅Ubuntuではapt提供のOpenCV候補が4.6.0のみ。システムのNumPyは1.26.4。pipをaptで追加した後、`opencv-python-headless==4.8.1.78`を`~/.local/share/Geo360View/opencv-4.8.1`へ`--target --no-deps`で配置した。
- `PYTHONPATH`に専用ディレクトリを加え、`env -u LD_PRELOAD -u GEO360_PROBE_THREADS ... qgis`で起動すると、0.5.6が正常動作するとユーザが報告。
- 2026-10-09T02:36:25Zの診断: QGIS PID356107 / Web PID356403、CPU20、QGIS 3.44.7 / Qt 5.15.13 / Python 3.12.3。双方のcv2は専用ディレクトリ内4.8.1、APIあり、設定上限8、診断用環境変数は両方null。OpenCV汎用処理スレッド20は別の値。
- 新ビルドのロード済みFFmpegは専用wheel内のavcodec59.37.100、avformat59.27.100、avutil57.28.100、swscale6.7.100。従来のシステム版(avcodec60など)から変わっている。4.6の8/16/20スレッド比較が因果調査の主な根拠で、4.8.1更新の成功だけをスレッド設定単独の効果と断定しない。
- これで正式APIを利用できる構成での回避を実機確認できた。全動画・全環境での保証ではない。通常ランチャー起動ではシステム4.6へ戻るので、今後の日常起動方法の整備は別作業。
- 診断に`viewer.startup`が含まれていないため、今回の実機配布物がローカル最新の起動診断候補と完全に一致するとは断定しない。リリース前に最終ZIPを一本化して同じ成果物で確認する必要がある。

## 2026-10-09: Push前の環境別検証記録整理

- 利用者の依頼により[0.5.6環境別動作検証記録](runtime_validation.ja.md)を作成。Windows 3.40/4.2.2、会社Ubuntu、自宅Ubuntuを分け、診断値・動作・通常終了・未確認項目・配布物特定の限界を記録した。
- Windows終了確認はQGIS版が明示されていないため、両版で個別確認済みとは記載しない。0.5.5のMarking/GPKG等の結果も0.5.6へ流用していない。
- README両言語、品質保証方針、手動チェックリスト、移行記録からリンク。CHANGELOGの古い一括「実機未確認」記載とテスト数を現時点の記録へ更新した。
- 今回はドキュメント更新のみ。GitHubへのcommit/push、Release公開、配布ZIP更新は行っていない。

- 追加報告: 会社Ubuntuで0.5.6の正常動作を再確認。もともとCPU数8の環境。HTTPサーバの挙動は未確認と利用者が明示したため、通常終了・回収確認を済み扱いにしない。環境別検証記録に追記済み。

- 続報: 会社Ubuntuでプラグイン終了時とQGIS終了時にHTTPサーバが消えることを確認したと利用者が報告。環境別記録の両終了経路とCHANGELOGを確認済みに更新。自宅Ubuntuの終了確認、クラッシュ・強制終了時の回収は未確認のまま。

- 続報: 自宅Ubuntuでもプラグイン終了時とQGIS終了時のHTTPサーバ停止を確認したと利用者が報告。環境別記録とCHANGELOGを更新し、通常終了はWindows・会社Ubuntu・自宅Ubuntuの全環境で確認済み。Windowsの各QGIS版での個別終了確認、クラッシュ・強制終了時の回収は別項目として扱う。

- 追加報告: 自宅Ubuntuの通常起動でも0.5.6が正常表示。02:52:55Zの診断でQGIS PID359843・Web PID359935ともシステムOpenCV 4.6.0 / FFmpeg 60系、CPU20、診断用変数なし、APIなしを確認した。新規デコードと既存成果品・キャッシュの再利用は未区別。4.8.1試験で作った`seek-v2`画像を4.6でも再利用できるため、根本解消や8スレッド指定の適用とは扱わない。動画をキャッシュを介さず直接読み出すか、未抽出フレームで追加確認する。

- 続報: 利用者が自宅の通常起動4.6で別フレーム3933を指定すると、`/frames/…/3933.jpg`がHTTP 422となった。先の表示成功はキャッシュによるものと利用者が確認。環境別記録・CHANGELOGを修正し、通常起動4.6の新規読み出しは未解決と記録。422本文未取得のため今回の例外の種類は断定しない。日常利用には検証済みのOpenCV 4.8.1を選ぶ起動方法が必要。

- 続報: 利用者が診断用`LD_PRELOAD`方式で再度正常を確認したため、4.8への切り替えとは別と説明。その後専用ディレクトリを`PYTHONPATH`に指定し、診断用変数を外してQGISを再起動、OpenCV 4.8での正常動作を再確認した。
- 最終提示診断03:01:11Z: QGIS PID365842 / Web PID365926、双方OpenCV 4.8.1、APIあり、設定上限8、`LD_PRELOAD`と`GEO360_PROBE_THREADS`はnull、FFmpegはwheel内59系。環境別記録へ追記。今回の具体的フレーム番号・キャッシュ未使用の証拠は未記録のため、新規デコード確認項目は残す。
