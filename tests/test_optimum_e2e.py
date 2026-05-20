"""Test end-to-end OPTIMUM avec un vrai LLM.

Lance :
    python tests/test_optimum_e2e.py

Génère CV/Lettre nommés depuis (candidat, poste, entreprise).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from modules.optimum_pipeline import (
    CVPreferences,
    extract_text_from_pdf,
    run_optimum_pipeline,
)

OFFER_PATH = Path(r"C:\Users\admin\Downloads\CV_Builder\Offre DS.txt")
CV_PATH = Path(r"C:\Users\admin\Downloads\CV_Builder\CV_DataScientistJunior_SEGOUN.pdf")
OUT_DIR = PROJECT_ROOT / "outputs"


def main() -> int:
    offer = OFFER_PATH.read_text(encoding="utf-8")
    cv_text = extract_text_from_pdf(str(CV_PATH))
    print(f"[test] Offre : {len(offer)} chars  CV : {len(cv_text)} chars")

    prefs = CVPreferences(
        template="optimum",
        language="Français",
        accent_hex="#006699",
        leftbg_hex="#172E4A",
        include_photo=False,
        aggressive=True,
        company="VINCI Airports",
    )

    res = run_optimum_pipeline(offer, cv_text, prefs)
    print(f"[test] candidate={res['candidate_name']!r}  "
          f"title={res['job_title']!r}  company={res['company']!r}")
    print(f"[test] cv_latex={len(res['cv_latex'])}  "
          f"letter_body={len(res['letter_body'])}")
    print(f"[test] cv_pdf_bytes={'OK' if res['cv_pdf_bytes'] else 'NONE'}  "
          f"letter_pdf_bytes={'OK' if res['letter_pdf_bytes'] else 'NONE'}")
    print(f"[test] cv_errors={res['cv_errors']}")
    print(f"[test] letter_errors={res['letter_errors']}")
    print(f"[test] cv_filename={res['cv_filename']!r}")
    print(f"[test] letter_filename={res['letter_filename']!r}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "test_cv_source.tex").write_text(res["cv_latex"], encoding="utf-8")
    (OUT_DIR / "test_letter_body.txt").write_text(res["letter_body"], encoding="utf-8")
    (OUT_DIR / "test_letter_source.tex").write_text(res["letter_latex"], encoding="utf-8")
    if res["cv_pdf_bytes"]:
        (OUT_DIR / res["cv_filename"]).write_bytes(res["cv_pdf_bytes"])
    if res["letter_pdf_bytes"]:
        (OUT_DIR / res["letter_filename"]).write_bytes(res["letter_pdf_bytes"])

    return 0 if (res["cv_pdf_bytes"] and res["letter_pdf_bytes"]) else 1


if __name__ == "__main__":
    sys.exit(main())
