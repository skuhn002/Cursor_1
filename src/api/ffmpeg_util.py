"""Locate ffmpeg and run small probe/encode helpers."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from src.api.errors import ProjectServiceError


def resolve_ffmpeg_exe() -> Optional[str]:
    """Return an ffmpeg executable path, or None if none is available."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def resolve_ffprobe_exe() -> Optional[str]:
    """Return ffprobe path, often beside the resolved ffmpeg binary."""
    found = shutil.which("ffprobe")
    if found:
        return found
    ffmpeg = resolve_ffmpeg_exe()
    if ffmpeg is None:
        return None
    name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    sibling = Path(ffmpeg).with_name(name)
    return str(sibling) if sibling.is_file() else None


def parse_frame_rate(value: str) -> float:
    """Parse ffprobe frame-rate strings such as ``30000/1001`` or ``30``."""
    if not value or value in ("0/0", "N/A", "0"):
        return 0.0
    if "/" in value:
        num, den = value.split("/", 1)
        denominator = float(den)
        return float(num) / denominator if denominator else 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def ffmpeg_stderr_metadata(
    ffmpeg_exe: str, media_path: Path
) -> Optional[dict[str, float | int]]:
    """Parse duration and fps from ``ffmpeg -i`` stderr when ffprobe is unavailable."""
    if not media_path.is_file():
        return None

    completed = subprocess.run(
        [ffmpeg_exe, "-hide_banner", "-i", str(media_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    combined = (completed.stdout or "") + (completed.stderr or "")

    fps_match = re.search(r"(\d+(?:\.\d+)?)\s+fps", combined)
    fps = float(fps_match.group(1)) if fps_match else 0.0

    duration_match = re.search(
        r"Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", combined
    )
    duration_s = 0.0
    if duration_match:
        hours, minutes, seconds = duration_match.groups()
        duration_s = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    if fps <= 0 and duration_s <= 0:
        return None

    duration_frames = int(round(duration_s * fps)) if duration_s > 0 and fps > 0 else 0
    return {
        "duration_frames": duration_frames,
        "fps": fps if fps > 0 else 30.0,
        "width": 0,
        "height": 0,
    }


def ffprobe_media_metadata(media_path: Path) -> Optional[dict[str, float | int]]:
    """Read fps, frame count, and dimensions via ffprobe (preferred over OpenCV)."""
    ffprobe = resolve_ffprobe_exe()
    if ffprobe is None or not media_path.is_file():
        return None

    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate,r_frame_rate,nb_frames,duration,width,height",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(media_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None

    try:
        payload: dict[str, Any] = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None

    streams = payload.get("streams") or []
    if not streams:
        return None
    stream = streams[0]

    fps = parse_frame_rate(str(stream.get("avg_frame_rate") or ""))
    if fps <= 0:
        fps = parse_frame_rate(str(stream.get("r_frame_rate") or ""))

    duration_s = 0.0
    if stream.get("duration") not in (None, "N/A"):
        try:
            duration_s = float(stream["duration"])
        except (TypeError, ValueError):
            duration_s = 0.0
    if duration_s <= 0:
        format_block = payload.get("format") or {}
        if format_block.get("duration") not in (None, "N/A"):
            try:
                duration_s = float(format_block["duration"])
            except (TypeError, ValueError):
                duration_s = 0.0

    nb_frames = 0
    if stream.get("nb_frames") not in (None, "N/A"):
        try:
            nb_frames = int(stream["nb_frames"])
        except (TypeError, ValueError):
            nb_frames = 0
    if nb_frames <= 0 and duration_s > 0 and fps > 0:
        nb_frames = int(round(duration_s * fps))

    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)

    if fps <= 0 and nb_frames <= 0:
        return None

    return {
        "duration_frames": nb_frames,
        "fps": fps if fps > 0 else 30.0,
        "width": width,
        "height": height,
    }


def require_ffmpeg_exe() -> str:
    """Return ffmpeg path or raise a clear install hint."""
    exe = resolve_ffmpeg_exe()
    if exe:
        return exe
    raise ProjectServiceError(
        "Merging composition clips with audio requires ffmpeg. "
        "Install ffmpeg on your PATH, or install imageio-ffmpeg "
        "(pip install imageio-ffmpeg)."
    )


def probe_has_audio(ffmpeg_exe: str, media_path: Path) -> bool:
    """Return True if the file exposes at least one audio stream."""
    result = subprocess.run(
        [ffmpeg_exe, "-hide_banner", "-i", str(media_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    return "Audio:" in combined


def run_ffmpeg(
    ffmpeg_exe: str,
    args: list[str],
    *,
    error_context: str,
) -> None:
    """Run ffmpeg with the given arguments; raise ProjectServiceError on failure."""
    completed = subprocess.run(
        [ffmpeg_exe, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        if len(detail) > 800:
            detail = detail[-800:]
        raise ProjectServiceError(
            f"{error_context}: ffmpeg failed (exit {completed.returncode}). {detail}"
        )
