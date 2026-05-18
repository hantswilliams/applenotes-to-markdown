"""Tests for the pure conversion helpers."""
import json

import pytest

from notes_sync.convert import (
    attachment_filename,
    build_attachments_section,
    build_frontmatter,
    html_to_markdown,
    id_suffix,
    is_image_filename,
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


# ---------------------------------------------------------------------------
# attachment_filename
# ---------------------------------------------------------------------------

class TestAttachmentFilename:
    def test_named_uses_original_with_index_prefix(self):
        out = attachment_filename(1, "Screen Shot 2020-05-10 at 12.04.21 PM.png", "att-id-x")
        assert out == "01-Screen Shot 2020-05-10 at 12.04.21 PM.png"

    def test_index_zero_padded_to_two_digits(self):
        assert attachment_filename(7, "x.pdf", "id").startswith("07-")
        assert attachment_filename(42, "x.pdf", "id").startswith("42-")

    def test_unnamed_falls_back_to_hash_bin(self):
        out = attachment_filename(1, None, "x-coredata://X/ICAttachment/p999")
        assert out.startswith("01-attachment-")
        assert out.endswith(".bin")

    def test_unnamed_is_deterministic_per_id(self):
        a = attachment_filename(1, None, "id-A")
        b = attachment_filename(1, None, "id-A")
        c = attachment_filename(1, None, "id-B")
        assert a == b
        assert a != c

    def test_strips_unsafe_chars_from_original_name(self):
        out = attachment_filename(1, "weird/name?.png", "id")
        assert "/" not in out and "?" not in out
        assert out.endswith(".png")


# ---------------------------------------------------------------------------
# is_image_filename
# ---------------------------------------------------------------------------

class TestIsImageFilename:
    @pytest.mark.parametrize("name", [
        "x.png", "X.PNG", "photo.jpg", "photo.jpeg", "ani.gif",
        "modern.webp", "live.heic", "scan.tiff",
    ])
    def test_image_extensions(self, name):
        assert is_image_filename(name)

    @pytest.mark.parametrize("name", [
        "doc.pdf", "audio.m4a", "video.mov", "notes.txt", "archive.zip",
        "noext", "01-attachment-abc.bin",
    ])
    def test_non_image_extensions(self, name):
        assert not is_image_filename(name)


# ---------------------------------------------------------------------------
# build_attachments_section
# ---------------------------------------------------------------------------

class TestBuildAttachmentsSection:
    def test_empty_returns_empty(self):
        assert build_attachments_section([], assets_dirname="x.assets") == ""

    def test_image_uses_bang_link(self):
        out = build_attachments_section(
            [{"filename": "01-pic.png", "display": "01-pic.png"}],
            assets_dirname="My Note.assets",
        )
        assert "## Attachments" in out
        assert "![01-pic.png](My%20Note.assets/01-pic.png)" in out

    def test_non_image_uses_plain_link(self):
        out = build_attachments_section(
            [{"filename": "02-report.pdf", "display": "02-report.pdf"}],
            assets_dirname="Note.assets",
        )
        assert "[02-report.pdf](Note.assets/02-report.pdf)" in out
        assert "![02-report.pdf]" not in out

    def test_url_encodes_path_segments(self):
        out = build_attachments_section(
            [{"filename": "weird name.png", "display": "weird name.png"}],
            assets_dirname="Folder Name.assets",
        )
        assert "Folder%20Name.assets/weird%20name.png" in out

    def test_unsupported_count_appended(self):
        out = build_attachments_section(
            [],
            assets_dirname="x.assets",
            unsupported_count=2,
        )
        assert "2 attachments could not be exported" in out

    def test_unsupported_count_singular(self):
        out = build_attachments_section(
            [],
            assets_dirname="x.assets",
            unsupported_count=1,
        )
        assert "1 attachment could not be exported" in out

    def test_mixed_listing(self):
        out = build_attachments_section(
            [
                {"filename": "01-shot.png", "display": "01-shot.png"},
                {"filename": "02-doc.pdf",  "display": "02-doc.pdf"},
            ],
            assets_dirname="Note.assets",
            unsupported_count=1,
        )
        assert "![01-shot.png]" in out
        assert "[02-doc.pdf]" in out
        assert "1 attachment could not be exported" in out
