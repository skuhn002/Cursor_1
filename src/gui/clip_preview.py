"""Video preview panel for the Moment GUI."""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, Optional

from src.api.project_service import ProjectService, ProjectServiceError


class ClipPreviewPanel(ttk.LabelFrame):
    """Shows a selected clip with playback controls and frame scrubbing."""

    def __init__(
        self,
        parent: tk.Misc,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent, text="Preview", padding=12)
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

        self._clip_name_var = tk.StringVar(value="No clip selected")
        self._frame_info_var = tk.StringVar(value="Frame — / —")

        ttk.Label(self, textvariable=self._clip_name_var, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(0, 8)
        )

        self._canvas = tk.Canvas(
            self,
            width=480,
            height=270,
            bg="#111111",
            highlightthickness=1,
            highlightbackground="#cccccc",
        )
        self._canvas.pack(fill="both", expand=True)
        self._placeholder = self._canvas.create_text(
            240,
            135,
            text="Select a clip to preview",
            fill="#888888",
            font=("Segoe UI", 11),
        )

        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(8, 0))

        self._play_btn = ttk.Button(controls, text="Play", command=self.toggle_play, width=8)
        self._play_btn.pack(side="left")
        ttk.Button(controls, text="Stop", command=self.stop_playback, width=8).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(controls, textvariable=self._frame_info_var).pack(side="right")

        self._scrubber = ttk.Scale(
            self,
            from_=0,
            to=0,
            orient="horizontal",
            command=self._on_scrub,
        )
        self._scrubber.pack(fill="x", pady=(8, 0))
        self._scrubber.bind("<ButtonPress-1>", self._on_scrub_start)
        self._scrubber.bind("<ButtonRelease-1>", self._on_scrub_end)

        self._set_controls_enabled(False)

    def set_service(self, service: Optional[ProjectService]) -> None:
        """Attach the active project service."""
        self._service = service

    def clear(self) -> None:
        """Stop playback and reset the panel."""
        self.stop_playback()
        self._release_capture()
        self._clip_id = None
        self._video_path = None
        self._frame_count = 0
        self._current_frame = 0
        self._photo = None
        self._clip_name_var.set("No clip selected")
        self._frame_info_var.set("Frame — / —")
        self._scrubber.configure(from_=0, to=0)
        self._scrubber.set(0)
        self._canvas.delete("frame")
        self._canvas.itemconfigure(self._placeholder, state="normal")
        self._set_controls_enabled(False)

    def load_clip(self, clip_id: Optional[str]) -> None:
        """Load and show the first frame of a clip."""
        if clip_id is None or self._service is None:
            self.clear()
            return

        if clip_id == self._clip_id and self._capture is not None:
            return

        self.stop_playback()
        self._release_capture()
        self._clip_id = clip_id

        try:
            clip = self._service.get_clip(clip_id)
            video_path = self._service.get_clip_video_path(clip)
        except ProjectServiceError:
            self.clear()
            return

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
        fps = self._normalize_fps(resource.fps, capture_fps)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frame_count <= 0 and resource.duration_frames > 0:
            frame_count = resource.duration_frames
        if frame_count <= 0:
            frame_count = 1

        self._capture = capture
        self._video_path = video_path
        self._fps = fps
        self._frame_count = frame_count
        self._current_frame = 0
        self._clip_name_var.set(clip.display_name)
        self._scrubber.configure(from_=0, to=max(frame_count - 1, 0))
        self._scrubber.set(0)
        self._set_controls_enabled(True)
        self._show_frame(0)

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
        self._pause()
        if self._capture is not None:
            self._show_frame(0)

    def pause(self) -> None:
        """Pause playback without changing the current frame."""
        self._pause()

    def _play(self) -> None:
        if self._capture is None or self._frame_count <= 0:
            return
        if self._current_frame >= self._frame_count - 1:
            self._show_frame(0)

        self._playing = True
        self._play_btn.configure(text="Pause")
        frame_interval = 1.0 / self._fps
        self._next_frame_deadline = time.perf_counter() + frame_interval
        self._playback_tick()

    def _pause(self) -> None:
        self._playing = False
        self._play_btn.configure(text="Play")
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _playback_tick(self) -> None:
        """Advance playback using wall-clock timing at the clip's frame rate."""
        if not self._playing or self._capture is None:
            return

        frame_interval = 1.0 / self._fps
        now = time.perf_counter()

        while self._playing and now >= self._next_frame_deadline:
            if self._current_frame >= self._frame_count - 1:
                self._pause()
                return
            if not self._advance_frame_sequential():
                self._pause()
                return
            self._next_frame_deadline += frame_interval
            now = time.perf_counter()

            # Avoid runaway catch-up if rendering falls far behind.
            if now - self._next_frame_deadline > frame_interval * 5:
                self._next_frame_deadline = now + frame_interval

        wait_ms = max(1, int((self._next_frame_deadline - time.perf_counter()) * 1000))
        self._after_id = self.after(wait_ms, self._playback_tick)

    def _advance_frame_sequential(self) -> bool:
        """Read and display the next frame without seeking (fast path for playback)."""
        if self._capture is None:
            return False

        ok, frame = self._capture.read()
        if not ok:
            return False

        self._current_frame += 1
        self._render_frame(frame)
        if not self._scrubbing:
            self._scrubber.set(self._current_frame)
        self._frame_info_var.set(f"Frame {self._current_frame + 1} / {self._frame_count}")
        return True

    @staticmethod
    def _normalize_fps(resource_fps: float, capture_fps: float) -> float:
        """Pick a sensible playback frame rate from resource or container metadata."""
        for candidate in (resource_fps, capture_fps):
            if 1.0 <= candidate <= 240.0:
                return candidate
        return 30.0

    def _show_frame(self, frame_index: int) -> None:
        if self._capture is None:
            return

        import cv2  # type: ignore[import-untyped]

        frame_index = max(0, min(frame_index, self._frame_count - 1))
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = self._capture.read()
        if not ok:
            self._show_error("Failed to read frame")
            return

        self._current_frame = frame_index
        self._render_frame(frame)
        if not self._scrubbing:
            self._scrubber.set(frame_index)
        self._frame_info_var.set(f"Frame {frame_index + 1} / {self._frame_count}")

    def _render_frame(self, frame_bgr) -> None:
        import cv2  # type: ignore[import-untyped]

        canvas_w = max(self._canvas.winfo_width(), 480)
        canvas_h = max(self._canvas.winfo_height(), 270)

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        scale = min(canvas_w / width, canvas_h / height, 1.0)
        if scale < 1.0:
            rgb = cv2.resize(
                rgb,
                (max(int(width * scale), 1), max(int(height * scale), 1)),
                interpolation=cv2.INTER_AREA,
            )

        height, width = rgb.shape[:2]
        header = f"P6 {width} {height} 255 ".encode("ascii")
        self._photo = tk.PhotoImage(width=width, height=height, data=header + rgb.tobytes(), format="PPM")

        self._canvas.delete("frame")
        self._canvas.itemconfigure(self._placeholder, state="hidden")
        x = canvas_w // 2
        y = canvas_h // 2
        self._canvas.create_image(x, y, image=self._photo, anchor="center", tags="frame")

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
