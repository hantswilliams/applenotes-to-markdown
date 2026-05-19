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
- **Attachments exported** — images, PDFs, audio etc. saved into a sibling
  `<Note>.assets/` folder and linked at the bottom of the markdown.
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

### Run without installing

From a clone of the repo, you can run the CLI without installing it globally:

```bash
# with uv — handles deps automatically, no venv setup needed
uv run --with html2text python -m notes_sync list

# or, if you already have html2text in your environment
python -m notes_sync list
```

Every command shown below works with `python -m notes_sync ...` in place of
`notes-sync ...`.

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
notes-sync sync --no-attachments         # skip image/PDF export
notes-sync sync -f "Work" --force        # re-fetch every note in a folder
notes-sync watch -f "Work" --interval 30
notes-sync config -f "Work,Personal" -o ~/notes
```

### Output layout

```
~/notes/
├── .notes-sync-state.json        # id → mtime map (do not edit by hand)
├── Work/
│   ├── Meeting Notes.md
│   ├── Meeting Notes.assets/    # attachments live alongside their note
│   │   ├── 01-whiteboard.png
│   │   └── 02-handout.pdf
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

## Attachments

- ![whiteboard.png](Meeting%20Notes.assets/01-whiteboard.png)
- [handout.pdf](Meeting%20Notes.assets/02-handout.pdf)
```

### Attachments

Attachment export is **on by default**. For each note with attachments:

- A sibling `<Note Title>.assets/` directory is created.
- Files are named `NN-<original-name>` (`NN` = 1-based, two-digit index for
  stable ordering across re-syncs). Unnamed attachments fall back to
  `NN-attachment-<hash>.bin`.
- A trailing `## Attachments` section in the markdown links each file — images
  with `![]()`, everything else with `[]()`. URL-escaped so spaces work in
  Obsidian and most renderers.
- The `.assets/` folder is **owned by notes-sync** — it's wiped and rebuilt
  whenever the note's body is refetched, so don't drop files there manually.
- On `--prune`, the `.assets/` folder follows its `.md` into `.trash/`.
- Some attachments (inline drawings, scans, link previews) can't be exported
  via Apple's scripting bridge. They're counted and noted in the
  `## Attachments` section but not saved.

Opt out per-run with `--no-attachments`, or persist with
`notes-sync config --no-attachments`.

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

To bypass the diff and re-fetch every in-scope note (e.g. after editing the
converter, or to regenerate a single folder), pass `--force`:

```bash
notes-sync sync -f "Work" --force        # re-sync just that folder
notes-sync sync --force                  # re-sync everything
```

`--force` honours `-f` / `--folders`, so it's the supported way to regenerate a
single folder without touching the rest of the state file.

### Example: regenerate one folder, text-only

Say you have an Apple Notes folder called **Fordham** and want to rebuild its
Markdown from scratch — ignoring any prior sync state — and you don't want
images or other attachments to come along:

```bash
notes-sync sync -f "Fordham" --force --no-attachments
```

What this does:

- `-f "Fordham"` — restricts the sync to just the Fordham folder; other folders
  in your state file are untouched.
- `--force` — bypasses the `modified`-timestamp diff so every note in Fordham
  is re-fetched and rewritten, even if its modification date hasn't changed.
- `--no-attachments` — skips the attachment export entirely. No `.assets/`
  folder is created and no `## Attachments` section is appended.

Heads up: `--no-attachments` only controls the *current* run. If a previous
sync of Fordham already created `<Note>.assets/` folders, those still exist on
disk. Delete them manually if you want a fully attachment-free mirror:

```bash
rm -rf ~/notes/Fordham/*.assets
```

To persist the no-attachments default for future runs:

```bash
notes-sync config --no-attachments
```

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
- **Some attachments can't be exported.** Inline drawings, scans, and link
  previews aren't exposed as standalone files by Apple's scripting bridge.
  They're counted and called out in the markdown but not saved. Regular images,
  PDFs, audio, etc. export fine.
- **Locked notes are skipped.** Password-protected notes can't be read via JXA.
  They show up in the "locked" count but aren't synced.

## License

MIT
