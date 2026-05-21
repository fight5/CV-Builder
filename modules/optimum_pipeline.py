"""Pipeline OPTIMUM — CV + Lettre via DeepSeek/Gemini, sans JSON.

Préférences utilisateur :
- template       : "optimum" | "minimal"
- language       : "Français" | "English"
- accent_hex     : couleur d'accent (hex)
- leftbg_hex     : couleur de fond du bandeau gauche (optimum uniquement)
- include_photo  : bool
- photo_path     : str | None  (chemin local accessible à pdflatex)
- aggressive     : bool  (laisser le LLM lister des compétences/outils
                         non explicites dans le CV source — assumé par
                         le candidat)
- company        : str   (facultatif — utilisé pour nommer les fichiers)

Sortie : dict avec cv_latex, cv_pdf_bytes, letter_body, letter_latex,
letter_pdf_bytes, errors, et les noms de fichiers suggérés.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
TEMPLATE_LETTER = TEMPLATES_DIR / "letter.tex"
OUTPUT_DIR = PROJECT_ROOT / "outputs"

_MONTHS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
_MONTHS_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# ── Préférences ──────────────────────────────────────────────────────────────
@dataclass
class CVPreferences:
    template: str = "optimum"          # optimum | minimal
    language: str = "Français"         # Français | English
    accent_hex: str = "#006699"        # bleu pétrole par défaut
    leftbg_hex: str = "#172E4A"        # bleu marine bandeau gauche
    include_photo: bool = False
    photo_path: Optional[str] = None
    aggressive: bool = True            # le candidat assume les ajouts
    company: str = ""                  # entreprise (pour nommage + lettre)


# ── Extraction texte ─────────────────────────────────────────────────────────
def extract_text_from_pdf(file_path: str) -> str:
    import fitz
    doc = fitz.open(file_path)
    try:
        return "\n".join(page.get_text("text") for page in doc)
    finally:
        doc.close()


def extract_text_from_docx(file_path: str) -> str:
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
    """Streamlit UploadedFile -> texte brut. PDF/DOCX."""
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
    explicit = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if explicit in {"deepseek", "gemini"}:
        return explicit
    if os.getenv("DEEPSEEK_API_KEY"):
        return "deepseek"
    return "gemini"


def _call_deepseek(prompt: str, temperature: float) -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY manquante.")
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("Installer : pip install openai") from e
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
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY manquante.")
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage
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


def generate_with_llm(prompt: str, temperature: float = 0.35) -> str:
    provider = _provider()
    if provider == "deepseek":
        try:
            return _call_deepseek(prompt, temperature)
        except Exception as e:
            logger.warning("DeepSeek KO (%s) — fallback Gemini.", e)
            return _call_gemini(prompt, temperature)
    return _call_gemini(prompt, temperature)


# Alias historique.
generate_with_gemini = generate_with_llm


# ── Prompts ──────────────────────────────────────────────────────────────────
_PROMPT_CV_AGGRESSIVE = """\
Tu es un expert en recrutement, ATS (Applicant Tracking Systems), et rédaction de CV haut de gamme.

Ta mission : réécrire entièrement le CV du candidat pour qu'il corresponde parfaitement à l'offre d'emploi.

OBJECTIFS — mode "MAX ATS" :
1. Maximiser la compatibilité ATS, viser 95 % de couverture des mots-clés de l'offre.
2. Faire apparaître le candidat comme le profil idéal, "top 1 %".
3. Reformuler chaque expérience pour mettre en avant les éléments pertinents pour l'offre.
4. Quantifier autant que possible (chiffres, %, échelle).
5. Utiliser des verbes d'action puissants.
6. Style ATS-friendly (pas de tableaux complexes, pas de glyphes exotiques).

RÈGLES DURES — à respecter ABSOLUMENT :
- Ne JAMAIS inventer une expérience professionnelle (entreprise, intitulé, dates).
- Ne JAMAIS modifier les dates ni ajouter/retirer un diplôme.
- Ne JAMAIS inventer une certification (laisser vide si absente du CV source).
- Conserver les noms d'entreprises et d'écoles tels quels.

LIBERTÉ ASSUMÉE PAR LE CANDIDAT — autorisé :
- Lister dans COMPÉTENCES / OUTILS toute techno/concept mentionné dans l'offre,
  même s'il n'apparaît pas explicitement dans le CV source. Le candidat assume.
- Enrichir les bullet points des expériences avec les outils/concepts de l'offre,
  en gardant la mission générale plausible vis-à-vis du poste réel.
- Réécrire le titre du header pour matcher exactement celui de l'offre.

RÈGLE SECTIONS VIDES — TRÈS IMPORTANT :
Si le CV source ne fournit AUCUNE donnée pour une section (ex. aucune certification),
tu dois OMETTRE COMPLÈTEMENT la section : ne génère ni le titre, ni le bloc itemize.
Concrètement, ne remplis pas le placeholder correspondant — laisse-le ABSENT du
document final si tu n'as rien à mettre dedans. N'invente JAMAIS pour combler.

FORMAT DE SORTIE :
Tu produis le code LaTeX complet d'un CV en respectant EXACTEMENT le squelette ci-dessous.
- Ne modifie ni le préambule, ni les couleurs, ni la mise en page.
- Remplace chaque placeholder `{{...}}` par le contenu adapté.
- Pour les "...SECTION" du template optimum (ex. `{{CERTIFICATIONS_SECTION}}`),
  écris le titre + l'itemize complet, OU rien du tout si vide. Format attendu :

{{color{{white}}\\sffamily\\bfseries TITRE_SECTION}}

\\vspace{{0.2cm}}

\\begin{{itemize}}[label=\\textcolor{{white}}{{$\\blacktriangleright$}}]
\\item \\textcolor{{white}}{{contenu 1}}
\\item \\textcolor{{white}}{{contenu 2}}
\\end{{itemize}}

\\vspace{{0.45cm}}

- Pour les "...SECTION_FLAT" du template minimal (texte noir, pas blanc) :

\\section*{{TITRE_SECTION}}
\\begin{{itemize}}
\\item contenu 1
\\item contenu 2
\\end{{itemize}}

- `{{EXPERIENCES_BLOCK}}` : pour chaque expérience véridique, motif :

\\textbf{{Intitulé — Entreprise}}

\\emph{{Dates}}

\\begin{{itemize}}[label=\\textcolor{{accent}}{{$\\blacktriangleright$}}]
\\item Réalisation quantifiée 1.
\\item Réalisation quantifiée 2.
\\end{{itemize}}

\\vspace{{0.1cm}}

- `{{EDUCATION_BLOCK}}` : motif :

\\textbf{{Diplôme — École}} \\hfill \\emph{{Dates}}

\\vspace{{0.2cm}}

- `{{EXPERIENCE_HEADING}}` et `{{EDUCATION_HEADING}}` : titres traduits selon langue
  ({language_heading_experience} / {language_heading_education}).
- `{{HEADER_TITLE}}` = intitulé EXACT de l'offre.
- `{{SUMMARY}}` = paragraphe 3–5 lignes ancré sur le CV source et orienté offre.
- Échappe `&`, `%`, `_`, `#` avec `\\`.
- N'écris AUCUN commentaire, AUCUN texte hors LaTeX, AUCUN ```latex.
- LANGUE de TOUT le contenu : {language_label}.

OFFRE D'EMPLOI :
{job_offer}

CV SOURCE :
{source_cv}

SQUELETTE LATEX (renvoie l'intégralité, placeholders remplis ou OMIS si vides) :
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
- {language_label} professionnel.
- Pas de phrases génériques.
- Pas de commentaire.
- Ne reprends pas le CV : valorise ce qui n'est pas explicite (motivation, vision, projection).
- 3 paragraphes séparés par une ligne vide.

OFFRE :
{job_offer}

CV OPTIMISÉ :
{optimized_cv}

Retourne uniquement le corps de la lettre, sans salutation d'ouverture, sans formule de fermeture, sans en-tête, sans date, sans signature.
"""


# ── Helpers LaTeX ────────────────────────────────────────────────────────────
def _hex_to_rgb(hex_color: str) -> str:
    """`#006699` -> `0,102,153`. Tolère sans #."""
    h = (hex_color or "").lstrip("#").strip()
    if len(h) != 6:
        return "0,102,153"
    try:
        return f"{int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)}"
    except ValueError:
        return "0,102,153"


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


def _english_date() -> str:
    d = datetime.now()
    return f"{_MONTHS_EN[d.month - 1]} {d.day}, {d.year}"


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


# ── Build photo block ────────────────────────────────────────────────────────
def _photo_block(prefs: CVPreferences) -> str:
    """Bloc minipage avec photo, ou minipage vide. Garde l'alignement du header."""
    if prefs.include_photo and prefs.photo_path:
        # Copier la photo dans outputs/ pour qu'elle soit à côté du .tex
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            dest = OUTPUT_DIR / "photo_didentite.png"
            shutil.copyfile(prefs.photo_path, dest)
            return (
                "\\begin{minipage}[t]{0.23\\textwidth}\n"
                "\\vspace{0pt}\n"
                "\\includegraphics[width=\\linewidth]{photo_didentite.png}\n"
                "\\end{minipage}\n\\hfill"
            )
        except OSError as e:
            logger.warning("Photo non copiable : %s", e)
    return (
        "\\begin{minipage}[t]{0.0\\textwidth}\\vspace{0pt}\\end{minipage}\\hfill"
    )


def _photo_block_minimal(prefs: CVPreferences) -> str:
    """Photo centrée pour le template minimal."""
    if prefs.include_photo and prefs.photo_path:
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            dest = OUTPUT_DIR / "photo_didentite.png"
            shutil.copyfile(prefs.photo_path, dest)
            return (
                "\\begin{center}\n"
                "\\includegraphics[width=3.2cm,height=3.2cm,keepaspectratio]{photo_didentite.png}\n"
                "\\end{center}"
            )
        except OSError:
            pass
    return ""


# ── Template loader ──────────────────────────────────────────────────────────
def _load_template(name: str) -> str:
    name = (name or "optimum").lower()
    if name not in {"optimum", "minimal"}:
        name = "optimum"
    path = TEMPLATES_DIR / f"{name}.tex"
    return path.read_text(encoding="utf-8")


def _inject_style(template: str, prefs: CVPreferences) -> str:
    """Remplace les placeholders globaux (couleurs, langue, photo)."""
    babel = "english" if prefs.language.lower().startswith("en") else "french"
    accent_rgb = _hex_to_rgb(prefs.accent_hex)
    leftbg_rgb = _hex_to_rgb(prefs.leftbg_hex)
    photo_optimum = _photo_block(prefs)
    photo_minimal = _photo_block_minimal(prefs)
    # Headings — l'offre peut être en anglais aussi.
    if babel == "english":
        exp_heading = "Professional Experience"
        edu_heading = "Education"
    else:
        exp_heading = "Expériences professionnelles"
        edu_heading = "Formation"
    repl = {
        "{{BABEL_LANG}}": babel,
        "{{ACCENT_RGB}}": accent_rgb,
        "{{LEFTBG_RGB}}": leftbg_rgb,
        "{{PHOTO_BLOCK}}": (
            photo_minimal if "FLAT" in template else photo_optimum
        ),
        "{{EXPERIENCE_HEADING}}": exp_heading,
        "{{EDUCATION_HEADING}}": edu_heading,
    }
    out = template
    for k, v in repl.items():
        out = out.replace(k, v)
    return out


# ── Génération CV ────────────────────────────────────────────────────────────
def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _strip_empty_sections(latex: str) -> str:
    """Filet de sécurité — supprime les sections dont l'itemize est vide.

    Reconnait deux patterns :
    1. Bandeau gauche optimum : `{\\color{white}\\sffamily\\bfseries TITRE} ...
       \\begin{itemize}...\\end{itemize}` où l'itemize ne contient pas `\\item`.
    2. `\\section*{...}` suivi d'un itemize sans `\\item`.
    """
    # Pattern 1 — colonne gauche optimum.
    pat1 = re.compile(
        r"\{\\color\{white\}\\sffamily\\bfseries[^}]+\}.*?"
        r"\\begin\{itemize\}\[[^\]]*\](?P<items>.*?)\\end\{itemize\}"
        r"(?:\s*\\vspace\{[^}]+\})?",
        re.DOTALL,
    )
    def _maybe1(m: re.Match) -> str:
        items = m.group("items")
        if "\\item" in items:
            return m.group(0)
        return ""
    latex = pat1.sub(_maybe1, latex)
    # Pattern 2 — section minimal.
    pat2 = re.compile(
        r"\\section\*\{[^}]+\}\s*\\begin\{itemize\}(?P<items>.*?)\\end\{itemize\}",
        re.DOTALL,
    )
    latex = pat2.sub(
        lambda m: "" if "\\item" not in m.group("items") else m.group(0),
        latex,
    )
    # Pattern 3 — nettoyer les triples sauts.
    latex = re.sub(r"\n{3,}", "\n\n", latex)
    return latex


def generate_optimized_cv(
    job_offer: str,
    source_cv: str,
    prefs: Optional[CVPreferences] = None,
) -> str:
    prefs = prefs or CVPreferences()
    raw_template = _load_template(prefs.template)
    template = _inject_style(raw_template, prefs)
    language_label = "Anglais" if prefs.language.lower().startswith("en") else "Français"
    if prefs.language.lower().startswith("en"):
        exp_h, edu_h = "Professional Experience", "Education"
    else:
        exp_h, edu_h = "Expériences professionnelles", "Formation"
    prompt = _PROMPT_CV_AGGRESSIVE.format(
        language_label=language_label,
        language_heading_experience=exp_h,
        language_heading_education=edu_h,
        job_offer=(job_offer or "").strip()[:8000],
        source_cv=(source_cv or "").strip()[:8000],
        template=template,
    )
    raw = generate_with_llm(prompt, temperature=0.35)
    latex = _strip_code_fences(raw)
    if r"\documentclass" not in latex:
        raise RuntimeError("Le LLM n'a pas renvoyé un document LaTeX complet.")
    latex = _strip_empty_sections(latex)
    return latex


# ── Génération lettre ────────────────────────────────────────────────────────
def generate_cover_letter(
    job_offer: str,
    optimized_cv: str,
    prefs: Optional[CVPreferences] = None,
) -> str:
    prefs = prefs or CVPreferences()
    language_label = "Anglais" if prefs.language.lower().startswith("en") else "Français"
    prompt = _PROMPT_LETTER.format(
        language_label=language_label,
        job_offer=(job_offer or "").strip()[:8000],
        optimized_cv=(optimized_cv or "").strip()[:8000],
    )
    return _strip_code_fences(generate_with_llm(prompt, temperature=0.55))


# ── Extraction nom / titre / entreprise ──────────────────────────────────────
def _guess_name_from_cv_latex(cv_latex: str) -> str:
    m = re.search(r"\\textbf\{\s*([^{}\\]+?)\s*\}\s*\}", cv_latex)
    return m.group(1).strip() if m else ""


def _guess_title_from_cv_latex(cv_latex: str) -> str:
    matches = re.findall(r"\\textbf\{\s*([^{}\\]+?)\s*\}\s*\}", cv_latex)
    return matches[1].strip() if len(matches) > 1 else ""


def _guess_company(job_offer: str) -> str:
    """Heuristique : on cherche le 1er nom propre majuscule plausible."""
    txt = job_offer or ""
    # Pattern 1 — "chez X" / "at X" / "rejoindre X"
    m = re.search(
        r"(?:chez|at|pour|rejoindre|au sein de)\s+"
        r"([A-Z][\wÀ-ÿ&\.\- ]{2,40})",
        txt,
    )
    if m:
        return m.group(1).strip().rstrip(",.")
    # Pattern 2 — ligne de l'offre qui commence par un mot capitalisé long
    for line in txt.splitlines():
        line = line.strip()
        if 3 < len(line) < 50 and line[0].isupper() and " " in line:
            if any(w in line.lower() for w in ("ltd", "sa", "sas", "sarl", "concession", "airports", "group", "vinci")):
                return line
    return ""


# ── Lettre LaTeX ─────────────────────────────────────────────────────────────
def _build_letter_latex(
    body: str,
    prefs: CVPreferences,
    *,
    sender_name: str,
    job_title: str,
    company: str,
) -> str:
    template = TEMPLATE_LETTER.read_text(encoding="utf-8")
    is_en = prefs.language.lower().startswith("en")
    salutation = "Dear Hiring Manager" if is_en else "Madame, Monsieur"
    closing = (
        "Yours sincerely,"
        if is_en
        else "Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations distinguées."
    )
    subject_label = "Application for" if is_en else "Candidature au poste de"
    subject = f"{subject_label} {_latex_escape(job_title or '[poste]')}"
    if company:
        subject += " " + ("at " if is_en else "chez ") + _latex_escape(company)
    repl = {
        "{{SENDER_NAME}}": _latex_escape(sender_name or "[Votre nom]"),
        "{{SENDER_ADDRESS_BLOCK}}": "",
        "{{SENDER_EMAIL}}": "",
        "{{SENDER_PHONE}}": "",
        "{{SENDER_CITY}}": _latex_escape("Paris"),
        "{{RECIPIENT_COMPANY}}": _latex_escape(company or ""),
        "{{RECIPIENT_ADDRESS_BLOCK}}": "",
        "{{DATE}}": _english_date() if is_en else _french_date(),
        "{{SUBJECT}}": subject,
        "{{SALUTATION}}": salutation,
        "{{LETTER_BODY}}": _paragraphs_to_latex(body),
        "{{CLOSING}}": closing,
    }
    for k, v in repl.items():
        template = template.replace(k, v)
    return template


# ── Compilation PDF ──────────────────────────────────────────────────────────
def _compile_latex(latex_src: str, base_name: str) -> tuple[Optional[bytes], list[str]]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_\-]+", "_", base_name) or "document"
    tex_path = OUTPUT_DIR / f"{safe}.tex"
    pdf_path = OUTPUT_DIR / f"{safe}.pdf"
    tex_path.write_text(latex_src, encoding="utf-8")

    errors: list[str] = []
    if shutil.which("pdflatex") is None:
        return None, ["pdflatex introuvable, installez TeX Live ou MiKTeX."]

    cmd = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-output-directory", str(OUTPUT_DIR),
        str(tex_path),
    ]
    for run in (1, 2):
        try:
            res = subprocess.run(
                cmd, capture_output=True, timeout=300, cwd=str(OUTPUT_DIR)
            )
        except subprocess.TimeoutExpired:
            return None, ["pdflatex timeout (300s)"]
        except Exception as e:
            return None, [f"pdflatex erreur : {e}"]
        raw = res.stdout or b""
        if isinstance(raw, bytes):
            stdout = raw.decode("utf-8", errors="replace")
            if "�" in stdout:
                stdout = raw.decode("cp1252", errors="replace")
        else:
            stdout = raw
        if res.returncode != 0 and run == 2 and not pdf_path.exists():
            tail = "\n".join(stdout.splitlines()[-30:])
            errors.append(f"pdflatex exit={res.returncode}.\n{tail}")
            return None, errors

    if not pdf_path.exists():
        return None, errors or ["PDF non produit."]
    return pdf_path.read_bytes(), errors


def create_pdf(latex_or_text: str, output_filename: str) -> bytes:
    base = Path(output_filename).stem or "document"
    pdf_bytes, errors = _compile_latex(latex_or_text, base)
    if pdf_bytes is None:
        raise RuntimeError(
            f"Échec compilation {output_filename} : {'; '.join(errors) or 'inconnu'}"
        )
    return pdf_bytes


# ── Naming ───────────────────────────────────────────────────────────────────
def _slug(s: str, max_len: int = 40) -> str:
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


def build_output_basename(candidate: str, job_title: str, company: str) -> str:
    """`Nom_Poste_Entreprise` slug, fallback `CV`/`LM`."""
    parts = [_slug(candidate), _slug(job_title), _slug(company)]
    parts = [p for p in parts if p]
    return "_".join(parts) if parts else ""


# ── Pipeline complet ─────────────────────────────────────────────────────────
def run_optimum_pipeline(
    job_offer: str,
    source_cv_text: str,
    prefs: Optional[CVPreferences] = None,
) -> dict:
    prefs = prefs or CVPreferences()
    out: dict = {
        "cv_latex": "", "cv_pdf_bytes": None, "cv_errors": [],
        "letter_body": "", "letter_latex": "",
        "letter_pdf_bytes": None, "letter_errors": [],
        "candidate_name": "", "job_title": "", "company": prefs.company,
        "cv_filename": "CV.pdf", "letter_filename": "Lettre_Motivation.pdf",
    }

    # 1. CV
    cv_latex = generate_optimized_cv(job_offer, source_cv_text, prefs)
    out["cv_latex"] = cv_latex
    candidate = _guess_name_from_cv_latex(cv_latex)
    job_title = _guess_title_from_cv_latex(cv_latex)
    company = prefs.company.strip() or _guess_company(job_offer)
    out["candidate_name"] = candidate
    out["job_title"] = job_title
    out["company"] = company

    base = build_output_basename(candidate, job_title, company)
    cv_base = f"{base}_CV" if base else "CV"
    lm_base = f"{base}_LM" if base else "Lettre_Motivation"
    out["cv_filename"] = f"{cv_base}.pdf"
    out["letter_filename"] = f"{lm_base}.pdf"

    cv_bytes, cv_errors = _compile_latex(cv_latex, cv_base)
    out["cv_pdf_bytes"] = cv_bytes
    out["cv_errors"] = cv_errors

    # 2. Lettre
    body = generate_cover_letter(job_offer, cv_latex, prefs)
    out["letter_body"] = body
    letter_latex = _build_letter_latex(
        body, prefs,
        sender_name=candidate,
        job_title=job_title,
        company=company,
    )
    out["letter_latex"] = letter_latex
    lm_bytes, lm_errors = _compile_latex(letter_latex, lm_base)
    out["letter_pdf_bytes"] = lm_bytes
    out["letter_errors"] = lm_errors

    return out
