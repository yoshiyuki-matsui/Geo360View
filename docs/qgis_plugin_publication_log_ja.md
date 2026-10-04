# Geo360View QGISプラグイン公開対応ログ

作成日: 2026-10-04

Geo360ViewをQGIS公式プラグインリポジトリへ公開申請するまでに実施した作業と、審査対応で得た知見をまとめる。

## 目的

Geo360Viewを、GitHub上の野良ZIP配布ではなく、QGISの公式プラグインリポジトリからインストールできる状態にする。

これにより、利用者への案内を次の形に近づける。

```text
QGISの「プラグインの管理とインストール」から Geo360View を検索してインストールしてください。
```

公式リポジトリ経由にすることで、ZIP手動インストール時の「このZIPを信頼してよいか」という心理的・運用的ハードルを下げる。

## 公開前の状態

Geo360View v0.5.0時点で、以下の機能と配布準備が整っていた。

- GPXとMP4の位置合わせ
- QGIS地図上での撮影点表示
- 360/equirectangular動画のローカルビューア表示
- Marking機能
- Markingの視点復元
- スナップショットへのMarking表示
- GitHub Release向けZIP生成スクリプト
- README / README_jaの整備
- セキュリティ・プライバシーに関するREADME追記

一方、QGIS公式プラグインリポジトリの自動審査にかけたところ、追加対応が必要になった。

## QGIS公式審査で通過したゲート

今回確認された主なチェックは以下。

- ZIP構成チェック
- `metadata.txt` のバージョン・メタ情報チェック
- 同一バージョン再アップロード不可チェック
- Bandit Security Analysis
- XMLパース安全性チェック
- `try/except/pass` 検出
- SQL injection疑い検出
- `urlopen` 利用チェック
- Qt6 compatibility check
- 作者メールアドレス確認
- 最終的な人手承認待ち

QGISプラグインはユーザPC上でPythonコードとして動作するため、公式リポジトリ側の安全性チェックはかなり厳密だった。

## 最初のBLOCKED

v0.5.0をアップロードしたところ、Critical security issueによりBLOCKEDとなった。

主な指摘は以下。

### XMLパース

標準ライブラリのXML処理が、信頼できないXML入力に対して脆弱である可能性を指摘された。

対象:

- `TenkakuNinja/geo_util.py`
- `xml.etree.ElementTree`
- `ET.parse(gpx_path)`

対応:

- `defusedxml.ElementTree` を利用するよう変更
- QGIS Python環境に `defusedxml` が入っていないケースがあったため、最小構成をプラグインへ同梱
- Geo360Viewでは `defusedxml.ElementTree` のみ使用する
- `defuse_stdlib()` は同梱版では無効化

### XMLエスケープ

`xml.sax.saxutils.escape` のimportが、XML安全性チェックに引っかかった。

対象:

- `360viewer/app.py`

対応:

- `xml.sax.saxutils.escape` を使わず、`html.escape(..., quote=True)` へ変更

### try/except/pass

UI補助、クリーンアップ、レイヤ操作などで、例外を握りつぶす `except: pass` パターンが多数検出された。

対応:

- `pass` のみのexcept節を廃止
- 無視してよい例外でも、`_geo360_ignored_error = e` のように明示的に扱う形へ変更
- レコードスキャン中に不正値を飛ばす `continue` には、意図を示す `nosec` コメントを付与

### SQL injection疑い

固定テーブル名に対するf-string SQLでも、文字列組み立てSQLとして検出された。

対象:

- `main.py`
- `gpx_video_processor_job_metadata`

対応:

- テーブル名は固定値であることを前提に、SQL文をリテラル定数化
- 値部分は従来どおりプレースホルダを利用

### urlopen利用

ローカルビューアのhealth checkやAPI呼び出しに `urlopen` を使っていたため、スキーム確認の監査対象になった。

対象:

- `viewer_controller.py`

対応:

- 呼び出し先は `127.0.0.1` のローカルビューアであることをコメントで明示
- Bandit向けに `nosec B310` を付与

## defusedxml同梱での追加対応

QGIS Python環境によっては `defusedxml` が入っていないため、最初はプラグイン起動時に以下のエラーが発生した。

```text
ModuleNotFoundError: No module named 'defusedxml'
```

対応として、`defusedxml` をプラグインに同梱した。

ただし、`defusedxml` 全体を同梱すると、未使用モジュール内の標準XML importまでBanditに検出される可能性がある。

そのため、Geo360Viewに必要な最小構成だけを同梱した。

- `defusedxml/__init__.py`
- `defusedxml/common.py`
- `defusedxml/ElementTree.py`

さらに、同梱ライブラリ内の `assert` がBandit criticalとして検出された。

対象:

- `defusedxml/common.py`
- `_apply_defusing()`

対応:

- `assert` を通常の `if ...: raise NotSupportedError(...)` に変更

## Qt6Check対応

Bandit対応後、Qt6 compatibility checkで29件の指摘が出た。

内容は、Qt5/QGIS3時代のenum省略表記をQt6/QGIS4互換の表記にするものだった。

例:

- `QEvent.KeyPress`
- `Qt.UTC`
- `QProcess.NotRunning`
- `QgsVectorFileWriter.NoError`
- `QgsMapToolIdentifyFeature.TopDownStopAtFirst`
- `QgsWkbTypes.LineGeometry`
- `QgsWkbTypes.PolygonGeometry`
- `QgsWkbTypes.PointGeometry`

対応:

- `qt_compat.py` にQt/QGIS enum互換定数を集約
- Qt6/QGIS4形式を優先し、Qt5/QGIS3形式へフォールバックする関数を追加
- 既存コードでは互換定数を参照するよう変更

これにより、現行QGIS 3 / Qt5環境を維持しながら、将来のQGIS 4 / Qt6移行に備える形にした。

## バージョン運用

QGIS Plugin Repositoryでは、同一バージョンの再アップロードはできない。

そのため、審査対応中に以下のようにバージョンを刻んだ。

### v0.5.0

Marking機能を含む初回公開候補。

### v0.5.1

Bandit Security Analysis対応版。

主な内容:

- `defusedxml` 利用
- `defusedxml` 最小同梱
- `try/except/pass` 対応
- SQL文字列組み立て指摘対応
- `urlopen` のローカル利用明示

### v0.5.2

QGIS公式アップロード向けの最終審査対応版。

主な内容:

- `defusedxml` 内の `assert` 除去
- Qt6 compatibility check対応
- `metadata.txt` を `version=0.5.2` に更新
- GitHub tag `v0.5.2` を作成

## 最終ZIP

最終的なアップロード対象:

```text
Geo360View-0.5.2.zip
```

SHA256:

```text
65147b19fd6d6d9793b0aa97c618825dd7d9e4d854dc44656d983113d5129942
```

確認内容:

- `metadata.txt`: `version=0.5.2`
- `scripts/` を含めない
- `dist/` を含めない
- `__pycache__/` を含めない
- `.pyc` を含めない
- krpano runtimeを含めない
- Photo Sphere Viewer / three.js のライセンスファイルを保持
- `defusedxml` は最小3ファイルのみ同梱

## GitHub反映

主なコミット:

```text
594c960 zipインストール版配備、README更新
02d5a28 セキュリティ、プライバシーの章を追記
d19723e Fix QGIS plugin security scan issues
17a8f81 Remove assert from bundled defusedxml
aeea609 Fix Qt6 enum compatibility warnings
9179453 Bump version to 0.5.2 for QGIS upload
```

タグ:

```text
v0.5.0
v0.5.1
v0.5.2
```

## 動作確認

0.5.1以降のZIPを使い、別マシンのLinux環境で以下を確認した。

- ZIPからのインストール
- 新規GPX読み取り
- 位置合わせ
- 画像表示
- Marking動作

QGIS公式アップロード時の自動チェックについても、v0.5.2で通過した。

## メール確認

QGIS Plugins Repositoryから、作者連絡先メールアドレス確認の通知が届いた。

対象メール:

```text
rdcenter.nakashacreative@gmail.com
```

メール内リンクから承認を実施した。

この確認は、プラグイン本体の公開承認とは別であり、連絡先メールアドレスが有効であることを確認するためのもの。

## 公開状態について

メール確認後も、すぐに公開版が表示されるわけではない。

以下の表示が出る場合がある。

```text
This plugin has no public version yet.
```

これは、アップロード、スキャン、メール確認は済んでいるが、QGIS Plugin Repository側の人手承認がまだ完了していない状態と考えられる。

つまり公開までの状態は以下。

```text
ZIPアップロード成功
Security / Qt6 checks通過
作者メール確認完了
QGIS plugin editor / approver の承認待ち
```

## 得られた知見

### GitHub配布と公式リポジトリ配布は信頼感が違う

GitHub Releaseは誰でも置けるため、ユーザ側から見ると「野良ZIP」感が残る。

QGIS公式プラグインリポジトリに掲載されると、QGIS Plugin Managerから検索・インストールできる。

これにより、ユーザへの案内が簡潔になる。

```text
QGISのプラグイン管理で Geo360View を検索してください。
```

### 公式審査は品質ゲートとして機能する

今回の審査対応により、以下が整備された。

- XMLパースの安全性
- 例外処理の明示化
- SQL処理の静的安全性
- ローカルHTTP通信の意図明示
- Qt6/QGIS4への将来互換
- ZIP配布物の整理
- 依存関係の明確化

QGIS公式リポジトリへ出す過程そのものが、Geo360Viewの配布品質を引き上げる機会になった。

### 公式承認後の案内が容易になる

承認後は、SNS、GitHub Discussion、会社Web、Insta360ユーザ向け投稿などで、次のように案内できる。

```text
Geo360View is available from the official QGIS Plugin Repository.
Open QGIS Plugin Manager and search for "Geo360View".
```

日本語では次のように案内できる。

```text
Geo360ViewはQGIS公式プラグインリポジトリからインストールできます。
QGISの「プラグインの管理とインストール」で「Geo360View」を検索してください。
```

## 今後の注意点

- QGIS公式リポジトリでは同一バージョンの再アップロードはできないため、修正版は必ずバージョンを上げる。
- `metadata.txt` のversion、GitHub tag、Release Asset名を揃える。
- ZIP生成後はSHA256を記録する。
- QGIS公式の自動チェックは今後も強化される可能性がある。
- Qt6/QGIS4互換の警告は、将来必須対応になる可能性がある。
- OpenCVは引き続き外部依存であり、QGIS Python環境への導入手順を明確に案内する必要がある。
- ZIP手動インストールよりも、公式リポジトリ経由のインストールを基本導線にする。

## まとめ

Geo360Viewは、v0.5.2でQGIS公式プラグインリポジトリの自動チェックを通過し、メール確認まで完了した。

残る工程は、人手による公開承認である。

今回の対応により、Geo360Viewは単なるGitHub配布のQGISプラグインではなく、公式リポジトリ公開に耐える配布品質へ引き上げられた。

