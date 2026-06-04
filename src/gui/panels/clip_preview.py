"""Video preview panel for the Moment GUI."""

from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from typing import Callable, Optional

from src.api.errors import ProjectServiceError
from src.api.project_service import ProjectService
from src.api.video import clip_playback_trim, normalize_fps, resolve_playback_frame_count
from src.gui.audio_playback import FfmpegAudioPlayback, audio_playback_available
from src.gui.theme import Colors, Fonts, Spacing


@dataclass(frozen=True)
class _CompositionSegment:
    clip_id: str
    display_name: str
    video_path: Path
    fps: float
    frame_count: int


class ClipPreviewPanel(ttk.LabelFrame):
    """Shows a selected clip with playback controls and frame scrubbing."""

    def __init__(
        self,
        parent: tk.Misc,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, text="Preview", padding=Spacing.SECTION, style="Card.TLabelframe")
        self._on_status = on_status

        self._service: Optional[ProjectService] = None
        self._clip_id: Optional[str] = None
        self._video_path: Optional[Path] = None
        self._capture = None
        self._frame_count = 0
        self._fps = 30.0
        self._current_frame = 0
        self._playing = False
        self._after_id: Optional[str] = None
        self._next_frame_deadline = 0.0
        self._photo: Optional[tk.PhotoImage] = None
        self._scrubbing = False
        self._last_frame_bgr = None
        self._resize_after_id: Optional[str] = None
        self._audio = FfmpegAudioPlayback()
        self._audio_enabled = audio_playback_available()
        self._composition_mode = False
        self._composition_segments: list[_CompositionSegment] = []
        self._composition_index = 0
        self._playback_source_audio = True
        self._on_playback_finished: Optional[Callable[[], None]] = None
        self._playback_generation = 0

        self._clip_name_var = tk.StringVar(value="No clip selected")
        self._frame_entry_var = tk.StringVar(value="1")
        self._frame_total_var = tk.StringVar(value="—")
        self._syncing_entry = False

        ttk.Label(self, textvariable=self._clip_name_var, font=Fonts.BODY_BOLD).pack(
            anchor="w", pady=(0, Spacing.CONTROL_GAP)
        )

        preview_border = tk.Frame(self, bg=Colors.PREVIEW_BORDER)
        preview_border.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(
            preview_border,
            width=480,
            height=270,
            bg=Colors.PREVIEW_BG,
            highlightthickness=0,
            bd=0,
        )
        self._canvas.pack(fill="both", expand=True, padx=3, pady=3)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._placeholder = self._canvas.create_text(
            240,
            135,
            text="Select a clip to preview",
            fill=Colors.TEXT_MUTED,
            font=Fonts.HEADING,
        )

        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(Spacing.CONTROL_GAP, 0))

        self._play_btn = ttk.Button(controls, text="Play", command=self.toggle_play, width=8)
        self._play_btn.pack(side="left")
        ttk.Button(controls, text="Stop", command=self.stop_playback, width=8).pack(
            side="left", padx=(Spacing.CONTROL_GAP, 0)
        )

        frame_nav = ttk.Frame(self)
        frame_nav.pack(fill="x", pady=(Spacing.CONTROL_GAP, 0))

        self._prev_frame_btn = ttk.Button(
            frame_nav,
            text="◀",
            width=3,
            command=lambda: self._step_frame(-1),
        )
        self._prev_frame_btn.pack(side="left")

        ttk.Label(frame_nav, text="Frame").pack(side="left", padx=(Spacing.CONTROL_GAP, 4))
        self._frame_entry = ttk.Entry(frame_nav, textvariable=self._frame_entry_var, width=8)
        self._frame_entry.pack(side="left")
        self._frame_entry.bind("<Return>", self._go_to_entered_frame)
        self._frame_entry.bind("<FocusOut>", self._go_to_entered_frame)

        ttk.Label(frame_nav, textvariable=self._frame_total_var).pack(
            side="left", padx=(4, Spacing.CONTROL_GAP)
        )

        self._next_frame_btn = ttk.Button(
            frame_nav,
            text="▶",
            width=3,
            command=lambda: self._step_frame(1),
        )
        self._next_frame_btn.pack(side="left")

        self._scrubber = ttk.Scale(
            self,
            from_=0,
            to=0,
            orient="horizontal",
            command=self._on_scrub,
        )
        self._scrubber.pack(fill="x", pady=(Spacing.CONTROL_GAP, 0))
        self._scrubber.bind("<ButtonPress-1>", self._on_scrub_start)
        self._scrubber.bind("<ButtonRelease-1>", self._on_scrub_end)

        self._set_controls_enabled(False)

    def _bump_playback_generation(self) -> int:
        """Invalidate in-flight playback callbacks from a previous play session."""
        self._playback_generation += 1
        return self._playback_generation

    def _playback_active(self, generation: int) -> bool:
        return self._playing and generation == self._playback_generation

    def _cancel_playback_timer(self) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _schedule_playback(self, delay_ms: int, callback: Callable[[], None], *, generation: int) -> None:
        self._cancel_playback_timer()

        def wrapper() -> None:
            if not self.winfo_exists():
                return
            if not self._playback_active(generation):
                return
            callback()

        self._after_id = self.after(max(0, delay_ms), wrapper)

    def set_service(self, service: Optional[ProjectService]) -> None:
        """Attach the active project service."""
        self._service = service

    def frame_count(self) -> int:
        """Return the loaded clip's frame count (0 if none)."""
        return self._frame_count

    def clip_duration_seconds(self) -> float:
        """Return playback length of the loaded clip in seconds."""
        return self._frame_count / max(self._fps, 0.001)

    def play_for_voiceover(
        self,
        *,
        include_source_audio: bool,
        on_finished: Callable[[], None],
    ) -> None:
        """Play the current clip from the start; call ``on_finished`` at end."""
        if self._capture is None or self._composition_mode:
            return
        self._on_playback_finished = on_finished
        self._playback_source_audio = include_source_audio
        self.stop_playback()
        self._show_frame(0)
        self._play()

    def clear(self) -> None:
        """Stop playback and reset the panel."""
        self.stop_playback()
        self._audio.stop()
        self._exit_composition_mode()
        self._release_capture()
        self._clip_id = None
        self._video_path = None
        self._trim_start_frame = 0
        self._frame_count = 0
        self._current_frame = 0
        self._photo = None
        self._last_frame_bgr = None
        self._clip_name_var.set("No clip selected")
        self._frame_total_var.set("—")
        self._sync_frame_entry(1)
        self._scrubber.configure(from_=0, to=0)
        self._scrubber.set(0)
        self._canvas.delete("frame")
        self._canvas.itemconfigure(self._placeholder, state="normal")
        canvas_w, canvas_h = self._canvas_size()
        self._canvas.coords(self._placeholder, canvas_w // 2, canvas_h // 2)
        self._set_controls_enabled(False)

    def load_composition(self, autoplay: bool = False) -> bool:
        """Load all clips in composition order for sequential preview."""
        if self._service is None:
            return False

        self.stop_playback()
        self._exit_composition_mode()

        clips = self._service.list_clips()
        if not clips:
            if self._on_status:
                self._on_status("Composition is empty.")
            return False

        try:
            import cv2  # type: ignore[import-untyped]
        except ImportError:
            self._show_error("OpenCV required for preview")
            return False

        segments: list[_CompositionSegment] = []
        for clip in clips:
            try:
                video_path = self._service.get_clip_video_path(clip)
            except ProjectServiceError:
                continue
            if not video_path.is_file():
                continue
            segment = self._build_segment(clip, video_path)
            if segment is not None:
                segments.append(segment)

        if not segments:
            self._show_error("No playable clips in composition")
            return False

        self._composition_mode = True
        self._composition_segments = segments
        self._composition_index = 0
        self._clip_id = None
        self._load_composition_segment(0)
        self._set_controls_enabled(True)
        self._set_composition_controls(True)
        self.after_idle(self._rerender_last_frame)

        if autoplay:
            self._play()
        elif self._on_status:
            self._on_status(
                f"Loaded composition ({len(segments)} clip"
                f"{'' if len(segments) == 1 else 's'}) — press Play"
            )
        return True

    def load_clip(self, clip_id: Optional[str], *, force: bool = False) -> None:
        """Load and show the first frame of a clip."""
        if clip_id is None or self._service is None:
            self.clear()
            return

        try:
            clip = self._service.get_clip(clip_id)
            video_path = self._service.get_clip_video_path(clip)
        except ProjectServiceError:
            self.clear()
            return

        if (
            not force
            and not self._composition_mode
            and clip_id == self._clip_id
            and self._capture is not None
            and video_path == self._video_path
        ):
            return

        self.stop_playback()
        self._exit_composition_mode()
        self._release_capture()
        self._clip_id = clip_id
        self._audio_enabled = audio_playback_available()

        if not video_path.is_file():
            self._show_error("Video file not found")
            return

        try:
            import cv2  # type: ignore[import-untyped]
        except ImportError:
            self._show_error("OpenCV required for preview")
            return

        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            capture.release()
            self._show_error("Unable to open video")
            return

        resource = self._service.get_resource(clip.resource_id)
        capture_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        fps = normalize_fps(resource.fps, capture_fps)
        trim_start, trim_end = clip_playback_trim(clip)
        frame_count = resolve_playback_frame_count(
            video_path,
            trim_start_frame=trim_start,
            trim_end_frame=trim_end,
            resource_duration_frames=resource.duration_frames,
        )

        self._capture = capture
        self._video_path = video_path
        self._fps = fps
        self._frame_count = frame_count
        self._current_frame = 0
        self._trim_start_frame = trim_start or 0
        self._clip_name_var.set(clip.display_name)
        self._scrubber.configure(from_=0, to=max(frame_count - 1, 0))
        self._scrubber.set(0)
        self._frame_total_var.set(f"/ {frame_count}")
        self._set_controls_enabled(True)
        self._set_composition_controls(False)
        self._show_frame(0)
        self.after_idle(self._rerender_last_frame)

    def _canvas_size(self) -> tuple[int, int]:
        """Return the drawable canvas size, falling back before first layout."""
        width = self._canvas.winfo_width()
        height = self._canvas.winfo_height()
        if width <= 1:
            width = self._canvas.winfo_reqwidth()
        if height <= 1:
            height = self._canvas.winfo_reqheight()
        return max(width, 1), max(height, 1)

    def _on_canvas_configure(self, event: tk.Event) -> None:
        """Re-fit the current frame when the preview area is resized."""
        if event.widget is not self._canvas or self._last_frame_bgr is None:
            return
        if self._resize_after_id is not None:
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(50, self._rerender_last_frame)

    def _rerender_last_frame(self) -> None:
        self._resize_after_id = None
        if self._last_frame_bgr is not None:
            self._render_frame_bgr(self._last_frame_bgr)

    def _exit_composition_mode(self) -> None:
        self._composition_mode = False
        self._composition_segments = []
        self._composition_index = 0
        self._set_composition_controls(False)

    def _build_segment(self, clip, video_path: Path) -> Optional[_CompositionSegment]:
        import cv2  # type: ignore[import-untyped]

        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            capture.release()
            return None

        resource = self._service.get_resource(clip.resource_id)
        capture_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        fps = normalize_fps(resource.fps, capture_fps)
        trim_start, trim_end = clip_playback_trim(clip)
        frame_count = resolve_playback_frame_count(
            video_path,
            trim_start_frame=trim_start,
            trim_end_frame=trim_end,
            resource_duration_frames=resource.duration_frames,
        )
        capture.release()

        return _CompositionSegment(
            clip_id=clip.id,
            display_name=clip.display_name,
            video_path=video_path,
            fps=fps,
            frame_count=frame_count,
        )

    def _load_composition_segment(self, index: int, show_first_frame: bool = True) -> None:
        segment = self._composition_segments[index]
        self._composition_index = index
        self._release_capture()

        import cv2  # type: ignore[import-untyped]

        capture = cv2.VideoCapture(str(segment.video_path))
        if not capture.isOpened():
            capture.release()
            return

        self._capture = capture
        self._video_path = segment.video_path
        self._fps = segment.fps
        self._frame_count = segment.frame_count
        self._current_frame = 0
        self._clip_id = segment.clip_id
        self._update_composition_label()
        self._scrubber.configure(from_=0, to=max(segment.frame_count - 1, 0))
        self._scrubber.set(0)
        self._frame_total_var.set(f"/ {segment.frame_count}")
        if show_first_frame:
            self._show_frame(0)

    def _update_composition_label(self) -> None:
        segment = self._composition_segments[self._composition_index]
        total = len(self._composition_segments)
        self._clip_name_var.set(
            f"Composition {self._composition_index + 1}/{total} — {segment.display_name}"
        )

    def _set_composition_controls(self, composition: bool) -> None:
        state = "disabled" if composition else "normal"
        if self._capture is None and not composition:
            state = "disabled"
        self._scrubber.configure(state=state)
        self._prev_frame_btn.configure(state=state)
        self._next_frame_btn.configure(state=state)
        self._frame_entry.configure(state=state)

    def _advance_composition_segment(self) -> bool:
        """Advance to the next clip in the composition."""
        if not self._composition_mode:
            return False
        next_index = self._composition_index + 1
        if next_index >= len(self._composition_segments):
            return False
        self._audio.stop()
        self._load_composition_segment(next_index, show_first_frame=False)
        return True

    def _start_playback_audio(self, start_time: float) -> None:
        if not self._audio_enabled or not self._playback_source_audio or self._video_path is None:
            return
        try:
            self._audio.start(self._video_path, start_time)
        except (ProjectServiceError, OSError):
            if self._on_status:
                self._on_status("Audio preview unavailable — playing video only.")

    def _continue_composition_playback(self) -> None:
        """Resume playback after switching to the next composition clip."""
        if not self._playing or self._video_path is None:
            return

        generation = self._playback_generation
        self._start_playback_audio(0.0)
        self._play_with_opencv(generation)

    def _finish_composition_playback(self) -> None:
        if self._on_status:
            self._on_status("Composition preview finished.")

    def _end_playback(self) -> None:
        """Stop at clip end; advance composition segments when applicable."""
        if self._composition_mode and self._advance_composition_segment():
            self._continue_composition_playback()
            return
        self._pause()
        if self._composition_mode:
            self._finish_composition_playback()
        else:
            self._notify_playback_finished()

    def toggle_play(self) -> None:
        """Start or pause playback."""
        if self._capture is None:
            return
        if self._playing:
            self._pause()
        else:
            self._play()

    def stop_playback(self) -> None:
        """Pause and return to the first frame."""
        if self._composition_mode:
            self._pause()
            self._composition_index = 0
            self._load_composition_segment(0)
            return

        self._pause()
        if self._capture is not None:
            self._show_frame(0)

    def pause(self) -> None:
        """Pause playback without changing the current frame."""
        self._pause()

    def release_media_handles(self) -> None:
        """Stop playback/audio and close the open video file (needed before overwriting versions/)."""
        self._pause()
        self._audio.stop()
        self._release_capture()
        self._video_path = None

    def _play(self) -> None:
        if self._capture is None or self._frame_count <= 0 or self._video_path is None:
            return

        if self._composition_mode:
            at_last_segment = self._composition_index >= len(self._composition_segments) - 1
            if at_last_segment and self._current_frame >= self._frame_count - 1:
                self._composition_index = 0
                self._load_composition_segment(0)
        elif self._current_frame >= self._frame_count - 1:
            self._show_frame(0)

        self._cancel_playback_timer()
        generation = self._bump_playback_generation()
        self._playing = True
        self._play_btn.configure(text="Pause")

        start_time = (self._trim_start_frame + self._current_frame) / self._fps
        self._start_playback_audio(start_time)
        self._play_with_opencv(generation)

    def _play_with_opencv(self, generation: int) -> None:
        """Advance video frames on a wall-clock schedule."""
        frame_interval = 1.0 / self._fps
        self._next_frame_deadline = time.perf_counter() + frame_interval
        self._playback_tick_opencv(generation)

    def _notify_playback_finished(self) -> None:
        callback = self._on_playback_finished
        self._on_playback_finished = None
        self._playback_source_audio = True
        if callback is not None and self.winfo_exists():
            self.after(0, callback)

    def _pause(self) -> None:
        was_playing = self._playing
        self._playing = False
        self._bump_playback_generation()
        self._play_btn.configure(text="Play")
        self._cancel_playback_timer()
        self._audio.stop()

    def _playback_tick_opencv(self, generation: int) -> None:
        """Advance playback using wall-clock timing at the clip's frame rate."""
        if not self._playback_active(generation) or self._capture is None:
            return

        frame_interval = 1.0 / self._fps
        now = time.perf_counter()

        while self._playing and now >= self._next_frame_deadline:
            if self._current_frame >= self._frame_count - 1:
                if self._composition_mode and self._advance_composition_segment():
                    self._next_frame_deadline = time.perf_counter() + frame_interval
                    now = time.perf_counter()
                    continue
                self._end_playback()
                return
            if not self._advance_frame_sequential():
                if self._current_frame >= self._frame_count - 1:
                    self._end_playback()
                else:
                    self._pause()
                return
            self._next_frame_deadline += frame_interval
            now = time.perf_counter()

            # Avoid runaway catch-up if rendering falls far behind.
            if now - self._next_frame_deadline > frame_interval * 5:
                self._next_frame_deadline = now + frame_interval

        wait_ms = max(1, int((self._next_frame_deadline - time.perf_counter()) * 1000))
        self._schedule_playback(
            wait_ms,
            lambda: self._playback_tick_opencv(generation),
            generation=generation,
        )

    def _apply_frame_count(self, frame_count: int) -> None:
        self._frame_count = max(frame_count, 1)
        self._scrubber.configure(from_=0, to=max(self._frame_count - 1, 0))
        self._frame_total_var.set(f"/ {self._frame_count}")

    def _advance_frame_sequential(self) -> bool:
        """Read and display the next frame without seeking (fast path for playback)."""
        if self._capture is None:
            return False

        import cv2  # type: ignore[import-untyped]

        next_index = self._current_frame + 1
        ok, frame = self._capture.read()
        if not ok and next_index < self._frame_count:
            self._capture.set(
                cv2.CAP_PROP_POS_FRAMES,
                self._trim_start_frame + next_index,
            )
            ok, frame = self._capture.read()
        if not ok:
            if next_index < self._frame_count:
                self._apply_frame_count(next_index)
            return False

        self._current_frame = next_index
        self._render_frame_bgr(frame)
        if not self._scrubbing:
            self._scrubber.set(self._current_frame)
        self._sync_frame_entry(self._current_frame + 1)
        return True

    def _show_frame(self, frame_index: int) -> None:
        if self._capture is None:
            return

        import cv2  # type: ignore[import-untyped]

        frame_index = max(0, min(frame_index, self._frame_count - 1))
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, self._trim_start_frame + frame_index)
        ok, frame = self._capture.read()
        if not ok:
            self._show_error("Failed to read frame")
            return

        self._current_frame = frame_index
        self._render_frame_bgr(frame)
        if not self._scrubbing:
            self._scrubber.set(frame_index)
        self._sync_frame_entry(frame_index + 1)

    def _step_frame(self, delta: int) -> None:
        """Move to the previous or next frame."""
        if self._capture is None or self._frame_count <= 0:
            return
        if self._playing:
            self._pause()
        target = max(0, min(self._current_frame + delta, self._frame_count - 1))
        if target != self._current_frame:
            self._show_frame(target)

    def _go_to_entered_frame(self, _event: object = None) -> None:
        """Jump to the frame number entered by the user (1-based)."""
        if self._syncing_entry or self._capture is None:
            return

        raw = self._frame_entry_var.get().strip()
        if not raw.isdigit():
            self._sync_frame_entry(self._current_frame + 1)
            return

        user_frame = int(raw)
        user_frame = max(1, min(user_frame, self._frame_count))
        if self._playing:
            self._pause()
        self._show_frame(user_frame - 1)

    def _sync_frame_entry(self, display_frame: int) -> None:
        """Update the frame entry without triggering a seek."""
        self._syncing_entry = True
        self._frame_entry_var.set(str(display_frame))
        self._syncing_entry = False

    def _render_frame_bgr(self, frame_bgr) -> None:
        import cv2  # type: ignore[import-untyped]

        self._last_frame_bgr = frame_bgr
        self._render_rgb(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))

    def _render_rgb(self, rgb) -> None:
        canvas_w, canvas_h = self._canvas_size()

        height, width = rgb.shape[:2]
        if width <= 0 or height <= 0:
            return

        scale = min(canvas_w / width, canvas_h / height)
        target_w = max(int(width * scale), 1)
        target_h = max(int(height * scale), 1)
        if target_w != width or target_h != height:
            import cv2  # type: ignore[import-untyped]

            interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            rgb = cv2.resize(rgb, (target_w, target_h), interpolation=interpolation)

        height, width = rgb.shape[:2]
        header = f"P6 {width} {height} 255 ".encode("ascii")
        self._photo = tk.PhotoImage(
            width=width,
            height=height,
            data=header + rgb.tobytes(),
            format="PPM",
        )

        self._canvas.delete("frame")
        self._canvas.itemconfigure(self._placeholder, state="hidden")
        x = canvas_w // 2
        y = canvas_h // 2
        self._canvas.create_image(x, y, image=self._photo, anchor="center", tags="frame")
        self._canvas.coords(self._placeholder, x, y)

    def _on_scrub_start(self, _event: object) -> None:
        self._scrubbing = True
        if self._playing:
            self._pause()

    def _on_scrub_end(self, _event: object) -> None:
        if self._capture is None:
            self._scrubbing = False
            return
        frame_index = int(float(self._scrubber.get()))
        self._scrubbing = False
        self._show_frame(frame_index)

    def _on_scrub(self, value: str) -> None:
        if self._capture is None or not self._scrubbing:
            return
        self._show_frame(int(float(value)))

    def _show_error(self, message: str) -> None:
        self.clear()
        self._clip_name_var.set(message)
        if self._on_status:
            self._on_status(message)

    def _release_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._play_btn.configure(state=state)
        self._scrubber.configure(state=state)
        self._prev_frame_btn.configure(state=state)
        self._next_frame_btn.configure(state=state)
        self._frame_entry.configure(state=state)
