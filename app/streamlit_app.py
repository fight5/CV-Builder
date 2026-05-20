"""Interface Streamlit — 2 boutons :
  1. Candidature automatique
  2. CV | Lettre de motivation  (CV.pdf + Lettre_Motivation.pdf)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import streamlit as st

# Path setup ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# Bridge Streamlit Cloud secrets -> environment variables.
try:
    for _k in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL"):
        if _k in st.secrets and not os.getenv(_k):
            os.environ[_k] = str(st.secrets[_k])
except (FileNotFoundError, Exception):
    pass

from modules import auto_apply_ui
from modules.optimum_pipeline import extract_cv_text, run_optimum_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="CV Builder — Candidature & Optimum",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
.main-title { font-size: 2.2rem; font-weight: 800; color: #2E86AB; margin-bottom: 0.2rem; }
.subtitle   { font-size: 1rem; color: #555; margin-bottom: 1.5rem; }
.error-box  { background:#f8d7da; border-left:4px solid #dc3545; padding:0.8rem; border-radius:4px; }
.warning-box{ background:#fff3cd; border-left:4px solid #ffc107; padding:0.8rem; border-radius:4px; }
.empty-state{ text-align:center; padding:3rem 1rem; color:#888; }
.empty-state .title{ font-size:1.2rem; color:#555; margin-bottom:0.4rem; }
.empty-state .hint { font-size:0.95rem; color:#999; }
</style>
""", unsafe_allow_html=True)


# ── Page : CV | Lettre de motivation ─────────────────────────────────────────
def _render_cv_letter():
    st.markdown('<div class="main-title">CV | Lettre de motivation</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Génération automatique d\'un CV ATS optimisé '
        '("optimum") et d\'une lettre de motivation personnalisée à partir '
        'd\'une offre d\'emploi.</div>',
        unsafe_allow_html=True,
    )

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key == "your_gemini_api_key_here":
        st.markdown(
            '<div class="error-box"><strong>Clé API Gemini manquante</strong> : '
            'définissez <code>GOOGLE_API_KEY</code> dans <code>.env</code>.</div>',
            unsafe_allow_html=True,
        )
        st.stop()

    col1, col2 = st.columns(2, gap="large")
    with col1:
        st.subheader("1. Offre d'emploi")
        job_offer = st.text_area(
            "Offre",
            height=320,
            placeholder="Collez ici l'offre d'emploi complète…",
            label_visibility="collapsed",
        )
    with col2:
        st.subheader("2. CV source")
        cv_file = st.file_uploader(
            "Votre CV (PDF ou DOCX)",
            type=["pdf", "docx", "doc"],
            label_visibility="collapsed",
            key="optimum_cv_upload",
        )
        cv_text = ""
        if cv_file:
            try:
                cv_text = extract_cv_text(cv_file)
                st.success(f"{len(cv_text)} caractères extraits de {cv_file.name}")
            except Exception as e:
                st.error(f"Échec d'extraction : {e}")

    st.markdown("")
    btn_col1, btn_col2, btn_col3 = st.columns([1, 2, 1])
    with btn_col2:
        run = st.button(
            "Générer CV et Lettre de motivation",
            type="primary",
            use_container_width=True,
            disabled=not (job_offer.strip() and cv_text.strip()),
        )

    st.markdown("---")

    if "optimum_result" not in st.session_state:
        st.session_state.optimum_result = None

    if run:
        with st.spinner("Génération en cours — CV optimisé puis lettre de motivation…"):
            try:
                st.session_state.optimum_result = run_optimum_pipeline(job_offer, cv_text)
            except Exception as e:
                st.error(f"Erreur du pipeline : {e}")
                logger.exception("optimum pipeline failed")
                st.session_state.optimum_result = None

    result = st.session_state.optimum_result
    if result is None:
        st.markdown("""
<div class="empty-state">
  <div class="title">Vos documents apparaîtront ici</div>
  <div class="hint">Renseignez l'offre et téléversez votre CV, puis cliquez sur
  <strong>Générer CV et Lettre de motivation</strong>.</div>
</div>
        """, unsafe_allow_html=True)
        return

    cv_bytes = result.get("cv_pdf_bytes")
    lm_bytes = result.get("letter_pdf_bytes")

    st.subheader("Vos documents sont prêts")
    dl1, dl2 = st.columns(2)
    with dl1:
        if cv_bytes:
            st.download_button(
                "Télécharger CV.pdf",
                data=cv_bytes,
                file_name="CV.pdf",
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            )
        else:
            st.button("CV.pdf — non disponible", disabled=True, use_container_width=True)
            for err in result.get("cv_errors", []):
                st.warning(err)
    with dl2:
        if lm_bytes:
            st.download_button(
                "Télécharger Lettre_Motivation.pdf",
                data=lm_bytes,
                file_name="Lettre_Motivation.pdf",
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            )
        else:
            st.button("Lettre_Motivation.pdf — non disponible",
                     disabled=True, use_container_width=True)
            for err in result.get("letter_errors", []):
                st.warning(err)

    st.markdown("---")
    tab_letter, tab_cv_tex, tab_letter_tex = st.tabs([
        "Lettre — texte", "Source LaTeX (CV)", "Source LaTeX (Lettre)"
    ])
    with tab_letter:
        st.text_area("Corps de la lettre",
                     value=result.get("letter_body", ""),
                     height=320, label_visibility="collapsed")
    with tab_cv_tex:
        st.code(result.get("cv_latex", ""), language="latex", line_numbers=True)
    with tab_letter_tex:
        st.code(result.get("letter_latex", ""), language="latex", line_numbers=True)


# ── Routeur principal — 2 boutons ────────────────────────────────────────────
def main():
    if "page" not in st.session_state:
        st.session_state.page = "cv_letter"

    nav_cols = st.columns([1, 1, 5])
    with nav_cols[0]:
        if st.button(
            "Candidature automatique",
            type="primary" if st.session_state.page == "auto" else "secondary",
            use_container_width=True,
        ):
            st.session_state.page = "auto"
            st.rerun()
    with nav_cols[1]:
        if st.button(
            "CV | Lettre de motivation",
            type="primary" if st.session_state.page == "cv_letter" else "secondary",
            use_container_width=True,
        ):
            st.session_state.page = "cv_letter"
            st.rerun()

    st.markdown("---")

    if st.session_state.page == "auto":
        auto_apply_ui.render()
    else:
        _render_cv_letter()


if __name__ == "__main__":
    main()
