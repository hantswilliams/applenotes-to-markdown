"""Incremental sync orchestration.

Two-pass strategy:
  1. Fetch lightweight metadata for every note in the requested folders.
  2. Diff against the on-disk state file -> compute new/updated/unchanged.
  3. Fetch full HTML bodies *only* for new+updated notes.
  4. Write markdown files, update state, optionally prune orphans.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .convert import (
    attachment_filename,
    build_attachments_section,
    build_frontmatter,
    html_to_markdown,
    id_suffix,
    sanitize_filename,
)
from .jxa import fetch_note_bodies, fetch_notes_metadata, save_note_attachments
from .state import NoteRecord, SyncState


@dataclass
class SyncStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    pruned: int = 0
    locked: int = 0
    attachments_saved: int = 0
    attachments_skipped: int = 0  # Apple Notes refused to export (drawings etc.)
    errors: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.created or self.updated or self.pruned)


def _target_path(
    output_dir: Path,
    folder: str,
    name: str,
    note_id: str,
    used: set[Path],
    *,
    create: bool = True,
) -> Path:
    """Resolve a unique markdown path for a note, suffixing on collisions."""
    folder_path = output_dir / sanitize_filename(folder)
    if create:
        folder_path.mkdir(parents=True, exist_ok=True)
    base = sanitize_filename(name)
    candidate = folder_path / f"{base}.md"
    if candidate in used or (candidate.exists() and _claims_different_id(candidate, note_id)):
        candidate = folder_path / f"{base} [{id_suffix(note_id)}].md"
    used.add(candidate)
    return candidate


def _claims_different_id(path: Path, note_id: str) -> bool:
    """Best-effort check: does an existing file's frontmatter declare a different id?"""
    try:
        with path.open("r", encoding="utf-8") as fh:
            for _ in range(20):
                line = fh.readline()
                if not line:
                    break
                if line.startswith("id:"):
                    return note_id not in line
    except OSError:
        return False
    return False


def _assets_dir_for(md_path: Path) -> Path:
    """Sibling .assets/ folder for a given markdown file."""
    return md_path.with_suffix(".assets")


def _reset_assets_dir(assets_dir: Path) -> None:
    """Remove any prior .assets/ folder so we re-export from a clean slate."""
    if assets_dir.exists():
        shutil.rmtree(assets_dir, ignore_errors=True)


def _prune_orphans(
    output_dir: Path,
    orphans: list[tuple[str, NoteRecord]],
    stats: SyncStats,
    verbose: bool,
) -> None:
    if not orphans:
        return
    trash = output_dir / ".trash" / datetime.now().strftime("%Y%m%d-%H%M%S")
    trash.mkdir(parents=True, exist_ok=True)
    for note_id, rec in orphans:
        src = output_dir / rec.path
        if src.exists():
            dest = trash / Path(rec.path).name
            try:
                shutil.move(str(src), str(dest))
                stats.pruned += 1
                if verbose:
                    print(f"  Pruned: {rec.path} -> .trash/")
            except OSError as e:
                stats.errors.append(f"prune {rec.path}: {e}")
        # Also relocate the sibling .assets/ folder if it exists.
        assets_src = _assets_dir_for(src)
        if assets_src.exists():
            assets_dest = trash / assets_src.name
            try:
                shutil.move(str(assets_src), str(assets_dest))
            except OSError as e:
                stats.errors.append(f"prune {assets_src.name}: {e}")


def sync_notes(
    output_dir: Path,
    folder_names: list[str] | None,
    *,
    dry_run: bool = False,
    prune: bool = False,
    verbose: bool = True,
    save_attachments: bool = True,
) -> SyncStats:
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
    state = SyncState.load(output_dir)
    stats = SyncStats()

    if verbose:
        scope = f"in {len(folder_names)} folder(s)" if folder_names else "across all folders"
        print(f"Scanning notes {scope}...")

    meta = fetch_notes_metadata(folder_names)
    notes_meta: list[dict] = meta["notes"]
    stats.locked = meta.get("locked", 0)

    live_ids: set[str] = {n["id"] for n in notes_meta}
    needs_body: list[str] = []
    for note in notes_meta:
        if not state.is_unchanged(note["id"], note["modificationDate"]):
            needs_body.append(note["id"])

    if verbose:
        print(
            f"Found {len(notes_meta)} notes — "
            f"{len(needs_body)} need fetch, {len(notes_meta) - len(needs_body)} unchanged"
            + (f", {stats.locked} locked/inaccessible" if stats.locked else "")
        )

    bodies: dict[str, str] = {}
    note_attachments: dict[str, list[dict]] = {}
    if needs_body:
        if dry_run:
            if verbose:
                print("(dry-run) would fetch bodies — skipping fetch")
        else:
            body_result = fetch_note_bodies(needs_body)
            bodies = body_result["bodies"]
            note_attachments = body_result.get("attachments", {})
            stats.locked += body_result.get("locked", 0)
            for missing in body_result.get("missing", []):
                stats.errors.append(f"body fetch failed for id {missing}")

    # ----- Plan attachment writes for changed notes -----
    # plan: note_id -> [{att_id, dest (abs path), filename, display}, ...]
    attachment_plan: dict[str, list[dict]] = {}
    note_paths: dict[str, Path] = {}
    used_paths: set[Path] = set()

    for note in notes_meta:
        note_id = note["id"]
        if state.is_unchanged(note_id, note["modificationDate"]):
            if (rec := state.notes.get(note_id)) is not None:
                used_paths.add(output_dir / rec.path)
            continue
        if not dry_run and note_id not in bodies:
            continue
        file_path = _target_path(
            output_dir, note["folder"], note["name"], note_id, used_paths,
            create=not dry_run,
        )
        note_paths[note_id] = file_path
        if not save_attachments or dry_run:
            continue
        # Always reset the .assets/ folder when we're rewriting the note —
        # this also handles the case of attachments removed since last sync.
        _reset_assets_dir(_assets_dir_for(file_path))
        atts = note_attachments.get(note_id, [])
        if not atts:
            continue
        assets_dir = _assets_dir_for(file_path)
        entries = []
        for i, att in enumerate(atts, 1):
            filename = attachment_filename(i, att.get("name"), att["att_id"])
            entries.append({
                "att_id": att["att_id"],
                "dest": str((assets_dir / filename).resolve()),
                "filename": filename,
                "display": att.get("name") or filename,
            })
        attachment_plan[note_id] = entries

    # ----- Execute attachment writes (single JXA round-trip) -----
    save_results: dict[str, dict] = {}
    if attachment_plan:
        # Ensure .assets/ exists before save (already cleared above).
        for note_id, entries in attachment_plan.items():
            _assets_dir_for(note_paths[note_id]).mkdir(parents=True, exist_ok=True)
        save_plan = {
            nid: [{"att_id": e["att_id"], "dest": e["dest"]} for e in entries]
            for nid, entries in attachment_plan.items()
        }
        save_results = save_note_attachments(save_plan)

    # ----- Write markdown files -----
    for note in notes_meta:
        note_id = note["id"]
        is_new = note_id not in state.notes

        if state.is_unchanged(note_id, note["modificationDate"]):
            stats.skipped += 1
            continue

        if not dry_run and note_id not in bodies:
            stats.errors.append(f"no body fetched for: {note['name']}")
            continue

        file_path = note_paths[note_id]
        rel_path = file_path.relative_to(output_dir).as_posix()

        if is_new:
            stats.created += 1
            action = "Created"
        else:
            stats.updated += 1
            action = "Updated"

        # Resolve which planned attachments actually saved.
        saved_entries: list[dict] = []
        unsupported = 0
        for entry in attachment_plan.get(note_id, []):
            res = save_results.get(entry["att_id"], {"ok": False, "err": "no result"})
            if res.get("ok"):
                stats.attachments_saved += 1
                saved_entries.append(entry)
            else:
                stats.attachments_skipped += 1
                unsupported += 1
                # Drop the empty file the save attempt may have left behind.
                Path(entry["dest"]).unlink(missing_ok=True)

        if not dry_run:
            md_body = html_to_markdown(bodies[note_id])
            frontmatter = build_frontmatter(
                title=note["name"],
                note_id=note_id,
                folder=note["folder"],
                created=note["creationDate"],
                modified=note["modificationDate"],
            )
            attachments_block = ""
            if saved_entries or unsupported:
                attachments_block = "\n\n" + build_attachments_section(
                    saved_entries,
                    assets_dirname=_assets_dir_for(file_path).name,
                    unsupported_count=unsupported,
                )
            file_path.write_text(
                frontmatter + md_body + attachments_block + "\n",
                encoding="utf-8",
            )
            state.upsert(
                note_id,
                NoteRecord(
                    path=rel_path,
                    modified=note["modificationDate"],
                    name=note["name"],
                    folder=note["folder"],
                    attachments=[
                        (_assets_dir_for(file_path).relative_to(output_dir).as_posix()
                         + "/" + e["filename"])
                        for e in saved_entries
                    ],
                ),
            )

        if verbose:
            prefix = "(dry-run) " if dry_run else ""
            extra = ""
            if saved_entries or unsupported:
                bits = []
                if saved_entries:
                    bits.append(f"{len(saved_entries)} attachment(s)")
                if unsupported:
                    bits.append(f"{unsupported} skipped")
                extra = f"  [{', '.join(bits)}]"
            print(f"  {prefix}{action}: {rel_path}{extra}")

    orphans = state.orphans(live_ids)
    if prune and orphans:
        if dry_run:
            stats.pruned = len(orphans)
            if verbose:
                for nid, rec in orphans:
                    print(f"  (dry-run) Would prune: {rec.path}")
        else:
            _prune_orphans(output_dir, orphans, stats, verbose)
            for nid, _ in orphans:
                state.remove(nid)
    elif orphans and verbose:
        print(f"({len(orphans)} orphan(s) in state — pass --prune to move to .trash/)")

    if not dry_run:
        state.save(output_dir)

    return stats
