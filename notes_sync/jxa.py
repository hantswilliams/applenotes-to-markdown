"""JXA (JavaScript for Automation) bridge to Apple Notes via osascript."""
from __future__ import annotations

import json
import subprocess
import sys
import threading


class JXAError(RuntimeError):
    """Raised when an osascript invocation fails."""


def run_jxa(script: str) -> str:
    """Run a JXA script via osascript and return stdout.

    Stderr is streamed live to the caller's stderr (so scripts can emit
    progress lines while running) and also collected for error reporting.
    """
    proc = subprocess.Popen(
        ["osascript", "-l", "JavaScript", "-e", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stderr_chunks: list[str] = []

    def _drain_stderr() -> None:
        assert proc.stderr is not None
        for line in iter(proc.stderr.readline, ""):
            stderr_chunks.append(line)
            sys.stderr.write(line)
            sys.stderr.flush()

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()
    assert proc.stdout is not None
    stdout = proc.stdout.read()
    proc.wait()
    t.join()

    if proc.returncode != 0:
        msg = "Error accessing Apple Notes."
        joined = "".join(stderr_chunks).strip()
        if joined:
            msg += f"\n{joined}"
        msg += (
            "\n\nEnsure your terminal has Notes access:"
            "\nSystem Settings > Privacy & Security > Automation"
        )
        raise JXAError(msg)
    return stdout.strip()


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
    """Fetch full HTML body + attachment listing for the given note ids.

    Returns {
        "bodies": {id: body_html},
        "attachments": {id: [{"att_id": str, "name": str | None}, ...]},
        "missing": [id, ...],
        "locked": int,
    }.
    Streams a progress line to stderr every ``progress_every`` notes.
    """
    if not ids:
        return {"bodies": {}, "attachments": {}, "missing": [], "locked": 0}

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
    const attachments = {{}};
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
            const attList = [];
            try {{
                for (const a of note.attachments()) {{
                    let aid; try {{ aid = a.id(); }} catch (e) {{ continue; }}
                    let aname = null;
                    try {{ aname = a.name(); }} catch (e) {{ aname = null; }}
                    attList.push({{ att_id: aid, name: aname }});
                }}
            }} catch (e) {{ /* note has no accessible attachments */ }}
            attachments[id] = attList;
            count++;
            if (progressEvery > 0 && count % progressEvery === 0) logProgress(count);
        }}
    }}
    const missing = [];
    for (const id of targetIds) {{
        if (!(id in bodies)) missing.push(id);
    }}
    JSON.stringify({{
        bodies: bodies,
        attachments: attachments,
        missing: missing,
        locked: locked,
    }});
    """
    return json.loads(_run_or_exit(jxa))


def save_note_attachments(plan: dict[str, list[dict]]) -> dict:
    """Write attachments to disk in a single JXA round-trip.

    ``plan`` maps note_id -> [{"att_id": str, "dest": str (absolute path)}, ...].
    Caller is responsible for creating parent directories beforehand.

    Returns {att_id: {"ok": bool, "err": str | None}}. Attachments that error
    on save (typically inline drawings / link previews that Apple Notes won't
    export via JXA) come back with ok=False.
    """
    if not plan:
        return {}

    note_ids = list(plan.keys())
    plan_js = json.dumps(plan)
    note_ids_js = json.dumps(note_ids)
    jxa = f"""
    const app = Application("Notes");
    const targetNoteIds = new Set({note_ids_js});
    const plan = {plan_js};
    const results = {{}};
    for (const folder of app.folders()) {{
        for (const note of folder.notes()) {{
            let nid; try {{ nid = note.id(); }} catch (e) {{ continue; }}
            if (!targetNoteIds.has(nid)) continue;
            const wanted = {{}};
            for (const entry of plan[nid]) {{ wanted[entry.att_id] = entry.dest; }}
            for (const a of note.attachments()) {{
                let aid; try {{ aid = a.id(); }} catch (e) {{ continue; }}
                const dest = wanted[aid];
                if (!dest) continue;
                try {{
                    a.save({{ in: Path(dest) }});
                    results[aid] = {{ ok: true, err: null }};
                }} catch (e) {{
                    results[aid] = {{ ok: false, err: e.message }};
                }}
            }}
        }}
    }}
    // Mark any planned attachments we never reached (note disappeared, etc.)
    for (const nid of Object.keys(plan)) {{
        for (const entry of plan[nid]) {{
            if (!(entry.att_id in results)) {{
                results[entry.att_id] = {{ ok: false, err: "attachment not found" }};
            }}
        }}
    }}
    JSON.stringify(results);
    """
    return json.loads(_run_or_exit(jxa))
