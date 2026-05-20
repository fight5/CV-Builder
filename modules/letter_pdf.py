"""Pipeline complet de génération d'une lettre de motivation LaTeX + PDF.

Indépendant du pipeline CV :
1. `letter_generator.generate_letter()`  -> corps de lettre (texte via Gemini ou template fallback)
2. Substitution dans `templates/letter.tex`
3. Compilation via pdflatex (warm-up MiKTeX inclus)

Retourne un dict {body, latex_source, pdf_path, filename, errors}.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.tools import latex_escape

from .letter_generator import LetterContext, generate_letter

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "templates" / "letter.tex"
OUTPUT_DIR = PROJECT_ROOT / "outputs"

# Mois en français pour formater la date.
_MONTHS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


@dataclass
class LetterPDFContext:
    """Toutes les infos nécessaires pour produire la lettre + PDF."""

    # Expéditeur (candidat)
    sender_name: str = ""
    sender_address: str = ""        # rue, code postal — peut contenir des sauts de ligne (\n)
    sender_city: str = ""
    sender_email: str = ""
    sender_phone: str = ""

    # Destinataire
    recipient_company: str = ""
    recipient_address: str = ""     # peut être vide

    # Contenu
    job_title: str = ""
    job_description: str = ""
    resume_text: str = ""

    # Options
    language: str = "Français"      # "Français" | "English"
    tone: str = "professional"
    custom_body: str = ""           # si fourni, écrase la génération LLM


def _format_french_date(d: Optional[datetime] = None) -> str:
    """Retourne 'jour mois année', ex: '20 mai 2026'."""
    d = d or datetime.now()
    return f"{d.day} {_MONTHS_FR[d.month - 1]} {d.year}"


def _format_address_block(address: str) -> str:
    """Transforme un champ multiligne en suite \\\\ LaTeX-safe."""
    if not address:
        return ""
    lines = [latex_escape(ln.strip()) for ln in address.splitlines() if ln.strip()]
    return r" \\ ".join(lines)


def _paragraphs_to_latex(body: str) -> str:
    """Convertit le texte du LLM (paragraphes séparés par \\n\\n) en LaTeX.

    On échappe chaque paragraphe puis on les sépare par \\par + saut visuel.
    """
    body = (body or "").strip()
    if not body:
        return ""
    # Normalise : enlève les newlines simples DANS un paragraphe (Gemini en met parfois).
    paragraphs = re.split(r"\n\s*\n", body)
    out = []
    for p in paragraphs:
        cleaned = " ".join(line.strip() for line in p.splitlines() if line.strip())
        out.append(latex_escape(cleaned))
    return r" \\[0.4em] ".join(out)


def build_letter_latex(ctx: LetterPDFContext, body: str) -> str:
    """Lit le template et substitue les placeholders. Retourne la source LaTeX prête."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    is_en = ctx.language.lower().startswith("en")
    salutation = "Dear Hiring Manager" if is_en else "Madame, Monsieur"
    closing = (
        "Yours sincerely,"
        if is_en
        else "Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations distinguées."
    )
    subject_label = "Application for" if is_en else "Candidature au poste de"
    subject = f"{subject_label} {latex_escape(ctx.job_title or '[poste]')}"
    if ctx.recipient_company:
        subject += " " + ("at " if is_en else "chez ") + latex_escape(ctx.recipient_company)

    repl = {
        "{{SENDER_NAME}}": latex_escape(ctx.sender_name or "[Votre nom]"),
        "{{SENDER_ADDRESS_BLOCK}}": _format_address_block(ctx.sender_address),
        "{{SENDER_EMAIL}}": latex_escape(ctx.sender_email),
        "{{SENDER_PHONE}}": latex_escape(ctx.sender_phone),
        "{{SENDER_CITY}}": latex_escape(ctx.sender_city or "Paris"),
        "{{RECIPIENT_COMPANY}}": latex_escape(ctx.recipient_company or ""),
        "{{RECIPIENT_ADDRESS_BLOCK}}": _format_address_block(ctx.recipient_address),
        "{{DATE}}": _format_french_date(),
        "{{SUBJECT}}": subject,
        "{{SALUTATION}}": salutation,
        "{{LETTER_BODY}}": _paragraphs_to_latex(body),
        "{{CLOSING}}": closing,
    }
    for k, v in repl.items():
        template = template.replace(k, v)
    return template


def compile_letter_pdf(latex_src: str, base_name: str) -> tuple[Optional[Path], list[str]]:
    """Écrit le .tex puis lance pdflatex (2 passes). Retourne (pdf_path|None, errors)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_base = base_name or "lettre"
    tex_path = OUTPUT_DIR / f"{safe_base}.tex"
    pdf_path = OUTPUT_DIR / f"{safe_base}.pdf"

    errors: list[str] = []
    try:
        tex_path.write_text(latex_src, encoding="utf-8")
    except OSError as e:
        return None, [f"Écriture .tex échouée : {e}"]

    if shutil.which("pdflatex") is None:
        errors.append("pdflatex introuvable dans le PATH système — PDF non généré.")
        return None, errors

    cmd = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-output-directory", str(OUTPUT_DIR),
        str(tex_path),
    ]
    for run in (1, 2):
        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300, cwd=str(OUTPUT_DIR)
            )
            if res.returncode != 0 and run == 2 and not pdf_path.exists():
                tail = "\n".join((res.stdout or "").splitlines()[-25:])
                errors.append(f"pdflatex exit={res.returncode}. Logs :\n{tail}")
                return None, errors
        except subprocess.TimeoutExpired:
            errors.append("pdflatex timeout (300s)")
            return None, errors
        except Exception as e:  # pragma: no cover
            errors.append(f"pdflatex erreur : {e}")
            return None, errors

    return (pdf_path if pdf_path.exists() else None), errors


def _slug_for_filename(s: str, max_len: int = 30) -> str:
    import unicodedata
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    out = []
    for ch in ascii_str:
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_'":
            out.append("_")
    s = "".join(out)
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_")[:max_len]


def build_filename(ctx: LetterPDFContext) -> str:
    """Nom_Poste_Entreprise_LM (sans extension)."""
    parts = [
        _slug_for_filename(ctx.sender_name),
        _slug_for_filename(ctx.job_title),
        _slug_for_filename(ctx.recipient_company),
    ]
    parts = [p for p in parts if p]
    return ("_".join(parts) + "_LM") if parts else "LM"


def generate_letter_pipeline(ctx: LetterPDFContext) -> dict:
    """Pipeline complet : corps via Gemini -> LaTeX -> PDF. Retourne un dict de resultats."""
    # 1. Corps de la lettre.
    if ctx.custom_body:
        body = ctx.custom_body.strip()
    else:
        body = generate_letter(LetterContext(
            job_title=ctx.job_title,
            company=ctx.recipient_company,
            job_description=ctx.job_description,
            resume_text=ctx.resume_text,
            language=ctx.language,
            tone=ctx.tone,
            candidate_name=ctx.sender_name,
        ))

    # 2. Source LaTeX.
    latex_src = build_letter_latex(ctx, body)

    # 3. Compilation PDF.
    base = build_filename(ctx)
    pdf_path, errors = compile_letter_pdf(latex_src, base)

    return {
        "body": body,
        "latex_source": latex_src,
        "pdf_path": str(pdf_path) if pdf_path else None,
        "filename": base,
        "errors": errors,
    }
