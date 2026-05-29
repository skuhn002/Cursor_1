"""Command-line interface for Moment."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from src.api.project_service import ProjectService, ProjectServiceError
from src.project_state import load_active_project_path, save_active_project_path


def _get_service(project_override: Optional[Path] = None) -> ProjectService:
    project_path = project_override or load_active_project_path()
    if project_path is None:
        raise ProjectServiceError(
            "No active project. Run 'create' first or pass --project."
        )
    service = ProjectService(project_path)
    service.load_project()
    return service


def _cmd_create(args: argparse.Namespace) -> int:
    base_dir = Path(args.directory).resolve() if args.directory else Path.cwd()
    service = ProjectService()
    project_file = service.create_new_project(args.project_name, base_dir=base_dir)
    assert service.project_path is not None
    save_active_project_path(service.project_path)
    print(f"Created project: {project_file.project.name}")
    print(f"Location: {service.project_path}")
    print(f"Project ID: {project_file.project.id}")
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    service = _get_service(
        Path(args.project).resolve() if args.project else None
    )
    video_path = Path(args.video_path).expanduser()
    clip = service.import_video(video_path, display_name=args.display_name)
    print(f"Imported clip: {clip.display_name}")
    print(f"Clip ID: {clip.id}")
    print(f"Resource ID: {clip.resource_id}")
    return 0


def _cmd_addflag(args: argparse.Namespace) -> int:
    service = _get_service(
        Path(args.project).resolve() if args.project else None
    )
    flag = service.add_flag(
        clip_id=args.clip_id,
        frame=args.frame,
        note=args.note or "",
        color=args.color,
        flag_type=args.flag_type,
    )
    print(f"Added flag at frame {flag.frame}")
    print(f"Flag ID: {flag.id}")
    print(f"Type: {flag.flag_type}  Color: {flag.color}")
    if flag.note:
        print(f"Note: {flag.note}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    service = _get_service(
        Path(args.project).resolve() if args.project else None
    )
    clips = service.list_clips()
    if not clips:
        print("No clips in project.")
        return 0

    project = service.project
    assert project is not None
    print(f"Project: {project.name} ({len(clips)} clip(s))")
    print("-" * 60)
    for clip in clips:
        resource = project.resources.get(clip.resource_id)
        flag_count = len(clip.flags)
        res_name = resource.display_name if resource else "?"
        print(f"{clip.id}  {clip.display_name}  [{res_name}]  {flag_count} flag(s)")
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    service = _get_service(
        Path(args.project).resolve() if args.project else None
    )
    clip = service.get_clip(args.clip_id)
    resource = service.get_resource(clip.resource_id)
    flags = service.get_flags(args.clip_id)

    print(f"Clip: {clip.display_name} ({clip.id})")
    print(f"Resource: {resource.display_name} ({resource.id})")
    print(f"File: {resource.original_filename}")
    print(f"Frames: {resource.duration_frames} @ {resource.fps:.2f} fps")
    print(f"Resolution: {resource.width}x{resource.height}")
    print(f"Flags: {len(flags)}")
    if flags:
        print("-" * 60)
        for flag in flags:
            line = f"  frame {flag.frame:>6}  [{flag.flag_type}]  {flag.color}  {flag.id}"
            print(line)
            if flag.note:
                print(f"           note: {flag.note}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="moment",
        description="Moment — lightweight flag-driven video editor",
    )
    parser.add_argument(
        "--project",
        help="Path to a .clip project folder (overrides active project)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    create_p = sub.add_parser("create", help="Create a new project")
    create_p.add_argument("project_name", help="Name for the new project")
    create_p.add_argument(
        "-d",
        "--directory",
        help="Directory to create the project in (default: current directory)",
    )
    create_p.set_defaults(func=_cmd_create)

    import_p = sub.add_parser("import", help="Import a video into the active project")
    import_p.add_argument("video_path", help="Path to the source video file")
    import_p.add_argument(
        "display_name",
        nargs="?",
        default=None,
        help="Optional display name for the clip",
    )
    import_p.set_defaults(func=_cmd_import)

    flag_p = sub.add_parser("addflag", help="Add a flag to a clip at a frame")
    flag_p.add_argument("clip_id", help="Target clip ID")
    flag_p.add_argument("frame", type=int, help="Frame number")
    flag_p.add_argument("note", nargs="?", default="", help="Optional note text")
    flag_p.add_argument(
        "--color",
        default="#3B82F6",
        help="Hex color (default: #3B82F6)",
    )
    flag_p.add_argument(
        "--type",
        dest="flag_type",
        default="general",
        help="Flag type (default: general)",
    )
    flag_p.set_defaults(func=_cmd_addflag)

    list_p = sub.add_parser("list", help="List all clips in the active project")
    list_p.set_defaults(func=_cmd_list)

    info_p = sub.add_parser("info", help="Show details for a clip")
    info_p.add_argument("clip_id", help="Clip ID to inspect")
    info_p.set_defaults(func=_cmd_info)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ProjectServiceError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())


def entrypoint() -> None:
    """Console script entry point for ``pip install -e .``."""
    raise SystemExit(main())
