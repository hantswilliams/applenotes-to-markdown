"""Command-line entry point for notes-sync."""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import (
    config_path,
    load_config,
    resolve_folders,
    resolve_output_dir,
    resolve_save_attachments,
    save_config,
)
from .jxa import JXAError, fetch_folder_meta, fetch_folders, folder_exists
from .sync import sync_notes


def _add_folder_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-f", "--folders",
        help="Comma-separated folder names (default: all, or value from notes-sync.json)",
    )


def _add_output_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: cwd or value from notes-sync.json)",
    )


def _add_verbosity(p: argparse.ArgumentParser) -> None:
    p.add_argument("-q", "--quiet", action="store_true", help="Suppress per-note output")


def cmd_list(args: argparse.Namespace, _config: dict, _config_path: Path) -> int:
    folders = fetch_folders()
    total = sum(f["count"] for f in folders)
    print(f"\n{'Folder':<40} {'Notes':>6}")
    print("-" * 48)
    for f in sorted(folders, key=lambda x: x["name"].lower()):
        print(f"  {f['name']:<38} {f['count']:>6}")
    print("-" * 48)
    print(f"  {'Total':<38} {total:>6}\n")
    return 0


def cmd_info(args: argparse.Namespace, _config: dict, _config_path: Path) -> int:
    folder_name = args.folder
    if not folder_exists(folder_name):
        print(f"Folder '{folder_name}' not found. Run `notes-sync list` to see available folders.",
              file=sys.stderr)
        return 1

    notes = fetch_folder_meta(folder_name)
    if not notes:
        print(f"Folder '{folder_name}' exists but contains no notes.")
        return 0

    oldest   = min(n["creationDate"]     for n in notes)[:10]
    newest   = max(n["modificationDate"] for n in notes)[:10]
    total_sz = sum(n["bodyLength"]       for n in notes)
    avg_sz   = total_sz // len(notes)

    print(f"\nFolder:         {folder_name}")
    print(f"Notes:          {len(notes)}")
    print(f"Oldest created: {oldest}")
    print(f"Last modified:  {newest}")
    print(f"Total content:  {total_sz:,} chars")
    print(f"Avg note size:  {avg_sz:,} chars\n")

    print(f"  {'Note':<48} {'Modified':<12} {'Size':>8}")
    print("  " + "-" * 70)
    for note in sorted(notes, key=lambda n: n["modificationDate"], reverse=True):
        name = note["name"][:46]
        mod  = note["modificationDate"][:10]
        sz   = note["bodyLength"]
        print(f"  {name:<48} {mod:<12} {sz:>8,}")
    print()
    return 0


def cmd_sync(args: argparse.Namespace, config: dict, _config_path: Path) -> int:
    output_dir   = resolve_output_dir(args.output_dir, config)
    folder_names = resolve_folders(args.folders, config)
    save_attachments = resolve_save_attachments(args.no_attachments, config)

    if folder_names:
        print(f"Syncing folders: {', '.join(folder_names)}")
    else:
        print("Syncing all folders")
    print(f"Output: {output_dir}")
    if not save_attachments:
        print("(attachments disabled)")
    if args.dry_run:
        print("(dry-run: no files will be written)")
    print()

    stats = sync_notes(
        output_dir,
        folder_names=folder_names,
        dry_run=args.dry_run,
        prune=args.prune,
        verbose=not args.quiet,
        save_attachments=save_attachments,
        force=args.force,
    )

    print(
        f"\nDone. Created: {stats.created}, "
        f"Updated: {stats.updated}, "
        f"Unchanged: {stats.skipped}, "
        f"Pruned: {stats.pruned}"
    )
    if save_attachments and (stats.attachments_saved or stats.attachments_skipped):
        msg = f"Attachments: {stats.attachments_saved} saved"
        if stats.attachments_skipped:
            msg += f", {stats.attachments_skipped} skipped (drawings/link previews)"
        print(msg)
    if stats.locked:
        print(f"Note: {stats.locked} note(s) were locked or inaccessible.")
    if stats.errors:
        print(f"\n{len(stats.errors)} error(s):", file=sys.stderr)
        for err in stats.errors[:10]:
            print(f"  - {err}", file=sys.stderr)
        if len(stats.errors) > 10:
            print(f"  ... and {len(stats.errors) - 10} more", file=sys.stderr)
        return 1
    return 0


def cmd_watch(args: argparse.Namespace, config: dict, _config_path: Path) -> int:
    output_dir   = resolve_output_dir(args.output_dir, config)
    folder_names = resolve_folders(args.folders, config)
    save_attachments = resolve_save_attachments(args.no_attachments, config)
    output_dir.mkdir(parents=True, exist_ok=True)

    desc = f"folders: {', '.join(folder_names)}" if folder_names else "all folders"
    print(f"Watching Apple Notes ({desc}), syncing every {args.interval}s")
    print(f"Output: {output_dir}")
    if not save_attachments:
        print("(attachments disabled)")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            ts = datetime.now().strftime("%H:%M:%S")
            try:
                stats = sync_notes(
                    output_dir,
                    folder_names=folder_names,
                    prune=args.prune,
                    verbose=False,
                    save_attachments=save_attachments,
                )
                if stats.has_changes:
                    print(
                        f"[{ts}] Created: {stats.created}, "
                        f"Updated: {stats.updated}, "
                        f"Pruned: {stats.pruned}"
                    )
                else:
                    print(f"[{ts}] No changes")
            except JXAError as e:
                print(f"[{ts}] Sync error (will retry): {e.__class__.__name__}", file=sys.stderr)
            except Exception as e:  # pragma: no cover — defensive: keep loop alive
                print(f"[{ts}] Unexpected error (will retry): {e}", file=sys.stderr)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped watching.")
        return 0


def cmd_config(args: argparse.Namespace, config: dict, cfg_path: Path) -> int:
    changed = False

    if args.clear:
        if cfg_path.exists():
            cfg_path.unlink()
            print(f"Removed {cfg_path}")
            return 0
        print("No config file to clear.")
        return 0

    if args.folders is not None:
        if args.folders == "":
            config.pop("folders", None)
            print("Default folders cleared.")
        else:
            config["folders"] = [f.strip() for f in args.folders.split(",") if f.strip()]
            print(f"Default folders set: {', '.join(config['folders'])}")
        changed = True

    if args.output_dir is not None:
        resolved = args.output_dir.expanduser().resolve()
        config["output_dir"] = str(resolved)
        print(f"Default output dir set: {resolved}")
        changed = True

    if args.no_attachments:
        config["save_attachments"] = False
        print("Attachments disabled by default.")
        changed = True
    elif args.attachments:
        config.pop("save_attachments", None)  # back to default-on
        print("Attachments enabled by default.")
        changed = True

    if changed:
        save_config(cfg_path, config)
        print(f"Saved to {cfg_path}")
        return 0

    if config:
        print(f"\nConfig ({cfg_path}):")
        import json as _json
        print(_json.dumps(config, indent=2))
    else:
        print("No config saved yet. Use --folders / --output-dir to set defaults.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notes-sync",
        description="Sync Apple Notes to Markdown files on disk.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  notes-sync list\n"
            "  notes-sync info \"Work\"\n"
            "  notes-sync sync -f \"Work,Personal\" -o ~/notes\n"
            "  notes-sync sync --dry-run --prune\n"
            "  notes-sync watch -f \"Work\" --interval 30\n"
            "  notes-sync config -f \"Work,Personal\" -o ~/notes\n"
        ),
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    list_p = sub.add_parser("list", help="List all note folders with note counts")
    list_p.set_defaults(func=cmd_list)

    info_p = sub.add_parser("info", help="Show metadata for a specific folder")
    info_p.add_argument("folder", help="Folder name")
    info_p.set_defaults(func=cmd_info)

    sync_p = sub.add_parser("sync", help="Sync notes to markdown files (incremental)")
    _add_folder_arg(sync_p)
    _add_output_arg(sync_p)
    _add_verbosity(sync_p)
    sync_p.add_argument("--dry-run", action="store_true",
                        help="Print what would change without writing files")
    sync_p.add_argument("--prune", action="store_true",
                        help="Move .md files for deleted notes into .trash/")
    sync_p.add_argument("--no-attachments", action="store_true",
                        help="Skip exporting note attachments to .assets/ folders")
    sync_p.add_argument("--force", action="store_true",
                        help="Re-fetch and rewrite every in-scope note, ignoring saved state")
    sync_p.set_defaults(func=cmd_sync)

    watch_p = sub.add_parser("watch", help="Continuously watch and sync notes")
    _add_folder_arg(watch_p)
    _add_output_arg(watch_p)
    watch_p.add_argument("--interval", "-i", type=int, default=60,
                         help="Sync interval in seconds (default: 60)")
    watch_p.add_argument("--prune", action="store_true",
                         help="Also move deleted notes to .trash/ each tick")
    watch_p.add_argument("--no-attachments", action="store_true",
                         help="Skip exporting note attachments to .assets/ folders")
    watch_p.set_defaults(func=cmd_watch)

    cfg_p = sub.add_parser("config", help="View or set default configuration")
    cfg_p.add_argument("-f", "--folders", default=None,
                       help='Set default folders (comma-separated; pass "" to clear)')
    cfg_p.add_argument("-o", "--output-dir", type=Path, default=None,
                       help="Set default output directory")
    att_group = cfg_p.add_mutually_exclusive_group()
    att_group.add_argument("--no-attachments", action="store_true",
                           help="Persist: skip exporting attachments by default")
    att_group.add_argument("--attachments", action="store_true",
                           help="Persist: export attachments by default (the default)")
    cfg_p.add_argument("--clear", action="store_true",
                       help="Remove the config file entirely")
    cfg_p.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cfg_path = config_path()
    config = load_config(cfg_path)

    try:
        return args.func(args, config, cfg_path)
    except JXAError as e:
        print(str(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
