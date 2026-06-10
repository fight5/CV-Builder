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

import json as _json

from modules import applications_tracker, browser_manager, config, file_manager
from modules.browser_manager import BrowserSession, JsonlEventLogger, StopRequested
from modules.optimum_pipeline import CVPreferences, run_optimum_pipeline


PLATFORM_MODULES = {
    "linkedin": "modules.linkedin_apply",
    "jobteaser": "modules.jobteaser_apply",
}

# Sélecteurs pour scraper la description d'une offre LinkedIn
_LINKEDIN_DESC_SELECTORS = [
    ".jobs-description__content",
    "#job-details",
    ".jobs-description-content__text",
    ".show-more-less-html__markup",
    ".description__text",
]


def _scrape_job_description(session: "BrowserSession", job_url: str, logger) -> str:
    """Navigue vers la page de l'offre et extrait son texte complet.

    Retourne une chaîne vide si la description n'a pas pu être extraite.
    Ne lève pas d'exception — les erreurs sont loguées en debug.
    """
    try:
        session.page.goto(job_url, wait_until="domcontentloaded", timeout=20_000)
        session.page.wait_for_timeout(1_500)          # laisser le JS rendre le contenu
        for sel in _LINKEDIN_DESC_SELECTORS:
            try:
                el = session.page.locator(sel).first
                if el.count() > 0:
                    text = el.inner_text(timeout=4_000).strip()
                    if len(text) > 150:                # description non-vide
                        logger("debug", f"Description scrappée ({len(text)} chars) via {sel}")
                        return text
            except Exception:
                continue
    except Exception as e:
        logger("debug", f"Scrape description échoué ({job_url}): {e}")
    return ""


def _write_state(state: dict) -> None:
    file_manager.write_json(config.RUN_STATE_JSON, state)


def main() -> int:
    parser = argparse.ArgumentParser(description="Runner de candidatures automatiques")
    parser.add_argument("--platform", required=True, choices=list(PLATFORM_MODULES))
    parser.add_argument("--keywords", required=True)
    parser.add_argument("--location", default="")
    parser.add_argument("--max-applications", type=int, default=5)
    # CV génération par offre
    parser.add_argument("--cv-source-file", default="", help="Chemin vers le fichier texte du CV de base.")
    parser.add_argument("--job-target-file", default="", help="Chemin vers le fichier texte du poste ciblé.")
    parser.add_argument("--template", default="optimum", choices=["optimum", "minimal"])
    parser.add_argument("--language", default="Français")
    parser.add_argument("--accent-hex", default="#006699")
    parser.add_argument("--leftbg-hex", default="#172E4A")
    parser.add_argument("--include-photo", action="store_true",
                        help="Inclure la photo d'identité (templates/assets/photo_didentite.png)")
    parser.add_argument("--qr-code-label", default="",
                        help="Label affiché sous le QR code dans le CV.")
    # Compat legacy
    parser.add_argument("--cv-path", default="")
    parser.add_argument("--letter-path", default="")
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

    # Lecture du CV source et du poste ciblé depuis les fichiers temp
    cv_source_text = ""
    job_target_text = ""
    if args.cv_source_file and Path(args.cv_source_file).exists():
        cv_source_text = Path(args.cv_source_file).read_text(encoding="utf-8")
        event_logger("info", f"CV source chargé : {len(cv_source_text)} caractères")
    if args.job_target_file and Path(args.job_target_file).exists():
        job_target_text = Path(args.job_target_file).read_text(encoding="utf-8")

    # QR code : si qrcode.png existe dans templates/assets, l'utiliser
    assets_dir = Path(__file__).resolve().parent.parent / "templates" / "assets"
    qr_path = str(assets_dir / "qrcode.png") if (assets_dir / "qrcode.png").exists() else None

    cv_prefs = CVPreferences(
        template=args.template,
        language=args.language,
        accent_hex=args.accent_hex,
        leftbg_hex=args.leftbg_hex,
        aggressive=True,
        include_photo=args.include_photo,
        qr_code_path=qr_path,
        qr_code_label=args.qr_code_label,
    )

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
            # Vérification login
            if not session.has_saved_session():
                event_logger(
                    "error",
                    f"Aucune session sauvegardée pour {args.platform}. "
                    f"Clique 'Se connecter' dans l'UI, puis confirme.",
                )
                _write_state({"status": "error", "error": "no_saved_session"})
                return 3

            # Si la session est un marqueur vide (créé par le bouton Confirmer)
            # → on ouvre LinkedIn en headed et on attend le login manuel.
            cookies_path = config.COOKIES_DIR / f"{args.platform}.json"
            session_empty = False
            try:
                state_data = _json.loads(cookies_path.read_text(encoding="utf-8"))
                session_empty = not bool(state_data.get("cookies"))
            except Exception:
                pass

            if session_empty and not args.headless:
                event_logger("info", "Session vide détectée — connexion manuelle requise.")
                event_logger("info", "Une fenêtre Chrome va s'ouvrir — connectez-vous à LinkedIn.")
                spec = config.PLATFORMS[args.platform]
                try:
                    # Import du READY_SELECTOR spécifique à la plateforme
                    ready_sel = None
                    if args.platform == "linkedin":
                        from modules.linkedin_apply import READY_SELECTOR
                        ready_sel = READY_SELECTOR
                    elif args.platform == "jobteaser":
                        from modules.jobteaser_apply import READY_SELECTOR
                        ready_sel = READY_SELECTOR
                    session.manual_login(spec.base_url, ready_selector=ready_sel)
                    event_logger("info", "Connexion réussie — session sauvegardée.")
                except TimeoutError:
                    event_logger("error", "Login timeout (4 min). Relancez après connexion.")
                    _write_state({"status": "error", "error": "login_timeout"})
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

                # ── Génération CV personnalisé pour cette offre ───────────────
                cv_path_for_job = args.cv_path  # fallback legacy
                letter_path_for_job = args.letter_path
                letter_text_for_job = args.letter_text

                if cv_source_text:
                    try:
                        event_logger("info", f"Génération CV pour : {job.title} @ {job.company}")

                        # ── Scraper la vraie description de l'offre ──────────
                        raw_desc = _scrape_job_description(session, job.url, event_logger)
                        if raw_desc:
                            event_logger("info", f"Description offre scrappée ({len(raw_desc)} chars)")
                            job_description = (
                                f"Poste : {job.title}\n"
                                f"Entreprise : {job.company}\n\n"
                                f"{raw_desc}"
                            )
                        else:
                            # Fallback : titre + contexte générique de l'utilisateur
                            event_logger("warning", "Description offre non scrappée — fallback générique")
                            job_description = (
                                f"Poste : {job.title}\n"
                                f"Entreprise : {job.company}\n\n"
                                f"Profil ciblé : {job_target_text}"
                            )

                        result = run_optimum_pipeline(job_description, cv_source_text, cv_prefs)
                        cv_bytes = result.get("cv_pdf_bytes")
                        lm_bytes = result.get("letter_pdf_bytes")
                        cv_filename = result.get("cv_filename", f"{job.title}_CV.pdf")
                        lm_filename = result.get("letter_filename", f"{job.title}_Lettre.pdf")

                        config.CVS_GENERATED_DIR.mkdir(parents=True, exist_ok=True)
                        config.LETTERS_DIR.mkdir(parents=True, exist_ok=True)

                        if cv_bytes:
                            cv_dest = config.CVS_GENERATED_DIR / cv_filename
                            cv_dest.write_bytes(cv_bytes)
                            cv_path_for_job = str(cv_dest)
                            event_logger("info", f"CV généré : {cv_filename}")
                        if lm_bytes:
                            lm_dest = config.LETTERS_DIR / lm_filename
                            lm_dest.write_bytes(lm_bytes)
                            letter_path_for_job = str(lm_dest)
                            letter_text_for_job = result.get("letter_body", "")
                        else:
                            for err in result.get("cv_errors", []) + result.get("letter_errors", []):
                                event_logger("warning", f"Pipeline : {err}")
                    except Exception as gen_err:
                        event_logger("warning", f"Génération CV échouée, utilisation du CV par défaut : {gen_err}")

                try:
                    status, notes = platform_mod.apply_to_job(
                        session,
                        job,
                        cv_path=cv_path_for_job,
                        letter_text=letter_text_for_job,
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
                    cv_path=cv_path_for_job,
                    letter_path=letter_path_for_job,
                    notes=notes,
                )
                event_logger("info", f"Resultat: {status} ({notes})")

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
