"""Pure data models for Moment projects."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class Resource(BaseModel):
    """Manages on-disk folder structure for a single imported video."""

    id: str = Field(default_factory=lambda: _new_id("res"))
    display_name: str
    original_filename: str
    folder_name: str  # e.g. video_xxxx
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


class Clip(BaseModel):
    """A clip references a resource and holds frame-based flags."""

    id: str = Field(default_factory=lambda: _new_id("clip"))
    resource_id: str
    display_name: str
    flags: list[Flag] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)


class Project(BaseModel):
    """Top-level project metadata and in-memory state."""

    id: str = Field(default_factory=lambda: _new_id("proj"))
    name: str
    resources: dict[str, Resource] = Field(default_factory=dict)
    clips: dict[str, Clip] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    modified_at: datetime = Field(default_factory=_utc_now)


class ProjectFile(BaseModel):
    """Serializable project snapshot for save/load (project.json)."""

    version: str = "1.0"
    project: Project
    project_path: Optional[str] = None  # set at runtime, not persisted
