"""Dialog for placing a clip in the composition."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Literal, Optional

from src.api.project_service import ProjectService
from src.gui.dialogs.base import ModalDialog
from src.gui.theme import Spacing
from src.models import Clip

PlacementMode = Literal["start", "end", "before", "after", "between"]


class InsertClipDialog(ModalDialog):
    """Choose where to place a clip in the project composition."""

    def __init__(
        self,
        parent,
        service: ProjectService,
        clips: list[Clip],
        selected_clip_id: Optional[str],
        on_insert: Callable[[str, PlacementMode, Optional[str], Optional[str]], None],
    ) -> None:
        super().__init__(parent, "Insert Clip in Composition")
        self._service = service
        self._on_insert = on_insert
        self._clip_map = {clip.id: clip for clip in clips}
        composition_ids = set(service.list_composition())
        self._labels = [self._clip_label_with_status(clip, composition_ids) for clip in clips]
        self._label_to_id = {
            self._clip_label_with_status(clip, composition_ids): clip.id for clip in clips
        }
        self._reference_clips = [clip for clip in clips if clip.id in composition_ids]
        self._reference_labels = [self._clip_label(clip) for clip in self._reference_clips]
        self._reference_label_to_id = {
            self._clip_label(clip): clip.id for clip in self._reference_clips
        }
        self._simple_label_to_id = {self._clip_label(clip): clip.id for clip in clips}

        ttk.Label(
            self.body,
            text="Add a workspace clip to the composition or reorder clips already included.",
            style="MutedSurface.TLabel",
            wraplength=440,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, Spacing.SECTION))

        ttk.Label(self.body, text="Clip to place", style="MutedSurface.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 4)
        )
        default_label = ""
        if selected_clip_id and selected_clip_id in self._clip_map:
            default_label = self._clip_label_with_status(
                self._clip_map[selected_clip_id], composition_ids
            )
        elif self._labels:
            workspace_defaults = [
                self._clip_label_with_status(clip, composition_ids)
                for clip in clips
                if clip.id not in composition_ids
            ]
            default_label = workspace_defaults[0] if workspace_defaults else self._labels[0]
        self._clip_var = tk.StringVar(value=default_label)
        ttk.Combobox(
            self.body,
            textvariable=self._clip_var,
            values=self._labels,
            state="readonly",
            width=48,
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, Spacing.SECTION))

        ttk.Label(self.body, text="Position", style="MutedSurface.TLabel").grid(
            row=3, column=0, sticky="w", pady=(0, 4)
        )
        self._mode_var = tk.StringVar(value="end" if not composition_ids else "after")
        mode_frame = ttk.Frame(self.body, style="Surface.TFrame")
        mode_frame.grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, Spacing.SECTION))

        for value, label in (
            ("start", "At start"),
            ("end", "At end"),
            ("before", "Before clip"),
            ("after", "After clip"),
            ("between", "Between two clips"),
        ):
            ttk.Radiobutton(
                mode_frame,
                text=label,
                value=value,
                variable=self._mode_var,
                command=self._update_mode_fields,
            ).pack(anchor="w", pady=2)

        self._reference_label = ttk.Label(
            self.body, text="Reference clip", style="MutedSurface.TLabel"
        )
        self._reference_var = tk.StringVar(
            value=self._reference_labels[0] if self._reference_labels else ""
        )
        self._reference_combo = ttk.Combobox(
            self.body,
            textvariable=self._reference_var,
            values=self._reference_labels,
            state="readonly",
            width=48,
        )

        self._before_label = ttk.Label(
            self.body, text="After clip", style="MutedSurface.TLabel"
        )
        self._before_var = tk.StringVar()
        self._before_combo = ttk.Combobox(
            self.body,
            textvariable=self._before_var,
            values=[],
            state="readonly",
            width=48,
        )

        self._after_label = ttk.Label(
            self.body, text="Before clip", style="MutedSurface.TLabel"
        )
        self._after_var = tk.StringVar()
        self._after_combo = ttk.Combobox(
            self.body,
            textvariable=self._after_var,
            values=[],
            state="readonly",
            width=48,
        )

        self._mode_row = 5
        self._reference_row = 6
        self._before_row = 7
        self._after_row = 9

        self.body.columnconfigure(0, weight=1)
        self.add_button_row(11, "Insert", self._submit)
        self._refresh_between_choices()
        self._update_mode_fields()

        self.update_idletasks()
        self.center_over(parent)

    @staticmethod
    def _clip_label(clip: Clip) -> str:
        return f"{clip.display_name} ({clip.id})"

    @staticmethod
    def _clip_label_with_status(clip: Clip, composition_ids: set[str]) -> str:
        if clip.id in composition_ids:
            return f"{clip.display_name} [in composition] ({clip.id})"
        return f"{clip.display_name} [workspace] ({clip.id})"

    def _refresh_between_choices(self) -> None:
        pairs = self._adjacent_pairs()
        before_labels = [self._clip_label(self._clip_map[before_id]) for before_id, _ in pairs]
        after_labels = [self._clip_label(self._clip_map[after_id]) for _, after_id in pairs]
        pair_labels = [
            f"{self._clip_label(self._clip_map[before_id])}  →  {self._clip_label(self._clip_map[after_id])}"
            for before_id, after_id in pairs
        ]
        self._between_pairs = pairs
        self._between_pair_labels = pair_labels

        if pair_labels:
            self._before_combo.configure(values=before_labels)
            self._after_combo.configure(values=after_labels)
            self._before_var.set(before_labels[0])
            self._after_var.set(after_labels[0])
        else:
            self._before_combo.configure(values=[])
            self._after_combo.configure(values=[])
            self._before_var.set("")
            self._after_var.set("")

    def _adjacent_pairs(self) -> list[tuple[str, str]]:
        ordered_ids = self._service.list_composition()
        return [
            (ordered_ids[index], ordered_ids[index + 1])
            for index in range(len(ordered_ids) - 1)
        ]

    def _update_mode_fields(self) -> None:
        for widget in (
            self._reference_label,
            self._reference_combo,
            self._before_label,
            self._before_combo,
            self._after_label,
            self._after_combo,
        ):
            widget.grid_remove()

        mode = self._mode_var.get()
        if mode in ("before", "after"):
            self._reference_label.grid(
                row=self._reference_row, column=0, sticky="w", pady=(0, 4)
            )
            self._reference_combo.grid(
                row=self._reference_row + 1,
                column=0,
                columnspan=2,
                sticky="ew",
                pady=(0, Spacing.SECTION),
            )
        elif mode == "between":
            self._before_label.grid(
                row=self._before_row, column=0, sticky="w", pady=(0, 4)
            )
            self._before_combo.grid(
                row=self._before_row + 1,
                column=0,
                columnspan=2,
                sticky="ew",
                pady=(0, Spacing.CONTROL_GAP),
            )
            self._after_label.grid(
                row=self._after_row, column=0, sticky="w", pady=(0, 4)
            )
            self._after_combo.grid(
                row=self._after_row + 1,
                column=0,
                columnspan=2,
                sticky="ew",
                pady=(0, Spacing.SECTION),
            )

    def _submit(self) -> None:
        clip_id = self._label_to_id.get(self._clip_var.get())
        if not clip_id:
            messagebox.showerror("Invalid clip", "Choose a clip to place.", parent=self)
            return

        mode = self._mode_var.get()
        reference_id: Optional[str] = None
        after_reference_id: Optional[str] = None

        if mode in ("before", "after"):
            reference_id = self._reference_label_to_id.get(self._reference_var.get())
            if not reference_id:
                messagebox.showerror(
                    "Invalid reference",
                    "Choose a reference clip.",
                    parent=self,
                )
                return
        elif mode == "between":
            if not self._between_pairs:
                messagebox.showerror(
                    "Not enough clips",
                    "Need at least two clips in the composition to insert between them.",
                    parent=self,
                )
                return
            before_id = self._simple_label_to_id.get(self._before_var.get())
            after_id = self._simple_label_to_id.get(self._after_var.get())
            if not before_id or not after_id:
                messagebox.showerror(
                    "Invalid selection",
                    "Choose the clip pair to insert between.",
                    parent=self,
                )
                return
            if (before_id, after_id) not in self._between_pairs:
                messagebox.showerror(
                    "Not adjacent",
                    "The selected clips are not next to each other in the composition.",
                    parent=self,
                )
                return
            reference_id = before_id
            after_reference_id = after_id

        self._on_insert(clip_id, mode, reference_id, after_reference_id)
        self.destroy()
