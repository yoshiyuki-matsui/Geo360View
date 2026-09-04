"""ユーザ向けメッセージのテンプレート管理。

既定localeを持ち、同じキーを持つ英語/日本語テンプレートへ差し替えられるようにする。
QGIS非依存にしておき、通常Pythonのユニットテストで文言キーとformatを検証する。
"""


DEFAULT_LOCALE = "ja"
SUPPORTED_LOCALES = ("en", "ja")


class MissingFormatValue:
    """不足したformat変数を安全に文字列化するプレースホルダ。"""

    def __init__(self, key):
        """不足した変数名を保持する。"""
        self.key = str(key)

    def __format__(self, format_spec):
        """format指定付きでも例外にせず `{key}` 形式で返す。"""
        return "{" + self.key + "}"

    def __str__(self):
        """通常の文字列化でも `{key}` 形式で返す。"""
        return "{" + self.key + "}"


class SafeFormatDict(dict):
    """不足したformat変数を例外にせず `{name}` のまま残す辞書。"""

    def __missing__(self, key):
        """テンプレート変数不足時もUI表示自体を壊さない。"""
        return MissingFormatValue(key)


MESSAGES = {
    "en": {
        "calibration_fov_set": "Calibration FOV set. fov={fov:.1f} deg.",
        "center_map_failed": "Map centering failed. Check the frame geometry. {error}",
        "click_mode_active": "Click mode started. layer={layer}",
        "click_mode_stopped": "Click mode stopped.",
        "current_viewer_fov_unavailable": "Current viewer FOV is not available. Open or move the 360Viewer first.",
        "frame_cached": "Previously extracted frame displayed. frame={frame}; elapsed={elapsed:.3f}s.",
        "frame_extract_failed": "Frame extraction failed. Check the video codec or see log file. {error}",
        "frame_number_nonnegative": "Frame number is invalid. Enter a value greater than or equal to 0.",
        "frame_read_failed": "Frame read failed. frame={frame}. Check the video file.",
        "frame_saved": "Frame saved. frame={frame}; total={total:.3f}s; path={path}",
        "images_dir_failed": "Image folder could not be created. Check output folder permission. {error}",
        "input_validation_failed": "Input validation failed. {errors}",
        "kp_match_failed": "KP matching failed. Check the KP CSV format. {error}",
        "kp_navigation_fallback_frame": "KP navigation is unavailable. Navigation mode was changed to Frame step.",
        "layer_added": "Layer added. {count} frame point(s) were created.",
        "database_loaded": "GeoPackage loaded. frame layer={frame_layer}; target layer={target_layer}; candidate layer={candidate_layer}; path={path}",
        "database_load_failed": "GeoPackage could not be loaded. {error}",
        "matched_frame_csv_missing": "Matched frame CSV was not found. Run Process with KP CSV or choose another navigation mode.",
        "no_frame_point_found": "No frame point was found. Click a Video GPX Points feature.",
        "no_kp_frame": "No {direction} KP frame is available.",
        "no_detection_frame": "No {direction} detection-candidate frame is available.",
        "no_kp_matches": "No KP matches were found within {distance:.1f} m.",
        "no_layer_frame": "No {direction} layer frame is available.",
        "no_picked_frame": "No {direction} picked-point frame is available.",
        "no_rows_layer": "No frame rows were created. Check the GPX timestamps and video duration.",
        "opencv_unavailable": "OpenCV is not available in this Python environment. {error}",
        "output_dir_failed": "Output folder could not be created. Check folder permission. {error}",
        "output_files_failed": "Output files could not be saved. Check output folder permission. {error}",
        "process_inputs_missing": "GPX file or video file is not selected. Select both files first.",
        "processing_still_running": "Processing is still running. Exit will finish after the worker stops.",
        "saved_frame_csv": "Frame CSV saved. path={path}",
        "save_generated_layers_failed": "Generated layers could not be saved. Layers were not removed. path={path}; {error}",
        "saved_navigation_json": "Navigation JSON saved. path={path}",
        "saved_viewer_matched_csv": "Viewer matched CSV saved. path={path}",
        "session_close_requested": "Session close was requested. Generated layers and viewer were cleaned up where possible.",
        "session_closed": "Session closed. Saved {saved_count} layer(s). Removed {removed_count} generated layer(s). 360Viewer process stopped.",
        "selected_layer_no_frame": "Selected layer has no frame field. Select a Video GPX Points layer.",
        "video_gpx_layer_missing": "Video GPX Points layer is not available. Run Process first.",
        "video_open_failed": "Video file could not be opened. Check the MP4 codec or OpenCV environment.",
        "video_required": "Video file is not selected. Select an MP4 file first.",
        "worker_error": "Processing failed. {error}",
    },
    "ja": {
        "calibration_fov_set": "校正FOVを設定しました。fov={fov:.1f} deg。",
        "center_map_failed": "地図中心の移動に失敗しました。フレーム地物の形状を確認してください。{error}",
        "click_mode_active": "クリックモードを開始しました。layer={layer}",
        "click_mode_stopped": "クリックモードを停止しました。",
        "current_viewer_fov_unavailable": "現在のビューアFOVを取得できません。360Viewerを開くか視点を動かしてください。",
        "frame_cached": "抽出済みフレームを表示しました。frame={frame}; elapsed={elapsed:.3f}s。",
        "frame_extract_failed": "フレーム抽出に失敗しました。動画コーデックまたはログを確認してください。{error}",
        "frame_number_nonnegative": "フレーム番号が不正です。0以上の値を入力してください。",
        "frame_read_failed": "フレームを読み込めませんでした。frame={frame}。動画ファイルを確認してください。",
        "frame_saved": "フレームを保存しました。frame={frame}; total={total:.3f}s; path={path}",
        "images_dir_failed": "画像フォルダを作成できません。出力フォルダの権限を確認してください。{error}",
        "input_validation_failed": "入力値の検証に失敗しました。{errors}",
        "kp_match_failed": "KPマッチングに失敗しました。KP CSV形式を確認してください。{error}",
        "kp_navigation_fallback_frame": "KPナビゲーションを利用できないため、Frame stepへ切り替えました。",
        "layer_added": "レイヤを追加しました。{count}件の撮影点を作成しました。",
        "database_loaded": "GeoPackageを読み込みました。撮影点={frame_layer}; path={path}",
        "database_load_failed": "GeoPackageを読み込めません。{error}",
        "matched_frame_csv_missing": "マッチ済みフレームCSVが見つかりません。KP CSV付きでProcessを実行するか、別のナビゲーションモードを選択してください。",
        "no_frame_point_found": "フレーム点が見つかりません。Video GPX Pointsの地物をクリックしてください。",
        "no_kp_frame": "{direction}方向のKPフレームがありません。",
        "no_detection_frame": "{direction}方向の検出候補フレームがありません。",
        "no_kp_matches": "{distance:.1f}m以内のKPマッチがありません。",
        "no_layer_frame": "{direction}方向のレイヤフレームがありません。",
        "no_picked_frame": "{direction}方向の保存済みクリック点フレームがありません。",
        "no_rows_layer": "フレーム行が作成されませんでした。GPX時刻と動画時間を確認してください。",
        "opencv_unavailable": "このPython環境でOpenCVを利用できません。{error}",
        "output_dir_failed": "出力フォルダを作成できません。フォルダ権限を確認してください。{error}",
        "output_files_failed": "出力ファイルを保存できません。出力フォルダの権限を確認してください。{error}",
        "process_inputs_missing": "GPXファイルまたは動画ファイルが選択されていません。両方のファイルを選択してください。",
        "processing_still_running": "処理が継続中です。worker停止後に終了処理を完了します。",
        "saved_frame_csv": "フレームCSVを保存しました。path={path}",
        "save_generated_layers_failed": "生成レイヤを保存できません。レイヤは削除しませんでした。path={path}; {error}",
        "saved_navigation_json": "ナビゲーションJSONを保存しました。path={path}",
        "saved_viewer_matched_csv": "ビューア用マッチ済みCSVを保存しました。path={path}",
        "session_close_requested": "セッション終了を要求しました。生成レイヤとビューアは可能な範囲で片付けました。",
        "session_closed": "セッションを終了しました。{saved_count}レイヤを保存し、{removed_count}件の生成レイヤを削除しました。360Viewerプロセスを停止しました。",
        "selected_layer_no_frame": "選択レイヤにframeフィールドがありません。Video GPX Pointsレイヤを選択してください。",
        "video_gpx_layer_missing": "Video GPX Pointsレイヤがありません。先にProcessを実行してください。",
        "video_open_failed": "動画ファイルを開けません。MP4コーデックまたはOpenCV環境を確認してください。",
        "video_required": "動画ファイルが選択されていません。MP4ファイルを選択してください。",
        "worker_error": "処理に失敗しました。{error}",
    },
}


UI_TEXTS = {
    "en": {
        "ui.action.exit": "Exit",
        "ui.action.open_viewer": "Open 360Viewer",
        "ui.action.start": "Control Panel",
        "ui.button.browse": "Browse",
        "ui.button.click_layer": "Camera Point",
        "ui.button.extract": "Extract",
        "ui.button.load_database": "Load",
        "ui.button.process": "Process",
        "ui.button.stop_click": "Stop Click",
        "ui.button.use_fov": "Use FOV",
        "ui.checkbox.follow": "Follow",
        "ui.checkbox.log": "Log",
        "ui.help.cal_dist": "Calibrated forward distance from the camera point at CalFOV. This is a visual calibration value, not a survey result.",
        "ui.help.cal_fov": "Reference field of view used when CalDist was calibrated. Use the current viewer FOV if the visible scene is the reference.",
        "ui.help.camera_height": "Camera height above the ground for this job. It is stored in viewer_session.json and used by the browser ground range rings.",
        "ui.help.hud_height_scale": "Visual-only multiplier applied to CamH for browser ground range rings. Use it to fit measured calibration circles without changing the physical camera height.",
        "ui.help.click_layer": "Temporarily switches the QGIS map tool to Geo360View so a camera point can be selected on the map.",
        "ui.help.database": "Loads video_gpx_points from a GeoPackage into a temporary QGIS layer for review and session backup.",
        "ui.help.extract": "Extracts only the selected frame for preview and viewer use. This is an on-demand extracted image, not the full evidence export.",
        "ui.help.follow": "Centers the QGIS map on the displayed camera point when the frame changes. The map zoom is not changed.",
        "ui.help.frame": "Video frame number. Frame numbers are immutable even when position shift or KP matching changes.",
        "ui.help.frame_shift": "Position source frame = video frame - Shift. The video frame number itself remains unchanged.",
        "ui.help.gpx": "GPX file containing timestamped track points used to interpolate camera positions.",
        "ui.help.kp": "Optional KP master CSV. When specified, frame positions are matched to the nearest KP within KP tol.",
        "ui.help.kp_tolerance": "Maximum distance for KP matching. For 10 m KP intervals, 5 m is a typical initial value.",
        "ui.help.nav_fast": "Large navigation step used by Shift + arrow keys and the double-arrow buttons.",
        "ui.help.nav_mode": "Frame step moves by frame number. Layer point moves through generated camera points. KP matched CSV moves through matched frame_index values.",
        "ui.help.nav_step": "Normal navigation step used by arrow keys and single-arrow buttons.",
        "ui.help.log": "Shows high-frequency debug messages such as frame navigation, frame extraction, and viewer access logs. Leave it off during normal navigation.",
        "ui.help.offset": "Clockwise correction for videos whose visual front is not the travel direction.",
        "ui.help.output": "Folder for frame CSV, temporary GPKG, viewer session JSON, cache, and generated image paths.",
        "ui.help.process": "Generates all frame positions from GPX and MP4, creates the QGIS layer, and writes CSV/JSON outputs.",
        "ui.help.radar_range": "Fixed map range circle radius. A second circle is drawn at twice this distance.",
        "ui.help.radar_scale": "Manual multiplier for the calibrated radar marker distance.",
        "ui.help.stop_click": "Stops Geo360View camera-point click mode and returns map-click control to other tools.",
        "ui.help.use_fov": "Sets CalFOV to the current 360Viewer FOV.",
        "ui.help.video": "Source MP4 video. The 0-based frame number is the immutable key shared by CSV, GPKG, JPEG, and viewer state.",
        "ui.label.move": "Move:",
        "ui.path.default_output": "Default output",
        "ui.path.no_database": "No GPKG",
        "ui.path.no_gpx": "No GPX",
        "ui.path.no_kp": "No KP CSV",
        "ui.path.no_video": "No video",
        "ui.preview.empty": "No frame extracted",
        "ui.preview.frame_info": "Frame {frame} {status}: {path}\n{timing}",
        "ui.preview.status.existing": "existing",
        "ui.preview.status.saved": "saved",
        "ui.preview.timing.existing": "load {elapsed:.3f}s",
        "ui.preview.title": "Preview",
        "ui.preview.unavailable": "Preview unavailable",
        "ui.status.current": "Current: {frame}",
        "ui.status.current_empty": "Current: -",
        "ui.tab.control": "Control / Preview",
        "ui.tab.load": "Load / Process",
        "ui.window.title": "Geo360View",
    },
    "ja": {
        "ui.action.exit": "終了",
        "ui.action.open_viewer": "360Viewer起動",
        "ui.action.start": "操作パネル",
        "ui.button.browse": "選択",
        "ui.button.click_layer": "撮影点選択",
        "ui.button.extract": "抽出",
        "ui.button.load_database": "読込",
        "ui.button.process": "全件処理",
        "ui.button.stop_click": "選択解除",
        "ui.button.use_fov": "FOV反映",
        "ui.checkbox.follow": "追従",
        "ui.checkbox.log": "Log",
        "ui.help.cal_dist": "CalFOV時に、視野中央の目安線を撮影点から何m先として扱うかを指定します。測量値ではなく目視校正用の距離です。",
        "ui.help.cal_fov": "CalDistを決めた時の基準FOVです。現在のビューア表示を基準にしたい場合はFOV反映を使います。",
        "ui.help.camera_height": "このジョブの地面からカメラ中心までの高さです。viewer_session.jsonへ保存し、WEBビューア上の地面範囲円に使います。",
        "ui.help.hud_height_scale": "WEBビューアの地面範囲円だけに使うCamH倍率です。物理カメラ高は変えず、実測校正円に見た目を合わせるために使います。",
        "ui.help.click_layer": "QGIS地図クリックを一時的にGeo360Viewへ切り替え、地図上の撮影点を選択できるようにします。",
        "ui.help.database": "GeoPackage内のvideo_gpx_pointsを一時QGISレイヤへ読み替え、見直しと終了時バックアップに使います。",
        "ui.help.extract": "指定フレームだけをオンデマンドで抽出し、プレビューやビューア表示に使います。全件の証跡画像出力ではありません。",
        "ui.help.follow": "フレーム変更時に、対応する撮影点をQGIS地図中心へ移動します。ズーム倍率は変えません。",
        "ui.help.frame": "動画上のフレーム番号です。位置シフトやKPマッチ後も、この番号は不変キーとして扱います。",
        "ui.help.frame_shift": "位置参照元フレーム = 動画フレーム - Shift です。動画フレーム番号自体は変更しません。",
        "ui.help.gpx": "撮影位置を補間するための時刻付きトラックポイントを含むGPXファイルです。",
        "ui.help.kp": "任意のKPマスタCSVです。指定した場合、KP tol以内の最近接KPへ撮影点をマッチングします。",
        "ui.help.kp_tolerance": "KPマッチングを許容する最大距離です。10m単位KPの場合、5m程度が初期値の目安です。",
        "ui.help.nav_fast": "Shift+矢印キーと二重矢印ボタンで使う大きな移動量です。",
        "ui.help.nav_mode": "Frame stepはフレーム番号で移動します。Layer pointは生成済み撮影点を辿ります。KP matched CSVはマッチ済みframe_indexを辿ります。",
        "ui.help.nav_step": "矢印キーと単矢印ボタンで使う通常の移動量です。",
        "ui.help.log": "フレーム移動、静止画抽出、ビューアアクセスなどの高頻度な調査用ログを表示します。通常のNav中はOFF推奨です。",
        "ui.help.offset": "動画の見た目の正面が進行方向とずれている場合の時計回り補正角です。",
        "ui.help.output": "フレームCSV、一時GPKG、viewer_session.json、cache、画像パスを保存するフォルダです。",
        "ui.help.process": "GPXとMP4から全フレーム位置を生成し、QGISレイヤ作成とCSV/JSON出力を行います。",
        "ui.help.radar_range": "地図上へ描く固定距離円の半径です。2倍距離の円も同時に描画します。",
        "ui.help.radar_scale": "校正済みレーダ距離へ掛ける手動倍率です。",
        "ui.help.stop_click": "Geo360Viewの撮影点クリックモードを解除し、地図クリック操作を他ツールへ戻します。",
        "ui.help.use_fov": "現在の360ViewerのFOVをCalFOVへ設定します。",
        "ui.help.video": "元MP4動画です。0始まりのフレーム番号をCSV、GPKG、JPEG、ビューア状態の不変キーとして扱います。",
        "ui.label.move": "移動:",
        "ui.path.default_output": "既定出力先",
        "ui.path.no_database": "GPKG未選択",
        "ui.path.no_gpx": "GPX未選択",
        "ui.path.no_kp": "KP CSV未選択",
        "ui.path.no_video": "動画未選択",
        "ui.preview.empty": "未抽出",
        "ui.preview.frame_info": "Frame {frame} {status}: {path}\n{timing}",
        "ui.preview.status.existing": "既存",
        "ui.preview.status.saved": "保存",
        "ui.preview.timing.existing": "読込 {elapsed:.3f}s",
        "ui.preview.title": "プレビュー",
        "ui.preview.unavailable": "プレビュー不可",
        "ui.status.current": "現在: {frame}",
        "ui.status.current_empty": "現在: -",
        "ui.tab.control": "操作 / プレビュー",
        "ui.tab.load": "読込 / 処理",
        "ui.window.title": "Geo360View",
    },
}


def normalize_locale(locale):
    """`ja_JP` などをサポート済みlocaleへ丸める。未対応時は既定localeを返す。"""
    if not locale:
        return DEFAULT_LOCALE
    text = str(locale).replace("-", "_").split("_", 1)[0].lower()
    if text in SUPPORTED_LOCALES:
        return text
    return DEFAULT_LOCALE


def message_text(key, locale=DEFAULT_LOCALE, **params):
    """メッセージキーとlocaleから、format済みユーザ向け文言を返す。"""
    normalized_locale = normalize_locale(locale)
    template = MESSAGES.get(normalized_locale, {}).get(key)
    if template is None:
        template = MESSAGES[DEFAULT_LOCALE].get(key, key)
    return template.format_map(SafeFormatDict(params))


def ui_text(key, locale=DEFAULT_LOCALE, **params):
    """UIラベル/tooltipキーとlocaleから、format済みUI文言を返す。"""
    normalized_locale = normalize_locale(locale)
    template = UI_TEXTS.get(normalized_locale, {}).get(key)
    if template is None:
        template = UI_TEXTS[DEFAULT_LOCALE].get(key, key)
    return template.format_map(SafeFormatDict(params))


def missing_translation_keys(locale):
    """既定メッセージ辞書に存在し、指定localeに存在しないキーを返す。"""
    normalized_locale = normalize_locale(locale)
    return sorted(set(MESSAGES[DEFAULT_LOCALE]) - set(MESSAGES.get(normalized_locale, {})))


def missing_ui_translation_keys(locale):
    """既定UI辞書に存在し、指定localeに存在しないキーを返す。"""
    normalized_locale = normalize_locale(locale)
    return sorted(set(UI_TEXTS[DEFAULT_LOCALE]) - set(UI_TEXTS.get(normalized_locale, {})))
