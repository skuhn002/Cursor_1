"""Clip list panel with selection support."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from src.api.project_service import ProjectService
from src.gui.constants import CLIP_COLUMNS
from src.gui.theme import Colors, Fonts, Spacing
from src.models import Project


class ClipListPanel(ttk.LabelFrame):
    """Displays project clips in a selectable table."""

    def __init__(
        self,
        parent: tk.Misc,
        on_selection_changed: Callable[[Optional[str]], None],
    ) -> None:
        super().__init__(parent, text="Clips", padding=Spacing.SECTION, style="Card.TLabelframe")
        self._on_selection_changed = on_selection_changed
        self._service: Optional[ProjectService] = None

        self._tree = ttk.Treeview(
            self,
            columns=CLIP_COLUMNS,
            show="headings",
            selectmode="browse",
        )
        self._tree.heading("display_name", text="Name")
        self._tree.heading("frames", text="Frames")
        self._tree.heading("fps", text="FPS")
        self._tree.heading("flags", text="Flags")
        self._tree.heading("clip_id", text="Clip ID")

        self._tree.column("display_name", width=200, stretch=True)
        self._tree.column("frames", width=72, anchor="e")
        self._tree.column("fps", width=64, anchor="e")
        self._tree.column("flags", width=52, anchor="e")
        self._tree.column("clip_id", width=160, stretch=True)

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._empty_label = ttk.Label(
            self,
            text="No clips yet.\nImport a video to get started.",
            foreground=Colors.TEXT_MUTED,
            font=Fonts.BODY,
            justify="center",
        )

        self._tree.bind("<<TreeviewSelect>>", self._handle_selection)
        self._tree.bind("<ButtonRelease-1>", self._handle_selection)
        self._tree.bind("<KeyRelease-Up>", self._handle_selection)
        self._tree.bind("<KeyRelease-Down>", self._handle_selection)

    def set_service(self, service: Optional[ProjectService]) -> None:
        self._service = service

    def selected_clip_id(self) -> Optional[str]:
        selection = self._tree.selection()
        return selection[0] if selection else None

    def select_clip(self, clip_id: str) -> None:
        if self._tree.exists(clip_id):
            self._tree.selection_set(clip_id)
            self._tree.focus(clip_id)

    def refresh(self) -> None:
        """Reload clips from the current project."""
        for item in self._tree.get_children():
            self._tree.delete(item)

        project = self._service.project if self._service else None
        if project is None:
            self._show_empty()
            return

        clips = self._service.list_clips() if self._service else []
        if not clips:
            self._show_empty()
            return

        self._empty_label.place_forget()
        for clip in clips:
            self._tree.insert("", "end", iid=clip.id, values=self._row_values(clip, project))

    def _row_values(self, clip, project: Project) -> tuple:
        resource = project.resources.get(clip.resource_id)
        if clip.trim_start_frame is not None and clip.trim_end_frame is not None:
            frames = clip.trim_end_frame - clip.trim_start_frame + 1
        else:
            frames = resource.duration_frames if resource else 0
        fps = f"{resource.fps:.2f}" if resource else "—"
        return (clip.display_name, frames, fps, len(clip.flags), clip.id)

    def _show_empty(self) -> None:
        self._empty_label.place(relx=0.5, rely=0.5, anchor="center")

    def _handle_selection(self, _event: object = None) -> None:
        self._on_selection_changed(self.selected_clip_id())
