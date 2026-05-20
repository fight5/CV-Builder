"""LangGraph StateGraph orchestrator for the ATS Resume Generator pipeline."""

import os
import logging
from typing import Optional

from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from .state import ATSState
from agents.job_parser_agent import JobParserAgent
from agents.resume_parser_agent import ResumeParserAgent
from agents.gap_analysis_agent import GapAnalysisAgent
from agents.ats_optimizer_agent import ATSOptimizerAgent
from agents.latex_template_agent import LaTeXTemplateAgent
from agents.pdf_compiler_agent import PDFCompilerAgent
from agents.quality_control_agent import QualityControlAgent
from agents.report_agent import ReportAgent

load_dotenv()
logger = logging.getLogger(__name__)


def _build_llm() -> Optional[BaseChatModel]:
    """Instantiate the Gemini LLM from environment variables."""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", "")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    if not api_key or api_key == "your_gemini_api_key_here":
        logger.warning("GOOGLE_API_KEY/GEMINI_API_KEY not set. Agents will use fallback logic.")
        return None
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        temperature=0.3,
        max_output_tokens=8192,
    )


def build_graph() -> StateGraph:
    """Construct and compile the LangGraph pipeline."""
    llm = _build_llm()

    job_parser = JobParserAgent(llm=llm)
    resume_parser = ResumeParserAgent(llm=llm)
    gap_analyzer = GapAnalysisAgent(llm=llm)
    ats_optimizer = ATSOptimizerAgent(llm=llm)
    latex_agent = LaTeXTemplateAgent(llm=None)  # No LLM needed for template filling
    pdf_compiler = PDFCompilerAgent(llm=None)
    quality_checker = QualityControlAgent(llm=None)
    reporter = ReportAgent(llm=None)

    def node_parse_job(state: ATSState) -> ATSState:
        logger.info("Node: parse_job")
        return job_parser.run(state)

    def node_parse_resume(state: ATSState) -> ATSState:
        logger.info("Node: parse_resume")
        return resume_parser.run(state)

    def node_analyze_gaps(state: ATSState) -> ATSState:
        logger.info("Node: analyze_gaps")
        return gap_analyzer.run(state)

    def node_optimize_ats(state: ATSState) -> ATSState:
        logger.info("Node: optimize_ats")
        return ats_optimizer.run(state)

    def node_generate_latex(state: ATSState) -> ATSState:
        logger.info("Node: generate_latex")
        return latex_agent.run(state)

    def node_compile_pdf(state: ATSState) -> ATSState:
        logger.info("Node: compile_pdf")
        return pdf_compiler.run(state)

    def node_quality_check(state: ATSState) -> ATSState:
        logger.info("Node: quality_check")
        return quality_checker.run(state)

    def node_generate_report(state: ATSState) -> ATSState:
        logger.info("Node: generate_report")
        return reporter.run(state)

    def should_continue_after_optimize(state: ATSState) -> str:
        """Skip LaTeX/PDF if optimized_content is missing (critical error)."""
        if state.get("optimized_content"):
            return "generate_latex"
        logger.warning("optimized_content missing, jumping to quality_check")
        return "quality_check"

    graph = StateGraph(ATSState)

    graph.add_node("parse_job", node_parse_job)
    graph.add_node("parse_resume", node_parse_resume)
    graph.add_node("analyze_gaps", node_analyze_gaps)
    graph.add_node("optimize_ats", node_optimize_ats)
    graph.add_node("generate_latex", node_generate_latex)
    graph.add_node("compile_pdf", node_compile_pdf)
    graph.add_node("quality_check", node_quality_check)
    graph.add_node("generate_report", node_generate_report)

    graph.set_entry_point("parse_job")
    graph.add_edge("parse_job", "parse_resume")
    graph.add_edge("parse_resume", "analyze_gaps")
    graph.add_edge("analyze_gaps", "optimize_ats")
    graph.add_conditional_edges(
        "optimize_ats",
        should_continue_after_optimize,
        {
            "generate_latex": "generate_latex",
            "quality_check": "quality_check",
        },
    )
    graph.add_edge("generate_latex", "compile_pdf")
    graph.add_edge("compile_pdf", "quality_check")
    graph.add_edge("quality_check", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()


def run_pipeline(
    job_text: str,
    resume_text: str,
    preferences: Optional[dict] = None,
    photo_path: Optional[str] = None,
) -> ATSState:
    """Execute the full ATS resume generation pipeline and return the final state."""
    if preferences is None:
        preferences = {}

    # Apply defaults for missing preferences
    preferences.setdefault("color", "#2E86AB")
    preferences.setdefault("template", "modern")
    preferences.setdefault("language", "English")
    preferences.setdefault("conciseness", "balanced")
    preferences.setdefault("include_photo", bool(photo_path))

    initial_state: ATSState = {
        "job_description_text": job_text,
        "resume_text": resume_text,
        "user_preferences": preferences,
        "photo_path": photo_path,
        "job_requirements": None,
        "resume_structured": None,
        "gap_analysis": None,
        "optimized_content": None,
        "latex_source": None,
        "pdf_path": None,
        "matching_score": None,
        "keyword_coverage": None,
        "keywords_added": [],
        "executive_report": None,
        "diff_report": None,
        "errors": [],
        "metadata": {},
    }

    app = build_graph()
    logger.info("Starting ATS resume generation pipeline")

    try:
        final_state = app.invoke(initial_state)
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}", exc_info=True)
        initial_state["errors"].append(f"Pipeline fatal error: {e}")
        return initial_state

    if final_state.get("errors"):
        logger.warning(f"Pipeline completed with {len(final_state['errors'])} error(s): {final_state['errors']}")
    else:
        logger.info("Pipeline completed successfully")

    return final_state
