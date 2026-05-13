"""Agent that compiles LaTeX source into a PDF using pdflatex."""

import os
import subprocess
import shutil
import logging
from pathlib import Path

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "outputs"


class PDFCompilerAgent(BaseAgent):
    """Compiles LaTeX source to PDF via pdflatex subprocess."""

    name = "pdf_compiler_agent"
    description = "Compiles LaTeX source to PDF using pdflatex"

    def run(self, state: dict) -> dict:
        """Write .tex file and compile to PDF; populate state['pdf_path']."""
        self._log("Starting PDF compilation")

        latex_source = state.get("latex_source")
        if not latex_source:
            return self._add_error(state, "latex_source is missing.")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        tex_path = OUTPUT_DIR / "optimized_resume.tex"
        pdf_path = OUTPUT_DIR / "optimized_resume.pdf"

        # Write .tex file
        try:
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(latex_source)
            self._log(f"Wrote LaTeX source to {tex_path}")
        except Exception as e:
            return self._add_error(state, f"Failed to write .tex file: {e}")

        # Check if pdflatex is available
        pdflatex_path = shutil.which("pdflatex")
        if pdflatex_path is None:
            self._log("pdflatex not found in PATH. Returning .tex file only.", "warning")
            state["pdf_path"] = None
            state["metadata"] = state.get("metadata", {})
            state["metadata"]["tex_path"] = str(tex_path)
            state["metadata"]["pdflatex_available"] = False
            return state

        # Compile twice (needed for proper cross-references / page counts)
        compile_cmd = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-output-directory", str(OUTPUT_DIR),
            str(tex_path),
        ]

        for run_number in range(1, 3):
            self._log(f"pdflatex run {run_number}/2")
            try:
                result = subprocess.run(
                    compile_cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=str(OUTPUT_DIR),
                )
                if result.returncode != 0:
                    # Log last 30 lines of stdout for diagnostics
                    stdout_tail = "\n".join(result.stdout.splitlines()[-30:])
                    self._log(f"pdflatex run {run_number} exited with code {result.returncode}:\n{stdout_tail}", "warning")
                    # On first run, continue anyway (common with missing aux files)
                    if run_number == 2:
                        # If PDF was still produced despite errors, use it
                        if not pdf_path.exists():
                            self._log("PDF not produced, returning .tex only", "warning")
                            state["pdf_path"] = None
                            state["metadata"] = state.get("metadata", {})
                            state["metadata"]["tex_path"] = str(tex_path)
                            state["metadata"]["compile_error"] = stdout_tail
                            return state
            except subprocess.TimeoutExpired:
                return self._add_error(state, "pdflatex timed out after 120 seconds.")
            except Exception as e:
                return self._add_error(state, f"pdflatex subprocess error: {e}")

        if pdf_path.exists():
            state["pdf_path"] = str(pdf_path)
            self._log(f"PDF compiled successfully: {pdf_path}")
        else:
            self._log("PDF file not found after compilation; check LaTeX logs", "warning")
            state["pdf_path"] = None

        state["metadata"] = state.get("metadata", {})
        state["metadata"]["tex_path"] = str(tex_path)
        state["metadata"]["pdflatex_available"] = True

        return state
