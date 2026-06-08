"""Page Streamlit : Auto Apply.

Flux complet bout-en-bout :
  1. L'utilisateur colle son CV de base (ou uploade un fichier).
  2. Il décrit le type de poste ciblé (utilisé comme contexte pour optimiser chaque CV).
  3. Il se connecte à la plateforme choisie (LinkedIn / JobTeaser).
  4. Il configure la recherche (mots-clés, localisation, template, langue…).
  5. Il clique "Lancer" → le runner trouve chaque offre, génère un CV personnalisé
     pour cette offre, postule, et enregistre le tout dans un CSV local.
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
from .optimum_pipeline import extract_cv_text


# ── Utilitaires session_state ────────────────────────────────────────────────
def _ss_init() -> None:
    ss = st.session_state
    ss.setdefault("runner_proc", None)
    ss.setdefault("login_proc", None)
    ss.setdefault("auto_refresh", False)


def _proc_alive(p) -> bool:
    return p is not None and p.poll() is None


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
    cv_source_file: str,
    job_target_file: str,
    template: str,
    language: str,
    accent_hex: str,
    leftbg_hex: str,
    auto_submit: bool,
    headless: bool,
) -> subprocess.Popen:
    cmd = [
        sys.executable, "-m", "modules.auto_apply_runner",
        "--platform", platform,
        "--keywords", keywords,
        "--location", location,
        "--max-applications", str(max_apps),
        "--cv-source-file", cv_source_file,
        "--job-target-file", job_target_file,
        "--template", template,
        "--language", language,
        "--accent-hex", accent_hex,
        "--leftbg-hex", leftbg_hex,
    ]
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

    st.markdown('<div class="main-title">Candidature automatique</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">'
        'Colle ton CV de base, définis le poste ciblé, connecte-toi à la plateforme '
        'et lance la recherche. Le système trouve les offres, <strong>génère un CV optimisé '
        'pour chaque offre</strong>, postule et enregistre tout localement dans '
        f'<code>{config.JOB_AGENT_HOME}</code>.'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── 1. CV de base ─────────────────────────────────────────────────────────
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

    cv_source_text = extracted_text or cv_text_paste

    # ── 2. Poste & Recherche ──────────────────────────────────────────────────
    st.subheader("2. Poste & Recherche")
    st.caption(
        "Définissez le poste recherché : les mots-clés lancent la recherche sur la plateforme, "
        "la description sert de **contexte** pour personnaliser le CV sur chaque offre trouvée."
    )

    r1, r2, r3 = st.columns([3, 3, 1])
    with r1:
        keywords = st.text_input("Mots-clés de recherche", value="data scientist", key="auto_keywords",
                                 placeholder="Ex : data scientist, AI engineer…")
    with r2:
        location = st.text_input("Localisation", value="Paris", key="auto_location",
                                 placeholder="Ex : Paris, France, Remote…")
    with r3:
        max_apps = st.number_input("Nb max", min_value=1, max_value=50, value=5, key="auto_max_apps")

    job_target = st.text_area(
        "Description du poste ciblé",
        height=130,
        placeholder=(
            "Décrivez le type de poste visé : secteur, compétences clés, niveau d'expérience, contrat…\n"
            "Ex : Data Scientist senior, Python, scikit-learn, PyTorch, LLM, RAG, "
            "secteur finance / assurance, Paris, CDI, 5 ans d'expérience minimum…"
        ),
        key="auto_job_target",
        label_visibility="collapsed",
    )

    st.markdown("---")

    # ── 3. Plateforme ─────────────────────────────────────────────────────────
    st.subheader("3. Plateforme")
    plat_cols = st.columns(len(config.PLATFORMS))
    for col, (key, spec) in zip(plat_cols, config.PLATFORMS.items()):
        with col:
            cookies_path = config.COOKIES_DIR / f"{key}.json"
            connected = cookies_path.exists()
            badge = "✅ Connecté" if connected else "⚪ Non connecté"
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

    st.markdown("---")

    # ── 4. Options & Lancement ────────────────────────────────────────────────
    st.subheader("4. Lancer")

    col_mode, col_headless = st.columns([2, 1])
    with col_mode:
        mode = st.radio(
            "Mode de candidature",
            ["Automatique", "Semi-automatique"],
            horizontal=True,
            key="auto_mode",
            help="Automatique : soumet sans confirmation. Semi-auto : s'arrête avant chaque envoi.",
        )
    with col_headless:
        headless = st.toggle("Navigateur invisible", value=False, key="auto_headless")

    auto_submit = mode == "Automatique"

    # Préférences CV (compactes — appliquées à chaque CV généré par le runner)
    with st.expander("⚙️ Préférences CV (template, langue, couleurs)", expanded=False):
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
                "Langue du CV",
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

    st.markdown("")

    ready = bool(cv_source_text.strip() and job_target.strip())
    runner_alive = _proc_alive(st.session_state.runner_proc)

    a1, a2, a3 = st.columns(3)
    with a1:
        launch_disabled = runner_alive or not ready
        launch_help = (
            "Remplissez le CV de base et le poste ciblé (étapes 1 & 2)."
            if not ready
            else ("Runner déjà actif." if runner_alive else "")
        )
        if st.button(
            "🚀 Lancer les candidatures",
            type="primary",
            disabled=launch_disabled,
            use_container_width=True,
            help=launch_help,
        ):
            if not (config.COOKIES_DIR / f"{selected_platform}.json").exists():
                st.error(
                    f"Connectez-vous d'abord à {config.PLATFORMS[selected_platform].label} "
                    "(étape 3)."
                )
            else:
                # Sauvegarde CV source et job target dans des fichiers temp
                tmp_dir = config.JOB_AGENT_HOME / "temp"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                cv_src_file = tmp_dir / "cv_source.txt"
                jt_file = tmp_dir / "job_target.txt"
                cv_src_file.write_text(cv_source_text, encoding="utf-8")
                jt_file.write_text(job_target, encoding="utf-8")

                file_manager.clear_stop()
                st.session_state.runner_proc = _spawn_runner(
                    platform=selected_platform,
                    keywords=keywords,
                    location=location,
                    max_apps=int(max_apps),
                    cv_source_file=str(cv_src_file),
                    job_target_file=str(jt_file),
                    template=template,
                    language=language,
                    accent_hex=accent_hex,
                    leftbg_hex=leftbg_hex,
                    auto_submit=auto_submit,
                    headless=headless,
                )
                st.session_state.auto_refresh = True
                st.success(
                    f"Runner lancé — le CV sera généré automatiquement pour chaque offre trouvée."
                )

    with a2:
        if st.button("⏹ Arrêter", disabled=not runner_alive, use_container_width=True):
            file_manager.request_stop()
            st.warning("Stop demandé — le runner s'arrête à la prochaine action.")

    with a3:
        if st.button("📁 Ouvrir le dossier", use_container_width=True):
            try:
                file_manager.open_folder(config.JOB_AGENT_HOME)
            except Exception as e:
                st.error(f"Impossible d'ouvrir : {e}")

    # ── 6. Logs en direct ─────────────────────────────────────────────────────
    st.subheader("6. Logs")
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

    # ── 7. Historique ─────────────────────────────────────────────────────────
    st.subheader("7. Historique des candidatures")
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
