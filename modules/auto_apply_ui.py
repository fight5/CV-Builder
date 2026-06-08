"""Page Streamlit : Auto Apply.

Flux complet bout-en-bout :
  1. L'utilisateur colle son CV de base (ou uploade un fichier).
  2. Il décrit le poste recherché (prérequis) — utilisé pour optimiser le CV.
  3. Il choisit un template et les couleurs.
  4. On génère le CV LaTeX → PDF via le pipeline optimum + lettre de motivation.
  5. On se connecte à la plateforme choisie (LinkedIn / JobTeaser).
  6. On recherche les offres "Easy Apply" / "Candidature simplifiée".
  7. On postule automatiquement et on enregistre chaque candidature localement
     (CSV + chemin CV + chemin lettre).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from . import applications_tracker, config, file_manager
from .optimum_pipeline import CVPreferences, extract_cv_text, run_optimum_pipeline


# ── Utilitaires session_state ────────────────────────────────────────────────
def _ss_init() -> None:
    ss = st.session_state
    ss.setdefault("runner_proc", None)       # subprocess.Popen | None
    ss.setdefault("login_proc", None)        # subprocess.Popen | None
    ss.setdefault("auto_refresh", False)
    ss.setdefault("generated_cv_path", "")   # chemin du CV PDF généré
    ss.setdefault("generated_lm_path", "")   # chemin de la lettre PDF générée
    ss.setdefault("generated_letter_text", "")  # corps texte de la lettre


def _proc_alive(p) -> bool:
    return p is not None and p.poll() is None


# ── Génération CV + Lettre ───────────────────────────────────────────────────
def _generate_cv_action(
    cv_source_text: str,
    job_target: str,
    template: str,
    language: str,
    accent_hex: str,
    leftbg_hex: str,
) -> None:
    """Appelle le pipeline optimum, sauvegarde CV et lettre dans JobAgentAI/."""
    prefs = CVPreferences(
        template=template,
        language=language,
        accent_hex=accent_hex,
        leftbg_hex=leftbg_hex,
        aggressive=True,
    )
    with st.spinner("Génération du CV optimisé et compilation PDF…"):
        try:
            result = run_optimum_pipeline(job_target, cv_source_text, prefs)
        except Exception as e:
            st.error(f"Erreur de génération : {e}")
            return

    # ── Sauvegarde CV ────────────────────────────────────────────────────────
    cv_bytes = result.get("cv_pdf_bytes")
    cv_filename = result.get("cv_filename", "CV.pdf")
    config.CVS_GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    cv_dest = config.CVS_GENERATED_DIR / cv_filename
    if cv_bytes:
        cv_dest.write_bytes(cv_bytes)
        st.session_state.generated_cv_path = str(cv_dest)
    else:
        st.session_state.generated_cv_path = ""
        for err in result.get("cv_errors", []):
            st.warning(f"CV : {err}")

    # ── Sauvegarde Lettre ────────────────────────────────────────────────────
    lm_bytes = result.get("letter_pdf_bytes")
    lm_filename = result.get("letter_filename", "Lettre_Motivation.pdf")
    config.LETTERS_DIR.mkdir(parents=True, exist_ok=True)
    lm_dest = config.LETTERS_DIR / lm_filename
    if lm_bytes:
        lm_dest.write_bytes(lm_bytes)
        st.session_state.generated_lm_path = str(lm_dest)
    else:
        st.session_state.generated_lm_path = ""
        for err in result.get("letter_errors", []):
            st.warning(f"Lettre : {err}")

    st.session_state.generated_letter_text = result.get("letter_body", "")

    if st.session_state.generated_cv_path:
        st.success(
            f"CV compilé : **{cv_filename}** — "
            f"Lettre : **{lm_filename}**  \n"
            f"Sauvegardés dans `{config.JOB_AGENT_HOME}`"
        )


# ── Sous-processus : login headed ────────────────────────────────────────────
def _spawn_login(platform: str) -> subprocess.Popen:
    file_manager.ensure_directories()
    code = (
        "import sys, os; "
        f"sys.path.insert(0, r'{Path(__file__).resolve().parent.parent}'); "
        "from modules.browser_manager import BrowserSession, JsonlEventLogger; "
        "from modules.config import PLATFORMS; "
        f"spec = PLATFORMS[{platform!r}]; "
        "ready = None; "
        f"plat = {platform!r}; "
        "if plat == 'linkedin': "
        "    from modules.linkedin_apply import READY_SELECTOR as R; ready = R\n"
        "elif plat == 'jobteaser':\n"
        "    from modules.jobteaser_apply import READY_SELECTOR as R; ready = R\n"
        "logger = JsonlEventLogger();\n"
        "with BrowserSession(plat, headless=False, event_logger=logger) as s:\n"
        "    s.manual_login(spec.base_url, ready_selector=ready)\n"
    )
    return subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _spawn_runner(
    *,
    platform: str,
    keywords: str,
    location: str,
    max_apps: int,
    cv_path: str,
    letter_path: str,
    letter_text: str,
    auto_submit: bool,
    headless: bool,
) -> subprocess.Popen:
    cmd = [
        sys.executable, "-m", "modules.auto_apply_runner",
        "--platform", platform,
        "--keywords", keywords,
        "--location", location,
        "--max-applications", str(max_apps),
    ]
    if cv_path:
        cmd += ["--cv-path", cv_path]
    if letter_path:
        cmd += ["--letter-path", letter_path]
    if letter_text:
        cmd += ["--letter-text", letter_text]
    if auto_submit:
        cmd += ["--auto-submit"]
    if headless:
        cmd += ["--headless"]
    cwd = str(Path(__file__).resolve().parent.parent)
    return subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS if os.name == "nt" else 0,
    )


# ── Page principale ──────────────────────────────────────────────────────────
def render() -> None:
    _ss_init()
    file_manager.ensure_directories()

    st.markdown('<div class="main-title">Auto Apply</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Génère un CV ATS optimisé depuis votre base, '
        'puis postule automatiquement sur LinkedIn ou JobTeaser. '
        f'Données stockées dans <code>{config.JOB_AGENT_HOME}</code>.</div>',
        unsafe_allow_html=True,
    )

    # ── 1. CV Source ─────────────────────────────────────────────────────────
    st.subheader("1. Votre CV de base")
    src_col, upload_col = st.columns([3, 2])
    with src_col:
        cv_text_paste = st.text_area(
            "cv_paste",
            height=220,
            placeholder=(
                "Collez le texte brut de votre CV :\n"
                "expériences professionnelles, compétences, formation, langues…"
            ),
            key="auto_cv_text_paste",
            label_visibility="collapsed",
        )
    with upload_col:
        st.caption("Ou uploadez un fichier — le texte sera extrait automatiquement.")
        cv_file = st.file_uploader(
            "CV (PDF/DOCX)",
            type=["pdf", "docx", "doc"],
            key="auto_cv_file_upload",
            label_visibility="collapsed",
        )
        extracted_text = ""
        if cv_file is not None:
            try:
                extracted_text = extract_cv_text(cv_file)
                st.success(f"{len(extracted_text):,} caractères extraits de **{cv_file.name}**")
            except Exception as e:
                st.error(f"Extraction échouée : {e}")

    # Priorité au fichier uploadé ; sinon texte collé
    cv_source_text = extracted_text or cv_text_paste

    # ── 2. Prérequis du poste ─────────────────────────────────────────────
    st.subheader("2. Poste recherché (Prérequis)")
    st.caption(
        "Décrivez le type de poste visé, vos compétences clés, le secteur, "
        "le niveau d'expérience, le type de contrat…  \n"
        "Ce texte est utilisé pour **optimiser votre CV** avant la candidature."
    )
    job_target = st.text_area(
        "prereqs",
        height=140,
        placeholder=(
            "Ex : Data Scientist senior, Python, scikit-learn, PyTorch, LLM, RAG, "
            "secteur finance / assurance, Paris, CDI ou freelance, "
            "5 ans d'expérience minimum en machine learning…"
        ),
        key="auto_job_target",
        label_visibility="collapsed",
    )

    # ── 3. Personnalisation du CV ─────────────────────────────────────────
    st.subheader("3. Personnalisation du CV")
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        template = st.selectbox(
            "Template",
            options=["optimum", "minimal"],
            format_func=lambda x: "Optimum (design)" if x == "optimum" else "Minimal (ATS pur)",
            key="auto_template",
        )
    with p2:
        language = st.selectbox(
            "Langue",
            options=["Français", "English"],
            key="auto_language",
        )
    with p3:
        accent_hex = st.color_picker("Couleur accent", value="#006699", key="auto_accent")
    with p4:
        leftbg_hex = st.color_picker(
            "Couleur bandeau",
            value="#172E4A",
            key="auto_leftbg",
            disabled=(template != "optimum"),
        )

    gen_ready = bool(cv_source_text.strip() and job_target.strip())
    if st.button(
        "Générer et compiler mon CV",
        type="primary",
        disabled=not gen_ready,
        help="Remplissez le CV source et les prérequis pour activer." if not gen_ready else "",
    ):
        _generate_cv_action(
            cv_source_text, job_target, template, language, accent_hex, leftbg_hex
        )

    # Aperçu des fichiers générés
    if st.session_state.generated_cv_path:
        cv_p = Path(st.session_state.generated_cv_path)
        lm_p = (
            Path(st.session_state.generated_lm_path)
            if st.session_state.generated_lm_path
            else None
        )
        res_c1, res_c2 = st.columns(2)
        with res_c1:
            if cv_p.exists():
                st.download_button(
                    f"Aperçu CV — {cv_p.name}",
                    data=cv_p.read_bytes(),
                    file_name=cv_p.name,
                    mime="application/pdf",
                    use_container_width=True,
                )
        with res_c2:
            if lm_p and lm_p.exists():
                st.download_button(
                    f"Aperçu Lettre — {lm_p.name}",
                    data=lm_p.read_bytes(),
                    file_name=lm_p.name,
                    mime="application/pdf",
                    use_container_width=True,
                )

    st.markdown("---")

    # ── 4. Plateformes ────────────────────────────────────────────────────
    st.subheader("4. Plateforme")
    plat_cols = st.columns(len(config.PLATFORMS))
    for col, (key, spec) in zip(plat_cols, config.PLATFORMS.items()):
        with col:
            cookies_path = config.COOKIES_DIR / f"{key}.json"
            connected = cookies_path.exists()
            badge = "Connecté" if connected else "Non connecté"
            badge_color = "#28a745" if connected else "#888"
            st.markdown(
                f"**{spec.label}**<br>"
                f"<span style='color:{badge_color};font-size:0.85rem'>{badge}</span>",
                unsafe_allow_html=True,
            )
            if not spec.implemented:
                st.button("À venir", key=f"btn_soon_{key}", disabled=True, use_container_width=True)
                continue
            login_disabled = (
                _proc_alive(st.session_state.login_proc)
                or _proc_alive(st.session_state.runner_proc)
            )
            if st.button(
                "Se connecter" if not connected else "Re-connecter",
                key=f"btn_login_{key}",
                disabled=login_disabled,
                use_container_width=True,
            ):
                st.session_state.login_proc = _spawn_login(key)
                st.session_state.auto_refresh = True
                st.info(
                    f"Une fenêtre Chromium s'ouvre — connecte-toi à {spec.label}. "
                    "La session sera sauvegardée automatiquement."
                )

    impl_keys = [k for k, s in config.PLATFORMS.items() if s.implemented]
    selected_platform = st.selectbox(
        "Plateforme cible",
        options=impl_keys,
        format_func=lambda k: config.PLATFORMS[k].label,
        key="auto_selected_platform",
    )

    # ── 5. Paramètres de recherche ────────────────────────────────────────
    st.subheader("5. Recherche")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        keywords = st.text_input("Mots-clés", value="data scientist", key="auto_keywords")
    with c2:
        location = st.text_input("Localisation", value="Paris", key="auto_location")
    with c3:
        max_apps = st.number_input(
            "Nb max d'offres", min_value=1, max_value=50, value=5, key="auto_max_apps"
        )
    with c4:
        mode = st.radio(
            "Mode", ["Automatique", "Semi-automatique"], horizontal=False, key="auto_mode"
        )
    auto_submit = mode == "Automatique"
    headless = st.toggle(
        "Headless (navigateur invisible)",
        value=False,
        key="auto_headless",
        help="Désactivé par défaut : tu vois Playwright cliquer. Active pour gagner en performance.",
    )

    # ── 6. Candidatures ───────────────────────────────────────────────────
    st.subheader("6. Candidatures")
    a1, a2, a3 = st.columns(3)
    runner_alive = _proc_alive(st.session_state.runner_proc)

    cv_path_to_use = st.session_state.generated_cv_path
    lm_path_to_use = st.session_state.generated_lm_path
    letter_text_to_use = st.session_state.generated_letter_text

    with a1:
        launch_disabled = runner_alive or not cv_path_to_use
        launch_help = (
            "Générez d'abord votre CV (étape 3)."
            if not cv_path_to_use
            else ("Runner déjà actif." if runner_alive else "")
        )
        if st.button(
            "Lancer les candidatures",
            type="primary",
            disabled=launch_disabled,
            use_container_width=True,
            help=launch_help,
        ):
            if not (config.COOKIES_DIR / f"{selected_platform}.json").exists():
                st.error(
                    f"Connectez-vous à {config.PLATFORMS[selected_platform].label} "
                    "d'abord (étape 4)."
                )
            else:
                file_manager.clear_stop()
                st.session_state.runner_proc = _spawn_runner(
                    platform=selected_platform,
                    keywords=keywords,
                    location=location,
                    max_apps=int(max_apps),
                    cv_path=cv_path_to_use,
                    letter_path=lm_path_to_use,
                    letter_text=letter_text_to_use,
                    auto_submit=auto_submit,
                    headless=headless,
                )
                st.session_state.auto_refresh = True
                st.success("Runner lancé — les logs s'affichent ci-dessous.")

    with a2:
        if st.button("Arrêter", disabled=not runner_alive, use_container_width=True):
            file_manager.request_stop()
            st.warning("Stop demandé — le runner s'arrête à la prochaine action.")

    with a3:
        if st.button("Ouvrir le dossier", use_container_width=True):
            try:
                file_manager.open_folder(config.JOB_AGENT_HOME)
            except Exception as e:
                st.error(f"Impossible d'ouvrir : {e}")

    # ── 7. Logs en direct ─────────────────────────────────────────────────
    st.subheader("7. Logs")
    state = file_manager.read_json(config.RUN_STATE_JSON, default={}) or {}
    if state:
        cols = st.columns(5)
        cols[0].metric("Statut", state.get("status", "—"))
        cols[1].metric("Traitées", f"{state.get('processed', 0)} / {state.get('total', 0)}")
        cols[2].metric("Soumises", state.get("submitted", 0))
        cols[3].metric("Skipped", state.get("skipped", 0))
        cols[4].metric("Échec", state.get("failed", 0))
        if state.get("current_job"):
            st.caption(f"En cours : {state['current_job']}")

    log_lines = _tail_jsonl(config.RUN_LOG_JSONL, n=200)
    if log_lines:
        formatted = "\n".join(
            f"[{l.get('level', 'info').upper():<7}] {l.get('msg', '')}" for l in log_lines
        )
        st.code(formatted, language="text")
    else:
        st.caption("Aucun log pour le moment.")

    # Auto-rerun toutes les 2 s tant qu'un subprocess tourne.
    if _proc_alive(st.session_state.runner_proc) or _proc_alive(st.session_state.login_proc):
        time.sleep(2)
        st.rerun()
    else:
        if st.session_state.auto_refresh:
            st.session_state.auto_refresh = False

    # ── 8. Historique ─────────────────────────────────────────────────────
    st.subheader("8. Historique des candidatures")
    s = applications_tracker.stats()
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Total", s["total"])
    h2.metric("Soumises", s["submitted"])
    h3.metric("Échecs", s["failed"])
    h4.metric("Taux de réussite", f"{s['success_rate']} %")

    rows = applications_tracker.load_all()
    if rows:
        df = pd.DataFrame(rows)
        display_cols = [
            c for c in
            ["date", "platform", "company", "job_title", "status", "url", "cv_path", "letter_path", "notes"]
            if c in df.columns
        ]
        st.dataframe(df[display_cols].iloc[::-1], use_container_width=True, hide_index=True)
        st.download_button(
            "Télécharger l'historique (CSV)",
            data=config.APPLICATIONS_CSV.read_bytes(),
            file_name="applications.csv",
            mime="text/csv",
        )
    else:
        st.info("Aucune candidature enregistrée pour le moment.")


# ── Helpers ──────────────────────────────────────────────────────────────────
def _tail_jsonl(path: Path, n: int = 200) -> list[dict]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-n:]
        out: list[dict] = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return out
    except OSError:
        return []
