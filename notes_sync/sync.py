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
    build_frontmatter,
    html_to_markdown,
    id_suffix,
    sanitize_filename,
)
from .jxa import fetch_note_bodies, fetch_notes_metadata
from .state import NoteRecord, SyncState


@dataclass
class SyncStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    pruned: int = 0
    locked: int = 0
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
        if not src.exists():
            continue
        dest = trash / Path(rec.path).name
        try:
            shutil.move(str(src), str(dest))
            stats.pruned += 1
            if verbose:
                print(f"  Pruned: {rec.path} -> .trash/")
        except OSError as e:
            stats.errors.append(f"prune {rec.path}: {e}")


def sync_notes(
    output_dir: Path,
    folder_names: list[str] | None,
    *,
    dry_run: bool = False,
    prune: bool = False,
    verbose: bool = True,
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
    if needs_body:
        if dry_run:
            if verbose:
                print("(dry-run) would fetch bodies — skipping fetch")
        else:
            body_result = fetch_note_bodies(needs_body)
            bodies = body_result["bodies"]
            stats.locked += body_result.get("locked", 0)
            for missing in body_result.get("missing", []):
                stats.errors.append(f"body fetch failed for id {missing}")

    used_paths: set[Path] = set()
    for note in notes_meta:
        note_id = note["id"]
        is_new = note_id not in state.notes

        if state.is_unchanged(note_id, note["modificationDate"]):
            stats.skipped += 1
            if (rec := state.notes.get(note_id)) is not None:
                used_paths.add(output_dir / rec.path)
            continue

        if not dry_run and note_id not in bodies:
            stats.errors.append(f"no body fetched for: {note['name']}")
            continue

        file_path = _target_path(
            output_dir, note["folder"], note["name"], note_id, used_paths,
            create=not dry_run,
        )
        rel_path = file_path.relative_to(output_dir).as_posix()

        if is_new:
            stats.created += 1
            action = "Created"
        else:
            stats.updated += 1
            action = "Updated"

        if not dry_run:
            md_body = html_to_markdown(bodies[note_id])
            frontmatter = build_frontmatter(
                title=note["name"],
                note_id=note_id,
                folder=note["folder"],
                created=note["creationDate"],
                modified=note["modificationDate"],
            )
            file_path.write_text(frontmatter + md_body + "\n", encoding="utf-8")
            state.upsert(
                note_id,
                NoteRecord(
                    path=rel_path,
                    modified=note["modificationDate"],
                    name=note["name"],
                    folder=note["folder"],
                ),
            )

        if verbose:
            prefix = "(dry-run) " if dry_run else ""
            print(f"  {prefix}{action}: {rel_path}")

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
