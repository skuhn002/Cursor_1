"""Clip list panels for workspace and composition."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Literal, Optional

from src.api.errors import ProjectServiceError
from src.api.project_service import ProjectService
from src.api.video import clip_playback_trim
from src.gui.constants import CLIP_COLUMNS, WORKSPACE_COLUMNS
from src.gui.theme import Colors, Fonts, Spacing
from src.models import Clip, Project

ListSource = Literal["composition", "workspace"]


def _clip_row_values(
    clip: Clip,
    project: Project,
    service: Optional[ProjectService] = None,
    order: Optional[int] = None,
) -> tuple:
    resource = project.resources.get(clip.resource_id)
    display_name = clip.display_name
    if resource and resource.media_kind == "image":
        display_name = f"{display_name} [image]"
    elif resource and getattr(clip, "clip_kind", "standard") == "merged":
        display_name = f"{display_name} [merged]"
    trim_start, trim_end = clip_playback_trim(clip)
    if trim_start is not None and trim_end is not None:
        frames = trim_end - trim_start + 1
    elif service is not None:
        try:
            frames = service.get_clip_playback_frame_count(clip)
        except ProjectServiceError:
            frames = resource.duration_frames if resource else 0
    else:
        frames = resource.duration_frames if resource else 0
    fps = f"{resource.fps:.2f}" if resource else "—"
    if order is None:
        return (display_name, frames, fps, len(clip.flags), clip.id)
    return (order, display_name, frames, fps, len(clip.flags), clip.id)


class _ClipTreePanel(ttk.LabelFrame):
    """Base selectable clip table."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        columns: tuple[str, ...],
        empty_text: str,
        on_selection_changed: Callable[[Optional[str], ListSource], None],
        source: ListSource,
    ) -> None:
        super().__init__(parent, text=title, padding=Spacing.SECTION, style="Card.TLabelframe")
        self._on_selection_changed = on_selection_changed
        self._source = source
        self._service: Optional[ProjectService] = None
        self._empty_text = empty_text

        self._tree = ttk.Treeview(
            self,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=6,
        )
        self._configure_columns(columns)

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._empty_label = ttk.Label(
            self,
            text=empty_text,
            foreground=Colors.TEXT_MUTED,
            font=Fonts.BODY,
            justify="center",
        )

        self._tree.bind("<<TreeviewSelect>>", self._handle_selection)
        self._tree.bind("<ButtonRelease-1>", self._handle_selection)
        self._tree.bind("<KeyRelease-Up>", self._handle_selection)
        self._tree.bind("<KeyRelease-Down>", self._handle_selection)

    def _configure_columns(self, columns: tuple[str, ...]) -> None:
        headings = {
            "order": "#",
            "display_name": "Name",
            "frames": "Frames",
            "fps": "FPS",
            "flags": "Flags",
            "clip_id": "Clip ID",
        }
        widths = {
            "order": (36, "e", False),
            "display_name": (160, "w", True),
            "frames": (64, "e", False),
            "fps": (56, "e", False),
            "flags": (48, "e", False),
            "clip_id": (140, "w", True),
        }
        for column in columns:
            self._tree.heading(column, text=headings[column])
            width, anchor, stretch = widths[column]
            self._tree.column(column, width=width, anchor=anchor, stretch=stretch)

    def set_service(self, service: Optional[ProjectService]) -> None:
        self._service = service

    def selected_clip_id(self) -> Optional[str]:
        selection = self._tree.selection()
        return selection[0] if selection else None

    def clear_selection(self) -> None:
        self._tree.selection_remove(self._tree.selection())

    def select_clip(self, clip_id: str) -> None:
        if self._tree.exists(clip_id):
            self._tree.selection_set(clip_id)
            self._tree.focus(clip_id)
            self._tree.see(clip_id)

    def refresh(self) -> None:
        raise NotImplementedError

    def _clear_rows(self) -> None:
        for item in self._tree.get_children():
            self._tree.delete(item)

    def _show_empty(self) -> None:
        self._empty_label.place(relx=0.5, rely=0.5, anchor="center")

    def _hide_empty(self) -> None:
        self._empty_label.place_forget()

    def _handle_selection(self, _event: object = None) -> None:
        if self.selected_clip_id():
            self._on_selection_changed(self.selected_clip_id(), self._source)


class CompositionPanel(_ClipTreePanel):
    """Ordered clips included in playback/export."""

    def __init__(
        self,
        parent: tk.Misc,
        on_selection_changed: Callable[[Optional[str], ListSource], None],
    ) -> None:
        super().__init__(
            parent,
            title="Composition",
            columns=CLIP_COLUMNS,
            empty_text="No clips in the composition.\nAdd clips from the workspace below.",
            on_selection_changed=on_selection_changed,
            source="composition",
        )

    def refresh(self) -> None:
        self._clear_rows()
        project = self._service.project if self._service else None
        if project is None or self._service is None:
            self._show_empty()
            return

        clips = self._service.list_clips()
        if not clips:
            self._show_empty()
            return

        self._hide_empty()
        for index, clip in enumerate(clips, start=1):
            self._tree.insert(
                "",
                "end",
                iid=clip.id,
                values=_clip_row_values(clip, project, service=self._service, order=index),
            )


class WorkspacePanel(_ClipTreePanel):
    """Clips available in the project but not yet in the composition."""

    def __init__(
        self,
        parent: tk.Misc,
        on_selection_changed: Callable[[Optional[str], ListSource], None],
    ) -> None:
        super().__init__(
            parent,
            title="Workspace",
            columns=WORKSPACE_COLUMNS,
            empty_text="No workspace clips.\nImported clips appear here until added to the composition.",
            on_selection_changed=on_selection_changed,
            source="workspace",
        )

    def refresh(self) -> None:
        self._clear_rows()
        project = self._service.project if self._service else None
        if project is None or self._service is None:
            self._show_empty()
            return

        clips = self._service.list_workspace_clips()
        if not clips:
            self._show_empty()
            return

        self._hide_empty()
        for clip in clips:
            self._tree.insert(
                "",
                "end",
                iid=clip.id,
                values=_clip_row_values(clip, project, service=self._service),
            )


class ClipsSidebar(ttk.Frame):
    """Workspace and composition clip lists with shared selection."""

    def __init__(
        self,
        parent: tk.Misc,
        on_selection_changed: Callable[[Optional[str]], None],
        on_clip_activated: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._callback = on_selection_changed
        self._on_clip_activated = on_clip_activated
        self._active_source: Optional[ListSource] = None
        self._service: Optional[ProjectService] = None

        self._composition = CompositionPanel(self, on_selection_changed=self._on_panel_select)
        self._composition.pack(fill="both", expand=True, pady=(0, Spacing.CONTROL_GAP))

        self._workspace = WorkspacePanel(self, on_selection_changed=self._on_panel_select)
        self._workspace.pack(fill="both", expand=True)

        if on_clip_activated is not None:
            self._composition._tree.bind(
                "<Double-Button-1>",
                lambda event: self._handle_double_click(event, "composition"),
            )
            self._workspace._tree.bind(
                "<Double-Button-1>",
                lambda event: self._handle_double_click(event, "workspace"),
            )

    def set_service(self, service: Optional[ProjectService]) -> None:
        self._service = service
        self._composition.set_service(service)
        self._workspace.set_service(service)

    def selected_clip_id(self) -> Optional[str]:
        return self._composition.selected_clip_id() or self._workspace.selected_clip_id()

    def selected_in_composition(self) -> bool:
        return self._active_source == "composition"

    def refresh(self) -> None:
        self._composition.refresh()
        self._workspace.refresh()

    def select_clip(self, clip_id: str) -> None:
        if self._service and self._service.is_in_composition(clip_id):
            self._workspace.clear_selection()
            self._composition.select_clip(clip_id)
            self._active_source = "composition"
        else:
            self._composition.clear_selection()
            self._workspace.select_clip(clip_id)
            self._active_source = "workspace"
        self._callback(clip_id)

    def _on_panel_select(self, clip_id: Optional[str], source: ListSource) -> None:
        if clip_id is None:
            return
        if source == "composition":
            self._workspace.clear_selection()
        else:
            self._composition.clear_selection()
        self._active_source = source
        self._callback(clip_id)

    def _handle_double_click(self, event: object, source: ListSource) -> None:
        if self._on_clip_activated is None:
            return
        tree = self._composition._tree if source == "composition" else self._workspace._tree
        item = tree.identify_row(getattr(event, "y", 0))
        if item:
            self._on_clip_activated(item)


# Backward-compatible alias for imports that still reference ClipListPanel.
ClipListPanel = ClipsSidebar
