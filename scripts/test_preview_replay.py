"""Stress-test ClipPreviewPanel replay (dev only)."""

from __future__ import annotations

import subprocess
import tempfile
import time
import tkinter as tk
from pathlib import Path

import cv2
import numpy as np

from src.api.voiceover import apply_voiceover, write_voiceover_wav
from src.gui.panels.clip_preview import ClipPreviewPanel


def make_voiceover_clip() -> Path:
    ffmpeg = __import__("imageio_ffmpeg").get_ffmpeg_exe()
    tmpdir = Path(tempfile.mkdtemp())
    src = tmpdir / "src.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=d=2:size=320x240:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(src),
        ],
        check=True,
        capture_output=True,
    )
    wav = tmpdir / "w.wav"
    write_voiceover_wav(wav, (np.sin(np.linspace(0, 20, int(48000 * 2))) * 0.3).astype(np.float32))
    out = tmpdir / "vo.mp4"
    apply_voiceover(src, wav, out, "overwrite")
    return out


def main() -> None:
    out = make_voiceover_clip()
    root = tk.Tk()
    root.withdraw()
    panel = ClipPreviewPanel(root)
    cap = cv2.VideoCapture(str(out))
    panel._capture = cap
    panel._video_path = out
    panel._fps = 30.0
    panel._frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 60)
    panel._trim_start_frame = 0
    panel._current_frame = 0
    panel._audio_enabled = True

    for i in range(12):
        print(f"starting cycle {i}", flush=True)
        panel._play()
        deadline = time.time() + 8
        while panel._playing and time.time() < deadline:
            root.update()
            time.sleep(0.005)
        if panel._playing:
            print(f"timeout cycle {i}, forcing pause", flush=True)
            panel._pause()
        print(f"cycle {i} ok", flush=True)
        time.sleep(0.4)

    print("all done")
    panel._audio.stop()
    root.destroy()


if __name__ == "__main__":
    main()
