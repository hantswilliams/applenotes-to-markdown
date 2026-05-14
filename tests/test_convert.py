"""Tests for the pure conversion helpers."""
import json

import pytest

from notes_sync.convert import (
    build_frontmatter,
    html_to_markdown,
    id_suffix,
    sanitize_filename,
)


def _parse_frontmatter(text: str) -> dict:
    """Parse our frontmatter (each value is a JSON-encoded string)."""
    assert text.startswith("---\n") and text.endswith("---\n\n")
    body = text[len("---\n"):-len("---\n\n")]
    out = {}
    for line in body.strip().split("\n"):
        key, _, value = line.partition(":")
        out[key.strip()] = json.loads(value.strip())
    return out


# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------

class TestSanitizeFilename:
    @pytest.mark.parametrize("raw,expected", [
        ("Plain Name", "Plain Name"),
        ("With/slash", "Withslash"),
        ('a<>:"/\\|?*b', "ab"),
        ("  spaced  ", "spaced"),
        ("multi\t \nwhitespace", "multi whitespace"),
        ("", "Untitled"),
        ("///", "Untitled"),
        (".hidden", "hidden"),
    ])
    def test_basic_sanitation(self, raw, expected):
        assert sanitize_filename(raw) == expected

    def test_length_clamp(self):
        long_name = "x" * 250
        assert len(sanitize_filename(long_name)) == 100

    def test_control_chars_removed(self):
        assert sanitize_filename("hello\x00world\x01") == "helloworld"


# ---------------------------------------------------------------------------
# id_suffix
# ---------------------------------------------------------------------------

class TestIdSuffix:
    def test_deterministic(self):
        assert id_suffix("foo") == id_suffix("foo")

    def test_length(self):
        assert len(id_suffix("abc", length=8)) == 8
        assert len(id_suffix("abc", length=12)) == 12

    def test_different_ids_differ(self):
        assert id_suffix("x-coredata://1/note/A") != id_suffix("x-coredata://1/note/B")


# ---------------------------------------------------------------------------
# build_frontmatter
# ---------------------------------------------------------------------------

class TestBuildFrontmatter:
    def test_round_trip(self):
        fm = build_frontmatter(
            title="Hello",
            note_id="x-coredata://abc",
            folder="Work",
            created="2026-01-01T00:00:00.000Z",
            modified="2026-05-14T10:23:45.000Z",
        )
        parsed = _parse_frontmatter(fm)
        assert parsed == {
            "title": "Hello",
            "id": "x-coredata://abc",
            "folder": "Work",
            "created": "2026-01-01T00:00:00.000Z",
            "modified": "2026-05-14T10:23:45.000Z",
        }

    def test_escapes_breaking_chars(self):
        """Colons, quotes, and # in titles must not break parsing."""
        fm = build_frontmatter(
            title='Plan: "Q3" goals # roadmap',
            note_id="id1",
            folder="Work: Big",
            created="2026-01-01T00:00:00.000Z",
            modified="2026-01-01T00:00:00.000Z",
        )
        parsed = _parse_frontmatter(fm)
        assert parsed["title"] == 'Plan: "Q3" goals # roadmap'
        assert parsed["folder"] == "Work: Big"

    def test_handles_newlines_in_title(self):
        fm = build_frontmatter(
            title="line1\nline2",
            note_id="id1",
            folder="F",
            created="2026-01-01T00:00:00.000Z",
            modified="2026-01-01T00:00:00.000Z",
        )
        parsed = _parse_frontmatter(fm)
        assert parsed["title"] == "line1\nline2"


# ---------------------------------------------------------------------------
# html_to_markdown
# ---------------------------------------------------------------------------

class TestHtmlToMarkdown:
    def test_basic_conversion(self):
        out = html_to_markdown("<h1>Title</h1><p>Hello <b>world</b></p>")
        assert "# Title" in out
        assert "**world**" in out

    def test_collapses_excess_newlines(self):
        out = html_to_markdown("<p>a</p><br><br><br><br><br><p>b</p>")
        assert "\n\n\n" not in out

    def test_strips_outer_whitespace(self):
        out = html_to_markdown("<p>hi</p>")
        assert out == out.strip()
