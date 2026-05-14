# notes-sync

Sync Apple Notes to plain Markdown files on disk — one folder per Notes folder,
with YAML frontmatter, incremental updates, and a `watch` mode that keeps a
local mirror up to date.

Designed to play nicely with AI tools: once your notes live as Markdown on
disk, you can point Claude / Cursor / any RAG pipeline at them.

> macOS only. Uses [JXA](https://developer.apple.com/library/archive/documentation/LanguagesUtilities/Conceptual/MacAutomationScriptingGuide/index.html)
> via `osascript` to talk to Apple Notes.

## Features

- **Incremental sync** — only re-fetches notes whose modification date changed.
  Powered by a `.notes-sync-state.json` file alongside your output.
- **Watch mode** — poll every N seconds; recovers gracefully from transient errors.
- **Dry-run** — preview what would change without writing.
- **Prune** — move markdown files for deleted notes into `.trash/<timestamp>/`.
- **Safe filenames** — strips bad characters, clamps length, deterministically
  suffixes on collisions using a hash of the note id.
- **Safe frontmatter** — titles with colons, quotes, or `#` won't break parsers
  (values are JSON-quoted, which is valid YAML).
- **Config file** — save default folders + output dir so you can just type
  `notes-sync sync`.

## Install

Requires Python 3.10+ and macOS.

```bash
# from a clone of this repo
pip install .

# or with uv (recommended)
uv tool install .
```

Once installed, `notes-sync` is available on your PATH.

### First-run permissions

Apple Notes will prompt for permission the first time your terminal talks to it.
You may also need to grant access manually:

> System Settings → Privacy & Security → Automation → (your terminal) → Notes

If you see "Error accessing Apple Notes" with no other context, that's usually it.

## Usage

```text
notes-sync list                          # list all folders + note counts
notes-sync info "Work"                   # metadata for a single folder
notes-sync sync                          # sync all folders to cwd
notes-sync sync -f "Work,Personal" -o ~/notes
notes-sync sync --dry-run --prune        # preview changes incl. deletions
notes-sync watch -f "Work" --interval 30
notes-sync config -f "Work,Personal" -o ~/notes
```

### Output layout

```
~/notes/
├── .notes-sync-state.json        # id → mtime map (do not edit by hand)
├── Work/
│   ├── Meeting Notes.md
│   └── Q3 Plan.md
└── Personal/
    └── Grocery List.md
```

Each `.md` file starts with YAML frontmatter:

```yaml
---
title: "Meeting Notes"
id: "x-coredata://.../ICNote/p123"
folder: "Work"
created: "2026-01-15T14:00:00.000Z"
modified: "2026-05-14T10:23:45.000Z"
---

# meeting notes body as markdown...
```

### Config

Saved to `./notes-sync.json` in whatever directory you run `notes-sync config`
from. CLI flags always win over the config file.

```bash
notes-sync config -f "Work,Personal" -o ~/notes
notes-sync config                  # view current config
notes-sync config -f ""            # clear default folders
notes-sync config --clear          # remove config file entirely
```

### Watch mode

```bash
notes-sync watch -f "Work" --interval 30 --prune
```

Polls Apple Notes every 30s, syncs changes, and moves deleted notes to
`.trash/`. Errors during a tick are logged but don't kill the watcher.

## How incremental sync works

1. **Pass 1 — metadata.** A fast JXA call returns `(id, name, folder, modified)`
   for every note (no body content).
2. **Diff against state.** Notes whose `modified` matches the saved value are
   skipped entirely.
3. **Pass 2 — bodies.** Only changed/new notes have their HTML body fetched.
4. **Write + update state.**

This makes `watch` cheap: on quiet ticks it costs one metadata JXA call.

## Working with AI tools

The Markdown output is plain enough to feed to anything:

- Point a vector store / RAG pipeline at `~/notes/`
- Drop the folder into Claude / Cursor as project context
- `grep` / `rg` for quick search across notes
- Use the YAML frontmatter `id` field as a stable cross-reference

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests cover the pure functions (`convert`, `state`, `config`). The JXA layer is
not unit-tested — it requires a real macOS + Apple Notes install.

## Known limitations

- **Top-level folders only.** Apple Notes supports nested subfolders; this tool
  currently flattens to top-level. (PRs welcome.)
- **Multiple accounts merge.** If you have folders with the same name in
  different accounts (iCloud, On My Mac), they merge into one folder on disk.
- **Attachments are dropped.** Inline images and PDFs in notes are stripped by
  `html2text`. The text content survives.
- **Locked notes are skipped.** Password-protected notes can't be read via JXA.
  They show up in the "locked" count but aren't synced.

## License

MIT
