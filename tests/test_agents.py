"""Unit tests for agents and core tools."""

import sys
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── Tool Tests ────────────────────────────────────────────────────────────────
class TestLatexEscape(unittest.TestCase):
    """Test the latex_escape utility function."""

    def setUp(self):
        from core.tools import latex_escape
        self.latex_escape = latex_escape

    def test_ampersand(self):
        self.assertEqual(self.latex_escape("R&D"), r"R\&D")

    def test_percent(self):
        self.assertEqual(self.latex_escape("50%"), r"50\%")

    def test_dollar(self):
        self.assertEqual(self.latex_escape("$100k"), r"\$100k")

    def test_hash(self):
        self.assertEqual(self.latex_escape("#1 ranked"), r"\#1 ranked")

    def test_underscore(self):
        self.assertEqual(self.latex_escape("api_key"), r"api\_key")

    def test_curly_braces(self):
        result = self.latex_escape("{test}")
        self.assertIn(r"\{", result)
        self.assertIn(r"\}", result)

    def test_no_special_chars(self):
        text = "Senior Data Scientist at Acme Corp"
        self.assertEqual(self.latex_escape(text), text)

    def test_empty_string(self):
        self.assertEqual(self.latex_escape(""), "")

    def test_backslash(self):
        result = self.latex_escape("a\\b")
        self.assertIn("textbackslash", result)

    def test_combined(self):
        text = "5% of $1000 & R#D"
        result = self.latex_escape(text)
        self.assertIn(r"\%", result)
        self.assertIn(r"\$", result)
        self.assertIn(r"\&", result)
        self.assertIn(r"\#", result)


class TestComputeKeywordDensity(unittest.TestCase):
    """Test the compute_keyword_density utility function."""

    def setUp(self):
        from core.tools import compute_keyword_density
        self.compute_keyword_density = compute_keyword_density

    def test_full_match(self):
        text = "Python machine learning data science SQL"
        keywords = ["python", "machine learning", "sql"]
        result = self.compute_keyword_density(text, keywords)
        self.assertEqual(result, 1.0)

    def test_no_match(self):
        text = "Sales and marketing strategy"
        keywords = ["Python", "TensorFlow", "Kubernetes"]
        result = self.compute_keyword_density(text, keywords)
        self.assertEqual(result, 0.0)

    def test_partial_match(self):
        text = "Python developer with SQL experience"
        keywords = ["Python", "Java", "SQL", "Golang"]
        result = self.compute_keyword_density(text, keywords)
        self.assertEqual(result, 0.5)

    def test_empty_keywords(self):
        result = self.compute_keyword_density("some text", [])
        self.assertEqual(result, 0.0)

    def test_empty_text(self):
        result = self.compute_keyword_density("", ["Python"])
        self.assertEqual(result, 0.0)

    def test_case_insensitive(self):
        text = "PYTHON and TENSORFLOW"
        keywords = ["python", "tensorflow"]
        result = self.compute_keyword_density(text, keywords)
        self.assertEqual(result, 1.0)

    def test_returns_float(self):
        result = self.compute_keyword_density("Python", ["Python"])
        self.assertIsInstance(result, float)


class TestFormatExperienceLatex(unittest.TestCase):
    """Test the format_experience_latex utility."""

    def setUp(self):
        from core.tools import format_experience_latex
        self.format_experience_latex = format_experience_latex

    def test_basic_entry(self):
        exp = {
            "title": "Data Scientist",
            "company": "Acme Corp",
            "dates": "Jan 2022 - Present",
            "location": "Paris",
            "description": "Built ML models",
            "achievements": ["Reduced latency by 30%", "Deployed 5 models"],
        }
        result = self.format_experience_latex(exp)
        self.assertIn("Data Scientist", result)
        self.assertIn("Acme Corp", result)
        self.assertIn("itemize", result)
        self.assertIn(r"\item", result)

    def test_empty_achievements(self):
        exp = {
            "title": "Analyst",
            "company": "Corp",
            "dates": "2020",
            "location": "",
            "description": "Analyzed data",
            "achievements": [],
        }
        result = self.format_experience_latex(exp)
        self.assertIn("Analyst", result)
        self.assertIn("Analyzed data", result)

    def test_special_chars_escaped(self):
        exp = {
            "title": "R&D Scientist",
            "company": "BioTech & Co",
            "dates": "2021",
            "location": "Lyon",
            "description": "",
            "achievements": [],
        }
        result = self.format_experience_latex(exp)
        # Special chars should be escaped
        self.assertNotIn("R&D", result)  # Should be escaped to R\&D
        self.assertIn(r"\&", result)


# ── JobParserAgent Tests ──────────────────────────────────────────────────────
class TestJobParserAgent(unittest.TestCase):
    """Test JobParserAgent with a mock LLM."""

    def _make_mock_llm(self, response_dict: dict):
        """Create a mock LLM that returns a given dict as JSON content."""
        import json
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps(response_dict)
        mock_llm.invoke.return_value = mock_response
        return mock_llm

    def test_successful_parse(self):
        from agents.job_parser_agent import JobParserAgent
        expected = {
            "required_skills": ["Python", "SQL", "Machine Learning"],
            "nice_to_have_skills": ["Spark"],
            "ats_keywords": ["Python", "SQL", "MLOps"],
            "experience_level": "senior",
            "responsibilities": ["Build models", "Deploy pipelines"],
            "company_values": ["Innovation"],
            "tech_stack": ["Python", "Kubernetes"],
            "job_title": "Senior Data Scientist",
            "industry": "FinTech",
        }
        mock_llm = self._make_mock_llm(expected)
        agent = JobParserAgent(llm=mock_llm)
        state = {
            "job_description_text": "We need a Senior Data Scientist with Python and SQL skills.",
            "errors": [],
            "metadata": {},
        }
        result = agent.run(state)
        self.assertIsNotNone(result.get("job_requirements"))
        self.assertEqual(result["job_requirements"]["experience_level"], "senior")
        self.assertIn("Python", result["job_requirements"]["required_skills"])

    def test_empty_job_description(self):
        from agents.job_parser_agent import JobParserAgent
        agent = JobParserAgent(llm=None)
        state = {"job_description_text": "", "errors": [], "metadata": {}}
        result = agent.run(state)
        self.assertTrue(len(result["errors"]) > 0)
        self.assertIn("empty", result["errors"][0].lower())

    def test_regex_fallback_when_llm_none(self):
        from agents.job_parser_agent import JobParserAgent
        agent = JobParserAgent(llm=None)
        state = {
            "job_description_text": (
                "Senior Python Developer needed. "
                "Must know Docker, Kubernetes, AWS. "
                "5+ years of experience required."
            ),
            "errors": [],
            "metadata": {},
        }
        result = agent.run(state)
        req = result.get("job_requirements")
        self.assertIsNotNone(req)
        self.assertEqual(req.get("experience_level"), "senior")

    def test_llm_json_with_code_fences(self):
        """LLM sometimes wraps JSON in markdown code fences; agent should handle this."""
        import json
        from agents.job_parser_agent import JobParserAgent
        data = {
            "required_skills": ["Java"], "nice_to_have_skills": [], "ats_keywords": ["Java"],
            "experience_level": "mid", "responsibilities": [], "company_values": [],
            "tech_stack": ["Java"], "job_title": "Java Developer", "industry": "Software",
        }
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = f"```json\n{json.dumps(data)}\n```"
        mock_llm.invoke.return_value = mock_response
        agent = JobParserAgent(llm=mock_llm)
        state = {"job_description_text": "Java developer needed", "errors": [], "metadata": {}}
        result = agent.run(state)
        self.assertEqual(result["job_requirements"]["job_title"], "Java Developer")


# ── GapAnalysisAgent Tests ────────────────────────────────────────────────────
class TestGapAnalysisAgent(unittest.TestCase):
    """Test GapAnalysisAgent logic with preset inputs (no LLM)."""

    def _make_preset_state(self):
        return {
            "job_requirements": {
                "required_skills": ["Python", "Docker", "Kubernetes", "TensorFlow"],
                "nice_to_have_skills": ["Spark"],
                "ats_keywords": ["MLOps", "Python", "model deployment"],
                "experience_level": "senior",
                "responsibilities": [],
                "company_values": [],
                "tech_stack": ["Python", "Docker"],
                "job_title": "ML Engineer",
                "industry": "Tech",
            },
            "resume_structured": {
                "personal_info": {"name": "John Doe", "email": "john@example.com"},
                "summary": "Python developer with machine learning experience",
                "experiences": [
                    {
                        "title": "Data Scientist",
                        "company": "TechCorp",
                        "dates": "2021-Present",
                        "location": "Paris",
                        "description": "Built ML pipelines with Python and TensorFlow",
                        "achievements": ["Deployed models to production"],
                    }
                ],
                "skills": ["Python", "TensorFlow", "scikit-learn", "SQL"],
                "education": [],
                "certifications": [],
                "projects": [],
                "languages": [],
            },
            "errors": [],
            "metadata": {},
        }

    def test_local_fallback_identifies_missing_skills(self):
        """Without LLM, the rule-based fallback should find Docker/Kubernetes as missing."""
        from agents.gap_analysis_agent import GapAnalysisAgent
        agent = GapAnalysisAgent(llm=None)
        state = self._make_preset_state()
        result = agent.run(state)
        gap = result.get("gap_analysis")
        self.assertIsNotNone(gap)
        # Python and TensorFlow are in skills, Docker/Kubernetes are not
        matching_lower = [s.lower() for s in gap.get("matching_skills", [])]
        self.assertIn("python", matching_lower)
        missing_lower = [s.lower() for s in gap.get("missing_skills", [])]
        self.assertIn("docker", missing_lower)
        self.assertIn("kubernetes", missing_lower)

    def test_severity_score_range(self):
        from agents.gap_analysis_agent import GapAnalysisAgent
        agent = GapAnalysisAgent(llm=None)
        state = self._make_preset_state()
        result = agent.run(state)
        severity = result["gap_analysis"].get("severity_score", 0)
        self.assertGreaterEqual(severity, 0.0)
        self.assertLessEqual(severity, 1.0)

    def test_missing_job_requirements_returns_error(self):
        from agents.gap_analysis_agent import GapAnalysisAgent
        agent = GapAnalysisAgent(llm=None)
        state = {"job_requirements": None, "resume_structured": {}, "errors": [], "metadata": {}}
        result = agent.run(state)
        self.assertTrue(len(result["errors"]) > 0)

    def test_missing_resume_returns_error(self):
        from agents.gap_analysis_agent import GapAnalysisAgent
        agent = GapAnalysisAgent(llm=None)
        state = {"job_requirements": {"required_skills": ["Python"]}, "resume_structured": None, "errors": [], "metadata": {}}
        result = agent.run(state)
        self.assertTrue(len(result["errors"]) > 0)


# ── QualityControlAgent Tests ────────────────────────────────────────────────
class TestQualityControlAgent(unittest.TestCase):
    """Test QualityControlAgent scoring logic."""

    def _make_state(self, skills_in_resume: list, required_skills: list, ats_keywords: list) -> dict:
        return {
            "optimized_content": {
                "personal_info": {"name": "Jane", "email": "jane@test.com"},
                "summary": "Experienced software engineer with " + " ".join(skills_in_resume),
                "experiences": [
                    {
                        "title": "Engineer",
                        "company": "Corp",
                        "dates": "2020-Present",
                        "location": "",
                        "description": "Worked with " + " ".join(skills_in_resume[:3]),
                        "achievements": ["Improved performance by 20%"],
                    }
                ],
                "skills": skills_in_resume,
                "education": [],
                "certifications": [],
                "projects": [],
                "languages": [],
            },
            "job_requirements": {
                "required_skills": required_skills,
                "ats_keywords": ats_keywords,
            },
            "keywords_added": [],
            "errors": [],
            "metadata": {},
        }

    def test_perfect_match_score(self):
        from agents.quality_control_agent import QualityControlAgent
        agent = QualityControlAgent(llm=None)
        skills = ["Python", "Docker", "SQL"]
        state = self._make_state(skills, skills, skills)
        result = agent.run(state)
        self.assertGreater(result["matching_score"], 90)

    def test_zero_match_score(self):
        from agents.quality_control_agent import QualityControlAgent
        agent = QualityControlAgent(llm=None)
        state = self._make_state(
            ["Excel", "PowerPoint"],
            ["Python", "Docker", "Kubernetes", "TensorFlow"],
            [],
        )
        result = agent.run(state)
        self.assertLess(result["matching_score"], 10)

    def test_keyword_coverage_partial(self):
        from agents.quality_control_agent import QualityControlAgent
        agent = QualityControlAgent(llm=None)
        state = self._make_state(
            ["Python", "SQL"],
            ["Python"],
            ["Python", "SQL", "Kubernetes", "Docker"],
        )
        result = agent.run(state)
        self.assertGreater(result["keyword_coverage"], 0)
        self.assertLess(result["keyword_coverage"], 100)

    def test_scores_are_floats(self):
        from agents.quality_control_agent import QualityControlAgent
        agent = QualityControlAgent(llm=None)
        state = self._make_state(["Python"], ["Python"], ["Python"])
        result = agent.run(state)
        self.assertIsInstance(result["matching_score"], float)
        self.assertIsInstance(result["keyword_coverage"], float)


if __name__ == "__main__":
    unittest.main(verbosity=2)
