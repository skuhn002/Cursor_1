"""OpenCV-backed video probing, thumbnails, cropping, and image clips."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.api.errors import ProjectServiceError
from src.api.ffmpeg_util import (
    ffmpeg_stderr_metadata,
    ffprobe_media_metadata,
    probe_has_audio,
    require_ffmpeg_exe,
    resolve_ffmpeg_exe,
    run_ffmpeg,
)
from src.models import Clip

IMAGE_CLIP_FRAME_COUNT = 30
IMAGE_CLIP_FPS = 30.0


def probe_metadata(video_path: Path) -> dict[str, float | int]:
    """Read frame count, FPS, and dimensions (ffmpeg/ffprobe preferred, else OpenCV)."""
    probed = ffprobe_media_metadata(video_path)
    if probed is None or int(probed.get("duration_frames", 0) or 0) <= 0:
        try:
            ffmpeg_exe = require_ffmpeg_exe()
            probed = ffmpeg_stderr_metadata(ffmpeg_exe, video_path)
        except ProjectServiceError:
            probed = None
    if probed is not None and int(probed.get("duration_frames", 0) or 0) > 0:
        opencv_meta = probe_metadata_opencv(video_path)
        if int(opencv_meta.get("width", 0) or 0) > 0:
            probed["width"] = int(opencv_meta["width"])
        if int(opencv_meta.get("height", 0) or 0) > 0:
            probed["height"] = int(opencv_meta["height"])
        return probed
    return probe_metadata_opencv(video_path)


def probe_metadata_opencv(video_path: Path) -> dict[str, float | int]:
    """Read frame count, FPS, and dimensions using OpenCV (fallback)."""
    defaults: dict[str, float | int] = {
        "duration_frames": 0,
        "fps": 30.0,
        "width": 0,
        "height": 0,
    }
    try:
        import cv2  # type: ignore[import-untyped]
    except ImportError:
        return defaults

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return defaults

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    capture.release()

    return {
        "duration_frames": frame_count,
        "fps": fps if fps > 0 else 30.0,
        "width": width,
        "height": height,
    }


def count_decodable_frames(
    video_path: Path,
    *,
    start_frame: int = 0,
    max_frames: Optional[int] = None,
) -> int:
    """Count frames OpenCV can actually read from a file.

    Container metadata often over-reports length (especially after ffmpeg
    re-encodes). Sequential reads reflect what preview playback can use.
    """
    try:
        import cv2  # type: ignore[import-untyped]
    except ImportError:
        return 0

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return 0

    if start_frame > 0:
        capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    count = 0
    while max_frames is None or count < max_frames:
        ok, _ = capture.read()
        if not ok:
            break
        count += 1

    capture.release()
    return count


def clip_playback_trim(clip: Clip) -> tuple[Optional[int], Optional[int]]:
    """Return trim bounds for playback/export, or none when using a version file.

    Files under ``versions/`` (crop output, ``current.mp4``, etc.) are already the
    playable segment; source-timeline trim must not be applied again.
    """
    if clip.version_filename:
        return None, None
    return clip.trim_start_frame, clip.trim_end_frame


def resolve_playback_frame_count(
    video_path: Path,
    *,
    trim_start_frame: Optional[int] = None,
    trim_end_frame: Optional[int] = None,
    resource_duration_frames: int = 0,
) -> int:
    """Return the number of frames that can be played for a clip."""
    if trim_start_frame is not None and trim_end_frame is not None:
        return max(trim_end_frame - trim_start_frame + 1, 1)

    reported = resource_duration_frames
    if reported <= 0 and video_path.is_file():
        reported = int(probe_metadata(video_path)["duration_frames"])

    if not video_path.is_file():
        return max(reported, 1)

    max_scan = reported if reported > 0 else None
    decodable = count_decodable_frames(video_path, max_frames=max_scan)
    if decodable <= 0:
        return max(reported, 1)
    if reported <= 0:
        return decodable
    return min(decodable, reported)


def write_thumbnail(video_path: Path, thumbnail_path: Path) -> None:
    """Save the first frame as a poster image, or an empty stub on failure."""
    try:
        import cv2  # type: ignore[import-untyped]
    except ImportError:
        thumbnail_path.write_bytes(b"")
        return

    capture = cv2.VideoCapture(str(video_path))
    if capture.isOpened():
        ok, frame = capture.read()
        capture.release()
        if ok:
            cv2.imwrite(str(thumbnail_path), frame)
            return

    thumbnail_path.write_bytes(b"")


def write_crop(
    source_path: Path,
    output_path: Path,
    start_frame: int,
    end_frame: int,
    fps: float,
) -> None:
    """Write an inclusive frame-range crop from source to output, keeping audio when present."""
    ffmpeg_exe = resolve_ffmpeg_exe()
    if ffmpeg_exe is not None:
        write_crop_ffmpeg(
            ffmpeg_exe,
            source_path,
            output_path,
            start_frame,
            end_frame,
            fps,
        )
        return

    if probe_has_audio_on_file(source_path):
        raise ProjectServiceError(
            "Cropping a clip with audio requires ffmpeg. "
            "Install ffmpeg on your PATH, or install imageio-ffmpeg "
            "(pip install imageio-ffmpeg)."
        )

    _write_crop_opencv(source_path, output_path, start_frame, end_frame, fps)


def probe_has_audio_on_file(media_path: Path) -> bool:
    """Return True if the media file has an audio stream (requires ffmpeg to probe)."""
    ffmpeg_exe = resolve_ffmpeg_exe()
    if ffmpeg_exe is None:
        return False
    return probe_has_audio(ffmpeg_exe, media_path)


def write_crop_ffmpeg(
    ffmpeg_exe: str,
    source_path: Path,
    output_path: Path,
    start_frame: int,
    end_frame: int,
    fps: float,
) -> None:
    """Crop video and audio with ffmpeg so voice-over and source audio are preserved."""
    probed = probe_metadata(source_path)
    effective_fps = float(probed["fps"]) if probed.get("fps") else (fps if fps > 0 else 30.0)
    end_exclusive = end_frame + 1
    start_s = start_frame / effective_fps
    end_s = end_exclusive / effective_fps

    # Frame-based video trim; audio uses the same timeline in seconds from ffprobe fps.
    video_filter = (
        f"trim=start_frame={start_frame}:end_frame={end_exclusive},setpts=PTS-STARTPTS"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if probe_has_audio(ffmpeg_exe, source_path):
        audio_filter = f"atrim=start={start_s}:end={end_s},asetpts=PTS-STARTPTS"
        run_ffmpeg(
            ffmpeg_exe,
            [
                "-y",
                "-i",
                str(source_path),
                "-vf",
                video_filter,
                "-af",
                audio_filter,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "fast",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            error_context="Failed to crop clip with audio",
        )
    else:
        run_ffmpeg(
            ffmpeg_exe,
            [
                "-y",
                "-i",
                str(source_path),
                "-vf",
                video_filter,
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "fast",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            error_context="Failed to crop clip",
        )

    if not output_path.is_file() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise ProjectServiceError("Crop produced no output file.")


def _write_crop_opencv(
    source_path: Path,
    output_path: Path,
    start_frame: int,
    end_frame: int,
    fps: float,
) -> None:
    """Video-only crop fallback when ffmpeg is unavailable."""
    try:
        import cv2  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ProjectServiceError(
            "OpenCV is required for video cropping. Install opencv-python-headless."
        ) from exc

    capture = cv2.VideoCapture(str(source_path))
    if not capture.isOpened():
        raise ProjectServiceError(f"Unable to open video: {source_path}")

    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if width <= 0 or height <= 0:
        capture.release()
        raise ProjectServiceError(f"Invalid video dimensions: {source_path}")

    effective_fps = float(capture.get(cv2.CAP_PROP_FPS) or fps or 30.0)
    if effective_fps <= 0:
        effective_fps = 30.0

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, effective_fps, (width, height))
    if not writer.isOpened():
        capture.release()
        raise ProjectServiceError(f"Unable to create output video: {output_path}")

    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frames_written = 0
    for _ in range(start_frame, end_frame + 1):
        ok, frame = capture.read()
        if not ok:
            break
        writer.write(frame)
        frames_written += 1

    capture.release()
    writer.release()

    if frames_written == 0:
        output_path.unlink(missing_ok=True)
        raise ProjectServiceError("Crop produced no frames.")


def normalize_fps(resource_fps: float, capture_fps: float) -> float:
    """Pick a sensible playback frame rate, preferring the open file over project metadata."""
    for candidate in (capture_fps, resource_fps):
        if 1.0 <= candidate <= 240.0:
            return candidate
    return 30.0


def resolve_crop_frames(start: int, end: int, duration_frames: int) -> tuple[int, int]:
    """Clamp and order crop bounds to valid inclusive frame indices."""
    last_frame = max(duration_frames - 1, 0)
    start_frame = max(0, min(start, last_frame))
    end_frame = max(0, min(end, last_frame))
    if start_frame > end_frame:
        start_frame, end_frame = end_frame, start_frame
    return start_frame, end_frame


def resolve_image_clip_frames(
    *,
    frames: Optional[int] = None,
    seconds: Optional[float] = None,
    fps: float = IMAGE_CLIP_FPS,
) -> int:
    """Convert a frames or seconds duration to a frame count for image clips."""
    if frames is not None and seconds is not None:
        raise ProjectServiceError("Specify either frames or seconds, not both.")

    if seconds is not None:
        if seconds <= 0:
            raise ProjectServiceError(f"Duration must be positive, got {seconds}")
        return max(int(round(seconds * fps)), 1)

    if frames is not None:
        if frames < 1:
            raise ProjectServiceError(f"Frame count must be at least 1, got {frames}")
        return frames

    return IMAGE_CLIP_FRAME_COUNT


def write_image_clip(
    image_path: Path,
    output_path: Path,
    frame_count: int = IMAGE_CLIP_FRAME_COUNT,
    fps: float = IMAGE_CLIP_FPS,
) -> dict[str, float | int]:
    """Encode a still image as a short video clip for playback."""
    try:
        import cv2  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ProjectServiceError(
            "OpenCV is required for image import. Install opencv-python-headless."
        ) from exc

    frame = cv2.imread(str(image_path))
    if frame is None:
        raise ProjectServiceError(f"Unable to read image: {image_path}")

    height, width = frame.shape[:2]
    if width <= 0 or height <= 0:
        raise ProjectServiceError(f"Invalid image dimensions: {image_path}")

    effective_fps = fps if fps > 0 else IMAGE_CLIP_FPS
    frame_total = max(frame_count, 1)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(
        str(output_path),
        fourcc,
        effective_fps,
        (width, height),
    )
    if not writer.isOpened():
        raise ProjectServiceError(f"Unable to create image clip video: {output_path}")

    for _ in range(frame_total):
        writer.write(frame)

    writer.release()

    return {
        "duration_frames": frame_total,
        "fps": effective_fps,
        "width": width,
        "height": height,
    }


def write_image_thumbnail(image_path: Path, thumbnail_path: Path) -> None:
    """Save a poster thumbnail from a still image."""
    try:
        import cv2  # type: ignore[import-untyped]
    except ImportError:
        thumbnail_path.write_bytes(b"")
        return

    frame = cv2.imread(str(image_path))
    if frame is not None:
        cv2.imwrite(str(thumbnail_path), frame)
        return

    thumbnail_path.write_bytes(b"")
