"""Agent that compares job requirements with resume content to identify gaps."""

import json
import re
import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a senior talent acquisition specialist and ATS expert.
Given a job requirements JSON and a structured resume JSON, perform a thorough gap analysis.
Return ONLY a valid JSON object with these keys:
- missing_skills: list of strings (required skills completely absent from resume)
- partial_skills: list of dicts, each with: skill (str), resume_term (str), notes (str)
- matching_skills: list of strings (required skills clearly present in resume)
- undersold_experiences: list of dicts, each with: experience_index (int), reason (str), suggestion (str)
  (experiences that relate to job requirements but are poorly described)
- terms_to_rephrase: list of dicts, each with: current_term (str), suggested_term (str), reason (str)
  (generic terms that should be replaced with ATS-specific language from the job description)
- keyword_gaps: list of strings (ATS keywords from job description missing in resume)
- severity_score: float 0-1 (0=perfect match, 1=complete mismatch)
- summary: string (2-3 sentence summary of the gap analysis)
Return ONLY the JSON, no explanation."""

HUMAN_PROMPT = """Perform gap analysis between this job and this resume:

JOB REQUIREMENTS:
{job_requirements}

RESUME:
{resume_structured}"""


def _compute_gap_locally(job_requirements: dict, resume_structured: dict) -> dict:
    """Rule-based gap analysis as fallback when LLM is unavailable."""
    required = [s.lower() for s in job_requirements.get("required_skills", [])]
    ats_keywords = [k.lower() for k in job_requirements.get("ats_keywords", [])]
    resume_skills = [s.lower() for s in resume_structured.get("skills", [])]

    # Build a combined text blob from the resume for keyword search
    resume_blob = " ".join([
        " ".join(resume_structured.get("skills", [])),
        resume_structured.get("summary", ""),
        " ".join(
            exp.get("description", "") + " " + " ".join(exp.get("achievements", []))
            for exp in resume_structured.get("experiences", [])
        ),
    ]).lower()

    matching = [s for s in required if any(s in rs or rs in s for rs in resume_skills) or s in resume_blob]
    missing = [s for s in required if s not in matching]
    keyword_gaps = [k for k in ats_keywords if k not in resume_blob]

    severity = len(missing) / max(len(required), 1)

    return {
        "missing_skills": missing,
        "partial_skills": [],
        "matching_skills": matching,
        "undersold_experiences": [],
        "terms_to_rephrase": [],
        "keyword_gaps": keyword_gaps,
        "severity_score": round(severity, 2),
        "summary": (
            f"Found {len(matching)} matching and {len(missing)} missing required skills. "
            f"{len(keyword_gaps)} ATS keywords are absent from the resume."
        ),
    }


class GapAnalysisAgent(BaseAgent):
    """Identifies skill gaps, keyword deficiencies, and optimization opportunities."""

    name = "gap_analysis_agent"
    description = "Compares job requirements vs resume to find ATS gaps"

    def run(self, state: dict) -> dict:
        """Analyze gaps between job_requirements and resume_structured."""
        self._log("Starting gap analysis")

        job_requirements = state.get("job_requirements")
        resume_structured = state.get("resume_structured")

        if not job_requirements:
            return self._add_error(state, "job_requirements is missing from state.")
        if not resume_structured:
            return self._add_error(state, "resume_structured is missing from state.")

        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=HUMAN_PROMPT.format(
                    job_requirements=json.dumps(job_requirements, ensure_ascii=False, indent=2),
                    resume_structured=json.dumps(resume_structured, ensure_ascii=False, indent=2),
                )),
            ]
            response = self._safe_llm_invoke(messages, fallback_fn=lambda: None)

            if response is not None:
                content = response.content.strip()
                if content.startswith("```"):
                    content = re.sub(r"^```(?:json)?\n?", "", content)
                    content = re.sub(r"\n?```$", "", content)
                gap = json.loads(content)
                self._log(
                    f"Gap analysis: {len(gap.get('missing_skills', []))} missing skills, "
                    f"severity={gap.get('severity_score', 0)}"
                )
            else:
                raise ValueError("LLM returned None")

        except Exception as e:
            self._log(f"LLM gap analysis failed ({e}), using local fallback", "warning")
            gap = _compute_gap_locally(job_requirements, resume_structured)

        # Ensure all required keys
        defaults = {
            "missing_skills": [],
            "partial_skills": [],
            "matching_skills": [],
            "undersold_experiences": [],
            "terms_to_rephrase": [],
            "keyword_gaps": [],
            "severity_score": 0.5,
            "summary": "",
        }
        for key, default in defaults.items():
            gap.setdefault(key, default)

        state["gap_analysis"] = gap
        self._log("Gap analysis complete")
        return state
