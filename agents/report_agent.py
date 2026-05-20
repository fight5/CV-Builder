"""Agent that generates human-readable reports: executive summary, diff, and keywords CSV."""

import csv
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "outputs"


def _section_diff(original: list, optimized: list, section_name: str) -> str:
    """Produce a markdown diff block comparing two lists of strings."""
    lines = [f"### {section_name}\n"]
    if not original and not optimized:
        return ""
    if not original:
        lines.append("*No original content.*\n")
        lines.append("**Optimized:**")
        for item in optimized:
            lines.append(f"- {item}")
        return "\n".join(lines) + "\n"

    lines.append("| Original | Optimized |")
    lines.append("|---|---|")
    max_len = max(len(original), len(optimized))
    for i in range(max_len):
        orig = original[i] if i < len(original) else "_—_"
        opt = optimized[i] if i < len(optimized) else "_—_"
        # Escape pipe characters in markdown table
        orig_md = str(orig).replace("|", "\\|")
        opt_md = str(opt).replace("|", "\\|")
        lines.append(f"| {orig_md} | {opt_md} |")
    return "\n".join(lines) + "\n\n"


class ReportAgent(BaseAgent):
    """Generates the executive report, diff report, and ATS keywords CSV."""

    name = "report_agent"
    description = "Produces executive report, diff report, and keywords CSV"

    def run(self, state: dict) -> dict:
        """Generate and save all reports; populate state['executive_report'] and state['diff_report']."""
        self._log("Starting report generation")

        optimized = state.get("optimized_content") or {}
        original = state.get("resume_structured") or {}
        job_requirements = state.get("job_requirements") or {}
        gap_analysis = state.get("gap_analysis") or {}
        matching_score = state.get("matching_score", 0.0)
        keyword_coverage = state.get("keyword_coverage", 0.0)
        keywords_added = state.get("keywords_added", [])
        metadata = state.get("metadata", {})
        preferences = state.get("user_preferences", {})

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        candidate_name = optimized.get("personal_info", {}).get("name", "Candidate")
        job_title = job_requirements.get("job_title", "Target Position")
        language = preferences.get("language", "English")

        # ── Executive Report ──────────────────────────────────────────────
        exec_lines = [
            f"# ATS Optimization Report",
            f"**Candidate:** {candidate_name}  ",
            f"**Target Position:** {job_title}  ",
            f"**Generated:** {now}  ",
            f"**Language:** {language}  ",
            "",
            "---",
            "",
            "## Summary Scores",
            "",
            f"| Metric | Score |",
            f"|---|---|",
            f"| Matching Score (Required Skills) | **{matching_score:.1f}%** |",
            f"| ATS Keyword Coverage | **{keyword_coverage:.1f}%** |",
            f"| Keywords Successfully Added | **{len(keywords_added)}** |",
            f"| Total Required Skills | {metadata.get('required_skills_total', 'N/A')} |",
            f"| Total ATS Keywords | {metadata.get('ats_keywords_total', 'N/A')} |",
            "",
            "---",
            "",
            "## Gap Analysis Summary",
            "",
            gap_analysis.get("summary", "*No gap analysis available.*"),
            "",
        ]

        missing_skills = gap_analysis.get("missing_skills", [])
        matching_skills = gap_analysis.get("matching_skills", [])
        if missing_skills:
            exec_lines += [
                "### Missing Required Skills",
                "",
                *[f"- {s}" for s in missing_skills],
                "",
            ]
        if matching_skills:
            exec_lines += [
                "### Matching Skills",
                "",
                *[f"- {s}" for s in matching_skills],
                "",
            ]

        terms_to_rephrase = gap_analysis.get("terms_to_rephrase", [])
        if terms_to_rephrase:
            exec_lines += [
                "### Terms Rephrased for ATS",
                "",
                "| Original Term | ATS-Optimized Term | Reason |",
                "|---|---|---|",
            ]
            for item in terms_to_rephrase:
                curr = item.get("current_term", "")
                sugg = item.get("suggested_term", "")
                reason = item.get("reason", "").replace("|", "\\|")
                exec_lines.append(f"| {curr} | {sugg} | {reason} |")
            exec_lines.append("")

        if keywords_added:
            exec_lines += [
                "### Keywords Successfully Integrated",
                "",
                *[f"- `{kw}`" for kw in keywords_added],
                "",
            ]

        qc_warnings = metadata.get("qc_warnings", [])
        if qc_warnings:
            exec_lines += [
                "## Quality Control Warnings",
                "",
                *[f"- {w}" for w in qc_warnings],
                "",
            ]

        undersold = gap_analysis.get("undersold_experiences", [])
        if undersold:
            exec_lines += [
                "## Undersold Experiences Enhanced",
                "",
            ]
            for item in undersold:
                exec_lines.append(f"- **Experience #{item.get('experience_index', '?')+1}** — "
                                   f"{item.get('reason', '')}. *Enhancement*: {item.get('suggestion', '')}")
            exec_lines.append("")

        exec_lines += [
            "---",
            "",
            "## Recommendations",
            "",
            "1. Review the generated CV carefully before submitting — ensure all optimized content is accurate.",
            "2. Tailor the summary paragraph for each application.",
            "3. If the matching score is below 70%, consider acquiring or prominently showcasing the missing skills.",
            "4. Always submit the PDF version generated by this tool for ATS submissions.",
            "",
            "*Report generated by AI ATS Resume Generator Agent*",
        ]

        executive_report = "\n".join(exec_lines)

        # ── Diff Report ───────────────────────────────────────────────────
        diff_lines = [
            "# Resume Diff Report — Before / After Optimization",
            f"*Generated: {now}*",
            "",
            "---",
            "",
        ]

        # Summary diff
        orig_summary = original.get("summary", "")
        opt_summary = optimized.get("summary", "")
        if orig_summary or opt_summary:
            diff_lines += [
                "## Professional Summary",
                "",
                "**Before:**",
                f"> {orig_summary}" if orig_summary else "> *(empty)*",
                "",
                "**After:**",
                f"> {opt_summary}" if opt_summary else "> *(empty)*",
                "",
                "---",
                "",
            ]

        # Experiences diff
        orig_exps = original.get("experiences", [])
        opt_exps = optimized.get("experiences", [])
        if orig_exps or opt_exps:
            diff_lines.append("## Experience Sections\n")
            max_exp = max(len(orig_exps), len(opt_exps))
            for i in range(max_exp):
                o_exp = orig_exps[i] if i < len(orig_exps) else {}
                n_exp = opt_exps[i] if i < len(opt_exps) else {}
                role_title = n_exp.get("title") or o_exp.get("title") or f"Experience {i+1}"
                company = n_exp.get("company") or o_exp.get("company") or ""
                diff_lines.append(f"### {role_title} @ {company}\n")

                o_ach = o_exp.get("achievements", []) or ([o_exp.get("description", "")] if o_exp.get("description") else [])
                n_ach = n_exp.get("achievements", []) or ([n_exp.get("description", "")] if n_exp.get("description") else [])

                diff_lines.append(
                    _section_diff(o_ach, n_ach, "Achievements")
                )

        # Skills diff
        orig_skills = original.get("skills", [])
        opt_skills = optimized.get("skills", [])
        diff_lines.append("## Skills\n")
        added_skills = [s for s in opt_skills if s not in orig_skills]
        removed_skills = [s for s in orig_skills if s not in opt_skills]
        if added_skills:
            diff_lines.append(f"**Added:** {', '.join(added_skills)}\n")
        if removed_skills:
            diff_lines.append(f"**Removed/Merged:** {', '.join(removed_skills)}\n")
        if not added_skills and not removed_skills:
            diff_lines.append("*No changes in skills section.*\n")

        diff_report = "\n".join(diff_lines)

        # ── Save reports ─────────────────────────────────────────────────
        try:
            exec_path = OUTPUT_DIR / "matching_report.md"
            with open(exec_path, "w", encoding="utf-8") as f:
                f.write(executive_report)
            self._log(f"Executive report saved to {exec_path}")
        except Exception as e:
            self._log(f"Failed to save executive report: {e}", "warning")

        try:
            diff_path = OUTPUT_DIR / "diff_report.md"
            with open(diff_path, "w", encoding="utf-8") as f:
                f.write(diff_report)
            self._log(f"Diff report saved to {diff_path}")
        except Exception as e:
            self._log(f"Failed to save diff report: {e}", "warning")

        # ── Keywords CSV ──────────────────────────────────────────────────
        try:
            csv_path = OUTPUT_DIR / "ats_keywords.csv"
            all_keywords = job_requirements.get("ats_keywords", [])
            full_text = " ".join([
                optimized.get("summary", ""),
                " ".join(optimized.get("skills", [])),
                " ".join(
                    exp.get("description", "") + " " + " ".join(exp.get("achievements", []))
                    for exp in optimized.get("experiences", [])
                ),
            ]).lower()

            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Keyword", "Category", "Found in Resume", "Source"])
                for kw in job_requirements.get("required_skills", []):
                    found = kw.lower() in full_text
                    writer.writerow([kw, "Required Skill", "Yes" if found else "No", "Job Description"])
                for kw in job_requirements.get("nice_to_have_skills", []):
                    found = kw.lower() in full_text
                    writer.writerow([kw, "Nice to Have", "Yes" if found else "No", "Job Description"])
                for kw in all_keywords:
                    found = kw.lower() in full_text
                    category = "Added by AI" if kw in keywords_added else "ATS Keyword"
                    writer.writerow([kw, category, "Yes" if found else "No", "Job Description"])
            self._log(f"ATS keywords CSV saved to {csv_path}")
        except Exception as e:
            self._log(f"Failed to save keywords CSV: {e}", "warning")

        state["executive_report"] = executive_report
        state["diff_report"] = diff_report
        self._log("Report generation complete")
        return state
