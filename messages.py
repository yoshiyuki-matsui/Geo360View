"""ユーザ向けメッセージのテンプレート管理。

英語を既定値とし、同じキーを持つ日本語テンプレートへ差し替えられるようにする。
QGIS非依存にしておき、通常Pythonのユニットテストで文言キーとformatを検証する。
"""


DEFAULT_LOCALE = "en"
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
        "frame_cached": "Frame loaded from cache. frame={frame}; elapsed={elapsed:.3f}s.",
        "frame_extract_failed": "Frame extraction failed. Check the video codec or see log file. {error}",
        "frame_number_nonnegative": "Frame number is invalid. Enter a value greater than or equal to 0.",
        "frame_read_failed": "Frame read failed. frame={frame}. Check the video file.",
        "frame_saved": "Frame saved. frame={frame}; total={total:.3f}s; path={path}",
        "images_dir_failed": "Image folder could not be created. Check output folder permission. {error}",
        "input_validation_failed": "Input validation failed. {errors}",
        "kp_match_failed": "KP matching failed. Check the KP CSV format. {error}",
        "layer_added": "Layer added. {count} frame point(s) were created.",
        "matched_frame_csv_missing": "Matched frame CSV was not found. Run Process with KP CSV or choose another navigation mode.",
        "no_frame_point_found": "No frame point was found. Click a Video GPX Points feature.",
        "no_kp_frame": "No {direction} KP frame is available.",
        "no_kp_matches": "No KP matches were found within {distance:.1f} m.",
        "no_layer_frame": "No {direction} layer frame is available.",
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
        "frame_cached": "キャッシュ済みフレームを表示しました。frame={frame}; elapsed={elapsed:.3f}s。",
        "frame_extract_failed": "フレーム抽出に失敗しました。動画コーデックまたはログを確認してください。{error}",
        "frame_number_nonnegative": "フレーム番号が不正です。0以上の値を入力してください。",
        "frame_read_failed": "フレームを読み込めませんでした。frame={frame}。動画ファイルを確認してください。",
        "frame_saved": "フレームを保存しました。frame={frame}; total={total:.3f}s; path={path}",
        "images_dir_failed": "画像フォルダを作成できません。出力フォルダの権限を確認してください。{error}",
        "input_validation_failed": "入力値の検証に失敗しました。{errors}",
        "kp_match_failed": "KPマッチングに失敗しました。KP CSV形式を確認してください。{error}",
        "layer_added": "レイヤを追加しました。{count}件の撮影点を作成しました。",
        "matched_frame_csv_missing": "マッチ済みフレームCSVが見つかりません。KP CSV付きでProcessを実行するか、別のナビゲーションモードを選択してください。",
        "no_frame_point_found": "フレーム点が見つかりません。Video GPX Pointsの地物をクリックしてください。",
        "no_kp_frame": "{direction}方向のKPフレームがありません。",
        "no_kp_matches": "{distance:.1f}m以内のKPマッチがありません。",
        "no_layer_frame": "{direction}方向のレイヤフレームがありません。",
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


def normalize_locale(locale):
    """`ja_JP` などをサポート済みlocaleへ丸める。既定は英語。"""
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


def missing_translation_keys(locale):
    """既定英語に存在し、指定localeに存在しないキーを返す。"""
    normalized_locale = normalize_locale(locale)
    return sorted(set(MESSAGES[DEFAULT_LOCALE]) - set(MESSAGES.get(normalized_locale, {})))
