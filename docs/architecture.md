# Architecture — AI ATS Resume Generator Agent

## Overview

The AI ATS Resume Generator is an 8-agent pipeline orchestrated via **LangGraph StateGraph**. It accepts a job description and an existing resume, then produces an ATS-optimized CV exported as PDF via LaTeX.

---

## Pipeline Diagram

```
Input (Job Description + Resume + Preferences)
        │
        ▼
┌─────────────────┐
│  JobParserAgent │  ── Extracts: skills, keywords, experience_level, tech_stack
└────────┬────────┘
         │
         ▼
┌──────────────────────┐
│  ResumeParserAgent   │  ── Structures: experiences, skills, education, projects
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  GapAnalysisAgent    │  ── Computes: missing_skills, terms_to_rephrase, severity
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  ATSOptimizerAgent   │  ── Rewrites sections with ATS keywords + action verbs
└──────────┬───────────┘
           │
    ┌──────┴──────┐
    │  (if error) │
    ▼             ▼
┌──────────────────┐  ┌──────────────────────┐
│ QualityControl   │  │ LaTeXTemplateAgent   │  ── Fills .tex template
└──────────────────┘  └──────────┬───────────┘
                                 │
                                 ▼
                      ┌──────────────────────┐
                      │  PDFCompilerAgent    │  ── pdflatex subprocess (×2)
                      └──────────┬───────────┘
                                 │
                                 ▼
                      ┌──────────────────────┐
                      │ QualityControlAgent  │  ── Matching score, keyword coverage
                      └──────────┬───────────┘
                                 │
                                 ▼
                      ┌──────────────────────┐
                      │    ReportAgent       │  ── Executive report, diff, CSV
                      └──────────────────────┘
                                 │
                                 ▼
                           Final ATSState
```

---

## State Schema (core/state.py)

The `ATSState` TypedDict flows through every node. Key fields:

| Field | Type | Populated By |
|---|---|---|
| `job_description_text` | `str` | User input |
| `resume_text` | `str` | User input (PDF/DOCX extracted) |
| `user_preferences` | `dict` | Streamlit sidebar |
| `job_requirements` | `dict` | JobParserAgent |
| `resume_structured` | `dict` | ResumeParserAgent |
| `gap_analysis` | `dict` | GapAnalysisAgent |
| `optimized_content` | `dict` | ATSOptimizerAgent |
| `latex_source` | `str` | LaTeXTemplateAgent |
| `pdf_path` | `str` | PDFCompilerAgent |
| `matching_score` | `float` | QualityControlAgent |
| `keyword_coverage` | `float` | QualityControlAgent |
| `keywords_added` | `list` | ATSOptimizerAgent |
| `executive_report` | `str` | ReportAgent |
| `diff_report` | `str` | ReportAgent |
| `errors` | `list[str]` | Any agent |
| `metadata` | `dict` | Any agent |

---

## Agent Descriptions

### 1. JobParserAgent
**Input:** `job_description_text`  
**Output:** `job_requirements`  
Uses GPT-4o with a structured JSON prompt to extract required/nice-to-have skills, ATS keywords, experience level, responsibilities, tech stack, and company values. Falls back to regex-based extraction if the LLM is unavailable.

### 2. ResumeParserAgent
**Input:** `resume_text`  
**Output:** `resume_structured`  
Converts raw resume text (from PDF/DOCX extraction) into a structured JSON with sections: `personal_info`, `summary`, `experiences`, `skills`, `education`, `certifications`, `projects`, `languages`. Falls back to minimal regex parsing.

### 3. GapAnalysisAgent
**Input:** `job_requirements`, `resume_structured`  
**Output:** `gap_analysis`  
Computes `missing_skills`, `matching_skills`, `undersold_experiences` (roles that relate to requirements but are poorly described), `terms_to_rephrase` (generic → ATS-specific), `keyword_gaps`, and a `severity_score`. Has a local rule-based fallback.

### 4. ATSOptimizerAgent
**Input:** `resume_structured`, `gap_analysis`, `job_requirements`, `user_preferences`  
**Output:** `optimized_content`, `keywords_added`  
Rewrites every CV section using GPT-4o: integrates ATS keywords naturally, adds action verbs + metrics, rephrases undersold experiences. Output mirrors `resume_structured` structure. Preserves `personal_info` unchanged.

### 5. LaTeXTemplateAgent
**Input:** `optimized_content`, `user_preferences`, `photo_path`  
**Output:** `latex_source`  
Reads the chosen `.tex` template from `templates/`, injects all content sections via placeholder replacement (`{{CANDIDATE_NAME}}`, etc.), applies color customization and optional photo. No LLM required.

### 6. PDFCompilerAgent
**Input:** `latex_source`  
**Output:** `pdf_path`  
Writes the `.tex` file to `outputs/`, then calls `pdflatex -interaction=nonstopmode` twice (ensures proper page counts). Gracefully handles missing `pdflatex` by returning `None` for `pdf_path` while still providing the `.tex` file.

### 7. QualityControlAgent
**Input:** `optimized_content`, `job_requirements`, `keywords_added`  
**Output:** `matching_score`, `keyword_coverage`  
Computes `matching_score` = (required skills found / total required) × 100. Computes `keyword_coverage` using `compute_keyword_density`. Also runs ATS compliance checks: character encoding, date formats, content length, empty sections.

### 8. ReportAgent
**Input:** all state fields  
**Output:** `executive_report`, `diff_report`; also saves files  
Generates a markdown executive report with scores, rephrased terms, and recommendations. Generates a before/after diff for each section. Saves `outputs/matching_report.md`, `outputs/diff_report.md`, and `outputs/ats_keywords.csv`.

---

## LLM Configuration

All agents that use GPT-4o receive the same `ChatOpenAI` instance (temperature=0.3, max_tokens=4096), created by the orchestrator from `.env` settings. Every LLM call is wrapped in `_safe_llm_invoke` which catches exceptions and invokes a fallback.

---

## Templates

Three LaTeX templates are provided in `templates/`:

| Template | Style | Use Case |
|---|---|---|
| `modern.tex` | Clean, colored accent, icons | Tech / Startup roles |
| `executive.tex` | Formal, centered header, italic | Senior / Executive roles |
| `classic.tex` | Minimal, left-aligned | Conservative industries |

All templates use the same set of `{{PLACEHOLDER}}` strings and the same custom LaTeX commands (`\experienceentry`, `\educationentry`, `\projectentry`). The `\definecolor{maincolor}` line is replaced at runtime with the user's chosen color.

---

## File Outputs

```
outputs/
├── optimized_resume.tex   — LaTeX source
├── optimized_resume.pdf   — Compiled PDF (if pdflatex available)
├── matching_report.md     — Executive optimization report
├── diff_report.md         — Before/after section diffs
└── ats_keywords.csv       — Keyword coverage table
```

---

## Error Handling

- Every agent appends errors to `state["errors"]` without raising exceptions, ensuring the pipeline completes even if individual nodes fail.
- The orchestrator catches fatal pipeline errors.
- The Streamlit app shows warnings for any non-empty `errors` list.
- All LLM calls have local fallbacks.

---

## Technology Stack

| Component | Library |
|---|---|
| Orchestration | LangGraph (StateGraph) |
| LLM | OpenAI GPT-4o via langchain-openai |
| PDF Parsing | PyMuPDF (fitz) |
| DOCX Parsing | python-docx |
| LaTeX Compilation | subprocess + pdflatex |
| UI | Streamlit |
| Config | python-dotenv |
| Testing | unittest + unittest.mock |
