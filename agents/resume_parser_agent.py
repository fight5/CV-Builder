"""Agent that parses a raw resume text into a structured dictionary."""

import json
import re
import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from .base_agent import BaseAgent
from core.tools import extract_email, extract_phone

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an expert resume analyst and career coach.
Your task is to parse a raw resume text into a structured JSON object.
Return ONLY a valid JSON object with these keys:
- personal_info: dict with keys: name, email, phone, linkedin, github, location, title
- summary: string (professional summary or objective, empty string if not present)
- experiences: list of dicts, each with: title, company, dates, location, description, achievements (list of strings)
- skills: list of strings (flat list of all technical and soft skills)
- education: list of dicts, each with: degree, institution, dates, location, gpa, honors
- certifications: list of strings
- projects: list of dicts, each with: name, description, technologies (list), url
- languages: list of dicts, each with: language, level (e.g. Native, Fluent, Intermediate)
- publications: list of strings
Keep descriptions concise but complete. Preserve all achievements with metrics.
Do not invent information. Return empty lists/strings for missing sections.
Return ONLY the JSON, no explanation."""

HUMAN_PROMPT = """Parse this resume into structured JSON:

{resume_text}"""


def _minimal_fallback_parse(text: str) -> dict:
    """Basic regex-based resume parsing when LLM is unavailable."""
    email = extract_email(text) or ""
    phone = extract_phone(text) or ""

    # Try to extract name from first non-empty line
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    name = lines[0] if lines else ""
    # If first line looks like an email or URL, skip it
    if "@" in name or name.startswith("http"):
        name = ""

    # Extract skills section
    skills = []
    skill_section_match = re.search(
        r"(?:skills?|competences?|technologies?)[:\s]*\n(.*?)(?:\n\n|\Z)",
        text, re.IGNORECASE | re.DOTALL
    )
    if skill_section_match:
        raw_skills = skill_section_match.group(1)
        skills = [s.strip() for s in re.split(r"[,|•\n·]", raw_skills) if s.strip() and len(s.strip()) < 50]

    return {
        "personal_info": {
            "name": name,
            "email": email,
            "phone": phone,
            "linkedin": "",
            "github": "",
            "location": "",
            "title": "",
        },
        "summary": "",
        "experiences": [],
        "skills": skills,
        "education": [],
        "certifications": [],
        "projects": [],
        "languages": [],
        "publications": [],
    }


class ResumeParserAgent(BaseAgent):
    """Structures a raw resume text into a rich, machine-readable dictionary."""

    name = "resume_parser_agent"
    description = "Parses raw resume text into structured sections"

    def run(self, state: dict) -> dict:
        """Parse state['resume_text'] and populate state['resume_structured']."""
        self._log("Starting resume parsing")
        resume_text = state.get("resume_text", "")

        if not resume_text or not resume_text.strip():
            return self._add_error(state, "resume_text is empty.")

        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=HUMAN_PROMPT.format(resume_text=resume_text)),
            ]
            response = self._safe_llm_invoke(messages, fallback_fn=lambda: None)

            if response is not None:
                content = response.content.strip()
                if content.startswith("```"):
                    content = re.sub(r"^```(?:json)?\n?", "", content)
                    content = re.sub(r"\n?```$", "", content)
                parsed = json.loads(content)
                self._log(f"LLM parsed resume: "
                          f"{len(parsed.get('experiences', []))} experiences, "
                          f"{len(parsed.get('skills', []))} skills")
            else:
                raise ValueError("LLM returned None")

        except Exception as e:
            self._log(f"LLM parsing failed ({e}), using fallback", "warning")
            parsed = _minimal_fallback_parse(resume_text)

        # Ensure all required keys exist
        defaults = {
            "personal_info": {},
            "summary": "",
            "experiences": [],
            "skills": [],
            "education": [],
            "certifications": [],
            "projects": [],
            "languages": [],
            "publications": [],
        }
        for key, default in defaults.items():
            if key not in parsed:
                parsed[key] = default

        # Normalize personal_info fields
        pi_defaults = {"name": "", "email": "", "phone": "", "linkedin": "", "github": "", "location": "", "title": ""}
        for k, v in pi_defaults.items():
            parsed["personal_info"].setdefault(k, v)

        # If email/phone missing from LLM, try regex extraction
        if not parsed["personal_info"]["email"]:
            parsed["personal_info"]["email"] = extract_email(resume_text) or ""
        if not parsed["personal_info"]["phone"]:
            parsed["personal_info"]["phone"] = extract_phone(resume_text) or ""

        # Normalize experience entries
        for exp in parsed.get("experiences", []):
            exp.setdefault("title", "")
            exp.setdefault("company", "")
            exp.setdefault("dates", "")
            exp.setdefault("location", "")
            exp.setdefault("description", "")
            exp.setdefault("achievements", [])

        state["resume_structured"] = parsed
        self._log("Resume parsing complete")
        return state
