"""Agent that injects optimized resume content into a LaTeX template."""

import os
import re
import logging
from pathlib import Path
from typing import Optional

from .base_agent import BaseAgent
from core.tools import latex_escape, format_experience_latex

logger = logging.getLogger(__name__)

# Directory containing .tex template files
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _build_experience_section(experiences: list) -> str:
    """Render a list of experience dicts into LaTeX experience entries."""
    if not experiences:
        return ""
    parts = []
    for exp in experiences:
        parts.append(format_experience_latex(exp))
    return "\n\n".join(parts)


def _build_skills_section(skills: list) -> str:
    """Render a flat skills list into a LaTeX itemize block."""
    if not skills:
        return ""
    items = [r"  \item " + latex_escape(s) for s in skills if s]
    return "\\begin{itemize}[leftmargin=*, itemsep=1pt, topsep=2pt]\n" + "\n".join(items) + "\n\\end{itemize}"


def _build_skills_grouped(skills: list) -> str:
    """Render skills as a comma-separated paragraph (more ATS-friendly)."""
    if not skills:
        return ""
    escaped = [latex_escape(s) for s in skills if s]
    return ", ".join(escaped)


def _build_education_section(education: list) -> str:
    """Render education entries into LaTeX."""
    if not education:
        return ""
    parts = []
    for edu in education:
        degree = latex_escape(edu.get("degree", ""))
        institution = latex_escape(edu.get("institution", ""))
        dates = latex_escape(edu.get("dates", ""))
        location = latex_escape(edu.get("location", ""))
        gpa = latex_escape(str(edu.get("gpa", "")))
        honors = latex_escape(edu.get("honors", ""))

        entry = f"\\educationentry{{{degree}}}{{{institution}}}{{{dates}}}{{{location}}}"
        if gpa and gpa != "None" and gpa.strip():
            entry += f"\n  \\textit{{GPA: {gpa}}}"
        if honors and honors.strip():
            entry += f"\n  \\textit{{{honors}}}"
        parts.append(entry)
    return "\n\n".join(parts)


def _build_projects_section(projects: list) -> str:
    """Render projects into LaTeX entries."""
    if not projects:
        return ""
    parts = []
    for proj in projects:
        name = latex_escape(proj.get("name", ""))
        desc = latex_escape(proj.get("description", ""))
        techs = proj.get("technologies", [])
        tech_str = latex_escape(", ".join(techs)) if techs else ""
        url = proj.get("url", "")

        entry = f"\\projectentry{{{name}}}{{{desc}}}"
        if tech_str:
            entry += f"\n  \\textit{{Technologies: {tech_str}}}"
        if url:
            safe_url = url.replace("%", "\\%").replace("_", "\\_")
            entry += f"\n  \\href{{{safe_url}}}{{\\underline{{Link}}}}"
        parts.append(entry)
    return "\n\n".join(parts)


def _build_certifications_section(certifications: list) -> str:
    """Render certifications as a simple list."""
    if not certifications:
        return ""
    items = [r"  \item " + latex_escape(c) for c in certifications if c]
    return "\\begin{itemize}[leftmargin=*, itemsep=1pt]\n" + "\n".join(items) + "\n\\end{itemize}"


def _build_languages_section(languages: list) -> str:
    """Render language proficiency entries."""
    if not languages:
        return ""
    parts = []
    for lang in languages:
        language = latex_escape(lang.get("language", ""))
        level = latex_escape(lang.get("level", ""))
        if language:
            parts.append(f"\\textbf{{{language}}} -- {level}" if level else f"\\textbf{{{language}}}")
    return r" \quad \textbullet{} ".join(parts)


class LaTeXTemplateAgent(BaseAgent):
    """Fills a LaTeX template with optimized CV content and user preferences."""

    name = "latex_template_agent"
    description = "Renders optimized content into a selected LaTeX template"

    def run(self, state: dict) -> dict:
        """Generate state['latex_source'] from optimized_content and template."""
        self._log("Starting LaTeX template rendering")

        optimized = state.get("optimized_content")
        preferences = state.get("user_preferences", {})
        photo_path = state.get("photo_path")

        if not optimized:
            return self._add_error(state, "optimized_content is missing.")

        template_name = preferences.get("template", "modern").lower()
        color_hex = preferences.get("color", "#2E86AB").lstrip("#")
        include_photo = preferences.get("include_photo", False)

        # Convert hex color to RGB for LaTeX
        try:
            r = int(color_hex[0:2], 16)
            g = int(color_hex[2:4], 16)
            b = int(color_hex[4:6], 16)
            color_rgb = f"{r},{g},{b}"
        except (ValueError, IndexError):
            color_rgb = "46,134,171"  # default blue

        # Load template file
        template_path = TEMPLATES_DIR / f"{template_name}.tex"
        if not template_path.exists():
            template_path = TEMPLATES_DIR / "modern.tex"
            self._log(f"Template '{template_name}' not found, falling back to modern.tex", "warning")

        try:
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
        except Exception as e:
            return self._add_error(state, f"Failed to read template: {e}")

        # Extract personal info
        pi = optimized.get("personal_info", {})
        name = latex_escape(pi.get("name", "Your Name"))
        email = latex_escape(pi.get("email", ""))
        phone = latex_escape(pi.get("phone", ""))
        linkedin = pi.get("linkedin", "")
        location = latex_escape(pi.get("location", ""))
        title = latex_escape(pi.get("title", ""))

        # LinkedIn: strip URL prefix for display
        linkedin_display = linkedin.replace("https://", "").replace("http://", "").replace("www.", "")
        linkedin_display = latex_escape(linkedin_display)
        linkedin_url = linkedin if linkedin.startswith("http") else f"https://{linkedin}" if linkedin else ""

        # Build sections
        summary = latex_escape(optimized.get("summary", ""))
        experience_section = _build_experience_section(optimized.get("experiences", []))
        skills_section = _build_skills_grouped(optimized.get("skills", []))
        education_section = _build_education_section(optimized.get("education", []))
        projects_section = _build_projects_section(optimized.get("projects", []))
        certifications_section = _build_certifications_section(optimized.get("certifications", []))
        languages_section = _build_languages_section(optimized.get("languages", []))

        # Photo block
        if include_photo and photo_path and os.path.exists(photo_path):
            safe_photo = photo_path.replace("\\", "/").replace("%", "\\%")
            photo_block = f"\\includegraphics[width=2.5cm,height=3cm,keepaspectratio]{{{safe_photo}}}"
        else:
            photo_block = ""

        # Replace color placeholder
        template = re.sub(
            r"\\definecolor\{maincolor\}\{RGB\}\{[0-9,]+\}",
            f"\\definecolor{{maincolor}}{{RGB}}{{{color_rgb}}}",
            template,
        )

        # Replace all content placeholders
        replacements = {
            "{{CANDIDATE_NAME}}": name,
            "{{CANDIDATE_TITLE}}": title,
            "{{CANDIDATE_EMAIL}}": email,
            "{{CANDIDATE_PHONE}}": phone,
            "{{CANDIDATE_LINKEDIN}}": linkedin_display,
            "{{CANDIDATE_LINKEDIN_URL}}": linkedin_url,
            "{{CANDIDATE_LOCATION}}": location,
            "{{CANDIDATE_SUMMARY}}": summary,
            "{{EXPERIENCE_SECTION}}": experience_section,
            "{{SKILLS_SECTION}}": skills_section,
            "{{EDUCATION_SECTION}}": education_section,
            "{{PROJECTS_SECTION}}": projects_section,
            "{{CERTIFICATIONS_SECTION}}": certifications_section,
            "{{LANGUAGES_SECTION}}": languages_section,
            "{{PHOTO_BLOCK}}": photo_block,
        }

        for placeholder, value in replacements.items():
            template = template.replace(placeholder, value if value else "")

        state["latex_source"] = template
        self._log("LaTeX template rendering complete")
        return state
