"""OpenCV-backed video probing, thumbnails, and cropping."""

from __future__ import annotations

from pathlib import Path

from src.api.errors import ProjectServiceError


def probe_metadata(video_path: Path) -> dict[str, float | int]:
    """Read frame count, FPS, and dimensions from a video file."""
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
    """Write an inclusive frame-range crop from source to output."""
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
    """Pick a sensible playback frame rate from resource or container metadata."""
    for candidate in (resource_fps, capture_fps):
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
