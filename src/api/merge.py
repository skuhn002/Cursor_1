"""Merge composition clips into one video and remapped flags."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.api.errors import ProjectServiceError
from src.api.ffmpeg_util import probe_has_audio, require_ffmpeg_exe, run_ffmpeg
from src.api.video import (
    clip_playback_trim,
    normalize_fps,
    probe_metadata,
    resolve_playback_frame_count,
)
from src.models import Clip, Flag, Resource


@dataclass(frozen=True)
class ClipSegment:
    """One composition clip positioned on the merged timeline."""

    clip: Clip
    video_path: Path
    frame_count: int
    timeline_offset: int


@dataclass(frozen=True)
class MergePlan:
    """Ordered segments and remapped flags for a composition merge."""

    segments: list[ClipSegment]
    merged_flags: list[Flag]
    output_fps: float
    total_frames: int
    width: int
    height: int


def clip_playback_frame_count(clip: Clip, resource: Resource, video_path: Path) -> int:
    """Return the number of frames played for a clip."""
    trim_start, trim_end = clip_playback_trim(clip)
    return resolve_playback_frame_count(
        video_path,
        trim_start_frame=trim_start,
        trim_end_frame=trim_end,
        resource_duration_frames=resource.duration_frames,
    )


def build_merge_plan(
    ordered_clips: list[Clip],
    video_paths: list[Path],
    resources: list[Resource],
    output_fps: float,
) -> MergePlan:
    """Compute segment offsets and flags on the merged timeline."""
    if not ordered_clips:
        raise ProjectServiceError("Cannot merge an empty composition.")
    if len(ordered_clips) != len(video_paths) or len(ordered_clips) != len(resources):
        raise ProjectServiceError("Merge plan requires matching clips, paths, and resources.")

    segments: list[ClipSegment] = []
    merged_flags: list[Flag] = []
    offset = 0
    max_width = 0
    max_height = 0

    for clip, video_path, resource in zip(ordered_clips, video_paths, resources):
        if not video_path.is_file():
            raise ProjectServiceError(f"Video file not found for clip: {clip.display_name}")

        frame_count = clip_playback_frame_count(clip, resource, video_path)
        if frame_count <= 0:
            raise ProjectServiceError(
                f"Clip has no frames to merge: {clip.display_name}"
            )

        metadata = probe_metadata(video_path)
        max_width = max(max_width, int(metadata["width"]))
        max_height = max(max_height, int(metadata["height"]))

        segments.append(
            ClipSegment(
                clip=clip,
                video_path=video_path,
                frame_count=frame_count,
                timeline_offset=offset,
            )
        )

        last_frame = frame_count - 1
        for flag in sorted(clip.flags, key=lambda item: item.frame):
            local_frame = max(0, min(flag.frame, last_frame))
            merged_flags.append(
                Flag(
                    frame=offset + local_frame,
                    note=flag.note,
                    color=flag.color,
                    flag_type=flag.flag_type,
                )
            )

        offset += frame_count

    if offset <= 0:
        raise ProjectServiceError("Composition has no frames to merge.")

    merged_flags.sort(key=lambda item: item.frame)

    return MergePlan(
        segments=segments,
        merged_flags=merged_flags,
        output_fps=output_fps,
        total_frames=offset,
        width=max_width,
        height=max_height,
    )


def _build_video_filter(clip: Clip, width: int, height: int, fps: float) -> str:
    """Scale/pad to the merge canvas and honor optional trim on the clip."""
    parts: list[str] = []
    trim_start, trim_end = clip_playback_trim(clip)
    if trim_start is not None and trim_end is not None:
        end_frame = trim_end + 1
        parts.append(f"trim=start_frame={trim_start}:end_frame={end_frame}")
        parts.append("setpts=PTS-STARTPTS")
    parts.append(
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )
    parts.append(f"fps={fps}")
    return ",".join(parts)


def _build_audio_filter(clip: Clip, fps: float) -> str:
    """Resample to stereo 48 kHz and honor optional trim on the clip."""
    parts: list[str] = []
    trim_start, trim_end = clip_playback_trim(clip)
    if trim_start is not None and trim_end is not None:
        start_s = trim_start / fps
        end_s = (trim_end + 1) / fps
        parts.append(f"atrim=start={start_s}:end={end_s}")
        parts.append("asetpts=PTS-STARTPTS")
    parts.append("aresample=48000")
    parts.append("aformat=channel_layouts=stereo")
    return ",".join(parts)


def _write_normalized_segment(
    ffmpeg_exe: str,
    segment: ClipSegment,
    plan: MergePlan,
    dest: Path,
) -> None:
    """Encode one composition segment to a common format for concat."""
    clip = segment.clip
    vf = _build_video_filter(clip, plan.width, plan.height, plan.output_fps)
    duration_s = segment.frame_count / plan.output_fps
    has_audio = probe_has_audio(ffmpeg_exe, segment.video_path)

    if has_audio:
        run_ffmpeg(
            ffmpeg_exe,
            [
                "-y",
                "-i",
                str(segment.video_path),
                "-vf",
                vf,
                "-af",
                _build_audio_filter(clip, plan.output_fps),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-frames:v",
                str(segment.frame_count),
                "-shortest",
                str(dest),
            ],
            error_context=f"Failed to prepare segment “{clip.display_name}”",
        )
        return

    run_ffmpeg(
        ffmpeg_exe,
        [
            "-y",
            "-i",
            str(segment.video_path),
            "-f",
            "lavfi",
            "-t",
            str(duration_s),
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-frames:v",
            str(segment.frame_count),
            "-shortest",
            str(dest),
        ],
        error_context=f"Failed to prepare segment “{clip.display_name}”",
    )


def write_concatenated_video(plan: MergePlan, output_path: Path) -> dict[str, float | int]:
    """Concatenate segment videos (with audio) into one file at a common size and FPS."""
    if plan.width <= 0 or plan.height <= 0:
        raise ProjectServiceError("Unable to determine output dimensions for merge.")

    ffmpeg_exe = require_ffmpeg_exe()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="moment_merge_") as tmp_dir:
        tmp = Path(tmp_dir)
        segment_paths: list[Path] = []
        for index, segment in enumerate(plan.segments):
            segment_path = tmp / f"segment_{index:04d}.mp4"
            _write_normalized_segment(ffmpeg_exe, segment, plan, segment_path)
            if not segment_path.is_file():
                raise ProjectServiceError(
                    f"Segment file missing after encode: {segment.clip.display_name}"
                )
            segment_paths.append(segment_path)

        list_file = tmp / "concat.txt"
        lines = []
        for path in segment_paths:
            escaped = str(path.resolve()).replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
        list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        run_ffmpeg(
            ffmpeg_exe,
            [
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(output_path),
            ],
            error_context="Failed to concatenate merged segments",
        )

    if not output_path.is_file():
        raise ProjectServiceError("Merge produced no output file.")

    metadata = probe_metadata(output_path)
    duration_frames = int(metadata["duration_frames"])
    if duration_frames <= 0:
        duration_frames = plan.total_frames

    return {
        "duration_frames": duration_frames,
        "fps": plan.output_fps,
        "width": plan.width,
        "height": plan.height,
    }


def resolve_merge_output_fps(resources: list[Resource], video_paths: list[Path]) -> float:
    """Pick one output frame rate for the merged clip."""
    capture_fps = 0.0
    if video_paths:
        capture_fps = float(probe_metadata(video_paths[0])["fps"])
    resource_fps = resources[0].fps if resources else 30.0
    return normalize_fps(resource_fps, capture_fps)
