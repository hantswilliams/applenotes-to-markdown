"""Per-directory config file (folders + default output dir)."""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_FILENAME = "notes-sync.json"


def config_path(base: Path | None = None) -> Path:
    return (base or Path.cwd()) / CONFIG_FILENAME


def load_config(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_config(path: Path, config: dict) -> None:
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def resolve_folders(cli_folders: str | None, config: dict) -> list[str] | None:
    """CLI flag wins over config; both absent = all folders."""
    if cli_folders:
        return [f.strip() for f in cli_folders.split(",") if f.strip()]
    if "folders" in config:
        return config["folders"] or None
    return None


def resolve_output_dir(cli_output: Path | None, config: dict) -> Path:
    """CLI flag > config > cwd. Always expanduser'd + resolved."""
    if cli_output is not None:
        chosen = cli_output
    elif "output_dir" in config:
        chosen = Path(config["output_dir"])
    else:
        chosen = Path.cwd()
    return chosen.expanduser().resolve()


def resolve_save_attachments(cli_no_attachments: bool, config: dict) -> bool:
    """Default-on. CLI --no-attachments wins; otherwise honor config."""
    if cli_no_attachments:
        return False
    return bool(config.get("save_attachments", True))
