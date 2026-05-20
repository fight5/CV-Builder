"""Pipeline OPTIMUM : génération CV + Lettre via Gemini, sans JSON intermédiaire.

Flux :
1. Extraction du CV source (PDF/DOCX).
2. Appel Gemini -> LaTeX complet adapté au template `templates/optimum.tex`.
3. Compilation pdflatex -> CV.pdf.
4. Appel Gemini -> corps de lettre.
5. Insertion dans `templates/letter.tex` + compilation -> Lettre_Motivation.pdf.

Aucune sortie JSON : tout reste en texte / LaTeX / PDF binaire.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_CV = PROJECT_ROOT / "templates" / "optimum.tex"
TEMPLATE_LETTER = PROJECT_ROOT / "templates" / "letter.tex"
OUTPUT_DIR = PROJECT_ROOT / "outputs"

_MONTHS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


# ── Extraction texte ─────────────────────────────────────────────────────────
def extract_text_from_pdf(file_path: str) -> str:
    """Extrait le texte d'un PDF via PyMuPDF (fitz)."""
    import fitz
    doc = fitz.open(file_path)
    try:
        return "\n".join(page.get_text("text") for page in doc)
    finally:
        doc.close()


def extract_text_from_docx(file_path: str) -> str:
    """Extrait le texte d'un DOCX via python-docx."""
    from docx import Document
    doc = Document(file_path)
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text.strip())
    return "\n".join(parts)


def extract_cv_text(uploaded_file) -> str:
    """Streamlit UploadedFile -> texte brut. Supporte PDF et DOCX."""
    suffix = Path(uploaded_file.name).suffix.lower()
    data = uploaded_file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        if suffix == ".pdf":
            return extract_text_from_pdf(tmp_path)
        if suffix in (".docx", ".doc"):
            return extract_text_from_docx(tmp_path)
        return data.decode("utf-8", errors="ignore")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── LLM (DeepSeek prioritaire, Gemini en fallback) ───────────────────────────
def _provider() -> str:
    """Provider sélectionné via env. 'deepseek' par défaut si la clé est dispo."""
    explicit = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if explicit in {"deepseek", "gemini"}:
        return explicit
    if os.getenv("DEEPSEEK_API_KEY"):
        return "deepseek"
    return "gemini"


def _call_deepseek(prompt: str, temperature: float) -> str:
    """Appel DeepSeek via l'API OpenAI-compatible."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY manquante dans l'environnement.")
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError(
            "openai SDK requis pour DeepSeek. Installez : pip install openai"
        ) from e

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=8192,
    )
    text = (resp.choices[0].message.content or "").strip()
    if not text:
        raise RuntimeError("Réponse DeepSeek vide.")
    return text


def _call_gemini(prompt: str, temperature: float) -> str:
    """Appel Gemini (fallback)."""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY (ou GEMINI_API_KEY) manquante.")
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import HumanMessage
    except ImportError as e:
        raise RuntimeError(f"langchain-google-genai non installé : {e}") from e

    llm = ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        google_api_key=api_key,
        temperature=temperature,
        max_output_tokens=8192,
    )
    resp = llm.invoke([HumanMessage(content=prompt)])
    text = (resp.content or "").strip()
    if not text:
        raise RuntimeError("Réponse Gemini vide.")
    return text


def generate_with_gemini(prompt: str, temperature: float = 0.35) -> str:
    """Appel LLM. Nom historique conservé — route vers DeepSeek ou Gemini
    selon LLM_PROVIDER (cf. _provider())."""
    provider = _provider()
    if provider == "deepseek":
        try:
            return _call_deepseek(prompt, temperature)
        except Exception as e:
            logger.warning("DeepSeek KO (%s) — fallback Gemini.", e)
            return _call_gemini(prompt, temperature)
    return _call_gemini(prompt, temperature)


# Alias plus explicite pour le code appelant.
generate_with_llm = generate_with_gemini


# ── Prompts ──────────────────────────────────────────────────────────────────
_PROMPT_CV = """\
Tu es un expert en recrutement, ATS (Applicant Tracking Systems), et rédaction de CV haut de gamme.

Ta mission est de réécrire entièrement le CV du candidat afin qu'il corresponde parfaitement à l'offre d'emploi.

OBJECTIFS :
1. Maximiser la compatibilité ATS.
2. Intégrer au moins 80 % des mots-clés de l'offre.
3. Faire apparaître le candidat comme le profil idéal.
4. Reformuler les expériences pour mettre en avant les éléments les plus pertinents.
5. Conserver uniquement des informations véridiques issues du CV source.
6. Utiliser un style professionnel, clair et percutant.
7. Optimiser les intitulés de poste, les compétences et les réalisations.
8. Produire un CV de niveau top 1 %.

CONTRAINTES :
- Ne jamais inventer d'expérience.
- Ne jamais ajouter de diplôme non présent.
- Ne jamais modifier les dates.
- Utiliser un format ATS-friendly.
- Utiliser des verbes d'action.
- Quantifier les résultats quand possible.

OFFRE D'EMPLOI :
{job_offer}

CV SOURCE :
{source_cv}

FORMAT DE SORTIE — TRÈS IMPORTANT :
Tu dois produire le code LaTeX complet d'un CV en respectant EXACTEMENT le squelette ci-dessous.
- Ne modifie ni le préambule, ni les couleurs, ni la mise en page, ni les sections.
- Remplace chaque placeholder `{{...}}` par le contenu adapté (rien d'autre).
- Les `{{..._ITEMS}}` doivent être une suite de lignes `\\item \\textcolor{{white}}{{...}}`.
- `{{EXPERIENCES_BLOCK}}` : pour chaque expérience véridique, produire ce motif (sans logo `\\includegraphics`) :

\\textbf{{Intitulé — Entreprise}}

\\emph{{Dates}}

\\begin{{itemize}}[label=\\textcolor{{accent}}{{$\\blacktriangleright$}}]
\\item Réalisation quantifiée 1.
\\item Réalisation quantifiée 2.
\\end{{itemize}}

\\vspace{{0.1cm}}

- `{{EDUCATION_BLOCK}}` : motif similaire sans itemize, ex.

\\textbf{{Diplôme — École}} \\hfill \\emph{{Dates}}

\\vspace{{0.2cm}}

- N'écris AUCUN commentaire, AUCUN texte hors LaTeX, AUCUN bloc Markdown ```latex.
- Le `{{HEADER_TITLE}}` doit être l'intitulé EXACT du poste de l'offre.
- Le `{{SUMMARY}}` est un paragraphe court (3–5 lignes) ancré sur le CV source et orienté vers l'offre.
- Couvre au moins 80 % des mots-clés techniques de l'offre dans COMPÉTENCES + OUTILS + EXPÉRIENCES.
- Échappe les caractères spéciaux LaTeX (`&`, `%`, `_`, `#`) avec un backslash.

SQUELETTE LATEX À REMPLIR (renvoie l'intégralité, placeholders remplis) :
---
{template}
---

Retourne uniquement le code LaTeX final, prêt à compiler avec pdflatex.
"""

_PROMPT_LETTER = """\
Tu es un expert en rédaction de lettres de motivation haut de gamme.

Rédige une lettre de motivation personnalisée et convaincante en te basant sur :
- l'offre d'emploi,
- le CV optimisé du candidat.

OBJECTIFS :
1. Montrer clairement l'adéquation entre le candidat et le poste.
2. Mettre en avant les expériences les plus pertinentes.
3. Adopter un ton professionnel et naturel.
4. Faire ressortir la valeur ajoutée du candidat.
5. Donner envie au recruteur de le rencontrer.

CONTRAINTES :
- Une page maximum.
- Français professionnel.
- Pas de phrases génériques.
- Pas de commentaire.
- Ne reprends pas le CV : valorise ce qui n'est pas explicite dans le CV (motivation, vision, projection).
- 3 paragraphes séparés par une ligne vide (vous / nous / nous deux).

OFFRE :
{job_offer}

CV OPTIMISÉ :
{optimized_cv}

Retourne uniquement le corps de la lettre, sans salutation d'ouverture ni formule de politesse de fermeture (elles sont ajoutées automatiquement par le gabarit), sans en-tête, sans date, sans signature.
"""


# ── Génération CV ────────────────────────────────────────────────────────────
def _strip_code_fences(text: str) -> str:
    """Enlève les ```latex / ``` autour d'une réponse LLM si présents."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def generate_optimized_cv(job_offer: str, source_cv: str) -> str:
    """Retourne le code LaTeX complet du CV optimisé, prêt à compiler."""
    template = TEMPLATE_CV.read_text(encoding="utf-8")
    prompt = _PROMPT_CV.format(
        job_offer=(job_offer or "").strip()[:8000],
        source_cv=(source_cv or "").strip()[:8000],
        template=template,
    )
    raw = generate_with_gemini(prompt, temperature=0.3)
    latex = _strip_code_fences(raw)
    if r"\documentclass" not in latex:
        # Le LLM a peut-être renvoyé uniquement du contenu : on rejette.
        raise RuntimeError(
            "Gemini n'a pas renvoyé un document LaTeX complet (\\documentclass manquant)."
        )
    return latex


# ── Génération lettre ────────────────────────────────────────────────────────
def generate_cover_letter(job_offer: str, optimized_cv: str) -> str:
    """Retourne le corps de la lettre de motivation (texte brut, paragraphes)."""
    prompt = _PROMPT_LETTER.format(
        job_offer=(job_offer or "").strip()[:8000],
        optimized_cv=(optimized_cv or "").strip()[:8000],
    )
    return _strip_code_fences(generate_with_gemini(prompt, temperature=0.55))


# ── LaTeX helpers ────────────────────────────────────────────────────────────
def _latex_escape(s: str) -> str:
    if not isinstance(s, str):
        s = str(s)
    repl = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for k, v in repl:
        s = s.replace(k, v)
    return s


def _french_date() -> str:
    d = datetime.now()
    return f"{d.day} {_MONTHS_FR[d.month - 1]} {d.year}"


def _paragraphs_to_latex(body: str) -> str:
    body = (body or "").strip()
    if not body:
        return ""
    paragraphs = re.split(r"\n\s*\n", body)
    cleaned = []
    for p in paragraphs:
        line = " ".join(seg.strip() for seg in p.splitlines() if seg.strip())
        cleaned.append(_latex_escape(line))
    return r" \\[0.4em] ".join(cleaned)


def _guess_name_from_cv_latex(cv_latex: str) -> str:
    """Tente de récupérer le nom (FULL_NAME) déjà inséré dans le CV LaTeX."""
    m = re.search(r"\\textbf\{\s*([^{}]+?)\s*\}\s*\}\\\\", cv_latex)
    return m.group(1).strip() if m else ""


def _guess_title_from_cv_latex(cv_latex: str) -> str:
    matches = re.findall(r"\\textbf\{\s*([^{}]+?)\s*\}\s*\}\\\\", cv_latex)
    return matches[1].strip() if len(matches) > 1 else ""


def _build_letter_latex(
    body: str,
    *,
    sender_name: str,
    job_title: str,
    company: str,
    sender_email: str = "",
    sender_phone: str = "",
    sender_city: str = "",
) -> str:
    template = TEMPLATE_LETTER.read_text(encoding="utf-8")
    subject = f"Candidature au poste de {_latex_escape(job_title or '[poste]')}"
    if company:
        subject += " chez " + _latex_escape(company)
    repl = {
        "{{SENDER_NAME}}": _latex_escape(sender_name or "[Votre nom]"),
        "{{SENDER_ADDRESS_BLOCK}}": "",
        "{{SENDER_EMAIL}}": _latex_escape(sender_email),
        "{{SENDER_PHONE}}": _latex_escape(sender_phone),
        "{{SENDER_CITY}}": _latex_escape(sender_city or "Paris"),
        "{{RECIPIENT_COMPANY}}": _latex_escape(company or ""),
        "{{RECIPIENT_ADDRESS_BLOCK}}": "",
        "{{DATE}}": _french_date(),
        "{{SUBJECT}}": subject,
        "{{SALUTATION}}": "Madame, Monsieur",
        "{{LETTER_BODY}}": _paragraphs_to_latex(body),
        "{{CLOSING}}": "Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations distinguées.",
    }
    for k, v in repl.items():
        template = template.replace(k, v)
    return template


# ── Compilation PDF ──────────────────────────────────────────────────────────
def _compile_latex(latex_src: str, base_name: str) -> tuple[Optional[bytes], list[str]]:
    """Compile une source LaTeX et retourne (pdf_bytes|None, errors)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_\-]+", "_", base_name) or "document"
    tex_path = OUTPUT_DIR / f"{safe}.tex"
    pdf_path = OUTPUT_DIR / f"{safe}.pdf"
    tex_path.write_text(latex_src, encoding="utf-8")

    errors: list[str] = []
    if shutil.which("pdflatex") is None:
        return None, ["pdflatex introuvable dans le PATH — installez TeX Live ou MiKTeX."]

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
        except subprocess.TimeoutExpired:
            return None, ["pdflatex timeout (300s)"]
        except Exception as e:
            return None, [f"pdflatex erreur : {e}"]
        if res.returncode != 0 and run == 2 and not pdf_path.exists():
            tail = "\n".join((res.stdout or "").splitlines()[-30:])
            errors.append(f"pdflatex exit={res.returncode}.\n{tail}")
            return None, errors

    if not pdf_path.exists():
        return None, errors or ["PDF non produit (raison inconnue)."]
    return pdf_path.read_bytes(), errors


def create_pdf(latex_or_text: str, output_filename: str) -> bytes:
    """Compile du LaTeX en PDF. Lève RuntimeError si la compilation échoue."""
    base = Path(output_filename).stem or "document"
    pdf_bytes, errors = _compile_latex(latex_or_text, base)
    if pdf_bytes is None:
        raise RuntimeError(
            "Échec de compilation pdflatex pour "
            f"{output_filename} : {'; '.join(errors) or 'erreur inconnue'}"
        )
    return pdf_bytes


# ── Pipeline complet ─────────────────────────────────────────────────────────
def run_optimum_pipeline(job_offer: str, source_cv_text: str) -> dict:
    """Orchestration complète. Retourne :
        {
          "cv_latex":      str,
          "cv_pdf_bytes":  bytes | None,
          "cv_errors":     list[str],
          "letter_body":   str,
          "letter_latex":  str,
          "letter_pdf_bytes": bytes | None,
          "letter_errors": list[str],
          "candidate_name": str,
          "job_title":      str,
        }
    """
    out: dict = {
        "cv_latex": "", "cv_pdf_bytes": None, "cv_errors": [],
        "letter_body": "", "letter_latex": "", "letter_pdf_bytes": None, "letter_errors": [],
        "candidate_name": "", "job_title": "",
    }

    # 1. CV
    cv_latex = generate_optimized_cv(job_offer, source_cv_text)
    out["cv_latex"] = cv_latex
    out["candidate_name"] = _guess_name_from_cv_latex(cv_latex)
    out["job_title"] = _guess_title_from_cv_latex(cv_latex)
    cv_bytes, cv_errors = _compile_latex(cv_latex, "CV")
    out["cv_pdf_bytes"] = cv_bytes
    out["cv_errors"] = cv_errors

    # 2. Lettre
    body = generate_cover_letter(job_offer, cv_latex)
    out["letter_body"] = body

    # Company : tentative basique d'extraction depuis l'offre.
    company_match = re.search(
        r"(?:chez|at|pour|recrute pour)\s+([A-ZÉÀÂÊÎÔÛÇ][\wÀ-ÿ&\.\- ]{1,40})",
        job_offer or "",
    )
    company = company_match.group(1).strip() if company_match else ""

    letter_latex = _build_letter_latex(
        body,
        sender_name=out["candidate_name"],
        job_title=out["job_title"],
        company=company,
    )
    out["letter_latex"] = letter_latex
    lm_bytes, lm_errors = _compile_latex(letter_latex, "Lettre_Motivation")
    out["letter_pdf_bytes"] = lm_bytes
    out["letter_errors"] = lm_errors

    return out
