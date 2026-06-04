"""Dialog for voice-over audio handling (overwrite vs mix)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from src.gui.dialogs.base import ModalDialog
from src.gui.theme import Spacing
from src.user_settings import UserSettings, VoiceoverAudioMode, load_user_settings, save_user_settings


class VoiceoverModeDialog(ModalDialog):
    """Choose whether voice-over replaces or mixes with clip audio."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        initial_mode: Optional[VoiceoverAudioMode] = None,
        initial_remember: bool = False,
        on_confirm: Callable[[VoiceoverAudioMode, bool], None],
    ) -> None:
        super().__init__(parent, "Voice-over audio")
        self._on_confirm = on_confirm

        ttk.Label(
            self.body,
            text="How should your recording be applied to this clip?",
            wraplength=360,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, Spacing.SECTION))

        self._mode_var = tk.StringVar(
            value=initial_mode if initial_mode is not None else "overwrite"
        )
        ttk.Radiobutton(
            self.body,
            text="Overwrite the clip’s audio (replace with my voice-over)",
            variable=self._mode_var,
            value="overwrite",
        ).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(
            self.body,
            text="Mix with the clip’s audio (keep original + add my voice-over)",
            variable=self._mode_var,
            value="mix",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, Spacing.SECTION))

        self._remember_var = tk.BooleanVar(value=initial_remember)
        ttk.Checkbutton(
            self.body,
            text="Remember my choice and don’t ask again",
            variable=self._remember_var,
        ).grid(row=3, column=0, columnspan=2, sticky="w")

        self.add_button_row(4, "Continue", self._submit)

        self.center_over(parent)
        self.wait_window()

    def _submit(self) -> None:
        mode: VoiceoverAudioMode = (
            "mix" if self._mode_var.get() == "mix" else "overwrite"
        )
        remember = bool(self._remember_var.get())
        settings = load_user_settings()
        if remember:
            settings.voiceover_audio_mode = mode
            settings.voiceover_remember_mode = True
        else:
            settings.voiceover_remember_mode = False
        save_user_settings(settings)
        self._on_confirm(mode, remember)
        self.destroy()


def prompt_voiceover_mode(
    parent: tk.Misc,
    on_chosen: Callable[[VoiceoverAudioMode], None],
) -> None:
    """Show the dialog only when the user has not saved a remembered mode."""
    settings = load_user_settings()
    saved = settings.voiceover_audio_mode if settings.voiceover_remember_mode else None
    if saved is not None:
        on_chosen(saved)
        return

    def handle(mode: VoiceoverAudioMode, _remember: bool) -> None:
        on_chosen(mode)

    VoiceoverModeDialog(
        parent,
        initial_mode=settings.voiceover_audio_mode,
        initial_remember=settings.voiceover_remember_mode,
        on_confirm=handle,
    )


def configure_voiceover_default(parent: tk.Misc) -> None:
    """Open the mode dialog to set or change the saved default."""

    def handle(mode: VoiceoverAudioMode, remember: bool) -> None:
        settings = load_user_settings()
        settings.voiceover_audio_mode = mode
        settings.voiceover_remember_mode = remember
        save_user_settings(settings)

    settings = load_user_settings()
    VoiceoverModeDialog(
        parent,
        initial_mode=settings.voiceover_audio_mode or "overwrite",
        initial_remember=settings.voiceover_remember_mode,
        on_confirm=handle,
    )
