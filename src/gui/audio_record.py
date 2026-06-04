"""Microphone capture for clip voice-over."""

from __future__ import annotations

import threading
from typing import Callable, Optional

import numpy as np

from src.api.errors import ProjectServiceError

DEFAULT_SAMPLE_RATE = 48_000


def recording_available() -> bool:
    try:
        import sounddevice  # noqa: F401

        return True
    except ImportError:
        return False


def duration_to_sample_count(duration_seconds: float, sample_rate: int = DEFAULT_SAMPLE_RATE) -> int:
    """Convert a clip duration to the number of PCM samples to capture."""
    if duration_seconds <= 0:
        return 0
    return max(1, int(round(duration_seconds * sample_rate)))


class AudioRecorder:
    """Capture mono PCM audio from the default input device."""

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._active = False
        self._auto_stop_timer: Optional[threading.Timer] = None
        self._max_samples: Optional[int] = None
        self._on_auto_stop: Optional[Callable[[], None]] = None
        self._auto_stop_handled = False

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def start(self, *, max_duration_seconds: Optional[float] = None) -> None:
        """Begin capture; optionally stop automatically after ``max_duration_seconds``."""
        if self._active:
            return
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise ProjectServiceError(
                "Voice-over recording requires sounddevice. "
                "Install it with: pip install sounddevice"
            ) from exc

        self._chunks = []
        self._max_samples = (
            duration_to_sample_count(max_duration_seconds, self._sample_rate)
            if max_duration_seconds is not None and max_duration_seconds > 0
            else None
        )
        self._auto_stop_handled = False

        def callback(indata, _frames, _time, status) -> None:
            if not self._active:
                return
            if status:
                pass
            self._chunks.append(indata.copy())
            if self._max_samples is not None:
                total = sum(chunk.size for chunk in self._chunks)
                if total >= self._max_samples:
                    self._request_auto_stop()

        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            callback=callback,
        )
        self._stream.start()
        self._active = True

        if max_duration_seconds is not None and max_duration_seconds > 0:
            self._auto_stop_timer = threading.Timer(
                max_duration_seconds,
                self._request_auto_stop,
            )
            self._auto_stop_timer.daemon = True
            self._auto_stop_timer.start()

    def _request_auto_stop(self) -> None:
        """Called from the audio thread or timer when capture should end."""
        if not self._active or self._auto_stop_handled:
            return
        self._auto_stop_handled = True
        if self._on_auto_stop is not None:
            self._on_auto_stop()

    def set_on_auto_stop(self, callback: Optional[Callable[[], None]]) -> None:
        """Register a callback invoked when the clip duration elapses."""
        self._on_auto_stop = callback

    def stop(self, *, max_samples: Optional[int] = None) -> np.ndarray:
        """Stop capture and return samples, optionally trimmed to ``max_samples``."""
        self._cancel_auto_stop_timer()
        if not self._active or self._stream is None:
            return np.array([], dtype=np.float32)

        self._active = False
        self._stream.stop()
        self._stream.close()
        self._stream = None

        if not self._chunks:
            return np.array([], dtype=np.float32)

        samples = np.concatenate(self._chunks, axis=0).reshape(-1)
        limit = max_samples if max_samples is not None else self._max_samples
        if limit is not None and samples.size > limit:
            samples = samples[:limit]
        return samples

    def _cancel_auto_stop_timer(self) -> None:
        if self._auto_stop_timer is not None:
            self._auto_stop_timer.cancel()
            self._auto_stop_timer = None

    def is_recording(self) -> bool:
        return self._active
