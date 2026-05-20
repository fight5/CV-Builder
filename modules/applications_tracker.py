"""Tracker CSV des candidatures envoyées.

- Format : applications.csv avec en-tête fixe.
- Écriture append-safe (lock fichier par process — suffisant pour usage local).
- Helpers de stats utilisés par le dashboard Streamlit.
"""

from __future__ import annotations

import csv
import threading
from pathlib import Path
from typing import Any

from . import config, file_manager

_WRITE_LOCK = threading.Lock()

FIELDS = [
    "date",          # ISO 8601 UTC
    "platform",      # linkedin / jobteaser / ...
    "company",
    "job_title",
    "url",
    "status",        # submitted / failed / skipped
    "cv_path",       # chemin local du CV utilisé
    "letter_path",   # chemin local de la lettre utilisée (ou "")
    "notes",         # message libre / erreur
]


def _ensure_csv() -> None:
    """Crée le CSV avec l'en-tête s'il n'existe pas encore."""
    file_manager.ensure_directories()
    if not config.APPLICATIONS_CSV.exists():
        with open(config.APPLICATIONS_CSV, "w", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def record_application(
    *,
    platform: str,
    company: str,
    job_title: str,
    url: str,
    status: str,
    cv_path: str = "",
    letter_path: str = "",
    notes: str = "",
) -> None:
    """Ajoute une ligne au tracker. Thread-safe (verrou local)."""
    _ensure_csv()
    row = {
        "date": file_manager.utc_now_iso(),
        "platform": platform,
        "company": company or "",
        "job_title": job_title or "",
        "url": url or "",
        "status": status,
        "cv_path": cv_path,
        "letter_path": letter_path,
        "notes": notes,
    }
    with _WRITE_LOCK:
        with open(config.APPLICATIONS_CSV, "a", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writerow(row)


def load_all() -> list[dict[str, Any]]:
    """Retourne toutes les lignes du tracker (vide si fichier absent)."""
    if not config.APPLICATIONS_CSV.exists():
        return []
    with open(config.APPLICATIONS_CSV, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def stats() -> dict[str, Any]:
    """Stats agrégées pour le dashboard."""
    rows = load_all()
    total = len(rows)
    submitted = sum(1 for r in rows if r.get("status") == "submitted")
    failed = sum(1 for r in rows if r.get("status") == "failed")
    by_platform: dict[str, int] = {}
    for r in rows:
        p = r.get("platform") or "?"
        by_platform[p] = by_platform.get(p, 0) + 1
    success_rate = round((submitted / total) * 100, 1) if total else 0.0
    return {
        "total": total,
        "submitted": submitted,
        "failed": failed,
        "skipped": total - submitted - failed,
        "success_rate": success_rate,
        "by_platform": by_platform,
    }


def already_applied(url: str) -> bool:
    """True si une URL d'offre est déjà dans le tracker (anti-doublon)."""
    if not url:
        return False
    for r in load_all():
        if r.get("url") == url and r.get("status") in ("submitted", "skipped"):
            return True
    return False
