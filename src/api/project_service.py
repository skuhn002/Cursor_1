"""Business logic and file operations for Moment projects."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from src.models import Clip, Flag, Project, ProjectFile, Resource


class ProjectServiceError(Exception):
    """Raised when a project operation fails."""


class ProjectService:
    """Manages Moment project lifecycle, resources, clips, and flags."""

    PROJECT_EXTENSION = ".clip"
    RESOURCES_DIR = "resources"
    PROJECT_JSON = "project.json"
    EDGE_START_FLAG = "__moment_edge_start__"
    EDGE_END_FLAG = "__moment_edge_end__"

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

        metadata = self._probe_video_metadata(dest_original)
        resource.duration_frames = metadata["duration_frames"]
        resource.fps = metadata["fps"]
        resource.width = metadata["width"]
        resource.height = metadata["height"]

        self._generate_thumbnail_stub(dest_original, thumbnails_dir / "poster.jpg")

        clip = Clip(
            resource_id=resource.id,
            display_name=label,
        )
        project.resources[resource.id] = resource
        project.clips[clip.id] = clip
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

    def list_clips(self) -> list[Clip]:
        """Return all clips in the current project."""
        project = self._require_project()
        return list(project.clips.values())

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

        metadata = self._probe_video_metadata(source_path)
        duration_frames = int(metadata["duration_frames"])
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
        start_frame, end_frame = self._resolve_crop_frames(
            start_raw,
            end_raw,
            duration_frames,
        )

        ext = source_path.suffix or ".mp4"
        version_filename = f"crop_{start_frame}_{end_frame}_{uuid4().hex[:8]}{ext}"
        versions_dir = self._resource_root(resource) / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        output_path = versions_dir / version_filename

        self._write_video_crop(
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
            trim_start_frame=start_frame,
            trim_end_frame=end_frame,
        )
        project = self._require_project()
        project.clips[cropped_clip.id] = cropped_clip
        self.save_project()
        return cropped_clip

    def get_clip_video_path(self, clip: Clip) -> Path:
        """Return the on-disk video file path for a clip (original or cropped version)."""
        resource = self.get_resource(clip.resource_id)
        resource_root = self._resource_root(resource)
        if clip.version_filename:
            return resource_root / "versions" / clip.version_filename
        return resource_root / "original" / resource.original_filename

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

    def _resource_root(self, resource: Resource) -> Path:
        assert self._project_path is not None
        return self._project_path / self.RESOURCES_DIR / resource.folder_name

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
    def _resolve_crop_frames(
        start: int,
        end: int,
        duration_frames: int,
    ) -> tuple[int, int]:
        """Clamp and order crop bounds to valid inclusive frame indices."""
        last_frame = max(duration_frames - 1, 0)
        start_frame = max(0, min(start, last_frame))
        end_frame = max(0, min(end, last_frame))
        if start_frame > end_frame:
            start_frame, end_frame = end_frame, start_frame
        return start_frame, end_frame

    @staticmethod
    def _write_video_crop(
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
        writer = cv2.VideoWriter(
            str(output_path),
            fourcc,
            effective_fps,
            (width, height),
        )
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

    @staticmethod
    def _sanitize_project_folder_name(name: str) -> str:
        """Convert a project name into a safe ``Name.clip`` folder."""
        slug = re.sub(r"[^\w\s-]", "", name.strip())
        slug = re.sub(r"[\s_-]+", "_", slug).strip("_")
        if not slug:
            slug = "untitled"
        return f"{slug}{ProjectService.PROJECT_EXTENSION}"

    @staticmethod
    def _probe_video_metadata(video_path: Path) -> dict[str, float | int]:
        """Best-effort video metadata; returns sensible defaults if probing fails."""
        defaults: dict[str, float | int] = {
            "duration_frames": 0,
            "fps": 30.0,
            "width": 0,
            "height": 0,
        }
        try:
            import cv2  # type: ignore[import-untyped]

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
        except ImportError:
            return defaults

    @staticmethod
    def _generate_thumbnail_stub(video_path: Path, thumbnail_path: Path) -> None:
        """Generate a poster thumbnail or write a placeholder stub."""
        try:
            import cv2  # type: ignore[import-untyped]

            capture = cv2.VideoCapture(str(video_path))
            if capture.isOpened():
                ok, frame = capture.read()
                capture.release()
                if ok:
                    cv2.imwrite(str(thumbnail_path), frame)
                    return
        except ImportError:
            pass

        thumbnail_path.write_bytes(b"")
