"""
Test bout-en-bout du pipeline de candidature automatique LinkedIn.

Ce script :
  1. Génère un CV depuis un texte CV de base + prérequis (si une clé LLM est dispo).
  2. Ouvre un Chromium visible → connecte-toi à LinkedIn (session sauvegardée).
  3. Cherche des offres Easy Apply selon les mots-clés fournis.
  4. Affiche les offres trouvées.
  5. NE SOUMET AUCUNE CANDIDATURE (dry_run=True par défaut).

Usage :
    python test_linkedin_pipeline.py

Pour tester la soumission réelle (mode semi-auto) :
    python test_linkedin_pipeline.py --submit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Force UTF-8 sur Windows (console cp1252 par défaut)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ── Config du test ────────────────────────────────────────────────────────────
KEYWORDS  = "data scientist"
LOCATION  = "Paris"
MAX_JOBS  = 5
HEADLESS  = False   # toujours False pour voir ce qui se passe

CV_SOURCE_TEXT = """
Jean Dupont — Data Scientist
Email : jean.dupont@email.com | LinkedIn : linkedin.com/in/jeandupont | +33 6 12 34 56 78 | Paris

RÉSUMÉ
Data Scientist avec 5 ans d'expérience en machine learning, NLP et déploiement de modèles en production.
Passionné par l'IA générative et les LLMs.

EXPÉRIENCES
Data Scientist Senior — Safran (2022 – présent)
- Développement d'un modèle de détection d'anomalies réduisant les faux-positifs de 40 %
- Déploiement de 3 APIs ML en production (FastAPI, Docker, Kubernetes)
- Encadrement de 2 Data Scientists juniors

Data Scientist — Sanofi (2020 – 2022)
- Analyse de données cliniques avec Python/R, réduction des délais d'analyse de 25 %
- Construction de pipelines ETL (Airflow, Spark)

FORMATION
Master Data Science — CentraleSupélec (2018 – 2020)
Ingénieur — École Polytechnique (2015 – 2018)

COMPÉTENCES
Python, Scikit-learn, TensorFlow, PyTorch, SQL, Spark, Docker, Git, Airflow, FastAPI

LANGUES
Français (natif), Anglais (C1)
"""

JOB_TARGET = """
Data Scientist Senior, Python, Machine Learning, LLM, RAG, IA générative,
secteur industrie / défense / pharma, Paris, CDI, 4-6 ans d'expérience
"""


# ── Pipeline ──────────────────────────────────────────────────────────────────
def generate_cv_pdf() -> str | None:
    """Génère un CV PDF et retourne son chemin. None si pas de clé LLM."""
    import os
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    has_llm = bool(
        (os.getenv("DEEPSEEK_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
    )
    if not has_llm:
        print("[TEST] Aucune cle LLM - on saute la generation CV.")
        print("       Configurer DEEPSEEK_API_KEY ou GOOGLE_API_KEY dans .env")
        return None

    from modules.optimum_pipeline import CVPreferences, run_optimum_pipeline
    from modules import config

    prefs = CVPreferences(template="optimum", language="Français")
    print(f"[TEST] Génération du CV (LLM)…")
    result = run_optimum_pipeline(JOB_TARGET, CV_SOURCE_TEXT, prefs)

    cv_bytes = result.get("cv_pdf_bytes")
    if not cv_bytes:
        print("[TEST] Compilation PDF échouée :", result.get("cv_errors"))
        return None

    config.CVS_GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    cv_path = config.CVS_GENERATED_DIR / result.get("cv_filename", "test_cv.pdf")
    cv_path.write_bytes(cv_bytes)
    print(f"[TEST] CV genere -> {cv_path}")
    return str(cv_path)


def login_and_search(cv_path: str | None, auto_submit: bool, keywords: str = KEYWORDS, location: str = LOCATION) -> None:
    from modules import config, file_manager
    from modules.browser_manager import BrowserSession, JsonlEventLogger
    from modules.linkedin_apply import search_jobs, apply_to_job, READY_SELECTOR
    from modules import applications_tracker

    file_manager.ensure_directories()

    cookies_file = config.COOKIES_DIR / "linkedin.json"
    already_connected = cookies_file.exists()

    logger = JsonlEventLogger()

    print(f"\n[TEST] Ouverture Chromium (headed)…")
    if not already_connected:
        print("[TEST] Pas de session LinkedIn sauvegardee.")
        print("[TEST] Une fenetre Chromium va s'ouvrir -> connecte-toi a LinkedIn.")
        print("[TEST] La session sera sauvegardee automatiquement.\n")

    with BrowserSession("linkedin", headless=HEADLESS, event_logger=logger) as session:
        if not already_connected:
            session.manual_login(
                "https://www.linkedin.com/login",
                ready_selector=READY_SELECTOR,
            )
            print("[TEST] OK Session LinkedIn sauvegardee.")

        print(f"[TEST] Recherche : '{keywords}' à '{location}' (max {MAX_JOBS} offres Easy Apply)…")
        jobs = search_jobs(
            session,
            keywords=keywords,
            location=location,
            max_results=MAX_JOBS,
        )

        print(f"\n[TEST] {len(jobs)} offre(s) trouvée(s) :\n")
        for i, job in enumerate(jobs, 1):
            print(f"  {i}. {job.title} @ {job.company}")
            print(f"     {job.url}\n")

        if not auto_submit:
            print("[TEST] Mode DRY RUN — aucune candidature soumise.")
            print("[TEST] Relancer avec --submit pour postuler réellement.")
            return

        # ── Application sur chaque offre ─────────────────────────────────
        if not cv_path:
            print("[TEST] Pas de CV généré — impossible de postuler.")
            return

        print(f"\n[TEST] Mode SEMI-AUTO — soumission avec le CV : {cv_path}\n")
        for i, job in enumerate(jobs, 1):
            if applications_tracker.already_applied(job.url):
                print(f"  [{i}] Déjà postulé — skip : {job.title}")
                continue
            print(f"  [{i}] Candidature : {job.title} @ {job.company}…")
            status, notes = apply_to_job(
                session,
                job,
                cv_path=cv_path,
                letter_text="",
                auto_submit=False,   # semi-auto : s'arrête avant le submit final
            )
            print(f"       → {status} ({notes})")
            applications_tracker.record_application(
                platform="linkedin",
                company=job.company,
                job_title=job.title,
                url=job.url,
                status=status,
                cv_path=cv_path or "",
                letter_path="",
                notes=notes,
            )


# ── Entrée ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Test pipeline LinkedIn")
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Activer le mode semi-auto (affiche les formulaires avant soumission).",
    )
    parser.add_argument(
        "--keywords", default=KEYWORDS,
        help=f"Mots-clés de recherche (défaut : {KEYWORDS!r})"
    )
    parser.add_argument(
        "--location", default=LOCATION,
        help=f"Ville (défaut : {LOCATION!r})"
    )
    args = parser.parse_args()

    keywords = args.keywords
    location = args.location

    print("=" * 60)
    print("TEST PIPELINE — Candidature automatique LinkedIn")
    print("=" * 60)
    print(f"  Mots-clés : {keywords}")
    print(f"  Localisation : {location}")
    print(f"  Max offres : {MAX_JOBS}")
    print(f"  Mode : {'SEMI-AUTO' if args.submit else 'DRY RUN (affichage seul)'}")
    print("=" * 60 + "\n")

    cv_path = generate_cv_pdf()
    login_and_search(cv_path, auto_submit=args.submit, keywords=keywords, location=location)

    print("\n[TEST] Terminé.")


if __name__ == "__main__":
    main()
