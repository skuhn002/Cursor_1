"""Main application window for Moment."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional, TypeVar

from src.api.errors import ProjectServiceError
from src.api.project_service import ProjectService
from src.gui.dialogs import (
    AddFlagDialog,
    CropBetweenFlagsDialog,
    DuplicateClipDialog,
    ImportImageDialog,
    ImportVideoDialog,
    InsertClipDialog,
    NewProjectDialog,
    configure_voiceover_default,
)
from src.gui.windows import ClipEditorWindow
from src.gui.dialogs.insert_clip import PlacementMode
from src.gui.panels import ClipListPanel, ClipPreviewPanel
from src.gui.theme import Colors, Fonts, Spacing, apply_theme
from src.models import Clip
from src.project_state import load_active_project_path, save_active_project_path

T = TypeVar("T")


class MomentApp:
    """Coordinates the GUI, project service, and background tasks."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Moment")
        self.root.minsize(980, 600)
        self.root.geometry("1140x680")

        apply_theme(root)

        self.service = ProjectService()
        self._busy = False
        self._clip_editor: Optional[ClipEditorWindow] = None
        self._status_var = tk.StringVar(value="Ready")

        self._build_menu()
        self._build_layout()

        self._set_project_loaded(False)
        self._restore_last_project()

    # ------------------------------------------------------------------ UI setup

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Project…", command=self.new_project, accelerator="Ctrl+N")
        file_menu.add_command(label="Open Project…", command=self.open_project, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Import Video…", command=self.import_video, accelerator="Ctrl+I")
        file_menu.add_command(label="Import Image…", command=self.import_image)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        clip_menu = tk.Menu(menubar, tearoff=0)
        clip_menu.add_command(
            label="Edit Clip in Window…",
            command=self.open_clip_editor,
            accelerator="Ctrl+E",
        )
        clip_menu.add_command(
            label="Duplicate Clip…",
            command=self.duplicate_clip,
            accelerator="Ctrl+D",
        )
        clip_menu.add_separator()
        clip_menu.add_command(
            label="Voice-over Audio Default…",
            command=self.configure_voiceover_default,
        )
        clip_menu.add_separator()
        clip_menu.add_command(label="Add Flag…", command=self.add_flag, accelerator="Ctrl+F")
        clip_menu.add_command(label="Crop Between Flags…", command=self.crop_clip, accelerator="Ctrl+K")
        clip_menu.add_command(
            label="Insert in Composition…",
            command=self.insert_in_composition,
            accelerator="Ctrl+Shift+I",
        )
        clip_menu.add_command(
            label="Remove from Composition",
            command=self.remove_from_composition,
        )
        clip_menu.add_command(
            label="Merge Composition to Clip…",
            command=self.merge_composition,
        )
        clip_menu.add_command(
            label="Preview Composition",
            command=self.preview_composition,
            accelerator="Ctrl+Shift+P",
        )
        menubar.add_cascade(label="Clip", menu=clip_menu)
        self._clip_menu = clip_menu

        self.root.config(menu=menubar)
        self.root.bind("<Control-n>", lambda _e: self.new_project())
        self.root.bind("<Control-o>", lambda _e: self.open_project())
        self.root.bind("<Control-i>", lambda _e: self.import_video())
        self.root.bind("<Control-f>", lambda _e: self.add_flag())
        self.root.bind("<Control-k>", lambda _e: self.crop_clip())
        self.root.bind("<Control-Shift-I>", lambda _e: self.insert_in_composition())
        self.root.bind("<Control-Shift-P>", lambda _e: self.preview_composition())
        self.root.bind("<Control-e>", lambda _e: self.open_clip_editor())
        self.root.bind("<Control-d>", lambda _e: self.duplicate_clip())

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=Spacing.WINDOW)
        outer.pack(fill="both", expand=True)

        self._build_header(outer)
        self._build_toolbar(outer)

        content = ttk.Frame(outer)
        content.pack(fill="both", expand=True, pady=(Spacing.SECTION, 0))

        self._clip_list = ClipListPanel(
            content,
            on_selection_changed=self._on_clip_selected,
            on_clip_activated=self.open_clip_editor,
        )
        self._clip_list.pack(side="left", fill="both", expand=True, padx=(0, Spacing.CONTROL_GAP))

        self._preview = ClipPreviewPanel(content, on_status=self._status_var.set)
        self._preview.pack(side="right", fill="both", expand=True, padx=(Spacing.CONTROL_GAP, 0))

        status = ttk.Frame(self.root, padding=(Spacing.WINDOW, 8), style="Status.TFrame")
        status.pack(fill="x", side="bottom")
        ttk.Label(status, textvariable=self._status_var, style="Muted.TLabel").pack(anchor="w")

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.LabelFrame(parent, text="Project", padding=Spacing.SECTION, style="Card.TLabelframe")
        header.pack(fill="x", pady=(0, Spacing.SECTION))

        self._project_name_var = tk.StringVar(value="No project open")
        self._project_path_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self._project_name_var, style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, textvariable=self._project_path_var, style="MutedSurface.TLabel").pack(
            anchor="w", pady=(4, 0)
        )

    def _build_toolbar(self, parent: ttk.Frame) -> None:
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x")

        self._new_btn = ttk.Button(toolbar, text="New Project", command=self.new_project)
        self._open_btn = ttk.Button(toolbar, text="Open Project", command=self.open_project)
        self._import_btn = ttk.Button(
            toolbar, text="Import Video", style="Accent.TButton", command=self.import_video
        )
        self._import_image_btn = ttk.Button(
            toolbar, text="Import Image", command=self.import_image
        )
        self._edit_clip_btn = ttk.Button(
            toolbar,
            text="Edit Clip",
            style="Accent.TButton",
            command=self.open_clip_editor,
        )
        self._duplicate_btn = ttk.Button(
            toolbar,
            text="Duplicate Clip",
            command=self.duplicate_clip,
        )
        self._add_flag_btn = ttk.Button(toolbar, text="Add Flag", command=self.add_flag)
        self._crop_btn = ttk.Button(toolbar, text="Crop Between Flags", command=self.crop_clip)
        self._insert_btn = ttk.Button(
            toolbar, text="Add to Composition", command=self.insert_in_composition
        )
        self._remove_comp_btn = ttk.Button(
            toolbar, text="Remove from Composition", command=self.remove_from_composition
        )
        self._merge_comp_btn = ttk.Button(
            toolbar, text="Merge Composition", command=self.merge_composition
        )
        self._preview_comp_btn = ttk.Button(
            toolbar,
            text="Preview Composition",
            style="Accent.TButton",
            command=self.preview_composition,
        )

        for index, button in enumerate(
            (
                self._new_btn,
                self._open_btn,
                self._import_btn,
                self._import_image_btn,
                self._edit_clip_btn,
                self._duplicate_btn,
                self._add_flag_btn,
                self._crop_btn,
                self._insert_btn,
                self._remove_comp_btn,
                self._merge_comp_btn,
                self._preview_comp_btn,
            )
        ):
            button.pack(side="left", padx=(0, Spacing.CONTROL_GAP if index < 11 else 0))

    # ------------------------------------------------------------------ State

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        for button in (self._new_btn, self._open_btn, self._import_btn):
            button.configure(state="disabled" if busy else "normal")
        self._import_image_btn.configure(
            state="disabled" if busy else ("normal" if self.service.project else "disabled")
        )

        if busy:
            self._edit_clip_btn.configure(state="disabled")
            self._duplicate_btn.configure(state="disabled")
            self._add_flag_btn.configure(state="disabled")
            self._crop_btn.configure(state="disabled")
            self._insert_btn.configure(state="disabled")
            self._remove_comp_btn.configure(state="disabled")
            self._merge_comp_btn.configure(state="disabled")
            self._preview_comp_btn.configure(state="disabled")
            self._preview.pause()
        else:
            self._update_clip_actions()

        if message:
            self._status_var.set(message)
        elif not busy and not self._clip_list.selected_clip_id():
            self._status_var.set("Ready")

    def _set_project_loaded(self, loaded: bool) -> None:
        self._clip_list.set_service(self.service if loaded else None)
        self._preview.set_service(self.service if loaded else None)
        self._import_btn.configure(state="normal" if loaded else "disabled")
        self._import_image_btn.configure(state="normal" if loaded else "disabled")

        if not loaded:
            self._preview.clear()
            self._clip_list.refresh()

        self._update_clip_actions()

    def _update_clip_actions(self) -> None:
        clip_selected = bool(self._clip_list.selected_clip_id())
        clip_state = "normal" if clip_selected and not self._busy else "disabled"
        has_clips = bool(self.service.project and self.service.project.clips)
        has_composition = bool(
            self.service.project and self.service.list_composition() and not self._busy
        )
        selected_id = self._clip_list.selected_clip_id()
        selected_in_composition = (
            bool(selected_id and self.service.project and self.service.is_in_composition(selected_id))
            if not self._busy
            else False
        )

        self._edit_clip_btn.configure(state=clip_state)
        self._duplicate_btn.configure(state=clip_state)
        self._add_flag_btn.configure(state=clip_state)
        self._crop_btn.configure(state=clip_state)
        self._insert_btn.configure(state="normal" if has_clips and not self._busy else "disabled")
        self._remove_comp_btn.configure(
            state="normal" if selected_in_composition else "disabled"
        )
        self._preview_comp_btn.configure(state="normal" if has_composition else "disabled")
        self._merge_comp_btn.configure(state=self._preview_comp_btn.cget("state"))
        # Clip menu indices: 0 edit, 1 duplicate, 2 sep, 3 VO default, 4 sep,
        # 5 flag, 6 crop, 7 insert, 8 remove, 9 merge, 10 preview.
        project_state = "normal" if self.service.project and not self._busy else "disabled"
        self._clip_menu.entryconfigure(0, state=clip_state)
        self._clip_menu.entryconfigure(1, state=clip_state)
        self._clip_menu.entryconfigure(3, state=project_state)
        self._clip_menu.entryconfigure(5, state=clip_state)
        self._clip_menu.entryconfigure(6, state=clip_state)
        self._clip_menu.entryconfigure(7, state=self._insert_btn.cget("state"))
        self._clip_menu.entryconfigure(8, state=self._remove_comp_btn.cget("state"))
        self._clip_menu.entryconfigure(9, state=self._merge_comp_btn.cget("state"))
        self._clip_menu.entryconfigure(10, state=self._preview_comp_btn.cget("state"))

        if self._busy or self.service.project is None or not clip_selected:
            return

        clip = self.service.get_clip(selected_id)
        flag_count = len(clip.flags)
        location = "composition" if selected_in_composition else "workspace"
        suffix = f"{flag_count} flag(s)" if flag_count else "add flags or crop to clip edges"
        self._status_var.set(f"Selected “{clip.display_name}” ({location}) — {suffix}")

    def _on_clip_selected(self, clip_id: Optional[str]) -> None:
        self._update_clip_actions()
        self._preview.load_clip(clip_id)

    def open_clip_editor(self, clip_id: Optional[str] = None) -> None:
        """Open the per-clip editor window for the selected clip."""
        if self._busy or self.service.project is None:
            return
        target = clip_id or self._clip_list.selected_clip_id()
        if not target:
            messagebox.showinfo(
                "Edit clip",
                "Select a clip in the workspace or composition first.",
                parent=self.root,
            )
            return
        if self._clip_editor is not None and self._clip_editor.winfo_exists():
            if getattr(self._clip_editor, "_clip_id", None) == target:
                self._clip_editor.lift()
                self._clip_editor.focus_force()
                return
            self._clip_editor.destroy()

        self._clip_editor = ClipEditorWindow(
            self.root,
            self.service,
            target,
            on_clip_updated=self._on_clip_edited,
            on_status=self._status_var.set,
            on_release_media=self._preview.release_media_handles,
        )

    def configure_voiceover_default(self) -> None:
        configure_voiceover_default(self.root)

    def _on_clip_edited(self, clip: Clip) -> None:
        self._clip_list.refresh()
        self._clip_list.select_clip(clip.id)
        self._preview.load_clip(clip.id, force=True)
        self._update_clip_actions()
        self._status_var.set(f"Updated clip “{clip.display_name}”")

    def _refresh_view(self, project_name: str) -> None:
        assert self.service.project_path is not None
        self._project_name_var.set(project_name)
        self._project_path_var.set(str(self.service.project_path))
        self._set_project_loaded(True)
        self._clip_list.refresh()

    def _select_clip(self, clip_id: str) -> None:
        self._clip_list.select_clip(clip_id)
        self._on_clip_selected(clip_id)

    # ------------------------------------------------------------------ Background work

    def _run_in_background(self, work: Callable[[], T], on_success: Callable[[T], None]) -> None:
        def worker() -> None:
            try:
                result = work()
                self.root.after(0, lambda: on_success(result))
            except ProjectServiceError as exc:
                self.root.after(0, lambda: self._show_error(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _show_error(self, message: str) -> None:
        self._set_busy(False)
        messagebox.showerror("Moment", message, parent=self.root)

    # ------------------------------------------------------------------ File actions

    def _restore_last_project(self) -> None:
        project_path = load_active_project_path()
        if project_path and project_path.is_dir():
            try:
                self._open_project_path(project_path)
            except ProjectServiceError:
                pass

    def new_project(self) -> None:
        if not self._busy:
            NewProjectDialog(self.root, on_create=self._create_project)

    def _create_project(self, name: str, base_dir: Path) -> None:
        try:
            self.service = ProjectService()
            project_file = self.service.create_new_project(name, base_dir=base_dir)
            assert self.service.project_path is not None
            save_active_project_path(self.service.project_path)
            self._refresh_view(project_file.project.name)
            self._status_var.set(f"Created project “{project_file.project.name}”")
        except ProjectServiceError as exc:
            messagebox.showerror("Create project failed", str(exc), parent=self.root)

    def open_project(self) -> None:
        if self._busy:
            return
        directory = filedialog.askdirectory(
            parent=self.root,
            title="Open Moment project (.clip folder)",
            initialdir=str(Path.cwd()),
        )
        if directory:
            try:
                self._open_project_path(Path(directory))
            except ProjectServiceError as exc:
                messagebox.showerror("Open project failed", str(exc), parent=self.root)

    def _open_project_path(self, project_path: Path) -> None:
        self.service = ProjectService(project_path)
        project_file = self.service.load_project()
        save_active_project_path(project_path)
        self._refresh_view(project_file.project.name)
        self._status_var.set(f"Opened project “{project_file.project.name}”")

    def import_video(self) -> None:
        if self._busy:
            return
        if self.service.project is None:
            messagebox.showinfo(
                "No project",
                "Create or open a project before importing video.",
                parent=self.root,
            )
            return
        ImportVideoDialog(self.root, on_import=self._import_video)

    def _import_video(self, file_path: Path, display_name: Optional[str]) -> None:
        self._set_busy(True, f"Importing {file_path.name}…")
        self._run_in_background(
            work=lambda: self.service.import_video(file_path, display_name=display_name),
            on_success=self._on_video_imported,
        )

    def _on_video_imported(self, clip: Clip) -> None:
        self._clip_list.refresh()
        self._select_clip(clip.id)
        self._set_busy(False)
        self._status_var.set(f"Imported “{clip.display_name}” to workspace")

    def import_image(self) -> None:
        if self._busy:
            return
        if self.service.project is None:
            messagebox.showinfo(
                "No project",
                "Create or open a project before importing an image.",
                parent=self.root,
            )
            return
        ImportImageDialog(self.root, on_import=self._import_image)

    def _import_image(
        self, file_path: Path, display_name: Optional[str], frame_count: int
    ) -> None:
        self._set_busy(True, f"Importing {file_path.name}…")
        self._run_in_background(
            work=lambda: self.service.import_image(
                file_path,
                display_name=display_name,
                frame_count=frame_count,
            ),
            on_success=self._on_image_imported,
        )

    def _on_image_imported(self, clip: Clip) -> None:
        self._clip_list.refresh()
        self._select_clip(clip.id)
        self._set_busy(False)
        resource = self.service.get_resource(clip.resource_id)
        frames = resource.duration_frames
        self._status_var.set(
            f"Imported “{clip.display_name}” to workspace ({frames} frames)"
        )

    def add_flag(self) -> None:
        if self._busy or self.service.project is None:
            return

        clip_id = self._clip_list.selected_clip_id()
        if not clip_id:
            messagebox.showinfo("No clip selected", "Select a clip in the list first.", parent=self.root)
            return

        clip = self.service.get_clip(clip_id)
        resource = self.service.get_resource(clip.resource_id)
        max_frame = max(resource.duration_frames - 1, 0)

        AddFlagDialog(
            self.root,
            clip=clip,
            max_frame=max_frame,
            on_add=lambda frame, note, color, flag_type: self._save_flag(
                clip_id, frame, note, color, flag_type
            ),
        )

    def _save_flag(
        self,
        clip_id: str,
        frame: int,
        note: str,
        color: str,
        flag_type: str,
    ) -> None:
        try:
            flag = self.service.add_flag(
                clip_id=clip_id,
                frame=frame,
                note=note,
                color=color,
                flag_type=flag_type,
            )
            self._clip_list.refresh()
            self._select_clip(clip_id)
            self._status_var.set(f"Added flag at frame {flag.frame}")
        except ProjectServiceError as exc:
            messagebox.showerror("Add flag failed", str(exc), parent=self.root)

    def duplicate_clip(self) -> None:
        if self._busy or self.service.project is None:
            return

        clip_id = self._clip_list.selected_clip_id()
        if not clip_id:
            messagebox.showinfo(
                "No clip selected",
                "Select a clip in the list first.",
                parent=self.root,
            )
            return

        clip = self.service.get_clip(clip_id)
        DuplicateClipDialog(
            self.root,
            source_clip=clip,
            on_duplicate=lambda name: self._duplicate_clip(clip_id, name),
        )

    def _duplicate_clip(self, clip_id: str, display_name: str) -> None:
        source = self.service.get_clip(clip_id)
        self._set_busy(True, f"Duplicating “{source.display_name}”…")
        self._run_in_background(
            work=lambda: self.service.duplicate_clip(clip_id, display_name=display_name),
            on_success=self._on_clip_duplicated,
        )

    def _on_clip_duplicated(self, clip: Clip) -> None:
        self._clip_list.refresh()
        self._select_clip(clip.id)
        self._set_busy(False)
        self._status_var.set(f"Duplicated to workspace as “{clip.display_name}”")

    def crop_clip(self) -> None:
        if self._busy or self.service.project is None:
            return

        clip_id = self._clip_list.selected_clip_id()
        if not clip_id:
            messagebox.showinfo("No clip selected", "Select a clip in the list first.", parent=self.root)
            return

        clip = self.service.get_clip(clip_id)
        CropBetweenFlagsDialog(
            self.root,
            clip=clip,
            flags=self.service.get_flags(clip_id),
            on_crop=lambda start_id, end_id, name: self._crop_clip(clip_id, start_id, end_id, name),
        )

    def _crop_clip(
        self,
        clip_id: str,
        start_flag_id: str,
        end_flag_id: str,
        display_name: Optional[str],
    ) -> None:
        self._set_busy(True, "Cropping video…")
        self._run_in_background(
            work=lambda: self.service.crop_clip(
                clip_id=clip_id,
                start_flag_id=start_flag_id,
                end_flag_id=end_flag_id,
                display_name=display_name,
            ),
            on_success=self._on_clip_cropped,
        )

    def _on_clip_cropped(self, clip: Clip) -> None:
        self._clip_list.refresh()
        self._select_clip(clip.id)
        self._set_busy(False)
        frames = self.service.get_clip_playback_frame_count(clip)
        self._status_var.set(f"Cropped “{clip.display_name}” ({frames} frames)")

    def insert_in_composition(self) -> None:
        if self._busy or self.service.project is None:
            return

        clips = self.service.list_all_clips()
        if not clips:
            messagebox.showinfo(
                "No clips",
                "Import a clip before arranging the composition.",
                parent=self.root,
            )
            return

        InsertClipDialog(
            self.root,
            service=self.service,
            clips=clips,
            selected_clip_id=self._clip_list.selected_clip_id(),
            on_insert=self._apply_composition_insert,
        )

    def _apply_composition_insert(
        self,
        clip_id: str,
        mode: PlacementMode,
        reference_id: Optional[str],
        after_reference_id: Optional[str],
    ) -> None:
        try:
            if mode == "start":
                self.service.prepend_to_composition(clip_id)
            elif mode == "end":
                self.service.append_to_composition(clip_id)
            elif mode == "before":
                assert reference_id is not None
                self.service.insert_clip_in_composition(clip_id, reference_id, "before")
            elif mode == "after":
                assert reference_id is not None
                self.service.insert_clip_in_composition(clip_id, reference_id, "after")
            elif mode == "between":
                assert reference_id is not None and after_reference_id is not None
                self.service.insert_clip_between(clip_id, reference_id, after_reference_id)
            else:
                raise ProjectServiceError(f"Unknown placement mode: {mode}")

            self._clip_list.refresh()
            self._clip_list.select_clip(clip_id)
            clip = self.service.get_clip(clip_id)
            self._update_clip_actions()
            self._status_var.set(f"Added “{clip.display_name}” to the composition")
        except ProjectServiceError as exc:
            messagebox.showerror("Insert failed", str(exc), parent=self.root)

    def remove_from_composition(self) -> None:
        if self._busy or self.service.project is None:
            return

        clip_id = self._clip_list.selected_clip_id()
        if not clip_id:
            messagebox.showinfo(
                "No clip selected",
                "Select a clip in the composition to remove it.",
                parent=self.root,
            )
            return

        try:
            clip = self.service.get_clip(clip_id)
            self.service.remove_from_composition(clip_id)
            self._clip_list.refresh()
            self._clip_list.select_clip(clip_id)
            self._update_clip_actions()
            self._status_var.set(f"Moved “{clip.display_name}” to the workspace")
        except ProjectServiceError as exc:
            messagebox.showerror("Remove failed", str(exc), parent=self.root)

    def merge_composition(self) -> None:
        if self._busy or self.service.project is None:
            return

        if not self.service.list_composition():
            messagebox.showinfo(
                "Empty composition",
                "Add clips to the composition before merging.",
                parent=self.root,
            )
            return

        from tkinter import simpledialog

        display_name = simpledialog.askstring(
            "Merge composition",
            "Display name for the merged clip (optional):",
            parent=self.root,
        )
        if display_name is None:
            return

        replace = messagebox.askyesno(
            "Replace composition?",
            "Yes — replace the composition with only the merged clip.\n\n"
            "No — keep the current composition and add the merged clip to the workspace.",
            parent=self.root,
        )

        name = display_name.strip() or None
        self._set_busy(True, "Merging composition…")
        self._run_in_background(
            work=lambda: self.service.merge_composition_to_clip(
                name,
                replace_composition=replace,
            ),
            on_success=self._on_composition_merged,
        )

    def _on_composition_merged(self, clip: Clip) -> None:
        self._clip_list.refresh()
        self._clip_list.select_clip(clip.id)
        self._set_busy(False)
        flag_count = len(clip.flags)
        self._status_var.set(
            f"Merged composition into “{clip.display_name}” "
            f"({len(clip.merged_from_clip_ids)} source clips, {flag_count} flag(s))"
        )

    def preview_composition(self) -> None:
        if self._busy or self.service.project is None:
            return

        clips = self.service.list_clips()
        if not clips:
            messagebox.showinfo(
                "Empty composition",
                "Add clips to the composition before previewing.",
                parent=self.root,
            )
            return

        if self._preview.load_composition(autoplay=True):
            self._status_var.set(
                f"Previewing composition ({len(clips)} clip"
                f"{'' if len(clips) == 1 else 's'})"
            )


def main() -> int:
    """Launch the Moment GUI."""
    root = tk.Tk()
    MomentApp(root)
    root.mainloop()
    return 0


def entrypoint() -> None:
    """Console script entry point for ``pip install -e .``."""
    raise SystemExit(main())
