"""Pure data models for Moment projects.

Clips are the central editing unit. The composition is an ordered list of
isolated clip references — see docs/ARCHITECTURE.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field, field_serializer, field_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


MediaKind = Literal["video", "image"]


class Resource(BaseModel):
    """Manages on-disk folder structure for a single imported asset."""

    id: str = Field(default_factory=lambda: _new_id("res"))
    display_name: str
    original_filename: str
    folder_name: str  # e.g. video_xxxx or image_xxxx
    media_kind: MediaKind = "video"
    duration_frames: int = 0
    fps: float = 30.0
    width: int = 0
    height: int = 0
    created_at: datetime = Field(default_factory=_utc_now)


class Flag(BaseModel):
    """Frame-based annotation on a clip (formerly Marker)."""

    id: str = Field(default_factory=lambda: _new_id("flag"))
    frame: int
    note: str = ""
    color: str = "#3B82F6"
    flag_type: str = "general"
    created_at: datetime = Field(default_factory=_utc_now)


ClipKind = Literal["standard", "merged"]


class Clip(BaseModel):
    """An isolated timeline item: one resource view with flags and optional derivations."""

    id: str = Field(default_factory=lambda: _new_id("clip"))
    resource_id: str
    display_name: str
    flags: list[Flag] = Field(default_factory=list)
    clip_kind: ClipKind = "standard"
    merged_from_clip_ids: list[str] = Field(default_factory=list)
    source_clip_id: Optional[str] = None
    version_filename: Optional[str] = None
    trim_start_frame: Optional[int] = None
    trim_end_frame: Optional[int] = None
    created_at: datetime = Field(default_factory=_utc_now)


class Composition(BaseModel):
    """Ordered playback sequence of isolated clips.

    Each entry is exactly one ``clip_id`` already defined in ``Project.clips``.
    The composition never embeds media, resources, flags, or partial segments.
    """

    clip_ids: list[str] = Field(default_factory=list)

    def contains(self, clip_id: str) -> bool:
        return clip_id in self.clip_ids

    def ordered_ids(self) -> list[str]:
        return list(self.clip_ids)

    def prune_missing(self, valid_clip_ids: set[str]) -> None:
        """Drop references to clips that no longer exist."""
        self.clip_ids[:] = [clip_id for clip_id in self.clip_ids if clip_id in valid_clip_ids]

    def remove_clip(self, clip_id: str) -> None:
        if clip_id not in self.clip_ids:
            raise ValueError(f"Clip is not in the composition: {clip_id}")
        self.clip_ids.remove(clip_id)

    def append_clip(self, clip_id: str) -> None:
        self._place_clip(clip_id, at_end=True)

    def prepend_clip(self, clip_id: str) -> None:
        self._place_clip(clip_id, at_index=0)

    def insert_before(self, clip_id: str, reference_clip_id: str) -> None:
        index = self._require_reference_index(reference_clip_id)
        self._place_clip(clip_id, at_index=index)

    def insert_after(self, clip_id: str, reference_clip_id: str) -> None:
        index = self._require_reference_index(reference_clip_id)
        self._place_clip(clip_id, at_index=index + 1)

    def insert_between(self, clip_id: str, before_clip_id: str, after_clip_id: str) -> None:
        before_index = self._require_reference_index(before_clip_id)
        if (
            before_index + 1 >= len(self.clip_ids)
            or self.clip_ids[before_index + 1] != after_clip_id
        ):
            raise ValueError("The selected clips are not adjacent in the composition.")
        self._place_clip(clip_id, at_index=before_index + 1)

    def _require_reference_index(self, reference_clip_id: str) -> int:
        if reference_clip_id not in self.clip_ids:
            raise ValueError(f"Reference clip is not in the composition: {reference_clip_id}")
        return self.clip_ids.index(reference_clip_id)

    def _place_clip(
        self,
        clip_id: str,
        *,
        at_index: Optional[int] = None,
        at_end: bool = False,
    ) -> None:
        if clip_id in self.clip_ids:
            self.clip_ids.remove(clip_id)
        if at_end:
            self.clip_ids.append(clip_id)
        elif at_index is not None:
            self.clip_ids.insert(at_index, clip_id)
        else:
            self.clip_ids.append(clip_id)


class Project(BaseModel):
    """Top-level project metadata and in-memory state."""

    id: str = Field(default_factory=lambda: _new_id("proj"))
    name: str
    resources: dict[str, Resource] = Field(default_factory=dict)
    clips: dict[str, Clip] = Field(default_factory=dict)
    composition: Composition = Field(default_factory=Composition)
    created_at: datetime = Field(default_factory=_utc_now)
    modified_at: datetime = Field(default_factory=_utc_now)

    @field_validator("composition", mode="before")
    @classmethod
    def _coerce_composition(
        cls, value: Union[Composition, list[str], dict[str, list[str]], None]
    ) -> Composition:
        """Accept legacy JSON (plain id list) and the structured form."""
        if value is None:
            return Composition()
        if isinstance(value, Composition):
            return value
        if isinstance(value, list):
            return Composition(clip_ids=value)
        if isinstance(value, dict) and "clip_ids" in value:
            return Composition(clip_ids=value["clip_ids"])
        raise ValueError(f"Invalid composition value: {value!r}")

    @field_serializer("composition")
    def _serialize_composition(self, composition: Composition) -> list[str]:
        """Persist as a plain clip-id list for backward-compatible project.json."""
        return composition.clip_ids


class ProjectFile(BaseModel):
    """Serializable project snapshot for save/load (project.json)."""

    version: str = "1.0"
    project: Project
    project_path: Optional[str] = None  # set at runtime, not persisted
