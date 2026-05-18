"""Tests for the persistent sync state."""
import json

import pytest

from notes_sync.state import STATE_FILENAME, NoteRecord, SyncState


@pytest.fixture
def output_dir(tmp_path):
    return tmp_path


def _rec(path="Work/Foo.md", mod="2026-05-14T10:23:45.000Z", name="Foo", folder="Work"):
    return NoteRecord(path=path, modified=mod, name=name, folder=folder)


class TestSyncStatePersistence:
    def test_load_missing_file_returns_empty(self, output_dir):
        state = SyncState.load(output_dir)
        assert state.notes == {}

    def test_round_trip(self, output_dir):
        state = SyncState()
        state.upsert("id-1", _rec())
        state.upsert("id-2", _rec(path="Personal/Bar.md", name="Bar", folder="Personal"))
        state.save(output_dir)

        loaded = SyncState.load(output_dir)
        assert set(loaded.notes.keys()) == {"id-1", "id-2"}
        assert loaded.notes["id-1"].path == "Work/Foo.md"
        assert loaded.notes["id-2"].folder == "Personal"

    def test_corrupt_file_returns_empty(self, output_dir):
        (output_dir / STATE_FILENAME).write_text("{not valid json")
        state = SyncState.load(output_dir)
        assert state.notes == {}

    def test_save_writes_versioned_payload(self, output_dir):
        state = SyncState()
        state.upsert("id-1", _rec())
        state.save(output_dir)
        data = json.loads((output_dir / STATE_FILENAME).read_text())
        assert data["version"] == 1
        assert "notes" in data


class TestSyncStateLogic:
    def test_is_unchanged(self):
        state = SyncState()
        state.upsert("id-1", _rec(mod="2026-05-14T10:00:00.000Z"))
        assert state.is_unchanged("id-1", "2026-05-14T10:00:00.000Z")
        assert not state.is_unchanged("id-1", "2026-05-14T11:00:00.000Z")
        assert not state.is_unchanged("missing-id", "anything")

    def test_orphans(self):
        state = SyncState()
        state.upsert("id-1", _rec())
        state.upsert("id-2", _rec(path="A/B.md"))
        state.upsert("id-3", _rec(path="X/Y.md"))
        orphans = state.orphans(live_ids={"id-1"})
        orphan_ids = {nid for nid, _ in orphans}
        assert orphan_ids == {"id-2", "id-3"}

    def test_remove(self):
        state = SyncState()
        state.upsert("id-1", _rec())
        rec = state.remove("id-1")
        assert rec is not None
        assert "id-1" not in state.notes
        assert state.remove("id-1") is None


class TestAttachmentsField:
    def test_default_empty_list(self):
        rec = _rec()
        assert rec.attachments == []

    def test_round_trip_with_attachments(self, output_dir):
        state = SyncState()
        rec = NoteRecord(
            path="Work/Foo.md", modified="2026-01-01T00:00:00.000Z",
            name="Foo", folder="Work",
            attachments=["Work/Foo.assets/01-pic.png", "Work/Foo.assets/02-doc.pdf"],
        )
        state.upsert("id-1", rec)
        state.save(output_dir)

        loaded = SyncState.load(output_dir)
        assert loaded.notes["id-1"].attachments == [
            "Work/Foo.assets/01-pic.png",
            "Work/Foo.assets/02-doc.pdf",
        ]

    def test_legacy_state_without_attachments_field(self, output_dir):
        """State files written before attachments existed must still load."""
        legacy = {
            "version": 1,
            "notes": {
                "id-1": {
                    "path": "Work/Foo.md",
                    "modified": "2026-01-01T00:00:00.000Z",
                    "name": "Foo",
                    "folder": "Work",
                    # no "attachments" key
                },
            },
        }
        (output_dir / STATE_FILENAME).write_text(json.dumps(legacy))
        loaded = SyncState.load(output_dir)
        assert loaded.notes["id-1"].attachments == []
