"""Stress-test ffpyplayer replay under tkinter (dev only)."""

from __future__ import annotations

import subprocess
import tempfile
import time
import tkinter as tk
from pathlib import Path

import cv2
import numpy as np
from ffpyplayer.player import MediaPlayer

from src.api.voiceover import apply_voiceover, write_voiceover_wav


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
    cap = cv2.VideoCapture(str(out))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 60)
    fps = 30.0
    clip_end = frame_count / fps

    state = {"playing": False, "player": None, "cycle": 0}

    def finish_cycle() -> None:
        player = state["player"]
        if player is not None:
            try:
                player.set_pause(True)
            except Exception:
                pass
            try:
                player.close_player()
            except Exception:
                pass
            state["player"] = None
            time.sleep(0.25)
        state["playing"] = False
        print(f"cycle {state['cycle']} ok")
        state["cycle"] += 1
        if state["cycle"] < 12:
            root.after(50, start_cycle)
        else:
            print("all done")
            root.destroy()

    def tick() -> None:
        if not state["playing"]:
            return
        player = state["player"]
        if player is None:
            return
        frame, val = player.get_frame()
        if val == "eof":
            finish_cycle()
            return
        if frame is not None and frame[1] >= clip_end - (0.5 / fps):
            finish_cycle()
            return
        delay_ms = max(1, int((float(val) if isinstance(val, (int, float)) else 0.01) * 1000))
        root.after(delay_ms, tick)

    def start_cycle() -> None:
        state["playing"] = True
        state["player"] = MediaPlayer(str(out), ff_opts={"sync": "audio"})
        tick()

    start_cycle()
    root.mainloop()


if __name__ == "__main__":
    main()
