"""Interface Streamlit pour l'agent Générateur de CV ATS par IA."""

import os
import sys
import tempfile
import logging
from pathlib import Path

import streamlit as st
import pandas as pd

# S'assurer que la racine du projet est dans le path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# Bridge Streamlit Cloud secrets → environment variables so the orchestrator
# (which uses os.getenv) works both locally (.env) and on cloud (st.secrets).
try:
    for _k in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL"):
        if _k in st.secrets and not os.getenv(_k):
            os.environ[_k] = str(st.secrets[_k])
except (FileNotFoundError, Exception):
    pass  # No secrets.toml — running locally with .env

from core.tools import extract_text_from_pdf, extract_text_from_docx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Configuration de la page ──────────────────────────────────────────────────
st.set_page_config(
    page_title="Générateur de CV ATS par IA",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS personnalisé ──────────────────────────────────────────────────────────
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
.warning-box {
    background: #fff3cd;
    border-left: 4px solid #ffc107;
    padding: 0.8rem;
    border-radius: 4px;
}
.error-box {
    background: #f8d7da;
    border-left: 4px solid #dc3545;
    padding: 0.8rem;
    border-radius: 4px;
}
.empty-state {
    text-align: center;
    padding: 4rem 1rem;
    color: #888;
}
.empty-state .icon {
    font-size: 3rem;
    margin-bottom: 1rem;
}
.empty-state .title {
    font-size: 1.2rem;
    color: #555;
    margin-bottom: 0.5rem;
}
.empty-state .hint {
    font-size: 0.95rem;
    color: #999;
}
</style>
""", unsafe_allow_html=True)


def _extract_resume_text(uploaded_file) -> str:
    """Sauvegarde le fichier téléversé en local temporaire et extrait le texte."""
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
    """Extrait le texte d'une offre d'emploi depuis un PDF ou un fichier texte."""
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
    """Importe et exécute le pipeline d'orchestration."""
    try:
        from core.orchestrator import run_pipeline
        return run_pipeline(job_text, resume_text, preferences, photo_path)
    except ImportError as e:
        st.error(f"Erreur d'importation : {e}. Vérifiez que toutes les dépendances sont installées.")
        return None
    except Exception as e:
        st.error(f"Erreur du pipeline : {e}")
        logger.error(f"Erreur du pipeline : {e}", exc_info=True)
        return None


# ── Application principale ────────────────────────────────────────────────────
def main():
    st.markdown('<div class="main-title">Générateur de CV ATS par IA</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Générez un CV optimisé ATS au format LaTeX, adapté à toute offre d\'emploi — propulsé par Gemini.</div>', unsafe_allow_html=True)

    # ── Vérification de la clé API ───────────────────────────────────────────
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", "")
    api_key_valid = bool(api_key) and api_key != "your_gemini_api_key_here"

    if not api_key_valid:
        st.markdown(
            '<div class="error-box">⚠ <strong>Clé API Gemini manquante</strong> : '
            'renseignez <code>GOOGLE_API_KEY</code> dans le fichier <code>.env</code> '
            'à la racine du projet, puis relancez l\'application.</div>',
            unsafe_allow_html=True,
        )
        st.stop()

    # ── Étape 1 : Offre d'emploi + CV (côte à côte) ──────────────────────────
    col_jd, col_cv = st.columns(2, gap="large")

    with col_jd:
        st.subheader("1. Offre d'emploi")
        jd_input_method = st.radio(
            "Méthode de saisie",
            ["Coller le texte", "Téléverser un PDF"],
            horizontal=True,
            key="jd_method",
            label_visibility="collapsed",
        )

        job_text = ""
        if jd_input_method == "Coller le texte":
            job_text = st.text_area(
                "Offre d'emploi",
                height=260,
                placeholder="Collez ici l'offre d'emploi complète...",
                label_visibility="collapsed",
            )
        else:
            jd_file = st.file_uploader(
                "Téléverser l'offre d'emploi (PDF)",
                type=["pdf", "txt"],
                key="jd_upload",
                label_visibility="collapsed",
            )
            if jd_file:
                try:
                    job_text = _extract_jd_text(jd_file)
                    st.success(f"{len(job_text)} caractères extraits de {jd_file.name}")
                except Exception as e:
                    st.error(f"Échec de lecture du fichier : {e}")

    with col_cv:
        st.subheader("2. Votre CV")
        resume_file = st.file_uploader(
            "Téléverser votre CV (PDF ou DOCX)",
            type=["pdf", "docx", "doc"],
            key="resume_upload",
            label_visibility="collapsed",
        )
        resume_text = ""
        if resume_file:
            try:
                resume_text = _extract_resume_text(resume_file)
                st.success(f"{len(resume_text)} caractères extraits de {resume_file.name}")
            except Exception as e:
                st.error(f"Échec de lecture du CV : {e}")

    st.markdown("")

    # ── Étape 2 : Préférences (étalées sur 5 colonnes) ───────────────────────
    st.subheader("3. Personnalisez votre CV")

    template_labels = {"modern": "Moderne", "executive": "Exécutif", "classic": "Classique"}
    language_labels = {"French": "Français", "English": "Anglais"}
    conciseness_labels = {"concise": "Concis", "balanced": "Équilibré", "detailed": "Détaillé"}

    pref_col1, pref_col2, pref_col3, pref_col4, pref_col5 = st.columns(5)

    with pref_col1:
        template = st.radio(
            "Style de modèle",
            options=["modern", "executive", "classic"],
            format_func=lambda x: template_labels[x],
        )

    with pref_col2:
        language = st.selectbox(
            "Langue du CV",
            options=["French", "English"],
            index=0,
            format_func=lambda x: language_labels[x],
        )

    with pref_col3:
        conciseness = st.select_slider(
            "Niveau de concision",
            options=["concise", "balanced", "detailed"],
            value="balanced",
            format_func=lambda x: conciseness_labels[x],
        )

    with pref_col4:
        color_hex = st.color_picker("Couleur d'accent", value="#2E86AB")

    with pref_col5:
        include_photo = st.toggle("Inclure une photo", value=False)

    photo_path = None
    if include_photo:
        photo_file = st.file_uploader("Téléverser une photo (JPG/PNG)", type=["jpg", "jpeg", "png"], key="photo_upload")
        if photo_file:
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(photo_file.name).suffix) as tmp:
                tmp.write(photo_file.read())
                photo_path = tmp.name
            st.image(photo_file, width=120, caption="Aperçu de la photo")

    st.markdown("")

    # ── Bouton de génération (centré, large) ─────────────────────────────────
    btn_col1, btn_col2, btn_col3 = st.columns([1, 2, 1])
    with btn_col2:
        generate_btn = st.button(
            "Générer le CV ATS",
            type="primary",
            use_container_width=True,
            disabled=(not job_text.strip() or not resume_text.strip()),
        )

    st.markdown("---")

    # ── Exécution du pipeline ────────────────────────────────────────────────
    if "result" not in st.session_state:
        st.session_state.result = None

    if generate_btn:
        if not job_text.strip():
            st.error("Veuillez fournir une offre d'emploi.")
        elif not resume_text.strip():
            st.error("Veuillez téléverser votre CV ou en fournir le texte.")
        else:
            preferences = {
                "color": color_hex,
                "template": template,
                "language": language,
                "conciseness": conciseness,
                "include_photo": include_photo,
            }

            with st.spinner("Exécution du pipeline à 8 agents... Cela peut prendre 30 à 90 secondes."):
                result = _run_pipeline(job_text, resume_text, preferences, photo_path)
                if result:
                    st.session_state.result = result

    result = st.session_state.result

    if result is None:
        st.markdown("""
<div class="empty-state">
  <div class="icon">📄</div>
  <div class="title">Votre CV optimisé apparaîtra ici</div>
  <div class="hint">Complétez les étapes ci-dessus puis cliquez sur <strong>Générer le CV ATS</strong>.</div>
</div>
        """, unsafe_allow_html=True)
        return

    # ── Affichage des résultats ──────────────────────────────────────────────
    if result.get("errors"):
        for err in result["errors"]:
            st.warning(f"Avertissement du pipeline : {err}")

    latex_source = result.get("latex_source", "")
    pdf_path = result.get("pdf_path")
    report_md = result.get("executive_report", "")

    # ── Téléchargements (action principale, en haut) ─────────────────────────
    st.subheader("Votre CV optimisé est prêt")
    col_dl1, col_dl2, col_dl3 = st.columns(3)

    with col_dl1:
        if pdf_path and Path(pdf_path).exists():
            with open(pdf_path, "rb") as f:
                st.download_button(
                    label="⬇ Télécharger le PDF",
                    data=f.read(),
                    file_name="cv_optimise.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    type="primary",
                )
        else:
            st.button("⬇ Télécharger le PDF", disabled=True, use_container_width=True, help="pdflatex non disponible")

    with col_dl2:
        if latex_source:
            st.download_button(
                label="⬇ Télécharger le .tex",
                data=latex_source.encode("utf-8"),
                file_name="cv_optimise.tex",
                mime="text/x-tex",
                use_container_width=True,
            )

    with col_dl3:
        if report_md:
            st.download_button(
                label="⬇ Télécharger le rapport",
                data=report_md.encode("utf-8"),
                file_name="rapport_correspondance.md",
                mime="text/markdown",
                use_container_width=True,
            )

    if not result.get("metadata", {}).get("pdflatex_available", True) and not pdf_path:
        st.markdown('<div class="warning-box">pdflatex introuvable dans le PATH système. Seul le fichier .tex est disponible. Installez TeX Live ou MiKTeX pour activer la compilation PDF.</div>', unsafe_allow_html=True)

    st.markdown("---")

    # ── Onglets de détail ────────────────────────────────────────────────────
    tab_preview, tab_keywords, tab_gap, tab_report, tab_diff = st.tabs([
        "Aperçu LaTeX", "Mots-clés", "Analyse des écarts", "Rapport exécutif", "Modifications"
    ])

    with tab_preview:
        if latex_source:
            st.code(latex_source, language="latex", line_numbers=True)
        else:
            st.info("Aucune source LaTeX générée. Consultez les erreurs ci-dessus.")

    with tab_keywords:
        job_req = result.get("job_requirements") or {}
        kw_added = result.get("keywords_added") or []
        optimized = result.get("optimized_content") or {}

        full_text = " ".join([
            optimized.get("summary", ""),
            " ".join(optimized.get("skills", [])),
        ]).lower()

        rows = []
        for kw in job_req.get("required_skills", []):
            found = kw.lower() in full_text
            added = kw in kw_added
            rows.append({"Mot-clé": kw, "Catégorie": "Compétence requise", "Dans le CV": "Oui" if found else "Non", "Ajouté par l'IA": "Oui" if added else ""})
        for kw in job_req.get("nice_to_have_skills", []):
            found = kw.lower() in full_text
            rows.append({"Mot-clé": kw, "Catégorie": "Souhaitée", "Dans le CV": "Oui" if found else "Non", "Ajouté par l'IA": ""})
        for kw in job_req.get("ats_keywords", []):
            if kw not in [r["Mot-clé"] for r in rows]:
                found = kw.lower() in full_text
                added = kw in kw_added
                rows.append({"Mot-clé": kw, "Catégorie": "Mot-clé ATS", "Dans le CV": "Oui" if found else "Non", "Ajouté par l'IA": "Oui" if added else ""})

        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Dans le CV": st.column_config.TextColumn("Dans le CV"),
                    "Ajouté par l'IA": st.column_config.TextColumn("Ajouté par l'IA"),
                },
            )

            csv_path = PROJECT_ROOT / "outputs" / "ats_keywords.csv"
            if csv_path.exists():
                with open(csv_path, "rb") as f:
                    st.download_button(
                        "Télécharger les mots-clés (CSV)",
                        data=f.read(),
                        file_name="mots_cles_ats.csv",
                        mime="text/csv",
                    )
        else:
            st.info("Aucune donnée de mots-clés disponible.")

    with tab_gap:
        gap = result.get("gap_analysis") or {}
        if gap:
            st.markdown(f"**Résumé de l'analyse :** {gap.get('summary', '')}")
            st.markdown(f"**Score de sévérité :** {gap.get('severity_score', 0):.2f} (0 = parfait, 1 = non-correspondance)")
            st.markdown("")

            col_gap1, col_gap2 = st.columns(2)
            with col_gap1:
                missing = gap.get("missing_skills", [])
                if missing:
                    st.markdown("**Compétences requises manquantes**")
                    for s in missing:
                        st.markdown(f"- {s}")

            with col_gap2:
                matching = gap.get("matching_skills", [])
                if matching:
                    st.markdown("**Compétences correspondantes**")
                    for s in matching:
                        st.markdown(f"- {s}")

            terms = gap.get("terms_to_rephrase", [])
            if terms:
                st.markdown("**Termes reformulés pour l'ATS**")
                terms_df = pd.DataFrame(terms)
                st.dataframe(terms_df, use_container_width=True, hide_index=True)

            undersold = gap.get("undersold_experiences", [])
            if undersold:
                st.markdown("**Expériences sous-valorisées améliorées**")
                for item in undersold:
                    with st.expander(f"Expérience n°{item.get('experience_index', 0)+1}"):
                        st.write(f"**Raison :** {item.get('reason', '')}")
                        st.write(f"**Suggestion :** {item.get('suggestion', '')}")
        else:
            st.info("Aucune analyse des écarts disponible.")

    with tab_report:
        report = result.get("executive_report", "")
        if report:
            st.markdown(report)
        else:
            st.info("Aucun rapport exécutif généré.")

    with tab_diff:
        diff = result.get("diff_report", "")
        if diff:
            st.markdown(diff)
        else:
            st.info("Aucun rapport de modifications généré.")


if __name__ == "__main__":
    main()
