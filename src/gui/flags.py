"""Helpers for displaying flags in the GUI."""

from __future__ import annotations

from src.api.project_service import ProjectService
from src.models import Flag


def format_flag_choices(flags: list[Flag]) -> list[tuple[str, str]]:
    """Build dropdown labels for crop start/end selection."""
    choices: list[tuple[str, str]] = [
        ("Start of clip (frame 0)", ProjectService.EDGE_START_FLAG),
        ("End of clip (last frame)", ProjectService.EDGE_END_FLAG),
    ]
    for flag in sorted(flags, key=lambda item: item.frame):
        note = f' — "{flag.note}"' if flag.note else ""
        label = f"frame {flag.frame} [{flag.flag_type}]{note} ({flag.id})"
        choices.append((label, flag.id))
    return choices
