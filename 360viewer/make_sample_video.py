from pathlib import Path

import cv2
import numpy as np


def main() -> None:
    out = Path("sample_videos/abc.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)

    width, height = 640, 320
    writer = cv2.VideoWriter(
        str(out),
        cv2.VideoWriter_fourcc(*"mp4v"),
        30.0,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError("failed to open VideoWriter")

    try:
        for i in range(1500):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            x = np.linspace(0, 255, width, dtype=np.uint16)
            y = np.linspace(0, 255, height, dtype=np.uint16)[:, None]
            frame[:, :, 0] = ((x[None, :] + i) % 255).astype(np.uint8)
            frame[:, :, 1] = ((y + i * 2) % 255).astype(np.uint8)
            frame[:, :, 2] = (((x[None, :] // 2) + (y // 2) + i * 3) % 255).astype(np.uint8)
            cv2.putText(
                frame,
                f"frame_index={i}",
                (28, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.line(frame, (width // 2, 0), (width // 2, height), (255, 255, 255), 1)
            cv2.line(frame, (0, height // 2), (width, height // 2), (255, 255, 255), 1)
            writer.write(frame)
    finally:
        writer.release()

    print(f"created {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
