"""Separate window for editing a single clip."""

from __future__ import annotations

import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Optional
from uuid import uuid4

from src.api.errors import ProjectServiceError
from src.api.project_service import ProjectService
from src.api.voiceover import VoiceoverAudioMode, write_voiceover_wav
from src.gui.audio_record import AudioRecorder, duration_to_sample_count, recording_available
from src.gui.dialogs.voiceover_mode import prompt_voiceover_mode
from src.gui.panels.clip_preview import ClipPreviewPanel
from src.gui.theme import Spacing, apply_theme
from src.models import Clip


class ClipEditorWindow(tk.Toplevel):
    """Focused preview and tools for one clip."""

    def __init__(
        self,
        parent: tk.Misc,
        service: ProjectService,
        clip_id: str,
        *,
        on_clip_updated: Callable[[Clip], None],
        on_status: Optional[Callable[[str], None]] = None,
        on_release_media: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._clip_id = clip_id
        self._on_clip_updated = on_clip_updated
        self._on_status = on_status
        self._on_release_media = on_release_media
        self._recorder = AudioRecorder()
        self._recording = False
        self._busy = False
        self._voiceover_mode: VoiceoverAudioMode = "overwrite"
        self._clip_sample_limit = 0

        clip = service.get_clip(clip_id)
        self.title(f"Edit clip — {clip.display_name}")
        self.minsize(640, 480)
        self.geometry("820x560")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        apply_theme(self)

        outer = ttk.Frame(self, padding=Spacing.WINDOW)
        outer.pack(fill="both", expand=True)

        self._preview = ClipPreviewPanel(outer, on_status=self._set_status)
        self._preview.pack(fill="both", expand=True)
        self._preview.set_service(service)
        self._preview.load_clip(clip_id)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(Spacing.SECTION, 0))

        record_actions = ttk.Frame(actions)
        record_actions.pack(side="left")

        self._voiceover_btn = ttk.Button(
            record_actions,
            text="Record voice-over…",
            style="Accent.TButton",
            command=self._start_voiceover,
        )
        self._voiceover_btn.pack(side="left")

        self._stop_record_btn = ttk.Button(
            record_actions,
            text="Stop Recording",
            style="Accent.TButton",
            command=self._stop_voiceover_recording,
        )

        if not recording_available():
            self._voiceover_btn.configure(state="disabled")

        ttk.Button(actions, text="Close", command=self._on_close).pack(side="right")

        self._status_var = tk.StringVar(
            value="Record while the clip plays, or click Stop Recording when finished."
        )
        ttk.Label(outer, textvariable=self._status_var, style="Muted.TLabel").pack(
            anchor="w", pady=(Spacing.CONTROL_GAP, 0)
        )

        self.transient(parent)
        self._center_over(parent)

    def _center_over(self, parent: tk.Misc) -> None:
        self.update_idletasks()
        parent.update_idletasks()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_width()) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self.winfo_height()) // 2)
        self.geometry(f"+{x}+{y}")

    def _set_status(self, message: str) -> None:
        self._status_var.set(message)
        if self._on_status:
            self._on_status(message)

    def _on_close(self) -> None:
        if self._recording:
            self._recorder.stop()
            self._preview.stop_playback()
            self._recording = False
        self._preview.clear()
        self.destroy()

    def _start_voiceover(self) -> None:
        if self._busy or self._recording:
            return
        if not recording_available():
            messagebox.showerror(
                "Voice-over",
                "Install sounddevice to record voice-over:\n\npip install sounddevice",
                parent=self,
            )
            return

        prompt_voiceover_mode(self, on_chosen=self._begin_voiceover_recording)

    def _begin_voiceover_recording(self, mode: VoiceoverAudioMode) -> None:
        if self._preview.frame_count() <= 0:
            messagebox.showerror("Voice-over", "Clip has no frames to record against.", parent=self)
            return

        duration_s = self._preview.clip_duration_seconds()
        self._clip_sample_limit = duration_to_sample_count(
            duration_s,
            self._recorder.sample_rate,
        )
        self._recording = True
        self._voiceover_mode = mode
        self._set_recording_ui(True)
        self._set_status(
            "Recording… clip is playing. "
            + ("Original audio is on." if mode == "mix" else "Original audio is muted.")
            + " Recording stops automatically at the end of the clip."
        )

        self._recorder.set_on_auto_stop(
            lambda: self.after(0, self._on_clip_playback_finished)
        )
        try:
            self._recorder.start(max_duration_seconds=duration_s)
        except ProjectServiceError as exc:
            self._recording = False
            self._recorder.set_on_auto_stop(None)
            self._set_recording_ui(False)
            messagebox.showerror("Voice-over", str(exc), parent=self)
            return

        include_source_audio = mode == "mix"
        self._preview.play_for_voiceover(
            include_source_audio=include_source_audio,
            on_finished=self._on_clip_playback_finished,
        )

    def _on_clip_playback_finished(self) -> None:
        """Stop capture when the clip finishes playing."""
        self._complete_voiceover_recording(trim_to_clip=True)

    def _stop_voiceover_recording(self) -> None:
        """User stopped recording before the clip ended."""
        self._complete_voiceover_recording(trim_to_clip=False)

    def _complete_voiceover_recording(self, *, trim_to_clip: bool) -> None:
        if not self._recording:
            return

        self._recording = False
        self._recorder.set_on_auto_stop(None)
        self._preview.stop_playback()

        max_samples = self._clip_sample_limit if trim_to_clip else None
        samples = self._recorder.stop(max_samples=max_samples)
        self._set_recording_ui(False)

        if samples.size == 0:
            self._set_status("Recording cancelled (no audio captured).")
            return

        self._preview.release_media_handles()
        if self._on_release_media is not None:
            self._on_release_media()

        self._set_busy(True)
        self._set_status("Applying voice-over…")

        def work() -> Clip:
            with tempfile.TemporaryDirectory(prefix="moment_vo_") as tmp:
                wav_path = Path(tmp) / f"voiceover_{uuid4().hex[:8]}.wav"
                write_voiceover_wav(wav_path, samples, self._recorder.sample_rate)
                return self._service.apply_voiceover_to_clip(
                    self._clip_id,
                    wav_path,
                    self._voiceover_mode,
                )

        def on_success(clip: Clip) -> None:
            self._set_busy(False)
            self._preview.load_clip(clip.id, force=True)
            self._on_clip_updated(clip)
            self._set_status(f"Voice-over applied ({self._voiceover_mode}).")

        def on_error(message: str) -> None:
            self._set_busy(False)
            messagebox.showerror("Voice-over failed", message, parent=self)
            self._set_status("Voice-over failed.")

        threading.Thread(
            target=lambda: self._run_background(work, on_success, on_error),
            daemon=True,
        ).start()

    def _run_background(
        self,
        work: Callable[[], Clip],
        on_success: Callable[[Clip], None],
        on_error: Callable[[str], None],
    ) -> None:
        try:
            result = work()
            self.after(0, lambda: on_success(result))
        except Exception as exc:
            message = str(exc)
            self.after(0, lambda msg=message: on_error(msg))

    def _set_recording_ui(self, recording: bool) -> None:
        if recording:
            self._voiceover_btn.pack_forget()
            self._stop_record_btn.pack(side="left")
            self._stop_record_btn.configure(state="normal")
            self._preview._set_controls_enabled(False)
            return

        self._stop_record_btn.pack_forget()
        self._voiceover_btn.pack(side="left")
        self._preview._set_controls_enabled(True)
        self._set_busy(self._busy)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if self._recording:
            self._stop_record_btn.configure(state="disabled" if busy else "normal")
            return
        state = "disabled" if busy else "normal"
        if not recording_available():
            state = "disabled"
        self._voiceover_btn.configure(state=state)
