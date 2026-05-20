"""Agent that parses a raw job description and extracts structured requirements."""

import json
import re
import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an expert HR analyst and ATS specialist.
Your task is to analyze a job description and extract structured information.
Return ONLY a valid JSON object with the following keys:
- required_skills: list of strings (hard technical skills that are explicitly required)
- nice_to_have_skills: list of strings (skills mentioned as preferred or bonus)
- ats_keywords: list of strings (important keywords an ATS would scan for, including tools, frameworks, methodologies)
- experience_level: string, one of: "junior", "mid", "senior", "lead", "executive"
- responsibilities: list of strings (main job duties)
- company_values: list of strings (cultural or soft-skill requirements)
- tech_stack: list of strings (specific technologies, frameworks, languages mentioned)
- job_title: string (the main job title)
- company_name: string (the hiring company name if mentioned, otherwise empty string)
- industry: string (the industry sector)
Do not include any explanation, only the JSON object."""

HUMAN_PROMPT = """Analyze this job description and return the structured JSON:

{job_description}"""


def _regex_fallback(text: str) -> dict:
    """Minimal keyword extraction when the LLM is unavailable."""
    # Common tech keywords
    tech_pattern = re.compile(
        r"\b(Python|Java|JavaScript|TypeScript|React|Angular|Vue|Node\.?js|SQL|NoSQL|"
        r"AWS|GCP|Azure|Docker|Kubernetes|CI/CD|Git|REST|API|ML|AI|TensorFlow|PyTorch|"
        r"Spark|Hadoop|Kafka|Redis|PostgreSQL|MongoDB|MySQL|Django|Flask|FastAPI|"
        r"Linux|Agile|Scrum|DevOps|Microservices|GraphQL|Terraform|Ansible)\b",
        re.IGNORECASE,
    )
    tech_found = list(set(tech_pattern.findall(text)))

    # Experience level detection
    level = "mid"
    text_lower = text.lower()
    if any(w in text_lower for w in ["junior", "entry level", "entry-level", "0-2 years", "1-2 years"]):
        level = "junior"
    elif any(w in text_lower for w in ["senior", "lead", "principal", "5+ years", "7+ years", "10+ years"]):
        level = "senior"
    elif any(w in text_lower for w in ["director", "vp ", "vice president", "executive", "chief"]):
        level = "executive"

    # Extract bullet-point responsibilities
    responsibilities = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith(("•", "-", "–", "*", "·")) and len(line) > 10:
            responsibilities.append(line.lstrip("•-–*· ").strip())
    responsibilities = responsibilities[:15]

    return {
        "required_skills": tech_found[:15],
        "nice_to_have_skills": [],
        "ats_keywords": tech_found,
        "experience_level": level,
        "responsibilities": responsibilities,
        "company_values": [],
        "tech_stack": tech_found,
        "job_title": "",
        "company_name": "",
        "industry": "",
    }


class JobParserAgent(BaseAgent):
    """Extracts structured requirements from a raw job description text."""

    name = "job_parser_agent"
    description = "Parses job descriptions into structured ATS-ready requirements"

    def run(self, state: dict) -> dict:
        """Parse job_description_text and populate state['job_requirements']."""
        self._log("Starting job description parsing")
        job_text = state.get("job_description_text", "")

        if not job_text or not job_text.strip():
            return self._add_error(state, "job_description_text is empty.")

        # Try LLM-based extraction
        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=HUMAN_PROMPT.format(job_description=job_text)),
            ]
            response = self._safe_llm_invoke(messages, fallback_fn=lambda: None)

            if response is not None:
                content = response.content.strip()
                # Strip markdown code fences if present
                if content.startswith("```"):
                    content = re.sub(r"^```(?:json)?\n?", "", content)
                    content = re.sub(r"\n?```$", "", content)
                parsed = json.loads(content)
                self._log(f"LLM extracted {len(parsed.get('ats_keywords', []))} ATS keywords")
            else:
                raise ValueError("LLM returned None")

        except Exception as e:
            self._log(f"LLM parsing failed ({e}), using regex fallback", "warning")
            parsed = _regex_fallback(job_text)

        # Validate and clean
        required_keys = [
            "required_skills", "nice_to_have_skills", "ats_keywords",
            "experience_level", "responsibilities", "company_values",
            "tech_stack", "job_title", "company_name", "industry",
        ]
        for key in required_keys:
            if key not in parsed:
                parsed[key] = [] if key != "experience_level" else "mid"
                if key not in ("job_title", "company_name", "industry"):
                    self._log(f"Missing key '{key}' in LLM output, defaulting", "warning")

        # Deduplicate lists
        for list_key in ["required_skills", "nice_to_have_skills", "ats_keywords", "tech_stack", "responsibilities", "company_values"]:
            if isinstance(parsed.get(list_key), list):
                parsed[list_key] = list(dict.fromkeys(str(x).strip() for x in parsed[list_key] if x))

        state["job_requirements"] = parsed
        self._log(f"Job parsing complete. Level={parsed.get('experience_level')}, "
                  f"Required skills={len(parsed.get('required_skills', []))}")
        return state
