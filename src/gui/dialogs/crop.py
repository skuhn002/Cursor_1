"""Dialog for cropping a clip between two flags."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from src.gui.dialogs.base import ModalDialog
from src.gui.flags import format_flag_choices
from src.gui.theme import Spacing
from src.models import Clip, Flag


class CropBetweenFlagsDialog(ModalDialog):
    """Choose start/end flags and an optional name for the cropped clip."""

    def __init__(
        self,
        parent,
        clip: Clip,
        flags: list[Flag],
        on_crop: Callable[[str, str, Optional[str]], None],
    ) -> None:
        super().__init__(parent, f"Crop — {clip.display_name}")
        self._on_crop = on_crop
        flag_choices = format_flag_choices(flags)
        labels = [label for label, _ in flag_choices]
        self._flag_map = dict(flag_choices)

        ttk.Label(
            self.body,
            text="Crop to the frame range between two flags.\n"
            "Flags at the clip edges crop to the beginning or end.",
            style="MutedSurface.TLabel",
            wraplength=400,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, Spacing.SECTION))

        ttk.Label(self.body, text="Start flag", style="MutedSurface.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 4)
        )
        self._start_var = tk.StringVar(value=labels[0] if labels else "")
        ttk.Combobox(
            self.body,
            textvariable=self._start_var,
            values=labels,
            state="readonly",
            width=44,
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, Spacing.SECTION))

        ttk.Label(self.body, text="End flag", style="MutedSurface.TLabel").grid(
            row=3, column=0, sticky="w", pady=(0, 4)
        )
        self._end_var = tk.StringVar(value=labels[-1] if labels else "")
        ttk.Combobox(
            self.body,
            textvariable=self._end_var,
            values=labels,
            state="readonly",
            width=44,
        ).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, Spacing.SECTION))

        ttk.Label(self.body, text="Display name (optional)", style="MutedSurface.TLabel").grid(
            row=5, column=0, sticky="w", pady=(0, 4)
        )
        self._name_var = tk.StringVar()
        ttk.Entry(self.body, textvariable=self._name_var, width=42).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(0, Spacing.SECTION)
        )

        self.body.columnconfigure(0, weight=1)
        self.add_button_row(7, "Create Crop", self._submit)

        self.update_idletasks()
        self.center_over(parent)

    def _submit(self) -> None:
        start_id = self._flag_map.get(self._start_var.get())
        end_id = self._flag_map.get(self._end_var.get())
        if not start_id or not end_id:
            messagebox.showwarning(
                "Missing flags",
                "Choose both a start and end flag.",
                parent=self,
            )
            return

        display_name = self._name_var.get().strip() or None
        self._on_crop(start_id, end_id, display_name)
        self.destroy()
