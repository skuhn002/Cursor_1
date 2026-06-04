"""Command-line interface for Moment."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from src.api.errors import ProjectServiceError
from src.api.project_service import ProjectService
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
    print("Added to workspace (use 'compose insert' to include in the composition).")
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


def _cmd_import_image(args: argparse.Namespace) -> int:
    service = _get_service(
        Path(args.project).resolve() if args.project else None
    )
    image_path = Path(args.image_path).expanduser()
    if args.frames is not None and args.seconds is not None:
        raise ProjectServiceError("Specify either --frames or --seconds, not both.")

    clip = service.import_image(
        image_path,
        display_name=args.display_name,
        frame_count=args.frames,
        duration_seconds=args.seconds,
    )
    resource = service.get_resource(clip.resource_id)
    print(f"Imported image clip: {clip.display_name}")
    print(f"Clip ID: {clip.id}")
    print(f"Duration: {resource.duration_frames} frames @ {resource.fps:.0f} fps")
    print("Added to workspace (use 'compose insert' to include in the composition).")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    service = _get_service(
        Path(args.project).resolve() if args.project else None
    )
    project = service.project
    assert project is not None

    workspace = service.list_workspace_clips()
    composition = service.list_clips()

    if not workspace and not composition:
        print("No clips in project.")
        return 0

    print(f"Project: {project.name}")
    print("-" * 60)
    print(f"Workspace ({len(workspace)} clip(s))")
    if workspace:
        for clip in workspace:
            resource = project.resources.get(clip.resource_id)
            flag_count = len(clip.flags)
            res_name = resource.display_name if resource else "?"
            kind = f" [{resource.media_kind}]" if resource and resource.media_kind != "video" else ""
            print(f"  {clip.id}  {clip.display_name}{kind}  [{res_name}]  {flag_count} flag(s)")
    else:
        print("  (empty)")

    print(f"Composition ({len(composition)} clip(s))")
    if composition:
        for index, clip in enumerate(composition, start=1):
            resource = project.resources.get(clip.resource_id)
            flag_count = len(clip.flags)
            res_name = resource.display_name if resource else "?"
            kind = f" [{resource.media_kind}]" if resource and resource.media_kind != "video" else ""
            print(
                f"  {index:>3}. {clip.id}  {clip.display_name}{kind}  "
                f"[{res_name}]  {flag_count} flag(s)"
            )
    else:
        print("  (empty)")
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
    print(f"Type: {resource.media_kind}")
    print(f"File: {resource.original_filename}")
    if clip.version_filename:
        print(f"Version: {clip.version_filename}")
    if clip.trim_start_frame is not None and clip.trim_end_frame is not None:
        print(f"Trim: frames {clip.trim_start_frame}–{clip.trim_end_frame}")
    if clip.source_clip_id:
        print(f"Source clip: {clip.source_clip_id}")
    if service.is_in_composition(args.clip_id):
        position = service.list_composition().index(args.clip_id) + 1
        print(f"In composition: yes (position {position})")
    else:
        print("In composition: no (workspace only)")
    if clip.clip_kind == "merged" and clip.merged_from_clip_ids:
        print(f"Merged from: {', '.join(clip.merged_from_clip_ids)}")
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


def _cmd_duplicate(args: argparse.Namespace) -> int:
    service = _get_service(
        Path(args.project).resolve() if args.project else None
    )
    duplicated = service.duplicate_clip(
        args.clip_id,
        display_name=args.display_name,
    )
    print(f"Duplicated clip: {duplicated.display_name}")
    print(f"Clip ID: {duplicated.id}")
    print(f"Source clip: {duplicated.source_clip_id}")
    print("Added to workspace (use 'compose insert' to include in the composition).")
    return 0


def _cmd_crop(args: argparse.Namespace) -> int:
    service = _get_service(
        Path(args.project).resolve() if args.project else None
    )
    cropped = service.crop_clip(
        clip_id=args.clip_id,
        start_flag_id=args.start_flag_id,
        end_flag_id=args.end_flag_id,
        display_name=args.display_name,
    )
    print(f"Cropped clip: {cropped.display_name}")
    print(f"Clip ID: {cropped.id}")
    if cropped.version_filename:
        print(f"Version: {cropped.version_filename}")
    resource = service.get_resource(cropped.resource_id)
    print(f"Frames: {service.get_clip_playback_frame_count(cropped)} @ {resource.fps:.0f} fps")
    return 0


def _cmd_compose_list(args: argparse.Namespace) -> int:
    service = _get_service(
        Path(args.project).resolve() if args.project else None
    )
    clips = service.list_clips()
    if not clips:
        print("Composition is empty.")
        return 0

    print(f"Composition ({len(clips)} clip(s))")
    print("-" * 60)
    for index, clip in enumerate(clips, start=1):
        print(f"{index:>3}. {clip.display_name}  ({clip.id})")
    return 0


def _cmd_compose_insert(args: argparse.Namespace) -> int:
    service = _get_service(
        Path(args.project).resolve() if args.project else None
    )
    if args.start:
        service.prepend_to_composition(args.clip_id)
    elif args.end:
        service.append_to_composition(args.clip_id)
    elif args.before:
        service.insert_clip_in_composition(args.clip_id, args.before, "before")
    elif args.after:
        service.insert_clip_in_composition(args.clip_id, args.after, "after")
    elif args.between_before and args.between_after:
        service.insert_clip_between(args.clip_id, args.between_before, args.between_after)
    else:
        raise ProjectServiceError(
            "Specify one placement option: --start, --end, --before, --after, "
            "or both --between-before and --between-after."
        )

    clips = service.list_clips()
    position = next(
        (index for index, clip in enumerate(clips, start=1) if clip.id == args.clip_id),
        None,
    )
    print(f"Placed clip {args.clip_id} at position {position} in the composition.")
    return 0


def _cmd_compose_remove(args: argparse.Namespace) -> int:
    service = _get_service(
        Path(args.project).resolve() if args.project else None
    )
    service.remove_from_composition(args.clip_id)
    print(f"Removed clip {args.clip_id} from the composition (still in workspace).")
    return 0


def _cmd_compose_merge(args: argparse.Namespace) -> int:
    service = _get_service(
        Path(args.project).resolve() if args.project else None
    )
    if args.replace and args.add:
        raise ProjectServiceError("Use only one of --replace or --add.")

    clip = service.merge_composition_to_clip(
        display_name=args.display_name,
        add_to_composition=args.add,
        replace_composition=args.replace,
    )
    resource = service.get_resource(clip.resource_id)
    print(f"Merged clip: {clip.display_name}")
    print(f"Clip ID: {clip.id}")
    print(f"Source clips: {', '.join(clip.merged_from_clip_ids)}")
    print(f"Duration: {resource.duration_frames} frames @ {resource.fps:.0f} fps")
    print(f"Flags preserved: {len(clip.flags)}")
    if args.replace:
        print("Composition replaced with the merged clip.")
    elif args.add:
        print("Merged clip appended to the composition.")
    else:
        print("Merged clip added to the workspace.")
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

    import_image_p = sub.add_parser(
        "import-image",
        help="Import a still image as a timed workspace clip",
    )
    import_image_p.add_argument("image_path", help="Path to the source image file")
    import_image_p.add_argument(
        "display_name",
        nargs="?",
        default=None,
        help="Optional display name for the clip",
    )
    import_image_p.add_argument(
        "--frames",
        type=int,
        default=None,
        help="Clip length in frames (default: 30)",
    )
    import_image_p.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="Clip length in seconds at 30 fps",
    )
    import_image_p.set_defaults(func=_cmd_import_image)

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

    duplicate_p = sub.add_parser(
        "duplicate",
        help="Duplicate a clip with its own media copy (workspace only)",
    )
    duplicate_p.add_argument("clip_id", help="Clip ID to duplicate")
    duplicate_p.add_argument(
        "--name",
        dest="display_name",
        default=None,
        help="Optional display name for the copy",
    )
    duplicate_p.set_defaults(func=_cmd_duplicate)

    crop_p = sub.add_parser(
        "crop",
        help="Crop a clip between two flags (creates a new clip)",
    )
    crop_p.add_argument("clip_id", help="Source clip ID")
    crop_p.add_argument("start_flag_id", help="Start flag ID (inclusive)")
    crop_p.add_argument("end_flag_id", help="End flag ID (inclusive)")
    crop_p.add_argument(
        "--name",
        dest="display_name",
        default=None,
        help="Optional display name for the cropped clip",
    )
    crop_p.set_defaults(func=_cmd_crop)

    compose_p = sub.add_parser("compose", help="Manage the clip composition order")
    compose_sub = compose_p.add_subparsers(dest="compose_command", required=True)

    compose_list_p = compose_sub.add_parser("list", help="List clips in composition order")
    compose_list_p.set_defaults(func=_cmd_compose_list)

    compose_insert_p = compose_sub.add_parser(
        "insert",
        help="Place a clip in the composition",
    )
    compose_insert_p.add_argument("clip_id", help="Clip ID to place")
    compose_insert_p.add_argument(
        "--start",
        action="store_true",
        help="Place at the start of the composition",
    )
    compose_insert_p.add_argument(
        "--end",
        action="store_true",
        help="Place at the end of the composition",
    )
    compose_insert_p.add_argument(
        "--before",
        metavar="REF_CLIP_ID",
        help="Place immediately before this clip",
    )
    compose_insert_p.add_argument(
        "--after",
        metavar="REF_CLIP_ID",
        help="Place immediately after this clip",
    )
    compose_insert_p.add_argument(
        "--between-before",
        metavar="CLIP_ID",
        help="When inserting between two clips, the earlier clip",
    )
    compose_insert_p.add_argument(
        "--between-after",
        metavar="CLIP_ID",
        help="When inserting between two clips, the later clip",
    )
    compose_insert_p.set_defaults(func=_cmd_compose_insert)

    compose_remove_p = compose_sub.add_parser(
        "remove",
        help="Remove a clip from the composition (keeps it in the workspace)",
    )
    compose_remove_p.add_argument("clip_id", help="Clip ID to remove from the composition")
    compose_remove_p.set_defaults(func=_cmd_compose_remove)

    compose_merge_p = compose_sub.add_parser(
        "merge",
        help="Concatenate composition clips into one clip with remapped flags",
    )
    compose_merge_p.add_argument(
        "--name",
        dest="display_name",
        default=None,
        help="Display name for the merged clip",
    )
    compose_merge_p.add_argument(
        "--add",
        action="store_true",
        help="Append the merged clip to the composition",
    )
    compose_merge_p.add_argument(
        "--replace",
        action="store_true",
        help="Replace the composition with only the merged clip",
    )
    compose_merge_p.set_defaults(func=_cmd_compose_merge)

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
