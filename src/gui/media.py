"""Audio/video playback helpers for the GUI preview."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Literal, Optional

import numpy as np

FrameStatus = Literal["frame", "eof", "empty"]

# ffpyplayer/SDL needs time to stop audio before close_player on Windows.
_CLOSE_SETTLE_SECONDS = 0.25


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
        self._path: Optional[str] = None
        self._lock = threading.RLock()
        self._close_ready = threading.Event()
        self._close_ready.set()
        self._generation = 0

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._player is not None

    def open(self, video_path: Path, start_time: float) -> None:
        """Open a file and seek to ``start_time`` seconds."""
        from ffpyplayer.player import MediaPlayer

        self._wait_for_close()
        path_str = str(video_path.resolve())

        with self._lock:
            self._release_player_unlocked(blocking=True)
            self._generation += 1
            self._player = MediaPlayer(
                path_str,
                ff_opts={"sync": "audio", "loglevel": "quiet"},
            )
            self._path = path_str
            if start_time > 0:
                self._player.seek(start_time, relative=False)

    def close(self) -> None:
        """Stop playback and release resources on a worker thread."""
        with self._lock:
            if self._player is None:
                self._close_ready.set()
                return
            player = self._player
            self._player = None
            self._path = None
            self._generation += 1
            self._close_ready.clear()

        threading.Thread(
            target=self._release_player_worker,
            args=(player,),
            name="moment-media-close",
            daemon=True,
        ).start()

    def close_sync(self) -> None:
        """Block until playback resources are fully released."""
        with self._lock:
            player = self._player
            self._player = None
            self._path = None
            self._generation += 1
        if player is not None:
            self._release_player_worker(player)
        self._close_ready.set()

    def _wait_for_close(self) -> None:
        if not self._close_ready.wait(timeout=5.0):
            self._close_ready.set()

    def _release_player_unlocked(self, *, blocking: bool) -> None:
        player = self._player
        self._player = None
        self._path = None
        if player is None:
            return
        self._generation += 1
        if blocking:
            self._release_player_worker(player)
        else:
            threading.Thread(
                target=self._release_player_worker,
                args=(player,),
                name="moment-media-close",
                daemon=True,
            ).start()

    def _release_player_worker(self, player) -> None:
        try:
            try:
                player.set_pause(True)
            except Exception:
                pass

            deadline = time.time() + 0.75
            while time.time() < deadline:
                try:
                    _frame, val = player.get_frame()
                except Exception:
                    break
                if val == "eof":
                    break
                time.sleep(0.01)

            try:
                player.close_player()
            except Exception:
                pass
        finally:
            time.sleep(_CLOSE_SETTLE_SECONDS)
            self._close_ready.set()

    def poll(self) -> tuple[Optional[np.ndarray], float, FrameStatus, float]:
        """Return the next frame if one is ready, synchronized with audio."""
        with self._lock:
            player = self._player
            generation = self._generation
        if player is None:
            return None, 0.0, "empty", 0.0

        try:
            frame, val = player.get_frame()
        except Exception:
            return None, 0.0, "eof", 0.0

        with self._lock:
            if self._player is not player or self._generation != generation:
                return None, 0.0, "eof", 0.0

        if val == "eof":
            return None, 0.0, "eof", 0.0
        if val == "paused":
            return None, 0.0, "empty", 0.0

        delay = float(val) if isinstance(val, (int, float)) else 0.0
        if frame is None:
            return None, 0.0, "empty", delay

        img, pts = frame
        return _image_to_rgb(img), float(pts), "frame", delay
