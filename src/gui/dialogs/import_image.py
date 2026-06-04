"""Dialog for importing a still image as a workspace clip."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Literal, Optional

from src.api.errors import ProjectServiceError
from src.api.video import IMAGE_CLIP_FRAME_COUNT, IMAGE_CLIP_FPS, resolve_image_clip_frames
from src.gui.constants import IMAGE_FILETYPES
from src.gui.dialogs.base import ModalDialog
from src.gui.theme import Spacing

DurationUnit = Literal["frames", "seconds"]
OnImportImage = Callable[[Path, Optional[str], int], None]


class ImportImageDialog(ModalDialog):
    """Pick an image file, display name, and clip duration."""

    def __init__(self, parent, on_import: OnImportImage) -> None:
        super().__init__(parent, "Import Image")
        self._on_import = on_import

        ttk.Label(
            self.body,
            text="Images are added to the workspace as timed clips at 30 fps.",
            style="MutedSurface.TLabel",
            wraplength=400,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, Spacing.SECTION))

        ttk.Label(self.body, text="Image file", style="MutedSurface.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 4)
        )
        self._file_var = tk.StringVar()
        ttk.Entry(self.body, textvariable=self._file_var, width=38).grid(
            row=2, column=0, sticky="ew", pady=(0, Spacing.SECTION)
        )
        ttk.Button(self.body, text="Browse…", command=self._browse_file).grid(
            row=2, column=1, padx=(8, 0), pady=(0, Spacing.SECTION)
        )

        ttk.Label(self.body, text="Display name (optional)", style="MutedSurface.TLabel").grid(
            row=3, column=0, sticky="w", pady=(0, 4)
        )
        self._name_var = tk.StringVar()
        ttk.Entry(self.body, textvariable=self._name_var, width=42).grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(0, Spacing.SECTION)
        )

        ttk.Label(self.body, text="Duration", style="MutedSurface.TLabel").grid(
            row=5, column=0, sticky="w", pady=(0, 4)
        )
        duration_frame = ttk.Frame(self.body, style="Surface.TFrame")
        duration_frame.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, Spacing.SECTION))

        self._duration_unit = tk.StringVar(value="frames")
        ttk.Radiobutton(
            duration_frame,
            text="Frames",
            value="frames",
            variable=self._duration_unit,
            command=self._on_duration_unit_changed,
        ).pack(side="left")
        ttk.Radiobutton(
            duration_frame,
            text="Seconds",
            value="seconds",
            variable=self._duration_unit,
            command=self._on_duration_unit_changed,
        ).pack(side="left", padx=(Spacing.CONTROL_GAP, 0))

        self._duration_var = tk.StringVar(value=str(IMAGE_CLIP_FRAME_COUNT))
        ttk.Entry(duration_frame, textvariable=self._duration_var, width=10).pack(
            side="left", padx=(Spacing.CONTROL_GAP, 4)
        )
        self._duration_hint = ttk.Label(
            duration_frame,
            text="frames",
            style="MutedSurface.TLabel",
        )
        self._duration_hint.pack(side="left")

        self.body.columnconfigure(0, weight=1)
        self.add_button_row(7, "Import Image", self._submit)

        self.update_idletasks()
        self.center_over(parent)

    def _on_duration_unit_changed(self) -> None:
        unit = self._duration_unit.get()
        if unit == "seconds":
            self._duration_hint.configure(text=f"sec @ {IMAGE_CLIP_FPS:.0f} fps")
            if self._duration_var.get().strip() == str(IMAGE_CLIP_FRAME_COUNT):
                self._duration_var.set("1")
        else:
            self._duration_hint.configure(text="frames")
            if self._duration_var.get().strip() in ("1", "1.0"):
                self._duration_var.set(str(IMAGE_CLIP_FRAME_COUNT))

    def _browse_file(self) -> None:
        file_path = self.ask_open_filename(
            title="Select image file",
            filetypes=IMAGE_FILETYPES,
        )
        if file_path:
            self._file_var.set(file_path)
            if not self._name_var.get().strip():
                self._name_var.set(Path(file_path).stem)

    def _parse_duration(self) -> int:
        raw = self._duration_var.get().strip()
        if not raw:
            raise ProjectServiceError("Enter a duration for the image clip.")

        unit = self._duration_unit.get()
        try:
            if unit == "seconds":
                return resolve_image_clip_frames(seconds=float(raw))
            return resolve_image_clip_frames(frames=int(raw))
        except ValueError as exc:
            raise ProjectServiceError(
                f"Invalid {'seconds' if unit == 'seconds' else 'frame count'}: {raw}"
            ) from exc
        except ProjectServiceError:
            raise
        except Exception as exc:
            raise ProjectServiceError(f"Invalid duration: {raw}") from exc

    def _submit(self) -> None:
        file_path = Path(self._file_var.get().strip()).expanduser()
        if not file_path.is_file():
            messagebox.showwarning(
                "Missing file",
                "Choose a valid image file to import.",
                parent=self,
            )
            return

        try:
            frame_count = self._parse_duration()
        except ProjectServiceError as exc:
            messagebox.showerror("Invalid duration", str(exc), parent=self)
            return

        display_name = self._name_var.get().strip() or None
        self._on_import(file_path, display_name, frame_count)
        self.destroy()
