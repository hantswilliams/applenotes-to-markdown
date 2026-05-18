"""Persistent sync state: maps note id → on-disk path + last-seen modification."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

STATE_FILENAME = ".notes-sync-state.json"
STATE_VERSION = 1


@dataclass
class NoteRecord:
    path: str                          # relative to output_dir
    modified: str                      # ISO8601 from JXA
    name: str
    folder: str
    attachments: list[str] = field(default_factory=list)  # rel paths under output_dir

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "modified": self.modified,
            "name": self.name,
            "folder": self.folder,
            "attachments": list(self.attachments),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NoteRecord":
        return cls(
            path=d["path"],
            modified=d["modified"],
            name=d["name"],
            folder=d["folder"],
            attachments=list(d.get("attachments", [])),
        )


@dataclass
class SyncState:
    notes: dict[str, NoteRecord] = field(default_factory=dict)

    @classmethod
    def load(cls, output_dir: Path) -> "SyncState":
        path = output_dir / STATE_FILENAME
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        notes_raw = data.get("notes", {})
        return cls(notes={k: NoteRecord.from_dict(v) for k, v in notes_raw.items()})

    def save(self, output_dir: Path) -> None:
        path = output_dir / STATE_FILENAME
        payload = {
            "version": STATE_VERSION,
            "notes": {k: v.to_dict() for k, v in self.notes.items()},
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def is_unchanged(self, note_id: str, modified_iso: str) -> bool:
        rec = self.notes.get(note_id)
        return rec is not None and rec.modified == modified_iso

    def upsert(self, note_id: str, rec: NoteRecord) -> None:
        self.notes[note_id] = rec

    def remove(self, note_id: str) -> NoteRecord | None:
        return self.notes.pop(note_id, None)

    def orphans(self, live_ids: set[str]) -> list[tuple[str, NoteRecord]]:
        """Records present in state but missing from a fresh metadata fetch."""
        return [(nid, rec) for nid, rec in self.notes.items() if nid not in live_ids]
