"""Agent that computes ATS quality scores and validates resume content."""

import re
import logging
from typing import Optional

from .base_agent import BaseAgent
from core.tools import compute_keyword_density

logger = logging.getLogger(__name__)

# Characters that commonly break ATS parsers
ATS_BREAKING_PATTERN = re.compile(r"[^\x00-\x7FÀ-ɏЀ-ӿ]")


class QualityControlAgent(BaseAgent):
    """Scores the optimized resume for ATS compatibility and content quality."""

    name = "quality_control_agent"
    description = "Computes matching score, keyword coverage, and ATS compliance checks"

    def run(self, state: dict) -> dict:
        """Compute quality metrics and populate state scoring fields."""
        self._log("Starting quality control checks")

        optimized = state.get("optimized_content")
        job_requirements = state.get("job_requirements")
        keywords_added = state.get("keywords_added", [])

        if not optimized:
            return self._add_error(state, "optimized_content is missing.")
        if not job_requirements:
            return self._add_error(state, "job_requirements is missing.")

        required_skills = job_requirements.get("required_skills", [])
        ats_keywords = job_requirements.get("ats_keywords", [])

        # Build full text blob from optimized content (filter None — LLM may emit nulls)
        text_parts = [optimized.get("summary") or ""]
        for exp in optimized.get("experiences") or []:
            text_parts.append(exp.get("description") or "")
            text_parts.extend(a for a in (exp.get("achievements") or []) if a)
        text_parts.extend(s for s in (optimized.get("skills") or []) if s)
        for proj in optimized.get("projects") or []:
            text_parts.append(proj.get("description") or "")
        full_text = " ".join(p for p in text_parts if p)

        # 1. Matching score: required skills found in resume
        if required_skills:
            full_text_lower = full_text.lower()
            matching_count = sum(
                1 for skill in required_skills
                if skill.lower() in full_text_lower
            )
            matching_score = round((matching_count / len(required_skills)) * 100, 1)
        else:
            matching_score = 0.0

        # 2. Keyword coverage: ATS keywords found in content
        keyword_coverage = round(compute_keyword_density(full_text, ats_keywords) * 100, 1) if ats_keywords else 0.0

        # 3. ATS compliance checks
        warnings = []

        # Check for ATS-breaking unicode characters
        breaking_chars = ATS_BREAKING_PATTERN.findall(full_text)
        if breaking_chars:
            unique_breaking = list(set(breaking_chars))[:10]
            warnings.append(f"Found potentially ATS-breaking characters: {unique_breaking}")

        # Check date format consistency
        date_pattern = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")  # MM/DD/YYYY — inconsistent
        if date_pattern.search(full_text):
            warnings.append("Inconsistent date format detected (MM/DD/YYYY). Prefer 'Month YYYY'.")

        # Check content length (rough word count proxy for page count)
        word_count = len(full_text.split())
        if word_count < 200:
            warnings.append(f"Resume content is very short ({word_count} words). Consider expanding.")
        elif word_count > 1200:
            warnings.append(f"Resume content is very long ({word_count} words). Consider trimming to 1-2 pages.")

        # Check that experiences have achievements
        exp_without_achievements = [
            exp.get("company", "?") for exp in optimized.get("experiences", [])
            if not exp.get("achievements") and not exp.get("description")
        ]
        if exp_without_achievements:
            warnings.append(f"Experiences without descriptions/achievements: {exp_without_achievements}")

        # Check summary present
        if not optimized.get("summary", "").strip():
            warnings.append("No professional summary found. A summary significantly helps ATS scoring.")

        # Check skills section not empty
        if not optimized.get("skills"):
            warnings.append("Skills section is empty. This is critical for ATS matching.")

        # Log warnings
        for w in warnings:
            self._log(f"QC Warning: {w}", "warning")

        state["matching_score"] = matching_score
        state["keyword_coverage"] = keyword_coverage
        if "keywords_added" not in state or not state["keywords_added"]:
            state["keywords_added"] = keywords_added

        # Store QC metadata
        state["metadata"] = state.get("metadata", {})
        state["metadata"]["qc_warnings"] = warnings
        state["metadata"]["word_count"] = word_count
        state["metadata"]["required_skills_total"] = len(required_skills)
        state["metadata"]["ats_keywords_total"] = len(ats_keywords)

        self._log(
            f"QC complete. Matching score={matching_score}%, "
            f"Keyword coverage={keyword_coverage}%, "
            f"Warnings={len(warnings)}"
        )
        return state
