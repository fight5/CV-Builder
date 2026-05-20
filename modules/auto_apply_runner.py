"""Subprocess CLI : exécute une session de candidatures et stream les events.

Pourquoi un subprocess plutôt qu'un thread Streamlit ?
- Playwright sync ouvre un event loop dans le thread courant — conflit certain
  avec le re-run loop de Streamlit.
- Subprocess = isolation propre : si le navigateur plante, Streamlit reste vivant.
- L'UI poll `temp/run_log.jsonl` (tail-like) et `temp/run_state.json` pour
  l'avancement, et peut `touch temp/STOP` pour interrompre.

Lancement :
    python -m modules.auto_apply_runner --platform linkedin \
        --keywords "data scientist" --location Paris --max-applications 5 \
        --cv-path /chemin/cv.pdf [--letter-text "..." ] [--auto-submit]

Outputs (dans JOB_AGENT_HOME/temp/) :
    run_log.jsonl   : 1 ligne JSON par event {ts, level, msg}
    run_state.json  : état courant {status, processed, total, current_job}
"""

from __future__ import annotations

import argparse
import importlib
import sys
import traceback
from pathlib import Path

# Permet de lancer ce module en standalone (`python -m modules.auto_apply_runner`)
# même si CWD n'est pas la racine projet.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules import applications_tracker, browser_manager, config, file_manager
from modules.browser_manager import BrowserSession, JsonlEventLogger, StopRequested


PLATFORM_MODULES = {
    "linkedin": "modules.linkedin_apply",
    "jobteaser": "modules.jobteaser_apply",
}


def _write_state(state: dict) -> None:
    file_manager.write_json(config.RUN_STATE_JSON, state)


def main() -> int:
    parser = argparse.ArgumentParser(description="Runner de candidatures automatiques")
    parser.add_argument("--platform", required=True, choices=list(PLATFORM_MODULES))
    parser.add_argument("--keywords", required=True)
    parser.add_argument("--location", default="")
    parser.add_argument("--max-applications", type=int, default=5)
    parser.add_argument("--cv-path", default="")
    parser.add_argument("--letter-text", default="")
    parser.add_argument(
        "--auto-submit",
        action="store_true",
        help="Soumettre automatiquement (sinon mode 'review' : s'arrête avant submit).",
    )
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    file_manager.ensure_directories()
    file_manager.clear_stop()
    # Réinitialise le log de run.
    if config.RUN_LOG_JSONL.exists():
        config.RUN_LOG_JSONL.unlink()

    event_logger = JsonlEventLogger()
    event_logger("info", f"Démarrage runner — plateforme={args.platform}, max={args.max_applications}")

    _write_state({
        "status": "starting",
        "platform": args.platform,
        "processed": 0,
        "total": args.max_applications,
        "submitted": 0,
        "skipped": 0,
        "failed": 0,
        "current_job": "",
    })

    try:
        platform_mod = importlib.import_module(PLATFORM_MODULES[args.platform])
    except ImportError as e:
        event_logger("error", f"Module plateforme introuvable : {e}")
        _write_state({"status": "error", "error": str(e)})
        return 2

    counters = {"submitted": 0, "skipped": 0, "failed": 0, "processed": 0}

    try:
        with BrowserSession(
            args.platform,
            headless=args.headless,
            event_logger=event_logger,
        ) as session:
            # Vérification login : si pas de cookies, on demande à l'utilisateur de
            # se connecter via le bouton dédié (le runner refuse de continuer).
            if not session.has_saved_session():
                event_logger(
                    "error",
                    f"Aucune session sauvegardée pour {args.platform}. "
                    f"Utilise d'abord le bouton 'Se connecter à {args.platform}' dans l'UI.",
                )
                _write_state({"status": "error", "error": "no_saved_session"})
                return 3

            event_logger("info", f"Recherche : keywords='{args.keywords}', location='{args.location}'")
            _write_state({**_state_skeleton(args, counters), "status": "searching"})

            jobs = platform_mod.search_jobs(
                session,
                keywords=args.keywords,
                location=args.location,
                max_results=args.max_applications,
            )
            event_logger("info", f"{len(jobs)} offre(s) à traiter")

            for idx, job in enumerate(jobs, start=1):
                if file_manager.stop_requested():
                    event_logger("warning", "Arrêt demandé par l'utilisateur.")
                    break

                _write_state({
                    **_state_skeleton(args, counters),
                    "status": "applying",
                    "current_job": f"{job.title} @ {job.company}",
                    "processed": idx - 1,
                })

                if applications_tracker.already_applied(job.url):
                    event_logger("info", f"[{idx}/{len(jobs)}] Déjà postulé — skip : {job.title}")
                    counters["skipped"] += 1
                    counters["processed"] += 1
                    continue

                event_logger("info", f"[{idx}/{len(jobs)}] {job.title} @ {job.company}")
                try:
                    status, notes = platform_mod.apply_to_job(
                        session,
                        job,
                        cv_path=args.cv_path,
                        letter_text=args.letter_text,
                        auto_submit=args.auto_submit,
                    )
                except StopRequested:
                    event_logger("warning", "Interrompu pendant la candidature.")
                    break
                except Exception as e:
                    status, notes = "failed", f"{type(e).__name__}: {e}"
                    event_logger("error", f"Erreur candidature : {notes}")
                    try:
                        session.screenshot(f"err_{job.job_id}")
                    except Exception:
                        pass

                counters[status if status in counters else "failed"] += 1
                counters["processed"] += 1

                applications_tracker.record_application(
                    platform=args.platform,
                    company=job.company,
                    job_title=job.title,
                    url=job.url,
                    status=status,
                    cv_path=args.cv_path,
                    letter_path="",
                    notes=notes,
                )
                event_logger("info", f"→ {status} ({notes})")

        _write_state({**_state_skeleton(args, counters), "status": "done"})
        event_logger("info", "Run terminé.")
        return 0

    except StopRequested:
        event_logger("warning", "Arrêt utilisateur.")
        _write_state({**_state_skeleton(args, counters), "status": "stopped"})
        return 4
    except Exception as e:
        tb = traceback.format_exc()
        event_logger("error", f"Erreur fatale : {e}\n{tb}")
        _write_state({**_state_skeleton(args, counters), "status": "error", "error": str(e)})
        return 1
    finally:
        file_manager.clear_stop()


def _state_skeleton(args, counters: dict) -> dict:
    return {
        "platform": args.platform,
        "processed": counters["processed"],
        "total": args.max_applications,
        "submitted": counters["submitted"],
        "skipped": counters["skipped"],
        "failed": counters["failed"],
    }


if __name__ == "__main__":
    sys.exit(main())
