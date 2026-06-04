"""Apply recorded voice-over audio to a clip's video file."""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Literal

import numpy as np

from src.api.errors import ProjectServiceError
from src.api.ffmpeg_util import probe_has_audio, require_ffmpeg_exe, run_ffmpeg
from src.api.video import probe_metadata

VoiceoverAudioMode = Literal["overwrite", "mix"]


def _video_duration_seconds(video_path: Path) -> float:
    metadata = probe_metadata(video_path)
    frame_count = int(metadata["duration_frames"])
    fps = float(metadata["fps"])
    if frame_count <= 0 or fps <= 0:
        return 0.0
    return frame_count / fps


def write_voiceover_wav(path: Path, samples: np.ndarray, sample_rate: int = 48000) -> None:
    """Persist mono float/int PCM samples as a 16-bit WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if samples.size == 0:
        raise ProjectServiceError("Voice-over recording is empty.")

    if samples.dtype.kind == "f":
        clipped = np.clip(samples, -1.0, 1.0)
        pcm = (clipped * 32767.0).astype(np.int16)
    else:
        pcm = samples.astype(np.int16)

    if pcm.ndim > 1:
        pcm = pcm.mean(axis=1).astype(np.int16)

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def apply_voiceover(
    video_path: Path,
    voiceover_wav: Path,
    output_path: Path,
    mode: VoiceoverAudioMode,
) -> None:
    """Mux a voice-over WAV onto a video file (replace or mix existing audio)."""
    if not video_path.is_file():
        raise ProjectServiceError(f"Video not found: {video_path}")
    if not voiceover_wav.is_file():
        raise ProjectServiceError(f"Voice-over recording not found: {voiceover_wav}")

    ffmpeg_exe = require_ffmpeg_exe()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    has_source_audio = probe_has_audio(ffmpeg_exe, video_path)
    video_encode = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast"]
    audio_encode = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]

    if mode == "overwrite" or not has_source_audio:
        duration_s = _video_duration_seconds(video_path)
        if duration_s > 0:
            audio_filter = (
                f"[1:a]aresample=48000,atrim=0:{duration_s},"
                f"apad=whole_dur={duration_s},asetpts=PTS-STARTPTS[aout]"
            )
            run_ffmpeg(
                ffmpeg_exe,
                [
                    "-y",
                    "-i",
                    str(video_path),
                    "-i",
                    str(voiceover_wav),
                    "-filter_complex",
                    audio_filter,
                    "-map",
                    "0:v:0",
                    "-map",
                    "[aout]",
                    *video_encode,
                    *audio_encode,
                    "-t",
                    str(duration_s),
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ],
                error_context="Failed to replace clip audio with voice-over",
            )
        else:
            run_ffmpeg(
                ffmpeg_exe,
                [
                    "-y",
                    "-i",
                    str(video_path),
                    "-i",
                    str(voiceover_wav),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    *video_encode,
                    *audio_encode,
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ],
                error_context="Failed to replace clip audio with voice-over",
            )
        return

    run_ffmpeg(
        ffmpeg_exe,
        [
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(voiceover_wav),
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0[aout]",
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            *video_encode,
            *audio_encode,
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        error_context="Failed to mix voice-over with clip audio",
    )


def clip_playback_duration_seconds(video_path: Path, resource_fps: float) -> float:
    """Estimate clip length in seconds for recording alignment."""
    metadata = probe_metadata(video_path)
    frame_count = int(metadata["duration_frames"])
    fps = float(metadata["fps"]) if float(metadata["fps"]) > 0 else resource_fps
    if frame_count <= 0:
        return 0.0
    return frame_count / max(fps, 0.001)
