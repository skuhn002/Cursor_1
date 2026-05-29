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
    ImportVideoDialog,
    NewProjectDialog,
)
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
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        clip_menu = tk.Menu(menubar, tearoff=0)
        clip_menu.add_command(label="Add Flag…", command=self.add_flag, accelerator="Ctrl+F")
        clip_menu.add_command(label="Crop Between Flags…", command=self.crop_clip, accelerator="Ctrl+K")
        menubar.add_cascade(label="Clip", menu=clip_menu)
        self._clip_menu = clip_menu

        self.root.config(menu=menubar)
        self.root.bind("<Control-n>", lambda _e: self.new_project())
        self.root.bind("<Control-o>", lambda _e: self.open_project())
        self.root.bind("<Control-i>", lambda _e: self.import_video())
        self.root.bind("<Control-f>", lambda _e: self.add_flag())
        self.root.bind("<Control-k>", lambda _e: self.crop_clip())

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=Spacing.WINDOW)
        outer.pack(fill="both", expand=True)

        self._build_header(outer)
        self._build_toolbar(outer)

        content = ttk.Frame(outer)
        content.pack(fill="both", expand=True, pady=(Spacing.SECTION, 0))

        self._clip_list = ClipListPanel(content, on_selection_changed=self._on_clip_selected)
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
        self._add_flag_btn = ttk.Button(toolbar, text="Add Flag", command=self.add_flag)
        self._crop_btn = ttk.Button(toolbar, text="Crop Between Flags", command=self.crop_clip)

        for index, button in enumerate(
            (self._new_btn, self._open_btn, self._import_btn, self._add_flag_btn, self._crop_btn)
        ):
            button.pack(side="left", padx=(0, Spacing.CONTROL_GAP if index < 4 else 0))

    # ------------------------------------------------------------------ State

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        for button in (self._new_btn, self._open_btn, self._import_btn):
            button.configure(state="disabled" if busy else "normal")

        if busy:
            self._add_flag_btn.configure(state="disabled")
            self._crop_btn.configure(state="disabled")
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

        if not loaded:
            self._preview.clear()
            self._clip_list.refresh()

        self._update_clip_actions()

    def _update_clip_actions(self) -> None:
        clip_selected = bool(self._clip_list.selected_clip_id())
        clip_state = "normal" if clip_selected and not self._busy else "disabled"

        self._add_flag_btn.configure(state=clip_state)
        self._crop_btn.configure(state=clip_state)
        self._clip_menu.entryconfigure(0, state=clip_state)
        self._clip_menu.entryconfigure(1, state=clip_state)

        if self._busy or self.service.project is None or not clip_selected:
            return

        clip = self.service.get_clip(self._clip_list.selected_clip_id())
        flag_count = len(clip.flags)
        suffix = f"{flag_count} flag(s)" if flag_count else "add flags or crop to clip edges"
        self._status_var.set(f"Selected “{clip.display_name}” — {suffix}")

    def _on_clip_selected(self, clip_id: Optional[str]) -> None:
        self._update_clip_actions()
        self._preview.load_clip(clip_id)

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
        self._status_var.set(f"Imported “{clip.display_name}”")

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
        self._status_var.set(
            f"Cropped “{clip.display_name}” "
            f"(frames {clip.trim_start_frame}–{clip.trim_end_frame})"
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
