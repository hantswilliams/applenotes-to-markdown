"""Conversion helpers: HTML to Markdown, filename sanitation, frontmatter."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from urllib.parse import quote

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

_IMAGE_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".heif",
    ".bmp", ".tiff", ".tif", ".svg",
})


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


def attachment_filename(index: int, name: str | None, att_id: str) -> str:
    """Build a stable, sanitized filename for an attachment within its note's
    .assets/ folder.

    - 1-based ``index`` keeps a deterministic ordering across re-syncs.
    - When Apple Notes provides ``name`` (e.g. ``Screen Shot ... .png``), we
      sanitize it and use it directly.
    - When ``name`` is missing, we fall back to ``attachment-<idhash>.bin``.
      (Apple Notes generally won't successfully save unnamed inline elements
      anyway; this is just defensive.)
    """
    prefix = f"{index:02d}-"
    if name:
        cleaned = sanitize_filename(name)
        if cleaned and cleaned != "Untitled":
            return prefix + cleaned
    return f"{prefix}attachment-{id_suffix(att_id)}.bin"


def is_image_filename(name: str) -> bool:
    return PurePosixPath(name).suffix.lower() in _IMAGE_EXTS


def build_attachments_section(
    entries: list[dict],
    *,
    assets_dirname: str,
    unsupported_count: int = 0,
) -> str:
    """Render the trailing ``## Attachments`` markdown block.

    ``entries`` is a list of ``{"filename": str, "display": str}`` for each
    attachment that was successfully exported. Image-typed filenames render
    with ``![]()``; everything else with ``[]()``.

    Returns the empty string when there's nothing to show.
    """
    if not entries and unsupported_count == 0:
        return ""

    lines = ["## Attachments", ""]
    for entry in entries:
        filename = entry["filename"]
        display = entry.get("display") or filename
        link = f"{quote(assets_dirname)}/{quote(filename)}"
        if is_image_filename(filename):
            lines.append(f"- ![{display}]({link})")
        else:
            lines.append(f"- [{display}]({link})")
    if unsupported_count:
        noun = "attachment" if unsupported_count == 1 else "attachments"
        lines.append(
            f"- *{unsupported_count} {noun} could not be exported "
            "(likely a drawing, scan, or link preview).*"
        )
    return "\n".join(lines) + "\n"


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
