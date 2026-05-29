"""Audio/video playback helpers for the GUI preview."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import numpy as np

FrameStatus = Literal["frame", "eof", "empty"]


def playback_available() -> bool:
    """Return True when ffpyplayer is installed."""
    try:
        import ffpyplayer  # noqa: F401

        return True
    except ImportError:
        return False


def _image_to_rgb(img) -> np.ndarray:
    """Convert an ffpyplayer frame image to an RGB numpy array."""
    import cv2  # type: ignore[import-untyped]

    pixel_format = img.get_pixel_format()
    width, height = img.get_size()
    buffer = img.to_bytearray()[0]

    if pixel_format == "rgb24":
        return np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 3)

    if pixel_format == "yuv420p":
        plane = np.frombuffer(buffer, dtype=np.uint8).reshape(height * 3 // 2, width)
        return cv2.cvtColor(plane, cv2.COLOR_YUV2RGB_I420)

    if pixel_format == "yuvj420p":
        plane = np.frombuffer(buffer, dtype=np.uint8).reshape(height * 3 // 2, width)
        return cv2.cvtColor(plane, cv2.COLOR_YUV2RGB_I420)

    raise ValueError(f"Unsupported preview pixel format: {pixel_format}")


class MediaPlayback:
    """Thin wrapper around ffpyplayer for synced audio/video preview."""

    def __init__(self) -> None:
        self._player = None

    @property
    def is_open(self) -> bool:
        return self._player is not None

    def open(self, video_path: Path, start_time: float) -> None:
        """Open a file and seek to ``start_time`` seconds."""
        from ffpyplayer.player import MediaPlayer

        self.close()
        self._player = MediaPlayer(
            str(video_path),
            ff_opts={"sync": "audio"},
        )
        if start_time > 0:
            self._player.seek(start_time, relative=False)

    def close(self) -> None:
        """Stop playback and release resources."""
        if self._player is not None:
            self._player.close_player()
            self._player = None

    def poll(self) -> tuple[Optional[np.ndarray], float, FrameStatus, float]:
        """Return the next frame if one is ready, synchronized with audio.

        The fourth value is ffpyplayer's suggested realtime delay (seconds) before
        displaying the frame to maintain 1.0x playback speed.
        """
        if self._player is None:
            return None, 0.0, "empty", 0.0

        frame, val = self._player.get_frame()
        if val == "eof":
            return None, 0.0, "eof", 0.0
        if val == "paused":
            return None, 0.0, "empty", 0.0

        delay = float(val) if isinstance(val, (int, float)) else 0.0
        if frame is None:
            return None, 0.0, "empty", delay

        img, pts = frame
        return _image_to_rgb(img), float(pts), "frame", delay
