"""Streamlit interface for the AI ATS Resume Generator Agent."""

import os
import sys
import json
import tempfile
import logging
from pathlib import Path

import streamlit as st
import pandas as pd

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from core.tools import extract_text_from_pdf, extract_text_from_docx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI ATS Resume Generator",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.main-title {
    font-size: 2.2rem;
    font-weight: 800;
    color: #2E86AB;
    margin-bottom: 0.2rem;
}
.subtitle {
    font-size: 1rem;
    color: #555;
    margin-bottom: 1.5rem;
}
.score-card {
    background: #f0f7ff;
    border-left: 4px solid #2E86AB;
    padding: 1rem;
    border-radius: 4px;
    margin-bottom: 1rem;
}
.warning-box {
    background: #fff3cd;
    border-left: 4px solid #ffc107;
    padding: 0.8rem;
    border-radius: 4px;
}
.success-box {
    background: #d4edda;
    border-left: 4px solid #28a745;
    padding: 0.8rem;
    border-radius: 4px;
}
</style>
""", unsafe_allow_html=True)


# ── Demo Data ─────────────────────────────────────────────────────────────────
DEMO_JOB = """Senior Data Scientist — FinTech AI Platform

We are looking for a Senior Data Scientist to join our AI team and build the next generation of credit risk models.

Requirements:
- 5+ years of experience in machine learning and data science
- Strong proficiency in Python, including pandas, scikit-learn, XGBoost, LightGBM
- Experience with deep learning frameworks: TensorFlow or PyTorch
- Proficiency in SQL and experience with BigQuery or Snowflake
- Familiarity with MLflow, DVC, or similar MLOps tools
- Experience deploying models in production using Docker and Kubernetes
- Strong understanding of statistical methods: hypothesis testing, A/B testing
- Experience with NLP and time-series forecasting is a plus
- Excellent communication skills to present findings to non-technical stakeholders

Nice to have:
- Experience in the financial services industry
- Knowledge of explainable AI (SHAP, LIME)
- AWS or GCP certification

Responsibilities:
- Design, train, and deploy machine learning models for credit risk assessment
- Collaborate with engineering teams to integrate models into production systems
- Monitor model performance and implement drift detection
- Mentor junior data scientists
- Present results to C-level executives
"""

DEMO_RESUME = """Marie Dupont
Senior Data Analyst | m.dupont@email.com | +33 6 12 34 56 78 | Paris, France
linkedin.com/in/mariedupont

PROFESSIONAL SUMMARY
Data professional with 6 years of experience transforming large datasets into actionable insights. Skilled in Python and SQL, with experience in machine learning projects for retail and logistics sectors.

EXPERIENCE

Data Analyst — RetailTech Group, Paris | Jan 2021 – Present
- Analyzed customer behavior data using Python and pandas
- Built predictive models for churn prediction with scikit-learn
- Created dashboards in Tableau for business stakeholders
- Worked with SQL databases to extract and transform data

Junior Data Scientist — LogiFlow, Lyon | Sept 2018 – Dec 2020
- Developed demand forecasting models using ARIMA and linear regression
- Processed and cleaned large datasets (>5M rows) with pandas and numpy
- Collaborated with engineering team to put models in a REST API

Education
MSc Data Science — Université Paul Sabatier, Toulouse | 2018
BSc Applied Mathematics — Université de Bordeaux | 2016

SKILLS
Python, SQL, pandas, numpy, scikit-learn, Tableau, Power BI, Git, Excel, R, statistics

LANGUAGES
French (Native), English (Fluent), Spanish (Intermediate)

CERTIFICATIONS
Google Data Analytics Certificate (2022)
"""


def _extract_resume_text(uploaded_file) -> str:
    """Save uploaded file to temp location and extract text."""
    suffix = Path(uploaded_file.name).suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name
    try:
        if suffix == ".pdf":
            return extract_text_from_pdf(tmp_path)
        elif suffix in (".docx", ".doc"):
            return extract_text_from_docx(tmp_path)
        else:
            return uploaded_file.read().decode("utf-8", errors="ignore")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _extract_jd_text(uploaded_file) -> str:
    """Extract job description text from uploaded PDF or text file."""
    suffix = Path(uploaded_file.name).suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name
    try:
        if suffix == ".pdf":
            return extract_text_from_pdf(tmp_path)
        else:
            with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _run_pipeline(job_text: str, resume_text: str, preferences: dict, photo_path: str | None):
    """Import and run the orchestrator pipeline."""
    try:
        from core.orchestrator import run_pipeline
        return run_pipeline(job_text, resume_text, preferences, photo_path)
    except ImportError as e:
        st.error(f"Import error: {e}. Ensure all dependencies are installed.")
        return None
    except Exception as e:
        st.error(f"Pipeline error: {e}")
        logger.error(f"Pipeline error: {e}", exc_info=True)
        return None


def _generate_demo_result() -> dict:
    """Return a mock result for demo mode (no API key required)."""
    return {
        "matching_score": 74.5,
        "keyword_coverage": 68.2,
        "keywords_added": ["XGBoost", "LightGBM", "MLflow", "Docker", "Kubernetes", "A/B testing", "SHAP", "MLOps"],
        "latex_source": r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[margin=2cm]{geometry}
\begin{document}
\begin{center}
  {\LARGE\textbf{Marie Dupont}}\\[4pt]
  Senior Data Scientist\\[4pt]
  m.dupont@email.com | +33 6 12 34 56 78 | Paris, France
\end{center}
\section*{Professional Summary}
Results-driven Senior Data Scientist with 6+ years of experience designing and deploying machine learning models in production environments. Proven expertise in Python (pandas, scikit-learn, XGBoost, LightGBM), SQL, and statistical modeling. Track record of building credit-risk and demand-forecasting models, integrating MLOps workflows (MLflow, Docker, Kubernetes), and presenting data-driven insights to executive stakeholders.
\section*{Professional Experience}
\textbf{Senior Data Analyst}, RetailTech Group, Paris | Jan 2021 -- Present
\begin{itemize}
  \item Designed and deployed customer churn prediction models (XGBoost, LightGBM) achieving 87\% AUC, reducing churn by 14\%
  \item Automated A/B testing framework reducing experiment cycle time by 40\%
  \item Built MLflow experiment tracking pipeline for 12+ production models
  \item Deployed models via Docker containers on Kubernetes cluster (GCP)
  \item Delivered bi-weekly model performance reports to C-level executives
\end{itemize}
\textbf{Junior Data Scientist}, LogiFlow, Lyon | Sept 2018 -- Dec 2020
\begin{itemize}
  \item Developed time-series demand forecasting models (ARIMA, LSTM) with MAPE < 8\%
  \item Built and maintained RESTful model serving API (Flask + Docker)
  \item Processed 5M+ row datasets using pandas, numpy, and BigQuery SQL
\end{itemize}
\section*{Skills}
Python, SQL, pandas, scikit-learn, XGBoost, LightGBM, TensorFlow, MLflow, Docker, Kubernetes, BigQuery, A/B testing, SHAP, statistics, Git, Tableau
\end{document}""",
        "pdf_path": None,
        "executive_report": """# ATS Optimization Report

**Candidate:** Marie Dupont
**Target Position:** Senior Data Scientist
**Matching Score:** 74.5%
**Keyword Coverage:** 68.2%

## Key Optimizations

- Integrated 8 missing ATS keywords: XGBoost, LightGBM, MLflow, Docker, Kubernetes, A/B testing, SHAP, MLOps
- Rewrote experience bullets with quantified achievements and action verbs
- Added production deployment context (Docker, Kubernetes, GCP)
- Enhanced summary to match senior-level positioning

## Missing Skills (to address)
- PyTorch / TensorFlow (partially addressed in summary)
- Snowflake (not inferred from experience)
- Hypothesis testing (now highlighted via A/B testing framing)
""",
        "diff_report": """# Diff Report

## Summary
**Before:** Data professional with 6 years of experience...
**After:** Results-driven Senior Data Scientist with 6+ years... (XGBoost, LightGBM, MLOps, Docker, Kubernetes added)

## Experiences
| Original | Optimized |
|---|---|
| Built predictive models for churn prediction with scikit-learn | Designed and deployed customer churn prediction models (XGBoost, LightGBM) achieving 87% AUC, reducing churn by 14% |
| Created dashboards in Tableau | Automated A/B testing framework reducing experiment cycle time by 40% |
""",
        "gap_analysis": {
            "missing_skills": ["PyTorch", "TensorFlow", "Snowflake", "DVC"],
            "matching_skills": ["Python", "pandas", "scikit-learn", "SQL", "statistics", "Git"],
            "keyword_gaps": ["MLOps", "model drift", "credit risk"],
            "severity_score": 0.35,
            "summary": "Strong Python/ML foundation. Key gaps: deep learning frameworks, MLOps tooling, cloud data warehouses.",
            "terms_to_rephrase": [
                {"current_term": "predictive models", "suggested_term": "XGBoost/LightGBM classification models", "reason": "More specific and ATS-scanned"},
            ],
            "undersold_experiences": [
                {"experience_index": 0, "reason": "REST API deployment not emphasized", "suggestion": "Highlight Docker + production deployment"}
            ],
        },
        "job_requirements": {
            "required_skills": ["Python", "pandas", "scikit-learn", "XGBoost", "LightGBM", "SQL", "TensorFlow", "PyTorch", "Docker", "Kubernetes"],
            "ats_keywords": ["MLOps", "A/B testing", "credit risk", "model deployment", "MLflow", "SHAP", "BigQuery"],
            "experience_level": "senior",
            "tech_stack": ["Python", "SQL", "Docker", "Kubernetes", "MLflow", "BigQuery"],
        },
        "errors": [],
        "metadata": {"pdflatex_available": False},
    }


# ── Main App ──────────────────────────────────────────────────────────────────
def main():
    st.markdown('<div class="main-title">AI ATS Resume Generator</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Generate an ATS-optimized, LaTeX-formatted CV tailored to any job offer — powered by GPT-4o.</div>', unsafe_allow_html=True)

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Configuration")

        api_key = os.getenv("OPENAI_API_KEY", "")
        demo_mode = not api_key or api_key == "your_openai_api_key_here"

        if demo_mode:
            st.markdown('<div class="warning-box">⚠ <strong>Demo Mode</strong>: No API key found in <code>.env</code>. Mock results will be shown.</div>', unsafe_allow_html=True)
            st.markdown("")
        else:
            st.markdown('<div class="success-box">✓ OpenAI API key detected</div>', unsafe_allow_html=True)
            st.markdown("")

        st.subheader("Job Description")
        jd_input_method = st.radio("Input method", ["Paste text", "Upload PDF"], horizontal=True, key="jd_method")

        job_text = ""
        if jd_input_method == "Paste text":
            job_text = st.text_area(
                "Job Description",
                value=DEMO_JOB if demo_mode else "",
                height=200,
                placeholder="Paste the full job description here...",
                label_visibility="collapsed",
            )
        else:
            jd_file = st.file_uploader("Upload Job Description PDF", type=["pdf", "txt"], key="jd_upload")
            if jd_file:
                try:
                    job_text = _extract_jd_text(jd_file)
                    st.success(f"Extracted {len(job_text)} characters from {jd_file.name}")
                except Exception as e:
                    st.error(f"Failed to read file: {e}")

        st.subheader("Your Resume")
        resume_file = st.file_uploader(
            "Upload Resume (PDF or DOCX)",
            type=["pdf", "docx", "doc"],
            key="resume_upload",
        )
        resume_text = ""
        if resume_file:
            try:
                resume_text = _extract_resume_text(resume_file)
                st.success(f"Extracted {len(resume_text)} characters from {resume_file.name}")
            except Exception as e:
                st.error(f"Failed to read resume: {e}")
        elif demo_mode:
            resume_text = DEMO_RESUME
            st.info("Using demo resume. Upload your own to test.")

        st.subheader("Preferences")

        color_hex = st.color_picker("Accent Color", value="#2E86AB")

        template = st.radio(
            "Template Style",
            options=["modern", "executive", "classic"],
            format_func=lambda x: x.capitalize(),
            horizontal=True,
        )

        language = st.selectbox(
            "CV Language",
            options=["English", "French"],
            index=0,
        )

        conciseness = st.select_slider(
            "Conciseness",
            options=["concise", "balanced", "detailed"],
            value="balanced",
        )

        include_photo = st.toggle("Include photo", value=False)
        photo_path = None
        if include_photo:
            photo_file = st.file_uploader("Upload Photo (JPG/PNG)", type=["jpg", "jpeg", "png"], key="photo_upload")
            if photo_file:
                with tempfile.NamedTemporaryFile(delete=False, suffix=Path(photo_file.name).suffix) as tmp:
                    tmp.write(photo_file.read())
                    photo_path = tmp.name
                st.image(photo_file, width=100, caption="Photo preview")

        st.markdown("---")
        generate_btn = st.button(
            "Generate ATS Resume",
            type="primary",
            use_container_width=True,
            disabled=(not job_text.strip() or not resume_text.strip()),
        )

    # ── Main Content Area ────────────────────────────────────────────────────
    if "result" not in st.session_state:
        st.session_state.result = None

    if generate_btn:
        if not job_text.strip():
            st.error("Please provide a job description.")
        elif not resume_text.strip():
            st.error("Please upload your resume or provide text.")
        else:
            preferences = {
                "color": color_hex,
                "template": template,
                "language": language,
                "conciseness": conciseness,
                "include_photo": include_photo,
            }

            if demo_mode:
                with st.spinner("Running demo pipeline (no API key — showing mock results)..."):
                    import time
                    time.sleep(1.5)
                    st.session_state.result = _generate_demo_result()
                    st.session_state.result["metadata"]["demo_mode"] = True
            else:
                with st.spinner("Running 8-agent pipeline... This may take 30-90 seconds."):
                    result = _run_pipeline(job_text, resume_text, preferences, photo_path)
                    if result:
                        st.session_state.result = result

    result = st.session_state.result

    if result is None:
        # Welcome / onboarding screen
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("### How it works")
            st.markdown("""
1. **Job Parser** — Extracts ATS keywords, skills, and requirements
2. **Resume Parser** — Structures your existing CV
3. **Gap Analysis** — Identifies missing skills and opportunities
4. **ATS Optimizer** — Rewrites sections with targeted keywords
5. **LaTeX Generator** — Fills a professional template
6. **PDF Compiler** — Compiles to PDF (requires pdflatex)
7. **Quality Control** — Scores ATS compatibility
8. **Report Generator** — Creates detailed optimization report
            """)
        with col2:
            st.markdown("### What you get")
            st.markdown("""
- ATS-optimized CV in LaTeX & PDF format
- Matching score vs. job requirements
- Keyword coverage analysis
- Before/after diff of all sections
- Executive optimization report
- ATS keywords CSV export
            """)
        with col3:
            st.markdown("### Requirements")
            st.markdown("""
- OpenAI API key (GPT-4o)
- Python 3.11+
- pdflatex (optional, for PDF)
- Resume in PDF or DOCX format
- Job description (paste or PDF)

Set `OPENAI_API_KEY` in `.env` to enable full pipeline.
            """)
        return

    # ── Display Results ───────────────────────────────────────────────────────
    if result.get("errors"):
        for err in result["errors"]:
            st.warning(f"Pipeline warning: {err}")

    if result.get("metadata", {}).get("demo_mode"):
        st.info("Demo mode: results are illustrative. Configure your OpenAI API key for real optimization.")

    # Score metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        score = result.get("matching_score") or 0
        st.metric(
            "Matching Score",
            f"{score:.1f}%",
            delta=f"+{score - 50:.1f}%" if score > 50 else f"{score - 50:.1f}%",
            delta_color="normal",
        )
    with col2:
        coverage = result.get("keyword_coverage") or 0
        st.metric("Keyword Coverage", f"{coverage:.1f}%")
    with col3:
        kw_added = result.get("keywords_added") or []
        st.metric("Keywords Added", len(kw_added))
    with col4:
        warnings = result.get("metadata", {}).get("qc_warnings", [])
        st.metric("QC Warnings", len(warnings), delta_color="inverse")

    st.markdown("---")

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_preview, tab_keywords, tab_gap, tab_report, tab_diff = st.tabs([
        "LaTeX Preview", "Keywords", "Gap Analysis", "Executive Report", "Diff Report"
    ])

    # Tab 1: LaTeX Preview + Downloads
    with tab_preview:
        latex_source = result.get("latex_source", "")
        pdf_path = result.get("pdf_path")
        tex_path = result.get("metadata", {}).get("tex_path", "")

        if not result.get("metadata", {}).get("pdflatex_available", True) and not pdf_path:
            st.markdown('<div class="warning-box">pdflatex not found in system PATH. Showing .tex file only. Install TeX Live or MiKTeX to enable PDF compilation.</div>', unsafe_allow_html=True)
            st.markdown("")

        col_dl1, col_dl2, col_dl3 = st.columns(3)

        with col_dl1:
            if latex_source:
                st.download_button(
                    label="Download .tex",
                    data=latex_source.encode("utf-8"),
                    file_name="optimized_resume.tex",
                    mime="text/x-tex",
                    use_container_width=True,
                )

        with col_dl2:
            if pdf_path and Path(pdf_path).exists():
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        label="Download PDF",
                        data=f.read(),
                        file_name="optimized_resume.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
            else:
                st.button("Download PDF", disabled=True, use_container_width=True, help="pdflatex not available")

        with col_dl3:
            report_md = result.get("executive_report", "")
            if report_md:
                st.download_button(
                    label="Download Report (.md)",
                    data=report_md.encode("utf-8"),
                    file_name="matching_report.md",
                    mime="text/markdown",
                    use_container_width=True,
                )

        if latex_source:
            st.code(latex_source, language="latex", line_numbers=True)
        else:
            st.info("No LaTeX source generated. Check for errors above.")

    # Tab 2: Keywords table
    with tab_keywords:
        job_req = result.get("job_requirements") or {}
        kw_added = result.get("keywords_added") or []
        gap = result.get("gap_analysis") or {}
        optimized = result.get("optimized_content") or {}

        # Build keyword dataframe
        full_text = " ".join([
            optimized.get("summary", ""),
            " ".join(optimized.get("skills", [])),
        ]).lower()

        rows = []
        for kw in job_req.get("required_skills", []):
            found = kw.lower() in full_text
            added = kw in kw_added
            rows.append({"Keyword": kw, "Category": "Required Skill", "In Resume": "Yes" if found else "No", "Added by AI": "Yes" if added else ""})
        for kw in job_req.get("nice_to_have_skills", []):
            found = kw.lower() in full_text
            rows.append({"Keyword": kw, "Category": "Nice to Have", "In Resume": "Yes" if found else "No", "Added by AI": ""})
        for kw in job_req.get("ats_keywords", []):
            if kw not in [r["Keyword"] for r in rows]:
                found = kw.lower() in full_text
                added = kw in kw_added
                rows.append({"Keyword": kw, "Category": "ATS Keyword", "In Resume": "Yes" if found else "No", "Added by AI": "Yes" if added else ""})

        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "In Resume": st.column_config.TextColumn("In Resume"),
                    "Added by AI": st.column_config.TextColumn("Added by AI"),
                },
            )

            # Download keywords CSV
            csv_path = PROJECT_ROOT / "outputs" / "ats_keywords.csv"
            if csv_path.exists():
                with open(csv_path, "rb") as f:
                    st.download_button(
                        "Download Keywords CSV",
                        data=f.read(),
                        file_name="ats_keywords.csv",
                        mime="text/csv",
                    )
        else:
            st.info("No keyword data available.")

    # Tab 3: Gap Analysis
    with tab_gap:
        gap = result.get("gap_analysis") or {}
        if gap:
            st.markdown(f"**Analysis Summary:** {gap.get('summary', '')}")
            st.markdown(f"**Severity Score:** {gap.get('severity_score', 0):.2f} (0=perfect, 1=mismatch)")
            st.markdown("")

            col_gap1, col_gap2 = st.columns(2)
            with col_gap1:
                missing = gap.get("missing_skills", [])
                if missing:
                    st.markdown("**Missing Required Skills**")
                    for s in missing:
                        st.markdown(f"- {s}")

            with col_gap2:
                matching = gap.get("matching_skills", [])
                if matching:
                    st.markdown("**Matching Skills**")
                    for s in matching:
                        st.markdown(f"- {s}")

            terms = gap.get("terms_to_rephrase", [])
            if terms:
                st.markdown("**Terms Rephrased for ATS**")
                terms_df = pd.DataFrame(terms)
                st.dataframe(terms_df, use_container_width=True, hide_index=True)

            undersold = gap.get("undersold_experiences", [])
            if undersold:
                st.markdown("**Undersold Experiences Enhanced**")
                for item in undersold:
                    with st.expander(f"Experience #{item.get('experience_index', 0)+1}"):
                        st.write(f"**Reason:** {item.get('reason', '')}")
                        st.write(f"**Suggestion:** {item.get('suggestion', '')}")
        else:
            st.info("No gap analysis data available.")

    # Tab 4: Executive Report
    with tab_report:
        report = result.get("executive_report", "")
        if report:
            st.markdown(report)
        else:
            st.info("No executive report generated.")

    # Tab 5: Diff Report
    with tab_diff:
        diff = result.get("diff_report", "")
        if diff:
            st.markdown(diff)
        else:
            st.info("No diff report generated.")


if __name__ == "__main__":
    main()
