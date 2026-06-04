"""Business logic and file operations for Moment projects.

Clips are the central editing unit; the composition is an ordered sequence of
isolated clip references. See docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from src.api.errors import ProjectServiceError
from src.api.merge import (
    build_merge_plan,
    resolve_merge_output_fps,
    write_concatenated_video,
)
from src.api.video import (
    IMAGE_CLIP_FRAME_COUNT,
    IMAGE_CLIP_FPS,
    probe_metadata,
    resolve_crop_frames,
    resolve_image_clip_frames,
    clip_playback_trim,
    resolve_playback_frame_count,
    write_crop,
    write_image_clip,
    write_image_thumbnail,
    write_thumbnail,
)
from src.api.voiceover import VoiceoverAudioMode, apply_voiceover, write_voiceover_wav
from src.models import Clip, Composition, Flag, Project, ProjectFile, Resource


class ProjectService:
    """Manages Moment project lifecycle, resources, clips, and flags."""

    PROJECT_EXTENSION = ".clip"
    RESOURCES_DIR = "resources"
    PROJECT_JSON = "project.json"
    EDGE_START_FLAG = "__moment_edge_start__"
    EDGE_END_FLAG = "__moment_edge_end__"
    # Single derived video for in-place clip edits (voice-over, image-as-video).
    CURRENT_VERSION_FILENAME = "current.mp4"
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}

    def __init__(self, project_path: Optional[Path] = None) -> None:
        self._project_path: Optional[Path] = (
            Path(project_path).resolve() if project_path else None
        )
        self._project_file: Optional[ProjectFile] = None

    @property
    def project_path(self) -> Optional[Path]:
        return self._project_path

    @property
    def project(self) -> Optional[Project]:
        if self._project_file is None:
            return None
        return self._project_file.project

    def create_new_project(self, name: str, base_dir: Optional[Path] = None) -> ProjectFile:
        """Create a new project folder with the standard Moment layout.

        Args:
            name: Human-readable project name.
            base_dir: Directory where the ``.clip`` folder is created.
                      Defaults to the current working directory.

        Returns:
            The in-memory ``ProjectFile`` for the new project.

        Raises:
            ProjectServiceError: If the project folder already exists.
        """
        base = Path(base_dir or Path.cwd()).resolve()
        folder_name = self._sanitize_project_folder_name(name)
        project_path = base / folder_name

        if project_path.exists():
            raise ProjectServiceError(
                f"Project folder already exists: {project_path}"
            )

        project_path.mkdir(parents=True)
        (project_path / self.RESOURCES_DIR).mkdir()

        project = Project(name=name)
        self._project_path = project_path
        self._project_file = ProjectFile(project=project, project_path=str(project_path))
        self.save_project()
        return self._project_file

    def load_project(self, project_path: Optional[Path] = None) -> ProjectFile:
        """Load an existing project from disk.

        Args:
            project_path: Path to the ``.clip`` folder. Uses the instance path if omitted.

        Returns:
            The loaded ``ProjectFile``.

        Raises:
            ProjectServiceError: If the path is missing or invalid.
        """
        path = Path(project_path or self._project_path or "").resolve()
        if not path:
            raise ProjectServiceError("No project path specified.")
        if not path.is_dir():
            raise ProjectServiceError(f"Project folder not found: {path}")

        json_path = path / self.PROJECT_JSON
        if not json_path.is_file():
            raise ProjectServiceError(f"Missing {self.PROJECT_JSON} in {path}")

        raw = json.loads(json_path.read_text(encoding="utf-8"))
        project = Project.model_validate(raw["project"])
        self._project_path = path
        self._project_file = ProjectFile(
            project=project,
            project_path=str(path),
        )
        self._prune_composition()
        return self._project_file

    def save_project(self) -> None:
        """Persist the current project to ``project.json``.

        Raises:
            ProjectServiceError: If no project is loaded or the path is invalid.
        """
        self._require_project()
        assert self._project_path is not None
        assert self._project_file is not None

        self._project_file.project.modified_at = datetime.now(timezone.utc)
        payload = {
            "version": self._project_file.version,
            "project": self._project_file.project.model_dump(mode="json"),
        }
        json_path = self._project_path / self.PROJECT_JSON
        json_path.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )

    def import_video(
        self,
        file_path: str | Path,
        display_name: Optional[str] = None,
    ) -> Clip:
        """Import a video file into the project as a new clip and resource.

        Creates the resource folder structure, copies the original file,
        and writes a placeholder thumbnail.

        Args:
            file_path: Path to the source video file.
            display_name: Optional label; defaults to the source filename stem.

        Returns:
            The newly created ``Clip``.

        Raises:
            ProjectServiceError: If the source file is missing or copy fails.
        """
        project = self._require_project()
        source = Path(file_path).expanduser().resolve()
        if not source.is_file():
            raise ProjectServiceError(f"Video file not found: {source}")

        original_filename = source.name
        label = display_name or source.stem
        folder_name = f"video_{uuid4().hex[:8]}"
        resource = Resource(
            display_name=label,
            original_filename=original_filename,
            folder_name=folder_name,
        )

        resource_root = self._resource_root(resource)
        original_dir = resource_root / "original"
        versions_dir = resource_root / "versions"
        thumbnails_dir = resource_root / "thumbnails"
        for directory in (original_dir, versions_dir, thumbnails_dir):
            directory.mkdir(parents=True, exist_ok=True)

        dest_original = original_dir / original_filename
        shutil.copy2(source, dest_original)

        metadata = probe_metadata(dest_original)
        resource.duration_frames = metadata["duration_frames"]
        resource.fps = metadata["fps"]
        resource.width = metadata["width"]
        resource.height = metadata["height"]

        write_thumbnail(dest_original, thumbnails_dir / "poster.jpg")

        clip = Clip(
            resource_id=resource.id,
            display_name=label,
        )
        project.resources[resource.id] = resource
        project.clips[clip.id] = clip
        self.save_project()
        return clip

    def import_image(
        self,
        file_path: str | Path,
        display_name: Optional[str] = None,
        *,
        frame_count: Optional[int] = None,
        duration_seconds: Optional[float] = None,
    ) -> Clip:
        """Import a still image as a timed clip in the workspace.

        The image is stored in the resource folder and encoded as a short video
        for preview and composition playback.

        Args:
            file_path: Path to the source image file.
            display_name: Optional label; defaults to the source filename stem.
            frame_count: Clip length in frames (mutually exclusive with ``duration_seconds``).
            duration_seconds: Clip length in seconds at 30 fps.

        Returns:
            The newly created ``Clip`` (workspace only; not added to the composition).

        Raises:
            ProjectServiceError: If the file is missing or unsupported.
        """
        project = self._require_project()
        source = Path(file_path).expanduser().resolve()
        if not source.is_file():
            raise ProjectServiceError(f"Image file not found: {source}")

        extension = source.suffix.lower()
        if extension not in self.IMAGE_EXTENSIONS:
            supported = ", ".join(sorted(self.IMAGE_EXTENSIONS))
            raise ProjectServiceError(
                f"Unsupported image type “{extension or '(none)'}”. "
                f"Supported: {supported}"
            )

        frames = resolve_image_clip_frames(
            frames=frame_count,
            seconds=duration_seconds,
        )

        original_filename = source.name
        label = display_name or source.stem
        folder_name = f"image_{uuid4().hex[:8]}"
        resource = Resource(
            display_name=label,
            original_filename=original_filename,
            folder_name=folder_name,
            media_kind="image",
        )

        resource_root = self._resource_root(resource)
        original_dir = resource_root / "original"
        versions_dir = resource_root / "versions"
        thumbnails_dir = resource_root / "thumbnails"
        for directory in (original_dir, versions_dir, thumbnails_dir):
            directory.mkdir(parents=True, exist_ok=True)

        dest_original = original_dir / original_filename
        shutil.copy2(source, dest_original)

        version_filename = self.CURRENT_VERSION_FILENAME
        output_path = versions_dir / version_filename
        metadata = write_image_clip(
            dest_original,
            output_path,
            frame_count=frames,
            fps=IMAGE_CLIP_FPS,
        )
        resource.duration_frames = int(metadata["duration_frames"])
        resource.fps = float(metadata["fps"])
        resource.width = int(metadata["width"])
        resource.height = int(metadata["height"])

        write_image_thumbnail(dest_original, thumbnails_dir / "poster.jpg")

        clip = Clip(
            resource_id=resource.id,
            display_name=label,
            version_filename=version_filename,
        )
        project.resources[resource.id] = resource
        project.clips[clip.id] = clip
        self._prune_resource_versions(resource)
        self.save_project()
        return clip

    def add_flag(
        self,
        clip_id: str,
        frame: int,
        note: str = "",
        color: str = "#3B82F6",
        flag_type: str = "general",
    ) -> Flag:
        """Add a frame-based flag to a clip.

        Args:
            clip_id: Target clip identifier.
            frame: Frame number (primary timing unit).
            note: Optional annotation text.
            color: Hex color for UI display.
            flag_type: Category label (e.g. ``general``, ``title``).

        Returns:
            The created ``Flag``.

        Raises:
            ProjectServiceError: If the clip is not found or frame is negative.
        """
        if frame < 0:
            raise ProjectServiceError(f"Frame must be non-negative, got {frame}")

        clip = self.get_clip(clip_id)
        flag = Flag(frame=frame, note=note, color=color, flag_type=flag_type)
        clip.flags.append(flag)
        clip.flags.sort(key=lambda f: f.frame)
        self.save_project()
        return flag

    def get_clip(self, clip_id: str) -> Clip:
        """Return a clip by ID.

        Raises:
            ProjectServiceError: If the clip is not found.
        """
        project = self._require_project()
        clip = project.clips.get(clip_id)
        if clip is None:
            raise ProjectServiceError(f"Clip not found: {clip_id}")
        return clip

    def duplicate_clip(
        self,
        clip_id: str,
        display_name: Optional[str] = None,
    ) -> Clip:
        """Duplicate a clip with an independent copy of its media.

        Copies ``original/``, ``versions/``, and ``thumbnails/`` into a new
        resource folder so edits on one copy do not affect the other. The new
        clip is added to the workspace only (not the composition).

        Args:
            clip_id: Clip to duplicate.
            display_name: Optional label; defaults to ``{name} (copy)``.

        Returns:
            The new clip.

        Raises:
            ProjectServiceError: If the clip or resource folder is missing.
        """
        source_clip = self.get_clip(clip_id)
        source_resource = self.get_resource(source_clip.resource_id)
        source_root = self._resource_root(source_resource)
        if not source_root.is_dir():
            raise ProjectServiceError(f"Resource folder not found: {source_root}")

        new_resource = Resource(
            display_name=source_resource.display_name,
            original_filename=source_resource.original_filename,
            folder_name=self._new_resource_folder_name(
                source_resource, clip_kind=source_clip.clip_kind
            ),
            media_kind=source_resource.media_kind,
            duration_frames=source_resource.duration_frames,
            fps=source_resource.fps,
            width=source_resource.width,
            height=source_resource.height,
        )
        dest_root = self._resource_root(new_resource)
        shutil.copytree(source_root, dest_root)

        new_flags = [
            Flag(
                frame=flag.frame,
                note=flag.note,
                color=flag.color,
                flag_type=flag.flag_type,
            )
            for flag in source_clip.flags
        ]

        label = (display_name or "").strip() or f"{source_clip.display_name} (copy)"
        duplicated = Clip(
            resource_id=new_resource.id,
            display_name=label,
            flags=new_flags,
            clip_kind=source_clip.clip_kind,
            merged_from_clip_ids=list(source_clip.merged_from_clip_ids),
            source_clip_id=source_clip.id,
            version_filename=source_clip.version_filename,
            trim_start_frame=source_clip.trim_start_frame,
            trim_end_frame=source_clip.trim_end_frame,
        )

        project = self._require_project()
        project.resources[new_resource.id] = new_resource
        project.clips[duplicated.id] = duplicated
        self.save_project()
        return duplicated

    def list_composition_clips(self) -> list[Clip]:
        """Return isolated clips in the composition, in playback order."""
        project = self._require_project()
        self._prune_composition()
        return [
            project.clips[clip_id]
            for clip_id in project.composition.ordered_ids()
            if clip_id in project.clips
        ]

    def list_clips(self) -> list[Clip]:
        """Return composition clips in playback order (alias)."""
        return self.list_composition_clips()

    def list_workspace_clips(self) -> list[Clip]:
        """Return isolated clips not currently placed in the composition."""
        project = self._require_project()
        self._prune_composition()
        in_composition = set(project.composition.ordered_ids())
        workspace = [
            clip for clip in project.clips.values() if clip.id not in in_composition
        ]
        workspace.sort(key=lambda clip: clip.created_at)
        return workspace

    def list_all_clips(self) -> list[Clip]:
        """Return every isolated clip in the project."""
        project = self._require_project()
        clips = list(project.clips.values())
        clips.sort(key=lambda clip: clip.created_at)
        return clips

    def is_in_composition(self, clip_id: str) -> bool:
        """Return True when the clip is placed in the composition sequence."""
        project = self._require_project()
        self._prune_composition()
        return project.composition.contains(clip_id)

    def list_composition(self) -> list[str]:
        """Return ordered clip IDs — one isolated clip per slot."""
        project = self._require_project()
        self._prune_composition()
        return project.composition.ordered_ids()

    def remove_from_composition(self, clip_id: str) -> None:
        """Remove an isolated clip from the composition without deleting it."""
        project = self._require_project()
        self._prune_composition()
        self._require_clip(clip_id)
        try:
            project.composition.remove_clip(clip_id)
        except ValueError as exc:
            raise ProjectServiceError(str(exc)) from exc
        self.save_project()

    def insert_clip_in_composition(
        self,
        clip_id: str,
        reference_clip_id: str,
        placement: Literal["before", "after"],
    ) -> None:
        """Place one isolated clip before or after another in the composition."""
        project = self._require_project()
        self._prune_composition()
        self._require_clip(clip_id)
        self._require_clip(reference_clip_id)
        if clip_id == reference_clip_id:
            raise ProjectServiceError("Cannot insert a clip relative to itself.")

        try:
            if placement == "before":
                project.composition.insert_before(clip_id, reference_clip_id)
            else:
                project.composition.insert_after(clip_id, reference_clip_id)
        except ValueError as exc:
            raise ProjectServiceError(str(exc)) from exc
        self.save_project()

    def insert_clip_between(
        self,
        clip_id: str,
        before_clip_id: str,
        after_clip_id: str,
    ) -> None:
        """Place one isolated clip between two adjacent composition clips."""
        project = self._require_project()
        self._prune_composition()
        self._require_clip(clip_id)
        self._require_clip(before_clip_id)
        self._require_clip(after_clip_id)
        if before_clip_id == after_clip_id:
            raise ProjectServiceError("Before and after clips must be different.")
        if clip_id in (before_clip_id, after_clip_id):
            raise ProjectServiceError("Cannot insert a clip between itself and another clip.")

        try:
            project.composition.insert_between(clip_id, before_clip_id, after_clip_id)
        except ValueError as exc:
            raise ProjectServiceError(str(exc)) from exc
        self.save_project()

    def append_to_composition(self, clip_id: str) -> None:
        """Append one isolated clip to the end of the composition."""
        project = self._require_project()
        self._require_clip(clip_id)
        self._prune_composition()
        project.composition.append_clip(clip_id)
        self.save_project()

    def prepend_to_composition(self, clip_id: str) -> None:
        """Place one isolated clip at the start of the composition."""
        project = self._require_project()
        self._require_clip(clip_id)
        self._prune_composition()
        project.composition.prepend_clip(clip_id)
        self.save_project()

    def merge_composition_to_clip(
        self,
        display_name: Optional[str] = None,
        *,
        add_to_composition: bool = False,
        replace_composition: bool = False,
    ) -> Clip:
        """Concatenate composition clips into one resource and remapped flags.

        Each source clip's flags are offset onto the merged timeline so they
        align with the concatenated video. Source clips are left unchanged.

        Args:
            display_name: Label for the new merged clip.
            add_to_composition: Append the merged clip to the composition.
            replace_composition: Replace the composition with only the merged clip.

        Returns:
            The new merged clip (in the workspace unless ``add_to_composition``
            or ``replace_composition`` is set).
        """
        project = self._require_project()
        ordered_clips = self.list_composition_clips()
        if not ordered_clips:
            raise ProjectServiceError("Cannot merge an empty composition.")

        source_ids = [clip.id for clip in ordered_clips]
        video_paths = [self.get_clip_video_path(clip) for clip in ordered_clips]
        resources = [self.get_resource(clip.resource_id) for clip in ordered_clips]
        output_fps = resolve_merge_output_fps(resources, video_paths)
        plan = build_merge_plan(ordered_clips, video_paths, resources, output_fps)

        label = display_name or f"Merged ({len(ordered_clips)} clips)"
        folder_name = f"merge_{uuid4().hex[:8]}"
        merged_filename = f"merged_{uuid4().hex[:8]}.mp4"

        resource = Resource(
            display_name=label,
            original_filename=merged_filename,
            folder_name=folder_name,
            media_kind="video",
        )

        resource_root = self._resource_root(resource)
        original_dir = resource_root / "original"
        versions_dir = resource_root / "versions"
        thumbnails_dir = resource_root / "thumbnails"
        for directory in (original_dir, versions_dir, thumbnails_dir):
            directory.mkdir(parents=True, exist_ok=True)

        output_path = original_dir / merged_filename
        metadata = write_concatenated_video(plan, output_path)
        resource.duration_frames = int(metadata["duration_frames"])
        resource.fps = float(metadata["fps"])
        resource.width = int(metadata["width"])
        resource.height = int(metadata["height"])

        write_thumbnail(output_path, thumbnails_dir / "poster.jpg")

        merged_clip = Clip(
            resource_id=resource.id,
            display_name=label,
            flags=plan.merged_flags,
            clip_kind="merged",
            merged_from_clip_ids=source_ids,
        )
        project.resources[resource.id] = resource
        project.clips[merged_clip.id] = merged_clip

        if replace_composition:
            project.composition = Composition(clip_ids=[merged_clip.id])
        elif add_to_composition:
            self._prune_composition()
            project.composition.append_clip(merged_clip.id)

        self.save_project()
        return merged_clip

    def get_flags(self, clip_id: str) -> list[Flag]:
        """Return all flags for a clip, sorted by frame."""
        clip = self.get_clip(clip_id)
        return sorted(clip.flags, key=lambda f: f.frame)

    def get_flag(self, clip_id: str, flag_id: str) -> Flag:
        """Return a single flag by ID from a clip.

        Raises:
            ProjectServiceError: If the clip or flag is not found.
        """
        clip = self.get_clip(clip_id)
        for flag in clip.flags:
            if flag.id == flag_id:
                return flag
        raise ProjectServiceError(f"Flag not found: {flag_id}")

    def crop_clip(
        self,
        clip_id: str,
        start_flag_id: str,
        end_flag_id: str,
        display_name: Optional[str] = None,
    ) -> Clip:
        """Crop a clip to the frame range between two flags.

        Flag frames are clamped to the clip edges (frame 0 and the last frame).
        If the start flag is after the end flag, their frames are swapped.

        Writes the cropped video to the resource ``versions/`` folder and
        creates a new clip referencing that version.

        Args:
            clip_id: Source clip to crop from.
            start_flag_id: Flag marking the crop start (inclusive).
            end_flag_id: Flag marking the crop end (inclusive).
            display_name: Optional label for the new clip.

        Returns:
            The newly created cropped clip.

        Raises:
            ProjectServiceError: If flags, source video, or crop range is invalid.
        """
        source_clip = self.get_clip(clip_id)
        resource = self.get_resource(source_clip.resource_id)

        source_path = self.get_clip_video_path(source_clip)
        if not source_path.is_file():
            raise ProjectServiceError(f"Source video not found: {source_path}")

        trim_start, trim_end = clip_playback_trim(source_clip)
        duration_frames = resolve_playback_frame_count(
            source_path,
            trim_start_frame=trim_start,
            trim_end_frame=trim_end,
            resource_duration_frames=resource.duration_frames,
        )
        if duration_frames <= 0:
            raise ProjectServiceError(
                "Cannot crop: unable to determine source video frame count."
            )

        start_raw = self._resolve_crop_flag_frame(
            clip_id, start_flag_id, duration_frames, edge="start"
        )
        end_raw = self._resolve_crop_flag_frame(
            clip_id, end_flag_id, duration_frames, edge="end"
        )
        start_frame, end_frame = resolve_crop_frames(
            start_raw,
            end_raw,
            duration_frames,
        )

        ext = source_path.suffix or ".mp4"
        version_filename = f"crop_{start_frame}_{end_frame}_{uuid4().hex[:8]}{ext}"
        versions_dir = self._resource_root(resource) / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        output_path = versions_dir / version_filename

        metadata = probe_metadata(source_path)
        write_crop(
            source_path,
            output_path,
            start_frame,
            end_frame,
            float(metadata["fps"]),
        )

        label = display_name or (
            f"{source_clip.display_name} [{start_frame}-{end_frame}]"
        )

        cropped_clip = Clip(
            resource_id=resource.id,
            display_name=label,
            source_clip_id=source_clip.id,
            version_filename=version_filename,
        )
        project = self._require_project()
        project.clips[cropped_clip.id] = cropped_clip
        self._prune_resource_versions(resource)
        self.save_project()
        return cropped_clip

    def apply_voiceover_to_clip(
        self,
        clip_id: str,
        voiceover_wav: Path,
        mode: VoiceoverAudioMode,
    ) -> Clip:
        """Apply a recorded voice-over to the clip's current video file.

        Writes a new version under the clip's resource and updates
        ``version_filename`` on the same clip (in-place edit).
        """
        clip = self.get_clip(clip_id)
        resource = self.get_resource(clip.resource_id)
        source_path = self.get_clip_video_path(clip)
        if not source_path.is_file():
            raise ProjectServiceError(f"Clip video not found: {source_path}")

        version_filename = self.CURRENT_VERSION_FILENAME
        versions_dir = self._resource_root(resource) / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        output_path = versions_dir / version_filename
        temp_path = versions_dir / f"_vo_{uuid4().hex[:8]}.mp4"

        try:
            apply_voiceover(source_path, voiceover_wav, temp_path, mode)
            if not temp_path.is_file() or temp_path.stat().st_size == 0:
                raise ProjectServiceError("Voice-over produced no output video.")
            self._commit_version_file(temp_path, output_path)
        finally:
            if temp_path.exists() and temp_path.resolve() != output_path.resolve():
                temp_path.unlink(missing_ok=True)

        clip.version_filename = version_filename
        clip.trim_start_frame = None
        clip.trim_end_frame = None
        project = self._require_project()
        project.clips[clip.id] = clip
        self._prune_resource_versions(resource)
        # Persist the new version path before any slow metadata probing.
        self.save_project()

        metadata = probe_metadata(output_path)
        resource.duration_frames = resolve_playback_frame_count(
            output_path,
            resource_duration_frames=int(metadata["duration_frames"]) or resource.duration_frames,
        )
        resource.fps = float(metadata["fps"]) or resource.fps
        resource.width = int(metadata["width"]) or resource.width
        resource.height = int(metadata["height"]) or resource.height
        project.resources[resource.id] = resource
        self._prune_resource_versions(resource)
        self.save_project()
        return clip

    def get_clip_video_path(self, clip: Clip) -> Path:
        """Return the on-disk video file path for a clip (original or cropped version)."""
        resource = self.get_resource(clip.resource_id)
        resource_root = self._resource_root(resource)
        if clip.version_filename:
            return resource_root / "versions" / clip.version_filename
        return resource_root / "original" / resource.original_filename

    def get_clip_playback_frame_count(self, clip: Clip) -> int:
        """Return how many frames can actually be played for a clip."""
        resource = self.get_resource(clip.resource_id)
        trim_start, trim_end = clip_playback_trim(clip)
        return resolve_playback_frame_count(
            self.get_clip_video_path(clip),
            trim_start_frame=trim_start,
            trim_end_frame=trim_end,
            resource_duration_frames=resource.duration_frames,
        )

    def get_resource(self, resource_id: str) -> Resource:
        """Return a resource by ID.

        Raises:
            ProjectServiceError: If the resource is not found.
        """
        project = self._require_project()
        resource = project.resources.get(resource_id)
        if resource is None:
            raise ProjectServiceError(f"Resource not found: {resource_id}")
        return resource

    def _require_project(self) -> Project:
        if self._project_file is None or self._project_path is None:
            raise ProjectServiceError(
                "No project loaded. Create or load a project first."
            )
        return self._project_file.project

    def _prune_composition(self) -> None:
        """Drop composition slots that reference missing clips."""
        project = self._require_project()
        project.composition.prune_missing(set(project.clips.keys()))

    def _require_clip(self, clip_id: str) -> Clip:
        """Ensure a clip exists before placing it in the composition."""
        return self.get_clip(clip_id)

    def _resource_root(self, resource: Resource) -> Path:
        assert self._project_path is not None
        return self._project_path / self.RESOURCES_DIR / resource.folder_name

    @staticmethod
    def _new_resource_folder_name(resource: Resource, *, clip_kind: str = "standard") -> str:
        """Allocate a unique on-disk folder name for a new resource."""
        if resource.media_kind == "image":
            return f"image_{uuid4().hex[:8]}"
        if clip_kind == "merged":
            return f"merge_{uuid4().hex[:8]}"
        return f"video_{uuid4().hex[:8]}"

    def _version_filenames_in_use(self, resource_id: str) -> set[str]:
        """Return version files still referenced by any clip on this resource."""
        project = self._require_project()
        in_use: set[str] = set()
        for clip in project.clips.values():
            if clip.resource_id == resource_id and clip.version_filename:
                in_use.add(clip.version_filename)
        return in_use

    def _prune_resource_versions(self, resource: Resource) -> None:
        """Remove version files not referenced by any clip (keep original/ untouched)."""
        versions_dir = self._resource_root(resource) / "versions"
        if not versions_dir.is_dir():
            return
        keep = self._version_filenames_in_use(resource.id)
        for path in versions_dir.iterdir():
            if path.is_file() and path.name not in keep:
                path.unlink(missing_ok=True)

    def _commit_version_file(self, temp_path: Path, output_path: Path) -> None:
        """Move a finished encode into place, replacing any existing version file."""
        if output_path.exists():
            last_error: Optional[Exception] = None
            for _ in range(8):
                try:
                    output_path.unlink()
                    last_error = None
                    break
                except PermissionError as exc:
                    last_error = exc
                    time.sleep(0.12)
            if last_error is not None:
                raise ProjectServiceError(
                    "Cannot replace the clip video file because it is still in use. "
                    "Stop playback in the main window and Edit Clip preview, then try again."
                ) from last_error
        try:
            temp_path.replace(output_path)
        except PermissionError as exc:
            raise ProjectServiceError(
                "Cannot save the voice-over video. Close any preview of this clip and try again."
            ) from exc

    def _resolve_crop_flag_frame(
        self,
        clip_id: str,
        flag_id: str,
        duration_frames: int,
        edge: str,
    ) -> int:
        """Map a flag ID (or edge sentinel) to a frame number."""
        if flag_id == self.EDGE_START_FLAG:
            return 0
        if flag_id == self.EDGE_END_FLAG:
            return max(duration_frames - 1, 0)
        return self.get_flag(clip_id, flag_id).frame

    @staticmethod
    def _sanitize_project_folder_name(name: str) -> str:
        """Convert a project name into a safe ``Name.clip`` folder."""
        slug = re.sub(r"[^\w\s-]", "", name.strip())
        slug = re.sub(r"[\s_-]+", "_", slug).strip("_")
        if not slug:
            slug = "untitled"
        return f"{slug}{ProjectService.PROJECT_EXTENSION}"
