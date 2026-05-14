"""JXA (JavaScript for Automation) bridge to Apple Notes via osascript."""
from __future__ import annotations

import json
import subprocess
import sys


class JXAError(RuntimeError):
    """Raised when an osascript invocation fails."""


def run_jxa(script: str) -> str:
    """Run a JXA script via osascript and return stdout."""
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = "Error accessing Apple Notes."
        if result.stderr:
            msg += f"\n{result.stderr.strip()}"
        msg += (
            "\n\nEnsure your terminal has Notes access:"
            "\nSystem Settings > Privacy & Security > Automation"
        )
        raise JXAError(msg)
    return result.stdout.strip()


def _run_or_exit(script: str) -> str:
    """Run JXA, printing the error and exiting on failure (CLI-friendly)."""
    try:
        return run_jxa(script)
    except JXAError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def fetch_folders() -> list[dict]:
    """Return [{name, count}] for every top-level Notes folder."""
    jxa = """
    const app = Application("Notes");
    const result = [];
    for (const folder of app.folders()) {
        result.push({ name: folder.name(), count: folder.notes().length });
    }
    JSON.stringify(result);
    """
    return json.loads(_run_or_exit(jxa))


def folder_exists(folder_name: str) -> bool:
    """Check whether a folder of the given name exists."""
    name_js = json.dumps(folder_name)
    jxa = f"""
    const app = Application("Notes");
    const target = {name_js};
    let found = false;
    for (const f of app.folders()) {{
        if (f.name() === target) {{ found = true; break; }}
    }}
    JSON.stringify(found);
    """
    return json.loads(_run_or_exit(jxa))


def fetch_folder_meta(folder_name: str) -> list[dict]:
    """Return note metadata for a single folder (no body content)."""
    name_js = json.dumps(folder_name)
    jxa = f"""
    const app = Application("Notes");
    const targetName = {name_js};
    let targetFolder = null;
    for (const f of app.folders()) {{
        if (f.name() === targetName) {{ targetFolder = f; break; }}
    }}
    if (!targetFolder) {{ JSON.stringify([]); }}
    else {{
        const notes = [];
        for (const note of targetFolder.notes()) {{
            notes.push({{
                name: note.name(),
                id: note.id(),
                creationDate: note.creationDate().toISOString(),
                modificationDate: note.modificationDate().toISOString(),
                bodyLength: note.body().length
            }});
        }}
        JSON.stringify(notes);
    }}
    """
    return json.loads(_run_or_exit(jxa))


def fetch_notes_metadata(folder_names: list[str] | None) -> dict:
    """Lightweight metadata for all notes (no bodies). Fast.

    Returns {"notes": [...], "locked": int}.
    """
    if folder_names:
        folder_filter = f"const targetFolders = new Set({json.dumps(folder_names)});"
        folder_check  = "if (!targetFolders.has(folderName)) continue;"
    else:
        folder_filter = ""
        folder_check  = ""

    jxa = f"""
    const app = Application("Notes");
    {folder_filter}
    const notes = [];
    let locked = 0;
    for (const folder of app.folders()) {{
        const folderName = folder.name();
        {folder_check}
        for (const note of folder.notes()) {{
            try {{
                notes.push({{
                    id: note.id(),
                    name: note.name(),
                    folder: folderName,
                    creationDate: note.creationDate().toISOString(),
                    modificationDate: note.modificationDate().toISOString()
                }});
            }} catch (e) {{
                locked++;
            }}
        }}
    }}
    JSON.stringify({{ notes: notes, locked: locked }});
    """
    return json.loads(_run_or_exit(jxa))


def fetch_note_bodies(ids: list[str], progress_every: int = 25) -> dict:
    """Fetch full HTML body for the given note ids.

    Returns {"bodies": {id: body}, "missing": [id, ...], "locked": int}.
    Streams a progress line to stderr every ``progress_every`` notes.
    """
    if not ids:
        return {"bodies": {}, "missing": [], "locked": 0}

    ids_js = json.dumps(ids)
    progress_js = json.dumps(progress_every)
    jxa = f"""
    const app = Application("Notes");
    const targetIds = new Set({ids_js});
    const progressEvery = {progress_js};
    ObjC.import("Foundation");
    const stderr = $.NSFileHandle.fileHandleWithStandardError;
    function logProgress(n) {{
        const msg = `  Progress: ${{n}}/${{targetIds.size}} bodies...\\n`;
        stderr.writeData($(msg).dataUsingEncoding($.NSUTF8StringEncoding));
    }}

    const bodies = {{}};
    let count = 0;
    let locked = 0;
    for (const folder of app.folders()) {{
        for (const note of folder.notes()) {{
            let id;
            try {{ id = note.id(); }} catch (e) {{ locked++; continue; }}
            if (!targetIds.has(id)) continue;
            try {{
                bodies[id] = note.body();
            }} catch (e) {{
                locked++;
                continue;
            }}
            count++;
            if (progressEvery > 0 && count % progressEvery === 0) logProgress(count);
        }}
    }}
    const missing = [];
    for (const id of targetIds) {{
        if (!(id in bodies)) missing.push(id);
    }}
    JSON.stringify({{ bodies: bodies, missing: missing, locked: locked }});
    """
    return json.loads(_run_or_exit(jxa))
