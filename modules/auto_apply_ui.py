"""Page Streamlit : Auto Apply.

Affichée à la place de la page CV quand l'utilisateur choisit le tab Auto Apply
dans la nav du fichier principal `app/streamlit_app.py`.

Responsabilités :
- Connecter manuellement chaque plateforme (login headed → cookies sauvegardés).
- Configurer une recherche (keywords / location / max / mode).
- Lancer un subprocess `auto_apply_runner` qui pilote Playwright.
- Streamer les logs JSONL en direct.
- Afficher dashboard + tableau d'historique.
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

from . import applications_tracker, config, file_manager, letter_generator
from .letter_generator import LetterContext


# ── Utilitaires session_state ────────────────────────────────────────────────
def _ss_init() -> None:
    ss = st.session_state
    ss.setdefault("runner_proc", None)            # subprocess.Popen | None
    ss.setdefault("login_proc", None)             # subprocess.Popen | None
    ss.setdefault("last_letter_text", "")
    ss.setdefault("last_letter_path", "")
    ss.setdefault("auto_refresh", False)


def _proc_alive(p) -> bool:
    return p is not None and p.poll() is None


# ── Sous-processus : login headed ────────────────────────────────────────────
def _spawn_login(platform: str) -> subprocess.Popen:
    """Lance un mini script Python qui ouvre Chromium et attend le login utilisateur."""
    file_manager.ensure_directories()
    # Inline script — évite un fichier de plus à maintenir.
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
        # Detach pour que le runner survive si Streamlit redémarre.
        creationflags=subprocess.DETACHED_PROCESS if os.name == "nt" else 0,
    )


# ── Page principale ──────────────────────────────────────────────────────────
def render() -> None:
    _ss_init()
    file_manager.ensure_directories()

    st.markdown('<div class="main-title">Auto Apply</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Génération de lettres + candidatures automatiques '
        'pilotées par Playwright. Données stockées localement dans '
        f'<code>{config.JOB_AGENT_HOME}</code>.</div>',
        unsafe_allow_html=True,
    )

    with st.expander("⚠ Avertissement légal — à lire avant d'utiliser", expanded=False):
        st.warning(
            "Automatiser des candidatures viole les Conditions d'utilisation de la plupart "
            "des plateformes (LinkedIn, Indeed, etc.) et peut entraîner le **bannissement "
            "définitif** de ton compte. Utilise ces fonctionnalités à tes propres risques, "
            "de préférence en mode semi-automatique (revue manuelle avant soumission) et "
            "avec des volumes raisonnables. Ne soumets jamais d'informations inventées."
        )

    # ── 1. Plateformes ──────────────────────────────────────────────────────
    st.subheader("1. Plateformes")
    plat_cols = st.columns(len(config.PLATFORMS))
    for col, (key, spec) in zip(plat_cols, config.PLATFORMS.items()):
        with col:
            cookies_path = config.COOKIES_DIR / f"{key}.json"
            badge = "✓ Connecté" if cookies_path.exists() else "✗ Non connecté"
            badge_color = "#28a745" if cookies_path.exists() else "#888"
            st.markdown(
                f"**{spec.label}**<br>"
                f"<span style='color:{badge_color};font-size:0.85rem'>{badge}</span>",
                unsafe_allow_html=True,
            )
            if not spec.implemented:
                st.button("À venir", key=f"btn_soon_{key}", disabled=True, use_container_width=True)
                continue

            login_disabled = _proc_alive(st.session_state.login_proc) or _proc_alive(st.session_state.runner_proc)
            if st.button(
                "Se connecter" if not cookies_path.exists() else "Re-connecter",
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

    # ── Plateforme + URL personnalisée ──────────────────────────────────────
    st.markdown("")
    custom_url = st.text_input(
        "URL personnalisée (optionnel — recherche pré-construite)",
        placeholder="https://www.linkedin.com/jobs/search/?keywords=...",
    )

    impl_keys = [k for k, s in config.PLATFORMS.items() if s.implemented]
    selected_platform = st.selectbox(
        "Plateforme cible",
        options=impl_keys,
        format_func=lambda k: config.PLATFORMS[k].label,
    )

    # ── 2. Paramètres ───────────────────────────────────────────────────────
    st.subheader("2. Recherche")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        keywords = st.text_input("Mots-clés", value="data scientist")
    with c2:
        location = st.text_input("Localisation", value="Paris")
    with c3:
        max_apps = st.number_input("Nb max d'offres", min_value=1, max_value=50, value=5)
    with c4:
        mode = st.radio("Mode", ["Automatique", "Semi-automatique"], horizontal=False)
    auto_submit = mode == "Automatique"
    headless = st.toggle(
        "Headless (navigateur invisible)",
        value=False,
        help="Désactivé par défaut : tu vois Playwright cliquer. Active pour gagner en perf.",
    )

    # ── 3. CV + lettre ──────────────────────────────────────────────────────
    st.subheader("3. CV & lettre de motivation")
    cv_col, letter_col = st.columns(2)

    with cv_col:
        st.caption("Chemin du CV (PDF ou DOCX) à uploader sur les formulaires.")
        cv_upload = st.file_uploader(
            "Téléverser votre CV",
            type=["pdf", "docx", "doc"],
            key="auto_cv_upload",
            label_visibility="collapsed",
        )
        cv_path = ""
        if cv_upload is not None:
            target = config.CVS_ORIGINAL_DIR / cv_upload.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(cv_upload.getvalue())
            cv_path = str(target)
            st.success(f"CV enregistré → {target.name}")
        else:
            # Fallback : dernier CV original déposé.
            existing = sorted(config.CVS_ORIGINAL_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
            if existing:
                cv_path = str(existing[0])
                st.caption(f"CV utilisé par défaut : `{existing[0].name}`")

    with letter_col:
        company_hint = st.text_input("Entreprise (pour la lettre)", value="")
        job_title_hint = st.text_input("Intitulé du poste (pour la lettre)", value=keywords)
        jd_hint = st.text_area("Description de l'offre (collez ici)", height=120)
        if st.button("✨ Générer la lettre de motivation"):
            if not (jd_hint and cv_path):
                st.error("Il faut un CV et une description d'offre pour générer la lettre.")
            else:
                with st.spinner("Génération via Gemini…"):
                    ctx = LetterContext(
                        job_title=job_title_hint,
                        company=company_hint,
                        job_description=jd_hint,
                        resume_text=letter_generator.read_resume_text(cv_path),
                        language="Français",
                    )
                    text = letter_generator.generate_letter(ctx)
                    path = letter_generator.save_letter(text, company=company_hint, job_title=job_title_hint)
                    st.session_state.last_letter_text = text
                    st.session_state.last_letter_path = str(path)
                    st.success(f"Lettre générée → {path.name}")

        if st.session_state.last_letter_text:
            st.text_area(
                "Lettre (modifiable avant envoi)",
                value=st.session_state.last_letter_text,
                key="letter_editable",
                height=180,
            )
            st.download_button(
                "⬇ Télécharger la lettre (.txt)",
                data=st.session_state.last_letter_text.encode("utf-8"),
                file_name=Path(st.session_state.last_letter_path).name if st.session_state.last_letter_path else "lettre.txt",
                mime="text/plain",
            )

    # ── 4. Actions ──────────────────────────────────────────────────────────
    st.subheader("4. Candidatures")
    a1, a2, a3, a4 = st.columns(4)
    runner_alive = _proc_alive(st.session_state.runner_proc)

    with a1:
        if st.button(
            "🚀 Lancer les candidatures",
            type="primary",
            disabled=runner_alive,
            use_container_width=True,
        ):
            if not cv_path:
                st.error("Téléversez un CV d'abord.")
            elif not (config.COOKIES_DIR / f"{selected_platform}.json").exists():
                st.error(f"Connectez-vous à {selected_platform} d'abord.")
            else:
                letter_text = st.session_state.get("letter_editable") or st.session_state.last_letter_text
                file_manager.clear_stop()
                st.session_state.runner_proc = _spawn_runner(
                    platform=selected_platform,
                    keywords=keywords,
                    location=location,
                    max_apps=int(max_apps),
                    cv_path=cv_path,
                    letter_text=letter_text or "",
                    auto_submit=auto_submit,
                    headless=headless,
                )
                st.session_state.auto_refresh = True
                st.success("Runner lancé — les logs s'affichent ci-dessous.")

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

    with a4:
        if custom_url:
            st.caption("URL custom prête à coller dans Chromium pendant la session.")

    # ── 5. Logs en direct ───────────────────────────────────────────────────
    st.subheader("5. Logs")
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

    log_box = st.container()
    log_lines = _tail_jsonl(config.RUN_LOG_JSONL, n=200)
    with log_box:
        if log_lines:
            formatted = "\n".join(
                f"[{l.get('level','info').upper():<7}] {l.get('msg','')}" for l in log_lines
            )
            st.code(formatted, language="text")
        else:
            st.caption("Aucun log pour le moment.")

    # Auto-rerun toutes les 2s tant qu'un subprocess tourne.
    if _proc_alive(st.session_state.runner_proc) or _proc_alive(st.session_state.login_proc):
        time.sleep(2)
        st.rerun()
    else:
        if st.session_state.auto_refresh:
            st.session_state.auto_refresh = False

    # ── 6. Historique + dashboard ──────────────────────────────────────────
    st.subheader("6. Historique")
    s = applications_tracker.stats()
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Total", s["total"])
    h2.metric("Soumises", s["submitted"])
    h3.metric("Échecs", s["failed"])
    h4.metric("Taux de réussite", f"{s['success_rate']} %")

    rows = applications_tracker.load_all()
    if rows:
        df = pd.DataFrame(rows)
        # Affiche les colonnes pertinentes seulement.
        cols = [c for c in ["date", "platform", "company", "job_title", "status", "url", "notes"] if c in df.columns]
        st.dataframe(df[cols].iloc[::-1], use_container_width=True, hide_index=True)
        st.download_button(
            "⬇ Télécharger l'historique (CSV)",
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
