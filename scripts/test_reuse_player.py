"""Test pause/seek replay without destroying MediaPlayer."""

from __future__ import annotations

import subprocess
import tempfile
import time
import tkinter as tk
from pathlib import Path

import numpy as np
from ffpyplayer.player import MediaPlayer

from src.api.voiceover import apply_voiceover, write_voiceover_wav


def make_clip() -> Path:
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
    out = make_clip()
    root = tk.Tk()
    root.withdraw()
    player = MediaPlayer(str(out), ff_opts={"sync": "audio"})
    end = 60 / 30.0
    state = {"playing": False, "cycle": 0}

    def finish() -> None:
        state["playing"] = False
        try:
            player.set_pause(True)
        except Exception:
            pass
        print(f"cycle {state['cycle']} ok", flush=True)
        state["cycle"] += 1
        if state["cycle"] < 15:
            root.after(10, start)
        else:
            player.close_player()
            root.destroy()

    def tick() -> None:
        if not state["playing"]:
            return
        frame, val = player.get_frame()
        if val == "eof" or (frame is not None and frame[1] >= end - 0.05):
            finish()
            return
        delay_ms = max(1, int((float(val) if isinstance(val, (int, float)) else 0.01) * 1000))
        root.after(delay_ms, tick)

    def start() -> None:
        state["playing"] = True
        player.set_pause(False)
        player.seek(0, relative=False)
        tick()

    start()
    root.mainloop()


if __name__ == "__main__":
    main()
