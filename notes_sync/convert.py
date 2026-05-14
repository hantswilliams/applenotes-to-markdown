"""Conversion helpers: HTML to Markdown, filename sanitation, frontmatter."""
from __future__ import annotations

import hashlib
import json
import re

import html2text

_h2t = html2text.HTML2Text()
_h2t.ignore_links = False
_h2t.ignore_images = False
_h2t.body_width = 0
_h2t.ignore_emphasis = False
_h2t.single_line_break = True

_FILENAME_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")
_TRIPLE_NEWLINE = re.compile(r"\n{3,}")
_MAX_FILENAME_LEN = 100


def html_to_markdown(html_content: str) -> str:
    """Convert HTML to Markdown, collapsing excess blank lines."""
    markdown = _h2t.handle(html_content)
    return _TRIPLE_NEWLINE.sub("\n\n", markdown).strip()


def sanitize_filename(name: str) -> str:
    """Strip filesystem-unsafe characters and clamp length."""
    safe = _FILENAME_BAD_CHARS.sub("", name)
    safe = _WHITESPACE.sub(" ", safe).strip()
    safe = safe.lstrip(".")  # avoid hidden files
    if len(safe) > _MAX_FILENAME_LEN:
        safe = safe[:_MAX_FILENAME_LEN].rstrip()
    return safe or "Untitled"


def id_suffix(note_id: str, length: int = 8) -> str:
    """Short deterministic suffix derived from a note id, for filename collisions."""
    return hashlib.sha256(note_id.encode("utf-8")).hexdigest()[:length]


def build_frontmatter(
    *,
    title: str,
    note_id: str,
    folder: str,
    created: str,
    modified: str,
) -> str:
    """YAML frontmatter block. String values are JSON-quoted for safe escaping
    (JSON strings are a strict subset of valid YAML)."""
    return (
        "---\n"
        f"title: {json.dumps(title)}\n"
        f"id: {json.dumps(note_id)}\n"
        f"folder: {json.dumps(folder)}\n"
        f"created: {json.dumps(created)}\n"
        f"modified: {json.dumps(modified)}\n"
        "---\n\n"
    )
