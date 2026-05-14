"""Tests for config helpers."""
from pathlib import Path

import pytest

from notes_sync.config import (
    load_config,
    resolve_folders,
    resolve_output_dir,
    save_config,
)


class TestLoadSave:
    def test_load_missing(self, tmp_path):
        assert load_config(tmp_path / "missing.json") == {}

    def test_round_trip(self, tmp_path):
        p = tmp_path / "cfg.json"
        save_config(p, {"folders": ["A", "B"], "output_dir": "/tmp/x"})
        assert load_config(p) == {"folders": ["A", "B"], "output_dir": "/tmp/x"}

    def test_corrupt_returns_empty(self, tmp_path):
        p = tmp_path / "cfg.json"
        p.write_text("not json")
        assert load_config(p) == {}


class TestResolveFolders:
    def test_cli_wins_over_config(self):
        assert resolve_folders("A,B", {"folders": ["X"]}) == ["A", "B"]

    def test_cli_strips_whitespace(self):
        assert resolve_folders(" A , B , ", {}) == ["A", "B"]

    def test_falls_back_to_config(self):
        assert resolve_folders(None, {"folders": ["X", "Y"]}) == ["X", "Y"]

    def test_no_cli_no_config(self):
        assert resolve_folders(None, {}) is None

    def test_empty_config_list_is_none(self):
        assert resolve_folders(None, {"folders": []}) is None


class TestResolveOutputDir:
    def test_cli_wins(self, tmp_path):
        assert resolve_output_dir(tmp_path, {"output_dir": "/somewhere"}) == tmp_path.resolve()

    def test_config_fallback(self, tmp_path):
        cfg = {"output_dir": str(tmp_path)}
        assert resolve_output_dir(None, cfg) == tmp_path.resolve()

    def test_expanduser(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        out = resolve_output_dir(Path("~/notes"), {})
        assert out == (tmp_path / "notes").resolve()

    def test_default_is_cwd(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        assert resolve_output_dir(None, {}) == tmp_path.resolve()
