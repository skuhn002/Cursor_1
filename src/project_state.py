"""Shared active-project persistence for CLI and GUI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

STATE_FILE = ".moment.json"
LEGACY_STATE_FILE = ".clipforge.json"


def state_path(base_dir: Optional[Path] = None) -> Path:
    """Return the path to the active-project state file."""
    return (base_dir or Path.cwd()) / STATE_FILE


def _read_state_file(path: Path) -> Optional[Path]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        project = data.get("active_project")
        if project:
            return Path(project).resolve()
    except (json.JSONDecodeError, OSError):
        return None
    return None


def load_active_project_path(base_dir: Optional[Path] = None) -> Optional[Path]:
    """Load the active project path from disk, if set."""
    base = base_dir or Path.cwd()
    found = _read_state_file(base / STATE_FILE)
    if found is not None:
        return found
    return _read_state_file(base / LEGACY_STATE_FILE)


def save_active_project_path(
    project_path: Path,
    base_dir: Optional[Path] = None,
) -> None:
    """Persist the active project path for later sessions."""
    state_path(base_dir).write_text(
        json.dumps({"active_project": str(project_path.resolve())}, indent=2),
        encoding="utf-8",
    )
