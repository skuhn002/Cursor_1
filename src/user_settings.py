"""Per-user application settings (not stored in project files)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

VoiceoverAudioMode = Literal["overwrite", "mix"]


class UserSettings(BaseModel):
    """Preferences that apply across all Moment projects on this machine."""

    voiceover_audio_mode: Optional[VoiceoverAudioMode] = None
    voiceover_remember_mode: bool = False


def settings_dir() -> Path:
    """Return the directory used for Moment user settings."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / "Moment"
    else:
        base = Path.home() / ".config" / "moment"
    base.mkdir(parents=True, exist_ok=True)
    return base


def settings_path() -> Path:
    return settings_dir() / "settings.json"


def load_user_settings() -> UserSettings:
    path = settings_path()
    if not path.is_file():
        return UserSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return UserSettings.model_validate(data)
    except (json.JSONDecodeError, OSError, ValueError):
        return UserSettings()


def save_user_settings(settings: UserSettings) -> None:
    path = settings_path()
    path.write_text(settings.model_dump_json(indent=2), encoding="utf-8")


def resolved_voiceover_mode(settings: UserSettings) -> Optional[VoiceoverAudioMode]:
    """Return the saved voice-over mode when the user opted out of prompts."""
    if settings.voiceover_remember_mode and settings.voiceover_audio_mode is not None:
        return settings.voiceover_audio_mode
    return None
