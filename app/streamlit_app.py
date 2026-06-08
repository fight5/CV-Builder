"""Interface Streamlit — 2 boutons :
  1. Candidature automatique
  2. CV | Lettre de motivation  (CV.pdf + Lettre_Motivation.pdf)

  v2.1 — Auto Apply E2E intégré (CV source → génération → candidature automatique)
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

try:
    for _k in (
        "GOOGLE_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL",
        "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "LLM_PROVIDER",
    ):
        if _k in st.secrets and not os.getenv(_k):
            os.environ[_k] = str(st.secrets[_k])
except (FileNotFoundError, Exception):
    pass

import importlib
from modules import auto_apply_ui
importlib.reload(auto_apply_ui)  # force reload after hot-deploy
from modules.optimum_pipeline import (
    CVPreferences,
    extract_cv_text,
    run_optimum_pipeline,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="CV Builder",
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
        'et d\'une lettre de motivation personnalisée à partir d\'une '
        'offre d\'emploi. Le candidat assume les compétences déclarées.</div>',
        unsafe_allow_html=True,
    )

    ds_key = os.getenv("DEEPSEEK_API_KEY", "")
    gm_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", "")
    has_ds = bool(ds_key) and ds_key != "your_deepseek_api_key_here"
    has_gm = bool(gm_key) and gm_key != "your_gemini_api_key_here"
    if not (has_ds or has_gm):
        st.markdown(
            '<div class="error-box"><strong>Aucune clé LLM configurée</strong> : '
            'renseignez <code>DEEPSEEK_API_KEY</code> ou '
            '<code>GOOGLE_API_KEY</code> dans <code>.env</code>.</div>',
            unsafe_allow_html=True,
        )
        st.stop()

    # ── Étape 1 — Inputs principaux ──────────────────────────────────────────
    col1, col2 = st.columns(2, gap="large")
    with col1:
        st.subheader("1. Offre d'emploi")
        job_offer = st.text_area(
            "Offre",
            height=320,
            placeholder="Collez ici l'offre d'emploi complète…",
            label_visibility="collapsed",
        )
        company = st.text_input(
            "Entreprise (facultatif, auto-détectée sinon)",
            value="",
            placeholder="ex. VINCI Airports",
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

    # ── Étape 3 — Préférences ────────────────────────────────────────────────
    st.subheader("3. Personnalisation")
    pcol1, pcol2, pcol3, pcol4 = st.columns(4)

    template_labels = {"optimum": "Optimum (vôtre)", "minimal": "Minimal (ATS pur)"}
    language_labels = {"Français": "Français", "English": "Anglais"}

    with pcol1:
        template = st.selectbox(
            "Type de CV",
            options=["optimum", "minimal"],
            format_func=lambda x: template_labels[x],
        )
    with pcol2:
        language = st.selectbox(
            "Langue",
            options=["Français", "English"],
            format_func=lambda x: language_labels[x],
        )
    with pcol3:
        accent_hex = st.color_picker("Couleur d'accent", value="#006699")
    with pcol4:
        leftbg_hex = st.color_picker(
            "Couleur bandeau",
            value="#172E4A",
            disabled=(template != "optimum"),
            help="Utilisé uniquement pour le template Optimum.",
        )

    include_photo = st.toggle("Inclure une photo", value=False)
    photo_path: str | None = None
    if include_photo:
        photo_file = st.file_uploader(
            "Téléverser une photo (JPG/PNG)",
            type=["jpg", "jpeg", "png"],
            key="optimum_photo_upload",
        )
        if photo_file:
            suffix = Path(photo_file.name).suffix.lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(photo_file.read())
                photo_path = tmp.name
            st.image(photo_file, width=120, caption="Aperçu")

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
        prefs = CVPreferences(
            template=template,
            language=language,
            accent_hex=accent_hex,
            leftbg_hex=leftbg_hex,
            include_photo=include_photo,
            photo_path=photo_path,
            aggressive=True,
            company=company.strip(),
        )
        with st.spinner("Génération en cours, CV optimisé puis lettre de motivation…"):
            try:
                st.session_state.optimum_result = run_optimum_pipeline(
                    job_offer, cv_text, prefs
                )
            except Exception as e:
                st.error(f"Erreur du pipeline : {e}")
                logger.exception("optimum pipeline failed")
                st.session_state.optimum_result = None

    result = st.session_state.optimum_result
    if result is None:
        st.markdown("""
<div class="empty-state">
  <div class="title">Vos documents apparaîtront ici</div>
  <div class="hint">Renseignez l'offre, le CV et les préférences, puis cliquez sur
  <strong>Générer CV et Lettre de motivation</strong>.</div>
</div>
        """, unsafe_allow_html=True)
        return

    cv_bytes = result.get("cv_pdf_bytes")
    lm_bytes = result.get("letter_pdf_bytes")
    cv_name = result.get("cv_filename", "CV.pdf")
    lm_name = result.get("letter_filename", "Lettre_Motivation.pdf")

    st.subheader("Vos documents sont prêts")
    st.caption(
        f"Candidat : **{result.get('candidate_name','?')}** · "
        f"Poste : **{result.get('job_title','?')}** · "
        f"Entreprise : **{result.get('company','?')}**"
    )

    dl1, dl2 = st.columns(2)
    with dl1:
        if cv_bytes:
            st.download_button(
                f"Télécharger {cv_name}",
                data=cv_bytes,
                file_name=cv_name,
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            )
        else:
            st.button("CV non disponible", disabled=True, use_container_width=True)
            for err in result.get("cv_errors", []):
                st.warning(err)
    with dl2:
        if lm_bytes:
            st.download_button(
                f"Télécharger {lm_name}",
                data=lm_bytes,
                file_name=lm_name,
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            )
        else:
            st.button("Lettre non disponible", disabled=True, use_container_width=True)
            for err in result.get("letter_errors", []):
                st.warning(err)

    st.markdown("---")
    st.subheader("Lettre (texte)")
    st.text_area(
        "Corps de la lettre",
        value=result.get("letter_body", ""),
        height=320,
        label_visibility="collapsed",
    )


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
