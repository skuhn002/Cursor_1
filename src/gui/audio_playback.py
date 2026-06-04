"""Stable audio preview via ffmpeg decode and sounddevice output."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import numpy as np

from src.api.errors import ProjectServiceError
from src.api.ffmpeg_util import require_ffmpeg_exe

DEFAULT_SAMPLE_RATE = 48_000
_CHUNK_SAMPLES = 2048


def audio_playback_available() -> bool:
    try:
        import sounddevice  # noqa: F401

        return True
    except ImportError:
        return False


class FfmpegAudioPlayback:
    """Play a media file's audio track without ffpyplayer (Windows-safe)."""

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def start(self, media_path: Path, start_time: float = 0.0) -> None:
        """Decode audio from ``media_path`` starting at ``start_time`` seconds."""
        if not audio_playback_available():
            raise ProjectServiceError(
                "Audio preview requires sounddevice. Install it with: pip install sounddevice"
            )

        self.stop()
        ffmpeg = require_ffmpeg_exe()
        command = [
            ffmpeg,
            "-loglevel",
            "quiet",
            "-ss",
            str(max(0.0, start_time)),
            "-i",
            str(media_path.resolve()),
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            str(self._sample_rate),
            "-vn",
            "pipe:1",
        ]

        with self._lock:
            self._stop.clear()
            try:
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                raise ProjectServiceError(f"Unable to start audio preview: {exc}") from exc
            self._thread = threading.Thread(
                target=self._play_stdout,
                name="moment-audio-preview",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            process = self._process
            self._process = None
            thread = self._thread
            self._thread = None

        if process is not None:
            try:
                if process.stdout is not None:
                    process.stdout.close()
            except OSError:
                pass
            try:
                process.terminate()
                process.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass

        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _play_stdout(self) -> None:
        import sounddevice as sd

        process = self._process
        if process is None or process.stdout is None:
            return

        byte_count = _CHUNK_SAMPLES * 4
        try:
            with sd.OutputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="float32",
            ) as stream:
                while not self._stop.is_set():
                    chunk = process.stdout.read(byte_count)
                    if not chunk:
                        break
                    samples = np.frombuffer(chunk, dtype=np.float32)
                    if samples.size == 0:
                        continue
                    stream.write(samples.reshape(-1, 1))
        except Exception:
            pass
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
            if process is not None:
                try:
                    process.terminate()
                    process.wait(timeout=0.5)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                    except OSError:
                        pass
