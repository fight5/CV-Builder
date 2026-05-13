"""LangGraph state schema for the ATS Resume Generator pipeline."""

from typing import TypedDict, Optional


class ATSState(TypedDict):
    # Inputs
    job_description_text: str
    resume_text: str
    user_preferences: dict  # color, photo, template, language, conciseness
    photo_path: Optional[str]

    # Parsed data
    job_requirements: Optional[dict]  # skills, keywords, experience_level, responsibilities
    resume_structured: Optional[dict]  # experiences, skills, education, certifications, projects

    # Analysis
    gap_analysis: Optional[dict]  # missing_skills, undersold_experiences, terms_to_rephrase

    # Generated content
    optimized_content: Optional[dict]  # rewritten sections
    latex_source: Optional[str]
    pdf_path: Optional[str]

    # Quality
    matching_score: Optional[float]
    keyword_coverage: Optional[float]
    keywords_added: Optional[list]

    # Reports
    executive_report: Optional[str]
    diff_report: Optional[str]

    # Meta
    errors: list
    metadata: dict
