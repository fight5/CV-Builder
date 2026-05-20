"""Génération de lettres de motivation via Gemini.

- Réutilise la clé GOOGLE_API_KEY déjà en place pour le pipeline CV.
- Tombe en fallback déterministe (template) si Gemini indisponible —
  l'app reste utilisable même hors connexion.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from . import config, file_manager

logger = logging.getLogger(__name__)


@dataclass
class LetterContext:
    """Contexte minimal pour produire une lettre."""
    job_title: str
    company: str
    job_description: str
    resume_text: str
    language: str = "Français"      # "Français" | "English"
    tone: str = "professional"      # professional | enthusiastic | concise
    candidate_name: str = ""


SYSTEM_PROMPT_FR = """\
Tu es un coach RH expert dans la rédaction de lettres de motivation pour le marché français.
Tu écris des lettres :
- structurées en 3 paragraphes (intérêt pour l'entreprise, adéquation avec le poste, projet pro / disponibilité),
- au ton professionnel mais incarné,
- sans formules creuses (\"forte motivation\", \"dynamique\", etc.),
- de 250 à 350 mots maximum,
- prêtes à être collées dans un formulaire de candidature en ligne (pas d'en-tête postal, pas de date).
Ne mens jamais sur l'expérience du candidat — appuie-toi uniquement sur le CV fourni.
"""

SYSTEM_PROMPT_EN = """\
You are an HR coach specialised in writing cover letters for the European job market.
You write letters that are:
- structured in 3 paragraphs (interest in company, fit with role, motivation / availability),
- professionally toned but personal,
- free of empty phrases ("highly motivated", "team player", etc.),
- 250 to 350 words maximum,
- ready to paste into an online application form (no postal header, no date).
Never invent experience — base every claim on the provided resume.
"""

USER_PROMPT_TEMPLATE = """\
Offre :
Titre : {job_title}
Entreprise : {company}
Description :
{job_description}

CV du candidat :
{resume_text}

Consignes : produis uniquement le corps de la lettre (pas d'en-tête, pas de signature ni de date).
Ton : {tone}.
"""


def _build_llm():
    """Instancie un client Gemini ou retourne None si clé absente."""
    api_key = config.get_gemini_api_key()
    if not api_key:
        return None
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL,
            google_api_key=api_key,
            temperature=0.5,
            max_output_tokens=2048,
        )
    except Exception as e:  # pragma: no cover - import-time safety net
        logger.warning("Gemini init failed: %s", e)
        return None


def _fallback_letter(ctx: LetterContext) -> str:
    """Template basique si LLM indisponible — mieux que rien."""
    sig = ctx.candidate_name or "[Votre nom]"
    if ctx.language.lower().startswith("en"):
        return (
            f"Dear Hiring Manager at {ctx.company},\n\n"
            f"I am writing to express my interest in the {ctx.job_title} position. "
            f"My background aligns with the responsibilities described, and I would "
            f"welcome the opportunity to contribute to your team.\n\n"
            f"You will find attached my resume detailing my relevant experience. "
            f"I am available for an interview at your convenience.\n\n"
            f"Kind regards,\n{sig}"
        )
    return (
        f"Bonjour,\n\n"
        f"Le poste de {ctx.job_title} chez {ctx.company} retient toute mon attention. "
        f"Mon parcours correspond aux missions décrites et je serais ravi(e) "
        f"d'échanger sur ma contribution potentielle.\n\n"
        f"Mon CV joint détaille mes expériences pertinentes. Je reste disponible "
        f"pour un entretien à votre convenance.\n\n"
        f"Cordialement,\n{sig}"
    )


def generate_letter(ctx: LetterContext) -> str:
    """Génère le corps d'une lettre de motivation. Retourne toujours un texte non-vide."""
    llm = _build_llm()
    if llm is None:
        logger.info("Gemini indisponible — fallback template.")
        return _fallback_letter(ctx)

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        system = SYSTEM_PROMPT_EN if ctx.language.lower().startswith("en") else SYSTEM_PROMPT_FR
        user = USER_PROMPT_TEMPLATE.format(
            job_title=ctx.job_title.strip() or "[poste]",
            company=ctx.company.strip() or "[entreprise]",
            job_description=(ctx.job_description or "")[:6000],  # cap pour rester < tokens
            resume_text=(ctx.resume_text or "")[:6000],
            tone=ctx.tone,
        )
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        body = (resp.content or "").strip()
        return body or _fallback_letter(ctx)
    except Exception as e:
        logger.warning("Gemini call failed: %s — fallback.", e)
        return _fallback_letter(ctx)


def save_letter(text: str, *, company: str, job_title: str, ext: str = "txt") -> Path:
    """Sauvegarde la lettre dans `letters/` avec un nom slugifié horodaté."""
    file_manager.ensure_directories()
    stamp = file_manager.utc_now_iso().replace(":", "").replace("-", "")[:13]  # YYYYMMDDTHHMM
    name = f"{stamp}_{file_manager.slugify(company)}_{file_manager.slugify(job_title)}.{ext}"
    path = config.LETTERS_DIR / name
    path.write_text(text, encoding="utf-8")
    return path


# Helper utilitaire pour la lecture de CV depuis un fichier (réutilise core.tools)
def read_resume_text(cv_path: str | Path) -> str:
    """Lit un CV PDF/DOCX/TXT et retourne son texte brut."""
    p = Path(cv_path)
    if not p.exists():
        return ""
    suffix = p.suffix.lower()
    try:
        if suffix == ".pdf":
            from core.tools import extract_text_from_pdf
            return extract_text_from_pdf(str(p))
        if suffix in (".docx", ".doc"):
            from core.tools import extract_text_from_docx
            return extract_text_from_docx(str(p))
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.warning("Lecture CV échouée (%s) : %s", p, e)
        return ""


# Helper utilisé par les modules plateforme pour normaliser un titre de poste.
_WHITESPACE_RE = re.compile(r"\s+")


def clean_title(s: str) -> str:
    return _WHITESPACE_RE.sub(" ", s or "").strip()
