"""Agent that rewrites resume sections to be ATS-optimized and keyword-rich."""

import json
import re
import copy
import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a professional resume writer and ATS optimization specialist.
You will receive:
1. The original structured resume
2. Gap analysis (missing skills, terms to rephrase, undersold experiences)
3. Job requirements (keywords, responsibilities, tech stack)
4. User preferences (language, conciseness level)

Your task: Rewrite all resume sections to maximize ATS compatibility while keeping the content truthful.

Rules:
- Integrate ATS keywords naturally — never stuff them awkwardly
- Use strong action verbs: Led, Developed, Implemented, Optimized, Delivered, Architected, Automated, Reduced, Increased, Managed
- Add metrics where plausible (%, €, users, team size) based on existing context
- Rephrase generic descriptions into specific, impactful statements
- Keep experiences truthful — only rephrase, never invent new roles or companies
- Incorporate missing skills only if they can be genuinely inferred from context
- Match the requested language (French/English)
- Conciseness: if "concise", keep bullets to 3-4 per role; if "detailed", allow 5-6

Return ONLY a valid JSON object with the SAME structure as the input resume_structured, but with rewritten content.
Also add a key "keywords_added": list of strings (the ATS keywords you successfully integrated).
Do not change personal_info fields (name, email, phone, linkedin, location).
Return ONLY the JSON."""

HUMAN_PROMPT = """Optimize this resume for ATS and the provided job requirements.

ORIGINAL RESUME:
{resume_structured}

GAP ANALYSIS:
{gap_analysis}

JOB REQUIREMENTS:
{job_requirements}

USER PREFERENCES:
- Language: {language}
- Conciseness: {conciseness}
- Template: {template}"""


class ATSOptimizerAgent(BaseAgent):
    """Rewrites resume content to maximize ATS keyword coverage and impact."""

    name = "ats_optimizer_agent"
    description = "Rewrites CV sections with ATS keywords and strong action verbs"

    def run(self, state: dict) -> dict:
        """Produce optimized_content from resume_structured + gap_analysis + job_requirements."""
        self._log("Starting ATS content optimization")

        resume_structured = state.get("resume_structured")
        gap_analysis = state.get("gap_analysis")
        job_requirements = state.get("job_requirements")
        preferences = state.get("user_preferences", {})

        if not resume_structured:
            return self._add_error(state, "resume_structured is missing.")
        if not gap_analysis:
            return self._add_error(state, "gap_analysis is missing.")
        if not job_requirements:
            return self._add_error(state, "job_requirements is missing.")

        language = preferences.get("language", "English")
        conciseness = preferences.get("conciseness", "balanced")
        template = preferences.get("template", "modern")

        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=HUMAN_PROMPT.format(
                    resume_structured=json.dumps(resume_structured, ensure_ascii=False, indent=2),
                    gap_analysis=json.dumps(gap_analysis, ensure_ascii=False, indent=2),
                    job_requirements=json.dumps(job_requirements, ensure_ascii=False, indent=2),
                    language=language,
                    conciseness=conciseness,
                    template=template,
                )),
            ]
            response = self._safe_llm_invoke(messages, fallback_fn=lambda: None)

            if response is not None:
                content = response.content.strip()
                if content.startswith("```"):
                    content = re.sub(r"^```(?:json)?\n?", "", content)
                    content = re.sub(r"\n?```$", "", content)
                optimized = json.loads(content)
                keywords_added = optimized.pop("keywords_added", [])
                self._log(f"Optimization complete. Keywords added: {len(keywords_added)}")
            else:
                raise ValueError("LLM returned None")

        except Exception as e:
            self._log(f"LLM optimization failed ({e}), returning original content with missing skills appended", "warning")
            optimized = copy.deepcopy(resume_structured)
            keywords_added = []
            # Append missing skills to skills list as a minimal enhancement
            missing = gap_analysis.get("missing_skills", [])
            if missing:
                optimized["skills"] = list(dict.fromkeys(optimized.get("skills", []) + missing[:5]))
                keywords_added = missing[:5]

        # Preserve personal_info from original
        optimized["personal_info"] = resume_structured.get("personal_info", {})

        # Ensure structure integrity
        for key in ["summary", "experiences", "skills", "education", "certifications", "projects", "languages"]:
            optimized.setdefault(key, resume_structured.get(key, [] if key != "summary" else ""))

        state["optimized_content"] = optimized
        state["keywords_added"] = keywords_added if isinstance(keywords_added, list) else []
        self._log("ATS optimization complete")
        return state
