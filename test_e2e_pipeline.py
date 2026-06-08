"""Test E2E complet du pipeline.

Ce script :
1. Lit le CV de base depuis 'new cv latex.txt' (ton vrai CV).
2. Teste la génération CV + lettre (pdflatex doit être installé).
3. Vérifie les PDFs générés dans outputs/.
4. (Optionnel) Lance le runner LinkedIn en DRY RUN (--dry-run flag).

Usage :
    python test_e2e_pipeline.py              # génère CV + lettre uniquement
    python test_e2e_pipeline.py --linkedin   # + test LinkedIn (DRY RUN, headed)
"""

from __future__ import annotations

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from modules.optimum_pipeline import (
    CVPreferences,
    run_optimum_pipeline,
    ASSETS_DIR,
    OUTPUT_DIR,
)

# -- Offre de test -------------------------------------------------------------
JOB_OFFER_TEST = """
Poste : AI Engineer / Agentic AI Engineer
Entreprise : Thales Group
Lieu : Île-de-France, France
Contrat : CDI

Description :
Nous recherchons un(e) AI Engineer passionné(e) par les architectures d'agents autonomes
pour rejoindre notre équipe Data & IA au sein de la direction innovation de Thales Group.

Missions :
- Concevoir et déployer des pipelines LLM en production (RAG, agents LangChain/LangGraph).
- Développer des systèmes multi-agents capables d'automatiser des workflows complexes.
- Intégrer des modèles de fondation (GPT-4, Claude, Gemini) via des API REST et SDKs Python.
- Mettre en place des évaluations de performance (LLM-as-judge, RAGAS, benchmarks internes).
- Collaborer avec les équipes produit et infrastructure pour industrialiser les prototypes IA.

Profil recherché :
- 3–5 ans d'expérience en Data Science / ML Engineering.
- Maîtrise de Python (LangChain, LangGraph, Pydantic, FastAPI).
- Expérience avec des LLMs : fine-tuning, prompt engineering, RAG.
- Connaissances en MLOps (Docker, CI/CD, MLflow ou Weights & Biases).
- Bonus : expérience avec des agents autonomes (AutoGen, CrewAI, Claude MCP).
- Anglais courant requis.
"""


def main():
    parser = argparse.ArgumentParser(description="Test E2E pipeline CV Builder")
    parser.add_argument("--linkedin", action="store_true",
                        help="Lancer aussi un test LinkedIn (DRY RUN headless)")
    parser.add_argument("--template", default="optimum", choices=["optimum", "minimal"])
    parser.add_argument("--no-pdf", action="store_true",
                        help="Sauter la compilation pdflatex (test LLM uniquement)")
    args = parser.parse_args()

    print("=" * 60)
    print("TEST E2E — CV Builder Pipeline")
    print("=" * 60)

    # -- 1. Vérifications préliminaires ----------------------------------------
    cv_source_path = ROOT / "new cv latex.txt"
    if not cv_source_path.exists():
        print(f"[ERREUR] Fichier CV source introuvable : {cv_source_path}")
        sys.exit(1)

    cv_source_text = cv_source_path.read_text(encoding="utf-8")
    print(f"[OK] CV source chargé : {len(cv_source_text)} caractères")

    if shutil.which("pdflatex") is None:
        if args.no_pdf:
            print("[WARN] pdflatex introuvable — compilation PDF désactivée (--no-pdf)")
        else:
            print("[ERREUR] pdflatex introuvable.")
            print("         Installez MiKTeX : https://miktex.org/download")
            print("         Ou TeX Live : https://tug.org/texlive/")
            print("         Puis relancez ce script.")
            sys.exit(1)
    else:
        print(f"[OK] pdflatex trouvé : {shutil.which('pdflatex')}")

    # -- 2. Vérification dossier assets ----------------------------------------
    print(f"\n[INFO] Dossier assets : {ASSETS_DIR}")
    if ASSETS_DIR.exists():
        imgs = [f.name for f in ASSETS_DIR.iterdir()
                if f.suffix.lower() in {".png", ".jpg", ".jpeg"}]
        if imgs:
            print(f"[OK]  Logos trouvés : {', '.join(imgs)}")
        else:
            print("[WARN] Aucun logo trouvé dans templates/assets/")
            print("       Mettez vos images là (Thales.png, Sanofi.png, EPF.png...)")
            print("       La photo (photo_didentite.png) sera incluse automatiquement.")
    else:
        print("[WARN] Dossier templates/assets/ absent — logos non inclus.")

    # -- 3. Génération CV + Lettre ---------------------------------------------
    print(f"\n[...] Génération CV (template={args.template}) via LLM...")
    start = time.time()

    prefs = CVPreferences(
        template=args.template,
        language="Français",
        accent_hex="#006699",
        leftbg_hex="#172E4A",
        aggressive=True,
        company="Thales Group",
    )

    try:
        result = run_optimum_pipeline(JOB_OFFER_TEST, cv_source_text, prefs)
    except Exception as e:
        print(f"[ERREUR] Pipeline échoué : {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    elapsed = time.time() - start
    print(f"[OK]  Pipeline terminé en {elapsed:.1f}s")

    # -- 4. Rapport des résultats ----------------------------------------------
    print("\n-- Résultats ----------------------------------------------")
    print(f"  Candidat    : {result.get('candidate_name', '?')}")
    print(f"  Poste       : {result.get('job_title', '?')}")
    print(f"  Entreprise  : {result.get('company', '?')}")
    print(f"  CV PDF      : {result.get('cv_filename', '?')}")
    print(f"  Lettre PDF  : {result.get('letter_filename', '?')}")

    cv_errors = result.get("cv_errors", [])
    lm_errors = result.get("letter_errors", [])

    if cv_errors:
        print(f"\n[WARN] Erreurs CV  : {cv_errors}")
    if lm_errors:
        print(f"[WARN] Erreurs LM  : {lm_errors}")

    if result.get("cv_pdf_bytes"):
        cv_pdf = OUTPUT_DIR / result["cv_filename"]
        print(f"\n[OK]  CV PDF généré  -> {cv_pdf} ({len(result['cv_pdf_bytes']):,} bytes)")
    else:
        print("[WARN] Pas de bytes CV PDF — vérifiez pdflatex.")

    if result.get("letter_pdf_bytes"):
        lm_pdf = OUTPUT_DIR / result["letter_filename"]
        print(f"[OK]  LM PDF généré  -> {lm_pdf} ({len(result['letter_pdf_bytes']):,} bytes)")
    else:
        print("[WARN] Pas de bytes Lettre PDF.")

    # -- 5. Aperçu de la lettre -----------------------------------------------
    letter_body = result.get("letter_body", "")
    if letter_body:
        print("\n-- Extrait lettre de motivation ---------------------------")
        print(letter_body[:600].strip() + ("..." if len(letter_body) > 600 else ""))

    # -- 6. Test LinkedIn (DRY RUN) --------------------------------------------
    if args.linkedin:
        print("\n" + "=" * 60)
        print("TEST LINKEDIN — DRY RUN")
        print("=" * 60)
        _test_linkedin_dry_run()

    print("\n[OK] Test E2E terminé.")


def _test_linkedin_dry_run():
    """Lance un DRY RUN LinkedIn : recherche les offres sans postuler."""
    from modules.browser_manager import BrowserSession, JsonlEventLogger
    from modules import config, file_manager
    from modules.linkedin_apply import search_jobs

    file_manager.ensure_directories()

    cookies_path = config.COOKIES_DIR / "linkedin.json"
    if not cookies_path.exists():
        print("[WARN] Pas de session LinkedIn sauvegardée.")
        print("       Lance l'app Streamlit, clique 'Se connecter' -> 'Confirmer', puis relance.")
        return

    event_log = []
    def logger(level, msg):
        print(f"  [{level.upper():<7}] {msg}")
        event_log.append((level, msg))

    print("[...] Ouverture LinkedIn (headed)...")
    try:
        with BrowserSession("linkedin", headless=False, event_logger=logger) as session:
            jobs = search_jobs(
                session,
                keywords="AI engineer agentic",
                location="Paris",
                max_results=3,
            )
            if jobs:
                print(f"\n[OK] {len(jobs)} offre(s) trouvée(s) :")
                for j in jobs:
                    print(f"     • {j.title} @ {j.company} — {j.url[:60]}...")
            else:
                print("[WARN] 0 offre Easy Apply trouvée (essaie avec d'autres mots-clés).")
            print("\n[OK] DRY RUN terminé — aucune candidature soumise.")
    except Exception as e:
        print(f"[ERREUR] LinkedIn test : {e}")
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    main()
