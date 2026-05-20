"""Gestion du dossier `JobAgentAI/` côté utilisateur.

- Crée l'arborescence au 1er lancement.
- I/O JSON/CSV en écriture atomique (tmpfile + os.replace) pour éviter de
  corrompre un fichier si le processus est tué pendant l'écriture.
- Fournit des helpers stop-flag / open-folder.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

# ── Initialisation ───────────────────────────────────────────────────────────
def ensure_directories() -> None:
    """Crée toute l'arborescence JobAgentAI/ si absente. Idempotent."""
    for d in (
        config.JOB_AGENT_HOME,
        config.DATA_DIR,
        config.COOKIES_DIR,
        config.CVS_DIR,
        config.CVS_ORIGINAL_DIR,
        config.CVS_GENERATED_DIR,
        config.LETTERS_DIR,
        config.SCREENSHOTS_DIR,
        config.LOGS_DIR,
        config.TEMP_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)

    # Bootstrap des fichiers JSON par défaut.
    if not config.SETTINGS_JSON.exists():
        write_json(config.SETTINGS_JSON, {
            "default_platform": "linkedin",
            "default_max_applications": 10,
            "headless": False,
            "human_delay_ms": [config.HUMAN_DELAY_MS_MIN, config.HUMAN_DELAY_MS_MAX],
        })
    if not config.USER_PROFILE_JSON.exists():
        write_json(config.USER_PROFILE_JSON, {
            "full_name": "",
            "email": "",
            "phone": "",
            "linkedin_url": "",
            "default_cv_path": "",
            "default_language": "Français",
        })


# ── Écriture atomique JSON ───────────────────────────────────────────────────
def write_json(path: Path, data: Any) -> None:
    """Écrit `data` en JSON UTF-8 de façon atomique."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_json(path: Path, default: Any = None) -> Any:
    """Lit un fichier JSON ; retourne `default` si absent ou corrompu."""
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


# ── Stop-flag : communication UI <-> subprocess ──────────────────────────────
def request_stop() -> None:
    """Touche le fichier STOP. Le subprocess Playwright le polle entre actions."""
    config.STOP_FLAG.parent.mkdir(parents=True, exist_ok=True)
    config.STOP_FLAG.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


def stop_requested() -> bool:
    return config.STOP_FLAG.exists()


def clear_stop() -> None:
    if config.STOP_FLAG.exists():
        try:
            config.STOP_FLAG.unlink()
        except OSError:
            pass


# ── Ouverture du dossier dans l'explorateur natif ────────────────────────────
def open_folder(path: Path | None = None) -> None:
    """Ouvre `path` (ou JOB_AGENT_HOME) dans l'explorateur de fichiers."""
    target = path or config.JOB_AGENT_HOME
    target = Path(target)
    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(target)], check=False)
    else:
        subprocess.run(["xdg-open", str(target)], check=False)


# ── Utilitaires divers ───────────────────────────────────────────────────────
def utc_now_iso() -> str:
    """ISO 8601 UTC, secondes précision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str, max_len: int = 60) -> str:
    """Slugify simple pour nommer fichiers (lettres, screenshots)."""
    out = []
    for ch in text.strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("-")
    s = "".join(out)
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")[:max_len] or "untitled"
