"""Compare raw OpenCV seeking with FFmpeg 6 decoder thread counts on Linux.

This standalone diagnostic does not load QGIS or change its installation.
Only child processes receive the diagnostic LD_PRELOAD library.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def probe(video, frame_index, output):
    import cv2

    report = {"opencv": cv2.__version__, "cv2_path": cv2.__file__,
              "cpus": os.sysconf("SC_NPROCESSORS_ONLN"),
              "requested_threads": os.environ.get("GEO360_PROBE_THREADS", "default"),
              "frame": frame_index}
    start = time.perf_counter()
    cap = cv2.VideoCapture(str(video), cv2.CAP_FFMPEG)
    report["open_seconds"] = time.perf_counter() - start
    try:
        report["opened"] = cap.isOpened()
        if not cap.isOpened():
            return report
        report["backend"] = cap.getBackendName()
        report["frame_count"] = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        start = time.perf_counter()
        report["seek"] = cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        report["seek_seconds"] = time.perf_counter() - start
        report["before"] = cap.get(cv2.CAP_PROP_POS_FRAMES)
        start = time.perf_counter()
        ok, image = cap.read()
        report["read_seconds"] = time.perf_counter() - start
        report["read"] = bool(ok and image is not None)
        report["after"] = cap.get(cv2.CAP_PROP_POS_FRAMES)
        if ok and image is not None:
            height, width = image.shape[:2]
            if width > 1536:
                image = cv2.resize(image, (1536, max(1, round(height * 1536 / width))))
            # Each invocation has its own fresh output directory. This image
            # is diagnostic evidence, even when seek positions are invalid.
            image_path = output / (str(report["requested_threads"]) + ".jpg")
            report["image_saved"] = bool(cv2.imwrite(str(image_path), image))
            report["image_path"] = str(image_path)
    finally:
        cap.release()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--frame", type=int, default=9571)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("This diagnostic is for Linux / FFmpeg 6 only")
    if not args.video.is_file() or args.frame < 0:
        parser.error("An existing video and a nonnegative frame are required")
    if args.child:
        print(json.dumps(probe(args.video, args.frame, args.output), ensure_ascii=False), flush=True)
        return
    compiler = shutil.which("cc") or shutil.which("gcc")
    if not compiler:
        parser.error("A C compiler (cc or gcc) is needed for this temporary diagnostic")
    if os.environ.get("LD_PRELOAD"):
        parser.error("Run from a terminal without LD_PRELOAD to keep the comparison controlled")
    output = Path(tempfile.mkdtemp(prefix="geo360-threads-"))
    library = output / "video_threads_probe.so"
    source = Path(__file__).with_name("video_threads_probe.c")
    subprocess.run([compiler, "-shared", "-fPIC", "-O2", "-Wall", "-Wextra",
                    str(source), "-o", str(library), "-ldl"], check=True, timeout=60)
    print(f"Diagnostic files: {output}", flush=True)
    log_path = output / "results.txt"
    with log_path.open("w", encoding="utf-8") as log:
        for threads in (None, 8, 16, 20):
            environment = dict(os.environ)
            environment.pop("GEO360_PROBE_THREADS", None)
            if threads is not None:
                environment["LD_PRELOAD"] = str(library)
                environment["GEO360_PROBE_THREADS"] = str(threads)
            command = [sys.executable, str(Path(__file__).resolve()), str(args.video.resolve()),
                       "--frame", str(args.frame), "--child", "--output", str(output)]
            print(f"Testing threads={threads or 'default'}", flush=True)
            try:
                result = subprocess.run(command, env=environment, capture_output=True,
                                        text=True, timeout=120, check=False)
                text = (f"threads={threads or 'default'} exit={result.returncode}\n"
                        f"{result.stdout}{result.stderr}")
            except subprocess.TimeoutExpired:
                text = f"threads={threads or 'default'} timed out after 120 seconds\n"
            print(text, flush=True)
            log.write(text + "\n")
            log.flush()
    print(f"Results: {log_path}", flush=True)


if __name__ == "__main__":
    main()
