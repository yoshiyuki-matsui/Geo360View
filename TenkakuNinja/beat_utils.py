"""
beat_utils.py

音声信号からビート（同期信号）を検出し、映像フレームとの時刻同期を行うユーティリティモジュール。

主な機能:
- WAVファイルから短時間エネルギーを用いたビート検出
- 最初のビート時刻の抽出
- 映像ファイルからFPSを取得（ffprobe使用）
- 秒数からフレーム番号への変換（ドロップフレーム対応）

使用例:
>>> t = detect_first_beat("expanded.wav")
>>> frame = time_to_frame(t, fps=29.97)
"""
import numpy as np
import subprocess

def get_fps_from_video(video_path):
    """
    映像ファイルから平均フレームレート（FPS）を取得する。

    Args:
        video_path (str or Path): 入力動画ファイルのパス

    Returns:
        float: 平均フレームレート（例: 29.97）
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    rate = result.stdout.strip()
    if "/" in rate:
        num, denom = map(int, rate.split("/"))
        return num / denom
    return float(rate)

@timed("[解析] ビート検出")
def analyze_beat(wavpath, verbose=False):
    """
    WAVファイルから短時間エネルギーを用いてビートを検出し、統計情報を返す。

    Args:
        wavpath (str or Path): 入力WAVファイル
        verbose (bool): デバッグ出力を有効にするか

    Returns:
        dict: {
            "first_beat_time": 最初のビート時刻（秒）,
            "beat_count": 検出されたビート数,
            "beat_intervals": 各種統計量（mean, median, min, max, std）
        }
    """
    show_progress("ビート解析中")

    y, sr = sf.read(wavpath)
    if y.ndim == 2:
        y = y.mean(axis=1)

    # 短時間エネルギー
    frame_size = int(0.02 * sr)  # 20ms
    hop_size = int(0.01 * sr)    # 10ms
    energy = np.array([
        np.sum(y[i:i+frame_size]**2)
        for i in range(0, len(y) - frame_size, hop_size)
    ])

    # ピーク検出
    peaks, _ = find_peaks(energy, height=np.max(energy) * 0.3, distance=sr * 0.2 * 0.5)
    times = np.array(peaks) * hop_size / sr

    if len(times) < 2:
        print("[WARN] ビートが十分に検出できませんでした。")
        return {
            "first_beat_time": None,
            "beat_count": 0,
            "beat_intervals": {}
        }

    intervals = np.diff(times)
    stats = {
        "mean": np.mean(intervals),
        "median": np.median(intervals),
        "min": np.min(intervals),
        "max": np.max(intervals),
        "std": np.std(intervals)
    }

    if verbose:
        print(f"[DEBUG] 検出されたビート時刻: {times}")
        print(f"[DEBUG] ビート間隔: {intervals}")

    return {
        "first_beat_time": float(times[0]),
        "beat_count": len(times),
        "beat_intervals": stats
    }

#1秒窓ベースの語り検出
@timed("[解析] ビート検出（統計評価付き）")
def analyze_beat2(wavpath, verbose=False):
    """
    1秒窓ごとのエネルギー立ち上がりから、同期に使えそうな最初のビートを推定する。

    単純なピーク検出だけではノイズを拾う場合があるため、1秒間隔で続く候補を優先する。
    現在のGeo360View本体では未使用だが、音声同期方式を戻す場合の候補処理として残す。
    """
    import numpy as np
    import soundfile as sf

    y, sr = sf.read(wavpath)
    if y.ndim == 2:
        y = y.mean(axis=1)

    window_size = sr  # 1秒
    hop_size = int(0.01 * sr)  # 10ms
    frame_size = int(0.02 * sr)  # 20ms
    num_windows = len(y) // window_size

    beat_candidates = []

    for i in range(num_windows):
        start = i * window_size
        end = start + window_size
        segment = y[start:end]

        energy = np.array([
            np.sum(segment[j:j+frame_size]**2)
            for j in range(0, len(segment) - frame_size, hop_size)
        ])

        delta = np.diff(energy)
        threshold = np.max(delta) * 0.5
        rise_indices = np.where(delta > threshold)[0]

        if rise_indices.size > 0:
            idx = rise_indices[0]
            strength = delta[idx]
            # 経験的な強度しきい値。小さな環境音ではなく同期音らしい立ち上がりを拾う。
            if strength >= 10.0:  # ← 語る資格の閾値
                beat_time = (start + idx * hop_size) / sr
                beat_candidates.append((beat_time, strength))
                if verbose:
                    print(f"[DEBUG] 窓 {i}: 立ち上がり検出 at {beat_time:.3f}s (strength={strength:.2f})")


    if len(beat_candidates) < 2:
        print("[WARN] 有効なビート候補が不足しています。")
        return {
            "first_beat_time": None,
            "beat_count": len(beat_candidates),
            "beat_intervals": {}
        }

    # 次のピークとの間隔を評価
    beat_times = [t for t, _ in beat_candidates]
    intervals = np.diff(beat_times)
    stats = {
        "mean": np.mean(intervals),
        "median": np.median(intervals),
        "min": np.min(intervals),
        "max": np.max(intervals),
        "std": np.std(intervals)
    }

    # 「次のピークとの間隔が約1秒」のものを抽出（±0.1秒許容）
    bingo_candidates = []
    for i in range(len(intervals)):
        if abs(intervals[i] - 1.0) < 0.1:
            t1, s1 = beat_candidates[i]
            t2, s2 = beat_candidates[i + 1]
            if s1 > 0 and s2 > 0:  # または s1+s2 > threshold
                avg_strength = (s1 + s2) / 2
                bingo_candidates.append((t1, avg_strength))

    # 1秒間隔ペアのうち最初のもの
    if bingo_candidates:
        bingo_candidates.sort(key=lambda x: x[0])  # 時間昇順
        first_beat_time = bingo_candidates[0][0]
        print(f"[INFO] 強度付き1秒ペアから選定: {first_beat_time:.3f}s (strength={bingo_candidates[0][1]:.2f})")
        
    else:
        max_strength = max(b[1] for b in beat_candidates)
        threshold = max_strength * 0.5
        print(f"[TRACE] 最大強度: {max_strength:.2f}, 閾値: {threshold:.2f}")

        valid_candidates = [b for b in beat_candidates if b[1] >= threshold]
        if valid_candidates:
            first_beat_time = valid_candidates[0][0]
            print(f"[INFO] 閾値超え候補から選定: {first_beat_time:.3f}s (strength={valid_candidates[0][1]:.2f})")
        else:
            first_beat_time = beat_candidates[0][0]
            print(f"[INFO] fallback: {first_beat_time:.3f}s")

    return {
        "first_beat_time": float(first_beat_time),
        "beat_count": len(beat_candidates),
        "beat_intervals": stats
    }


def detect_first_beat(wavpath, verbose=False) -> float:
    """
    WAVファイルから最初のビート時刻（秒）を検出する。

    Args:
        wavpath (str or Path): 入力WAVファイル
        verbose (bool): デバッグ出力を有効にするか

    Returns:
        float: 最初のビート時刻（秒）

    Raises:
        ValueError: ビートが検出できなかった場合
    """
    result = analyze_beat2(wavpath, verbose=verbose)
    if result["first_beat_time"] is None:
        raise ValueError("ビートが検出できませんでした")
    print(f"first_beat_time:{result['first_beat_time']}")
    return result["first_beat_time"]   

#ドロップフレームを処理すべきFPSかどうか
def is_drop_frame_fps(fps):
    """
    指定されたFPSがドロップフレーム対象かどうかを判定する。

    Args:
        fps (float): フレームレート（例: 29.97）

    Returns:
        bool: ドロップフレーム対象なら True
    """
    return abs(fps - 29.97) < 0.01 or abs(fps - 59.94) < 0.01


#時刻からフレーム番号を取得する（ドロップフレーム処理対応）
from decimal import Decimal, ROUND_HALF_UP
def time_to_frame(seconds, fps, drop_frame=None, rounding="round"):
    """
    秒数からフレーム番号を計算（ドロップフレーム対応）

    Parameters:
        seconds (float): 秒数
        fps (float): 実際のフレームレート（例：29.97）
        drop_frame (bool or None): True=補正あり, False=なし, None=自動判定
        rounding (str): "round", "floor", "ceil"

    Returns:
        int: フレーム番号
    """
    if drop_frame is None:
        drop_frame = is_drop_frame_fps(fps)

    total_frames = Decimal(seconds) * Decimal(str(fps))

    if drop_frame:
        skip = 2 if abs(fps - 29.97) < 0.01 else 4
        minutes = int(seconds // 60)
        dropped = skip * (minutes - minutes // 10)
        total_frames += dropped

    if rounding == "round":
        return int(total_frames.to_integral_value(rounding=ROUND_HALF_UP))
    elif rounding == "floor":
        return int(total_frames.to_integral_value(rounding="ROUND_FLOOR"))
    elif rounding == "ceil":
        return int(total_frames.to_integral_value(rounding="ROUND_CEILING"))
    else:
        raise ValueError("Invalid rounding mode")
