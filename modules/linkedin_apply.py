"""LinkedIn — Easy Apply.

Stratégie : ne tenter que les offres "Easy Apply" (filtre `f_AL=true`).
Pour les formulaires multi-étapes complexes ou avec questions custom, on
abandonne proprement (status='skipped') plutôt que de soumettre du contenu
inventé.

NOTE: Les selecteurs LinkedIn changent souvent. Verifie-les si tu observes
des skipped massifs.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from dataclasses import dataclass
from typing import Iterable, Optional

from .browser_manager import BrowserSession, StopRequested
from .letter_generator import clean_title

logger = logging.getLogger(__name__)

LOGIN_URL = "https://www.linkedin.com/login"
# Indicateur "je suis loggué" : la barre globale avec lien Me/Mon profil.
READY_SELECTOR = "header img.global-nav__me-photo, button[data-test-global-nav-me]"

SEARCH_URL_TEMPLATE = (
    "https://www.linkedin.com/jobs/search/"
    "?keywords={keywords}&location={location}&f_AL=true"
)


@dataclass
class Job:
    job_id: str
    title: str
    company: str
    url: str


# ── Recherche ────────────────────────────────────────────────────────────────
def _dismiss_cookie_banner(session: BrowserSession) -> None:
    """Ferme la bannière de consentement cookies LinkedIn si présente.

    Utilise d'abord JS pour bypasser tout overlay bloquant, puis fallback
    sur les sélecteurs Playwright classiques.
    """
    import time

    # Méthode 1 : JS evaluate (bypass overlay, plus fiable)
    try:
        clicked = session.page.evaluate("""
            () => {
                // Boutons artdeco-global-alert (RGPD LinkedIn 2024-2025)
                const alertBtns = document.querySelectorAll(
                    'button.artdeco-global-alert-action'
                );
                for (const btn of alertBtns) {
                    const txt = (btn.textContent || '').trim().toLowerCase();
                    if (txt.includes('accept') || txt.includes('accepter') ||
                        txt.includes('agree') || txt.includes('allow') ||
                        txt.includes('autoriser')) {
                        btn.click();
                        return true;
                    }
                }
                // Fallback attribut action-type
                const accept = document.querySelector(
                    'button[action-type="ACCEPT"], ' +
                    'button[data-control-name="ga-cookie.consent.accept.v3"]'
                );
                if (accept) { accept.click(); return true; }
                return false;
            }
        """)
        if clicked:
            session.log("info", "Bannière cookie fermée (JS).")
            time.sleep(1.2)
            return
    except Exception:
        pass

    # Méthode 2 : sélecteurs Playwright (fallback)
    for sel in (
        "button.artdeco-global-alert-action",
        "button[action-type='ACCEPT']",
        "button[data-control-name='ga-cookie.consent.accept.v3']",
        "#artdeco-global-alert-container button",
        "button.artdeco-global-alert__dismiss",
    ):
        try:
            btn = session.page.locator(sel).first
            if btn.count() and btn.is_visible(timeout=1500):
                btn.click()
                session.log("info", f"Bannière cookie fermée ({sel}).")
                time.sleep(1.2)
                return
        except Exception:
            continue


def _detect_page_mode(session: BrowserSession) -> str:
    """Retourne 'spa' ou 'static' pour la page de RECHERCHE LinkedIn."""
    if session.page.locator("li[data-occludable-job-id]").count() > 0:
        return "spa"
    if session.page.locator("div.base-card--link").count() > 0:
        return "static"
    return "unknown"


def _detect_page_mode_job(session: BrowserSession) -> str:
    """Retourne 'spa' ou 'static' pour une page DETAIL d'offre LinkedIn.

    LinkedIn 2025 SPA : le bouton s'appelle "Candidature simplifiée" (FR)
    ou "Easy Apply" (EN). La nav globale et le h1 titre sont aussi présents.
    """
    # Mode SPA (connecté) — LinkedIn 2025 (classes CSS minifiées + Shadow DOM)
    # get_by_role() traverse le Shadow DOM → plus fiable que les sélecteurs CSS
    for indicator in ("Enregistrer", "Candidature", "Apply", "Postuler"):
        try:
            if session.page.get_by_role("button", name=indicator, exact=False).count() > 0:
                return "spa"
        except Exception:
            pass
    # Fallback CSS : h1 ou classes LinkedIn connues
    if session.page.locator("h1, button.jobs-apply-button").count() > 0:
        return "spa"
    # Mode statique : top-card public LinkedIn (non connecté)
    if session.page.locator(
        "div.top-card-layout, div.show-more-less-html, "
        "section.core-section-container"
    ).count() > 0:
        return "static"
    return "unknown"


def search_jobs(
    session: BrowserSession,
    *,
    keywords: str,
    location: str = "",
    max_results: int = 10,
) -> list[Job]:
    """Récupère jusqu'à `max_results` offres Easy Apply correspondant aux critères.

    Gère deux modes de rendu LinkedIn :
    - SPA (React, connecté)  : li[data-occludable-job-id]
    - Static (bot-detected)  : div.base-card--link
    """
    url = SEARCH_URL_TEMPLATE.format(
        keywords=urllib.parse.quote(keywords or ""),
        location=urllib.parse.quote(location or ""),
    )
    session.log("info", f"LinkedIn — recherche : {url}")
    session.page.goto(url, wait_until="domcontentloaded", timeout=60000)

    # Fermer bannière cookie si présente
    _dismiss_cookie_banner(session)

    # Attendre les cards — SPA en priorité (jusqu'à 15s), puis static (5s)
    import time
    time.sleep(2)  # laisser la SPA React démarrer
    try:
        session.page.wait_for_selector("li[data-occludable-job-id]", timeout=15000)
    except Exception:
        try:
            session.page.wait_for_selector("div.base-card--link", timeout=5000)
        except Exception:
            pass

    session.human_pause()
    page_mode = _detect_page_mode(session)
    current_url = session.page.url
    session.log("info", f"LinkedIn page mode : {page_mode} | URL: {current_url[:80]}")

    jobs: dict[str, Job] = {}
    last_count = -1
    rounds = 0

    while len(jobs) < max_results and rounds < 8:
        session.check_stop()
        rounds += 1

        if page_mode == "spa":
            jobs = _parse_cards_spa(session, jobs, max_results)
        else:
            jobs = _parse_cards_static(session, jobs, max_results)

        if len(jobs) == last_count:
            break
        last_count = len(jobs)

        # Scroll pour charger davantage
        try:
            scroller = session.page.locator(
                "div.jobs-search-results-list, .scaffold-layout__list-container, "
                "ul.jobs-search__results-list"
            ).first
            if scroller.count():
                scroller.evaluate("el => el.scrollBy(0, 1200)")
            else:
                session.page.mouse.wheel(0, 1200)
        except Exception:
            session.page.mouse.wheel(0, 1200)
        session.human_pause()

    result = list(jobs.values())[:max_results]
    session.log("info", f"LinkedIn — {len(result)} offre(s) Easy Apply trouvée(s)")
    return result


def _parse_cards_spa(
    session: BrowserSession, jobs: dict, max_results: int
) -> dict:
    """Parse les cards en mode SPA (React, connecté)."""
    cards = session.page.locator("li[data-occludable-job-id]")
    for i in range(cards.count()):
        if len(jobs) >= max_results:
            break
        card = cards.nth(i)
        try:
            job_id = card.get_attribute("data-occludable-job-id") or ""
            title_el = card.locator(
                "a.job-card-container__link, a.job-card-list__title--link, "
                "a[class*='job-card'][href*='/jobs/view']"
            ).first
            comp_el = card.locator(
                ".artdeco-entity-lockup__subtitle, "
                "h4.job-card-container__company-name, "
                "span.job-card-container__primary-description"
            ).first
            title = clean_title(title_el.inner_text(timeout=2000)) if title_el.count() else ""
            company = clean_title(comp_el.inner_text(timeout=2000)) if comp_el.count() else ""
            href = title_el.get_attribute("href") if title_el.count() else None
            if not href:
                link = card.locator("a[href*='/jobs/view']").first
                href = link.get_attribute("href") if link.count() else None
            if not href:
                continue
            full_url = href if href.startswith("http") else f"https://www.linkedin.com{href}"
            key = job_id or full_url
            if key not in jobs:
                jobs[key] = Job(job_id=job_id or key, title=title, company=company, url=full_url)
        except Exception as e:
            session.log("debug", f"SPA card parse error: {e}")
    return jobs


def _normalize_job_url(url: str) -> str:
    """Convertit une URL LinkedIn publique (fr.linkedin.com, slug textuel) en URL SPA.

    fr.linkedin.com/jobs/view/data-scientist-at-canopee-4179375547
    → www.linkedin.com/jobs/view/4179375547/

    Toujours utiliser www.linkedin.com pour obtenir la version React (SPA)
    lorsqu'on est connecté. fr.linkedin.com et les slugs textuels renvoient
    systématiquement du HTML statique même avec une session active.
    """
    import re as _re
    # Extraire l'ID numérique final de l'URL (dernier segment de chiffres)
    m = _re.search(r"[/-](\d{7,})(?:[/?#]|$)", url)
    if m:
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
    # Fallback : remplacer juste le sous-domaine
    return url.replace("fr.linkedin.com", "www.linkedin.com")


def _parse_cards_static(
    session: BrowserSession, jobs: dict, max_results: int
) -> dict:
    """Parse les cards en mode statique (LinkedIn public / bot-detected).

    Les URLs sont normalisées vers www.linkedin.com/jobs/view/{id}/ pour
    pouvoir naviguer en mode SPA lors de la candidature.
    """
    import re as _re
    cards = session.page.locator("div.base-card--link")
    for i in range(cards.count()):
        if len(jobs) >= max_results:
            break
        card = cards.nth(i)
        try:
            title_el = card.locator(
                "h3.base-search-card__title, h3[class*='title']"
            ).first
            comp_el = card.locator(
                "h4.base-search-card__subtitle, a[class*='company'], "
                ".base-search-card__subtitle"
            ).first
            link_el = card.locator("a[href*='/jobs/view']").first
            title = clean_title(title_el.inner_text(timeout=2000)) if title_el.count() else ""
            company = clean_title(comp_el.inner_text(timeout=2000)) if comp_el.count() else ""
            href = link_el.get_attribute("href") if link_el.count() else None
            if not href:
                continue
            raw_url = href if href.startswith("http") else f"https://www.linkedin.com{href}"
            # Normaliser vers l'URL SPA (www.linkedin.com + ID numérique)
            full_url = _normalize_job_url(raw_url)
            m = _re.search(r"/jobs/view/(\d+)", full_url)
            job_id = m.group(1) if m else full_url
            if job_id not in jobs:
                jobs[job_id] = Job(job_id=job_id, title=title, company=company, url=full_url)
        except Exception as e:
            session.log("debug", f"Static card parse error: {e}")
    return jobs


# ── Candidature ──────────────────────────────────────────────────────────────
def _js_click(locator) -> None:
    """Force un click via JS pour bypasser les overlays."""
    locator.evaluate("el => el.click()")


def apply_to_job(
    session: BrowserSession,
    job: Job,
    *,
    cv_path: str = "",
    letter_text: str = "",
    auto_submit: bool = True,
) -> tuple[str, str]:
    """Tente Easy Apply sur une offre. Retourne (status, notes).

    status ∈ {"submitted", "skipped", "failed", "need_login"}.
    - submitted   : formulaire envoyé.
    - skipped     : modal multi-étapes ou questions non remplies — pas de soumission.
    - failed      : erreur Playwright (timeout, sélecteur introuvable, etc.).
    - need_login  : page en mode statique (non connecté) — login requis.
    """
    import time as _time

    # Normaliser l'URL vers www.linkedin.com (SPA) avant navigation.
    spa_url = _normalize_job_url(job.url)
    session.log("info", f"LinkedIn — ouverture : {job.title} @ {job.company} — {spa_url}")
    session.page.goto(spa_url, wait_until="domcontentloaded", timeout=60000)
    _time.sleep(3)

    # Fermer bannière cookie si présente
    _dismiss_cookie_banner(session)
    session.human_pause()
    session.check_stop()

    # Détecter mode page pour adapter la stratégie
    page_mode = _detect_page_mode_job(session)
    session.log("info", f"Job page mode : {page_mode}")

    if page_mode == "static":
        # LinkedIn en mode statique = non connecté (ou bot-detected malgré stealth).
        # Easy Apply est inaccessible dans cet état.
        screenshot = session.screenshot(f"static_{job.job_id}")
        return (
            "need_login",
            f"Page statique (non connecté) — Easy Apply inaccessible. "
            f"Screenshot: {screenshot.name}"
        )

    # ── Mode SPA (connecté) ───────────────────────────────────────────────────
    # Chercher le bouton "Candidature simplifiée" (FR) / "Easy Apply" (EN).
    # LinkedIn 2025 : toutes les classes CSS sont des hashes minifiés.
    # On se base sur le TEXTE et aria-label plutôt que sur les classes.

    # Attendre que la page ait chargé le panneau d'offre React (jusqu'à 20s).
    # IMPORTANT : on N'inclut PAS "h1" car h1 est toujours présent (résolution immédiate)
    # → on attend spécifiquement les boutons d'action de l'offre.
    content_ready_sel = (
        "button:has-text('Candidature'), "   # FR — "Candidature simplifiée"
        "button:has-text('Enregistrer'), "   # FR — toujours présent sur les offres SPA
        "button:has-text('Apply'), "         # EN
        "button:has-text('Save')"            # EN fallback
    )
    try:
        session.page.wait_for_selector(content_ready_sel, timeout=20000)
        session.log("info", "Contenu offre chargé (bouton d'action détecté)")
    except Exception:
        # Timeout : attendre encore 5s de plus, le rendu React peut être lent
        _time.sleep(5)
        session.log("info", "Timeout contenu offre — tentative bouton après 5s supplémentaires")

    _time.sleep(2)  # laisser React finaliser le rendu des boutons d'action

    # ── Debug : cataloguer TOUS les éléments contenant "Candidature" ─────────
    try:
        dom_info = session.page.evaluate("""
            () => {
                const result = {buttons: [], candidatureElements: [], frames: window.frames.length};
                // Tous les boutons du DOM principal
                const btns = Array.from(document.querySelectorAll('button'));
                result.buttons = btns.map(b => ({
                    tag: b.tagName,
                    text: (b.innerText || b.textContent || '').trim().substring(0, 50),
                    aria: b.getAttribute('aria-label') || '',
                    disabled: b.disabled,
                    classes: b.className.substring(0, 60)
                }));
                // Tous les éléments contenant "candidature" (case insensitive)
                const all = Array.from(document.querySelectorAll('*'));
                for (const el of all) {
                    const ownText = Array.from(el.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim())
                        .join(' ');
                    if (ownText.toLowerCase().includes('candidature')) {
                        result.candidatureElements.push({
                            tag: el.tagName,
                            text: ownText.substring(0, 60),
                            aria: el.getAttribute('aria-label') || '',
                            role: el.getAttribute('role') || '',
                            classes: el.className.substring(0, 60)
                        });
                    }
                }
                return result;
            }
        """)
        btn_list = dom_info.get("buttons", [])
        cand_list = dom_info.get("candidatureElements", [])
        frames_count = dom_info.get("frames", 0)
        session.log("info",
            f"DOM: {len(btn_list)} boutons, {frames_count} iframes, "
            f"{len(cand_list)} élément(s) 'candidature'"
        )
        for b in btn_list[:20]:
            session.log("debug", f"  btn: '{b['text']}' aria='{b['aria']}' classes='{b['classes'][:40]}'")
        for c in cand_list[:5]:
            session.log("info",
                f"  candidature-el: <{c['tag']}> text='{c['text']}' "
                f"aria='{c['aria']}' role='{c['role']}'"
            )
    except Exception as dbg_e:
        session.log("debug", f"DOM debug error: {dbg_e}")

    # ── Chercher le bouton Apply ──────────────────────────────────────────────
    apply_btn = None

    # Méthode 1 : locator text (Playwright text engine — traverse Shadow DOM)
    for txt_needle in [
        "Candidature simplifiée",
        "Easy Apply",
        "Postuler facilement",
        "Candidature",
        "Postuler",
        "Apply",
    ]:
        try:
            # filter(has_text=) utilise le moteur de texte Playwright (Shadow DOM aware)
            candidate = session.page.locator("button").filter(has_text=txt_needle)
            cnt = candidate.count()
            if cnt > 0:
                apply_btn = candidate.first
                session.log("info", f"Bouton Apply trouvé via filter(has_text='{txt_needle}'): {cnt} résultat(s)")
                break
        except Exception:
            continue

    # Méthode 2 : get_by_text() — trouve n'importe quel élément avec ce texte
    if apply_btn is None:
        for txt_needle in ["Candidature simplifiée", "Easy Apply", "Candidature"]:
            try:
                candidate = session.page.get_by_text(txt_needle, exact=False)
                if candidate.count() > 0:
                    apply_btn = candidate.first
                    session.log("info", f"Bouton Apply trouvé via get_by_text('{txt_needle}')")
                    break
            except Exception:
                continue

    # Méthode 3 : get_by_role (accessible name matching — Shadow DOM aware)
    if apply_btn is None:
        for btn_name in ["Candidature", "Easy Apply", "Postuler facilement", "Postuler", "Apply"]:
            try:
                candidate = session.page.get_by_role("button", name=btn_name, exact=False)
                if candidate.count() > 0:
                    apply_btn = candidate.first
                    session.log("info", f"Bouton Apply trouvé via get_by_role: '{btn_name}'")
                    break
            except Exception:
                continue

    # Méthode 4 : JS avec traversal récursif du Shadow DOM + iframes
    if apply_btn is None:
        try:
            found = session.page.evaluate("""
                () => {
                    const keywords = ['candidature', 'easy apply', 'postuler facilement'];
                    function search(root) {
                        const btns = Array.from(root.querySelectorAll('button, [role="button"]'));
                        for (const btn of btns) {
                            const txt = (btn.innerText || btn.textContent || '').toLowerCase().trim();
                            const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
                            if (keywords.some(k => txt.startsWith(k) || aria.includes(k))) {
                                if (!btn.disabled && !btn.hasAttribute('disabled')) {
                                    btn.setAttribute('data-pw-target', 'apply');
                                    return txt || aria;
                                }
                            }
                        }
                        for (const el of root.querySelectorAll('*')) {
                            if (el.shadowRoot) {
                                const r = search(el.shadowRoot);
                                if (r) return r;
                            }
                        }
                        return null;
                    }
                    return search(document);
                }
            """)
            if found:
                apply_btn = session.page.locator("[data-pw-target='apply']").first
                session.log("info", f"Bouton Apply trouvé via JS shadow DOM: '{found}'")
        except Exception as e:
            session.log("debug", f"JS shadow search: {e}")

    # Méthode 5 : aria-label CSS fallback
    if apply_btn is None or not apply_btn.count():
        apply_btn = session.page.locator(
            "button.jobs-apply-button, "
            "button[aria-label*='Apply' i], "
            "button[aria-label*='Candidature' i], "
            "button[aria-label*='Postuler' i], "
            "[data-control-name*='apply' i]"
        ).first

    # Méthode 6 : chercher dans les iframes (LinkedIn embed)
    if apply_btn is None or not apply_btn.count():
        for frame in session.page.frames[1:]:  # skip main frame
            for txt in ["Candidature", "Easy Apply", "Apply"]:
                try:
                    candidate = frame.locator("button").filter(has_text=txt)
                    if candidate.count() > 0:
                        apply_btn = candidate.first
                        session.log("info", f"Bouton Apply trouvé dans iframe: '{txt}'")
                        break
                except Exception:
                    continue
            if apply_btn is not None and apply_btn.count() > 0:
                break

    if apply_btn is None or not apply_btn.count():
        screenshot = session.screenshot(f"noapply_{job.job_id}")
        return "skipped", f"Bouton Easy Apply non trouvé. Screenshot: {screenshot.name}"

    url_before = session.page.url
    try:
        # Essai 1 : click normal
        apply_btn.click(timeout=8000)
    except Exception:
        try:
            # Essai 2 : JS click (bypass overlay)
            _js_click(apply_btn)
        except Exception as e:
            return "failed", f"Click Apply (JS fallback): {e}"
    session.human_pause()

    # Vérifier si on a été redirigé vers un site externe (apply classique, pas Easy Apply)
    _time.sleep(2)
    url_after = session.page.url
    if "linkedin.com" not in url_after:
        return "skipped", f"Redirection externe : {url_after[:80]}"

    session.check_stop()

    # Attendre que le modal Easy Apply s'ouvre
    # LinkedIn 2025 : le modal a role="dialog" et contient un h3 ou h2 "Candidature simplifiée"
    MODAL_SEL = "[role='dialog'], .jobs-easy-apply-modal, [class*='easy-apply-modal']"
    try:
        session.page.wait_for_selector(MODAL_SEL, timeout=8000)
        session.log("info", "Modal Easy Apply ouvert")
    except Exception:
        session.log("info", "Pas de modal détecté — peut-être un formulaire page entière")

    # Screenshot initial du modal pour debug
    modal_screenshot = session.screenshot(f"modal_{job.job_id}")
    session.log("info", f"Screenshot modal : {modal_screenshot.name}")

    # Boucle "Suivant" -> "Soumettre". On limite a N etapes pour éviter boucle infinie.
    MAX_STEPS = 8
    prev_action = None   # détection de boucle
    for step in range(MAX_STEPS):
        session.check_stop()
        _time.sleep(1.5)

        # ── Debug boutons dans le modal ──────────────────────────────────────
        try:
            modal_btns = session.page.evaluate("""
                () => {
                    const dialog = document.querySelector("[role='dialog']");
                    const root = dialog || document.body;
                    return Array.from(root.querySelectorAll('button')).map(b => ({
                        text: (b.innerText || b.textContent || '').trim().substring(0, 60),
                        aria: b.getAttribute('aria-label') || '',
                        disabled: b.disabled
                    }));
                }
            """)
            session.log("info", f"Step {step} — boutons modal ({len(modal_btns)}) : "
                        + str([f"'{b['text']}|aria={b['aria']}'" for b in modal_btns[:8]]))
        except Exception:
            pass

        # Upload du CV généré si disponible.
        if cv_path:
            _upload_cv(session, cv_path, job)

        # Lettre : si un textarea cover letter est visible.
        if letter_text:
            try:
                ta = session.page.locator(
                    "textarea[id*='cover' i], textarea[id*='message' i], "
                    "textarea[id*='motivation' i]"
                ).first
                if ta.count() and ta.is_visible(timeout=1000):
                    ta.fill(letter_text[:3500])
                    session.human_pause()
            except Exception:
                pass

        # Auto-remplir TOUS les champs requis du modal :
        # radio buttons, selects, téléphone, salaire, années d'expérience.
        _autofill_all_fields(session)

        # ── Chercher les boutons de navigation du modal ──────────────────────
        # LinkedIn 2025 Easy Apply modal : les boutons sont dans [role='dialog']
        # et leurs labels changent selon la langue et la version.
        # On utilise filter(has_text) qui est robuste au changement de classes.

        def _find_modal_btn(text_needles: list[str]) -> object:
            """Cherche un bouton dans le modal par son texte visible."""
            # Priorité au dialog, fallback sur la page entière
            for container_sel in ("[role='dialog']", "body"):
                container = session.page.locator(container_sel)
                if not container.count():
                    continue
                for needle in text_needles:
                    try:
                        btn = container.locator("button").filter(has_text=needle)
                        if btn.count() > 0:
                            # Prendre le premier non-disabled
                            for i in range(btn.count()):
                                b = btn.nth(i)
                                if not _looks_disabled(b) and b.is_visible(timeout=500):
                                    return b
                    except Exception:
                        continue
            return None

        # ── Bouton Submit ─────────────────────────────────────────────────────
        submit_btn = _find_modal_btn([
            "Envoyer la candidature",
            "Submit application",
            "Envoyer ma candidature",
            "Soumettre",
            "Submit",
        ])
        if submit_btn:
            if not auto_submit:
                screenshot = session.screenshot(f"ready_{job.job_id}")
                session.log("info", f"Mode semi-auto : formulaire prêt. Screenshot: {screenshot.name}")
                return "skipped", f"Soumission désactivée (mode semi-auto). Screenshot: {screenshot.name}"
            try:
                submit_btn.click(timeout=5000)
                session.log("info", "Candidature soumise !")
                session.human_pause()
                _dismiss_confirmation(session)
                return "submitted", f"OK en {step + 1} étape(s)"
            except Exception as e:
                return "failed", f"Submit failed: {e}"

        # ── Bouton Réviser / Vérifier / Review (avant Submit) ────────────────
        review_btn = _find_modal_btn([
            "Réviser la candidature",
            "Review your application",
            "Vérifier",     # FR LinkedIn 2025 : bouton avant soumission finale
            "Réviser",
            "Review",
        ])
        if review_btn:
            # Détection de boucle : si on a déjà cliqué "Vérifier" et qu'on le retrouve,
            # c'est que la validation a échoué (champs requis vides).
            if prev_action == "review":
                screenshot = session.screenshot(f"stuck_{job.job_id}")
                return "skipped", (
                    f"Validation bloquée à l'étape {step} — champs requis non remplis. "
                    f"Screenshot: {screenshot.name}"
                )
            try:
                screenshot = session.screenshot(f"review_step{step}_{job.job_id}")
                session.log("info", f"Bouton Réviser cliqué (étape {step}) — screenshot: {screenshot.name}")
                review_btn.click(timeout=5000)
                prev_action = "review"
                session.human_pause()
                continue
            except Exception as e:
                session.log("debug", f"Review click failed: {e}")

        # ── Bouton Suivant / Next / Continuer ─────────────────────────────────
        next_btn = _find_modal_btn([
            "Suivant",
            "Continuer",
            "Next",
            "Continue",
        ])
        if next_btn:
            try:
                next_btn.click(timeout=5000)
                session.log("info", f"Bouton Suivant cliqué (étape {step})")
                prev_action = "next"
                session.human_pause()
                continue
            except Exception as e:
                return "failed", f"Next click failed: {e}"

        # Ni Submit ni Next exploitable → screenshot + abandon
        screenshot = session.screenshot(f"skipped_{job.job_id}")
        return "skipped", f"Etape {step} bloquée (pas de bouton Suivant/Submit). Screenshot: {screenshot.name}"

    return "skipped", f"Plus de {MAX_STEPS} étapes — abandon (formulaire trop long)"


def _upload_cv(session: BrowserSession, cv_path: str, job: Job) -> None:
    """Upload le CV généré dans le modal Easy Apply.

    LinkedIn cache le <input type="file"> derrière un bouton "Changer" /
    "Upload a different resume". Il faut d'abord cliquer ce bouton pour
    exposer le file input dans le DOM, puis appeler set_input_files().
    set_input_files() fonctionne sur les inputs cachés — pas besoin de is_visible().
    """
    import time as _t

    # Étape 1 : cliquer le bouton d'upload LinkedIn
    # LinkedIn FR 2025 : "Télécharger le CV" · EN : "Upload resume" · variantes selon version
    _change_btn_needles = [
        "Télécharger le CV",
        "Télécharger un CV",
        "Upload resume",
        "Upload a different resume",
        "Change resume",
        "Changer de CV",
        "Changer le CV",
        "Téléverser un CV différent",
        "Téléverser",
        "Changer",
    ]
    for needle in _change_btn_needles:
        try:
            btn = session.page.locator("button, a, label").filter(has_text=needle)
            if btn.count() > 0:
                btn.first.click(timeout=3000)
                session.log("info", f"Bouton '{needle}' cliqué — attente file input")
                _t.sleep(1.0)
                break
        except Exception:
            continue

    # Étape 2 : chercher le file input (visible ou caché — set_input_files fonctionne dans les deux cas)
    _file_input_sels = [
        "input[type='file'][accept*='pdf']",
        "input[type='file'][accept*='doc']",
        "input[type='file']",
    ]
    for sel in _file_input_sels:
        try:
            fi = session.page.locator(sel).first
            if fi.count() > 0:
                fi.set_input_files(cv_path)
                session.log("info", f"CV uploadé : {cv_path}")
                session.human_pause()
                return
        except Exception as e:
            session.log("debug", f"Upload tentative ({sel}) : {e}")
            continue

    session.log("warning", f"File input introuvable — CV non uploadé pour {job.title} @ {job.company}")


def _looks_disabled(locator) -> bool:
    try:
        return (locator.get_attribute("aria-disabled") or "").lower() == "true" or \
               locator.is_disabled()
    except Exception:
        return False


# Table d'auto-réponse pour les questions numériques LinkedIn Easy Apply.
# Clé : substring (lowercase) de la question  → réponse (string)
_AUTOFILL_TABLE: dict[str, str] = {
    "sql":              "3",
    "python":           "3",
    "java":             "2",
    "javascript":       "1",
    "r (langage":       "2",
    "machine learning": "3",
    "apprentissage auto": "3",
    "data":             "3",
    "excel":            "4",
    "power bi":         "2",
    "tableau":          "2",
    "spark":            "2",
    "hadoop":           "1",
    "azure":            "2",
    "aws":              "1",
    "docker":           "2",
    "git":              "4",
    "agile":            "3",
    "scrum":            "3",
    "marketing":        "0",   # hors profil → 0 = aucune expérience
    "commercial":       "0",
    "vente":            "0",
    "gestion de projet": "2",
    "management":       "1",
}

# Mots-clés indiquant une question sur les années d'expérience
_YEARS_KEYWORDS = [
    "combien d'années", "combien d'annees", "years of experience",
    "années d'expérience", "annees d'experience", "how many years",
    "depuis combien",
]


def _autofill_experience_fields(session: BrowserSession) -> int:
    """Remplit automatiquement les champs numériques du modal Easy Apply.

    Cible les questions du type "Depuis combien d'années utilisez-vous X ?".
    Retourne le nombre de champs remplis.
    """
    import time as _t
    filled = 0
    try:
        # Chercher tous les inputs text/number visibles dans le modal ou la page
        fields_info = session.page.evaluate("""
            () => {
                // LinkedIn Easy Apply modal est un overlay fixed — offsetParent est null.
                // On cherche donc dans tout le body sans filtre offsetParent.
                const results = [];
                const inputs = Array.from(document.querySelectorAll(
                    'input[type="text"], input[type="number"], input:not([type])'
                ));
                for (const inp of inputs) {
                    // Vérifier la visibilité par getComputedStyle (fonctionne pour fixed)
                    const style = window.getComputedStyle(inp);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    if (inp.value && inp.value.trim()) continue;  // déjà rempli
                    // Trouver le label associé
                    let labelText = '';
                    const id = inp.id;
                    if (id) {
                        const lbl = document.querySelector('label[for="' + id + '"]');
                        if (lbl) labelText = lbl.innerText || lbl.textContent || '';
                    }
                    if (!labelText) {
                        // Chercher dans les parents (jusqu'à 5 niveaux)
                        let el = inp.parentElement;
                        for (let i = 0; i < 5; i++) {
                            if (!el) break;
                            const lbl = el.querySelector('label');
                            if (lbl) { labelText = lbl.innerText || lbl.textContent || ''; break; }
                            // Aussi chercher un span/div avec le texte de question
                            const spans = el.querySelectorAll('span, div, p');
                            for (const s of spans) {
                                const txt = (s.innerText || '').trim();
                                if (txt.length > 5 && txt.length < 200) {
                                    labelText = txt;
                                    break;
                                }
                            }
                            if (labelText) break;
                            el = el.parentElement;
                        }
                    }
                    results.push({
                        id: inp.id || '',
                        name: inp.name || '',
                        placeholder: inp.placeholder || '',
                        labelText: labelText.trim().toLowerCase()
                    });
                }
                return results;
            }
        """)
        for field in fields_info:
            label = field.get("labelText", "").lower()
            field_id = field.get("id", "")
            # Vérifier si c'est une question d'années d'expérience
            if not any(kw in label for kw in _YEARS_KEYWORDS):
                continue
            # Trouver la technologie mentionnée
            answer = "2"  # valeur par défaut
            for tech, val in _AUTOFILL_TABLE.items():
                if tech in label:
                    answer = val
                    break
            # Remplir le champ
            try:
                if field_id:
                    inp = session.page.locator(f"#{field_id}").first
                else:
                    inp = session.page.locator(
                        f"input[name='{field.get('name', '')}']"
                    ).first
                if inp.count() and inp.is_visible(timeout=500):
                    inp.fill(answer)
                    session.log("info", f"Auto-fill: '{label[:50]}' → {answer}")
                    filled += 1
                    _t.sleep(0.2)
            except Exception as e:
                session.log("debug", f"Auto-fill error ({label[:30]}): {e}")
    except Exception as e:
        session.log("debug", f"_autofill_experience_fields: {e}")
    return filled


def _load_apply_profile() -> dict:
    """Charge les données de profil depuis user_profile.json."""
    try:
        from .config import USER_PROFILE_JSON
        if USER_PROFILE_JSON.exists():
            import json as _json
            return _json.loads(USER_PROFILE_JSON.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


# ── Tables pour l'auto-remplissage des champs requis ────────────────────────
# Radio buttons : legend (lowercase) → réponse attendue ("oui" / "non" / "yes" / "no")
_RADIO_ANSWERS: list[tuple[str, str]] = [
    # Autorisation de travail → Oui
    ("légalement autorisé",     "oui"),
    ("autorisé à travailler",   "oui"),
    ("authorized to work",      "yes"),
    ("work authorization",      "yes"),
    ("right to work",           "yes"),
    ("droit de travailler",     "oui"),
    ("legally authorized",      "yes"),
    # Visa / sponsorship → Non/No
    # "no" est contenu dans "non" (FR) ET dans "no" (EN) → fonctionne dans les deux langues
    ("visa",                    "no"),
    ("sponsorship",             "no"),
    ("parrainage",              "no"),
    ("sponsor",                 "no"),
    # Télétravail / disponibilité → Oui
    ("télétravail",             "oui"),
    ("remote",                  "yes"),
    ("hybride",                 "oui"),
    ("hybrid",                  "yes"),
    ("disponible",              "oui"),
    ("available",               "yes"),
]

# Mots-clés pour le téléphone (champ text)
_PHONE_KEYWORDS = ["téléphone", "phone", "mobile", "portable", "numéro de contact", "tel"]
# Mots-clés pour le salaire
_SALARY_KEYWORDS = ["salaire", "salary", "prétention", "rémunération", "pretention", "remuneration",
                    "compensation", "expected salary"]
# Mots-clés pour le code postal
_ZIP_KEYWORDS = ["code postal", "zip", "postal code"]

# Salaire cible par défaut (brut annuel FR)
_DEFAULT_SALARY = "55000"


def _autofill_all_fields(session: BrowserSession) -> None:
    """Remplit tous les champs requis visibles dans le modal Easy Apply.

    Gère dans l'ordre :
    1. Radio buttons requis (autorisation travail, visa, etc.)
    2. Select / combobox requis (premier choix valide)
    3. Champs texte requis (téléphone, salaire, code postal)
    4. Champs numériques "années d'expérience"
    5. Checkboxes requises
    """
    _autofill_radio_fields(session)
    _autofill_select_fields(session)
    _autofill_contact_fields(session)
    _autofill_experience_fields(session)
    _autofill_checkbox_fields(session)


def _autofill_radio_fields(session: BrowserSession) -> int:
    """Coche les radio buttons requis non remplis.

    Stratégie :
    - Si la question contient un mot-clé "autorisation travail" → choisir "Oui"
    - Si la question contient "visa/sponsorship" → choisir "Non"
    - Sinon → choisir le 1er bouton radio disponible (souvent "Oui")

    Retourne le nombre de groupes remplis.
    """
    import time as _t
    filled = 0
    try:
        groups = session.page.evaluate("""
            () => {
                const results = [];
                // Chercher dans le modal ou sur la page entière
                const root = document.querySelector("[role='dialog']") || document.body;
                const fieldsets = Array.from(root.querySelectorAll('fieldset'));
                for (const fs of fieldsets) {
                    const radios = Array.from(fs.querySelectorAll('input[type="radio"]'));
                    if (radios.length === 0) continue;
                    // Ignorer les groupes déjà cochés
                    if (radios.some(r => r.checked)) continue;
                    // Obtenir le texte de la question (legend > span ou legend direct)
                    const legend = fs.querySelector('legend');
                    let legendText = '';
                    if (legend) {
                        legendText = (legend.innerText || legend.textContent || '').trim().toLowerCase();
                    }
                    // Construire la liste des options
                    const options = radios.map(r => {
                        let lblText = '';
                        if (r.id) {
                            const lbl = document.querySelector('label[for="' + r.id + '"]');
                            if (lbl) lblText = (lbl.innerText || lbl.textContent || '').trim().toLowerCase();
                        }
                        // Fallback: parent label
                        if (!lblText) {
                            const pLabel = r.closest('label');
                            if (pLabel) lblText = (pLabel.innerText || pLabel.textContent || '').trim().toLowerCase();
                        }
                        return {id: r.id, value: r.value, label: lblText};
                    });
                    results.push({legend: legendText, options});
                }
                return results;
            }
        """)

        profile = _load_apply_profile()

        for group in groups:
            legend = group.get("legend", "")
            options = group.get("options", [])
            if not options:
                continue

            # Déterminer la réponse cible
            target_answer = None
            for keyword, answer in _RADIO_ANSWERS:
                if keyword in legend:
                    target_answer = answer
                    break

            if target_answer is None:
                # Par défaut : premier bouton disponible
                chosen = options[0]
            else:
                # Chercher l'option dont le label correspond ("oui", "non", "yes", "no")
                chosen = None
                for opt in options:
                    if target_answer in opt.get("label", ""):
                        chosen = opt
                        break
                # Fallback si pas trouvé : premier bouton
                if chosen is None:
                    chosen = options[0]

            # Cliquer sur le radio button sélectionné
            if not chosen.get("id"):
                continue
            try:
                radio = session.page.locator(f"#{chosen['id']}").first
                if radio.count() and not radio.is_checked(timeout=500):
                    radio.check(timeout=3000)
                    session.log("info",
                        f"Radio auto-fill: '{legend[:60]}' → '{chosen.get('label','')[:30]}'")
                    filled += 1
                    _t.sleep(0.3)
            except Exception as e:
                session.log("debug", f"Radio check error ({legend[:30]}): {e}")

    except Exception as e:
        session.log("debug", f"_autofill_radio_fields: {e}")
    return filled


def _autofill_select_fields(session: BrowserSession) -> int:
    """Remplit les <select> requis avec le 1er choix valide.

    Retourne le nombre de selects remplis.
    """
    import time as _t
    filled = 0
    try:
        selects_info = session.page.evaluate("""
            () => {
                const root = document.querySelector("[role='dialog']") || document.body;
                const results = [];
                const selects = Array.from(root.querySelectorAll('select'));
                for (const sel of selects) {
                    const style = window.getComputedStyle(sel);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    // Déjà une valeur non-vide ?
                    if (sel.value && sel.value !== '' && sel.selectedIndex > 0) continue;
                    const lbl = sel.id ? document.querySelector('label[for="' + sel.id + '"]') : null;
                    const lblText = lbl ? (lbl.innerText || lbl.textContent || '').trim().toLowerCase() : '';
                    const opts = Array.from(sel.options).map(o => ({value: o.value, text: o.text}));
                    results.push({id: sel.id || '', name: sel.name || '', label: lblText, options: opts});
                }
                return results;
            }
        """)

        for sel_info in selects_info:
            sel_id = sel_info.get("id", "")
            opts = sel_info.get("options", [])
            label = sel_info.get("label", "")
            # Trouver le premier choix non-vide (ignorer placeholders)
            chosen_value = None
            for opt in opts:
                v = opt.get("value", "")
                t = opt.get("text", "").lower().strip()
                if v and v not in ("", "0", "-1") and t not in (
                    "sélectionner une option", "select an option",
                    "select", "sélectionner", "-- select --", "--", "choose"
                ):
                    chosen_value = v
                    break
            if chosen_value is None:
                continue
            try:
                if sel_id:
                    sel_loc = session.page.locator(f"select#{sel_id}").first
                else:
                    sel_loc = session.page.locator(f"select[name='{sel_info.get('name','')}']").first
                if sel_loc.count():
                    sel_loc.select_option(value=chosen_value)
                    session.log("info", f"Select auto-fill: '{label[:50]}' → '{chosen_value[:30]}'")
                    filled += 1
                    _t.sleep(0.3)
            except Exception as e:
                session.log("debug", f"Select fill error ({label[:30]}): {e}")

    except Exception as e:
        session.log("debug", f"_autofill_select_fields: {e}")
    return filled


def _autofill_contact_fields(session: BrowserSession) -> int:
    """Remplit les champs de contact requis : téléphone, salaire, code postal.

    Retourne le nombre de champs remplis.
    """
    import time as _t
    filled = 0
    profile = _load_apply_profile()
    phone_value = profile.get("phone", "").strip()
    salary_value = (profile.get("salary_expectation") or _DEFAULT_SALARY).strip()

    try:
        fields_info = session.page.evaluate("""
            () => {
                const root = document.querySelector("[role='dialog']") || document.body;
                const results = [];
                const inputs = Array.from(root.querySelectorAll(
                    'input[type="text"], input[type="number"], input[type="tel"], input:not([type])'
                ));
                for (const inp of inputs) {
                    const style = window.getComputedStyle(inp);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    if (inp.value && inp.value.trim()) continue;  // déjà rempli
                    let labelText = '';
                    if (inp.id) {
                        const lbl = document.querySelector('label[for="' + inp.id + '"]');
                        if (lbl) labelText = (lbl.innerText || lbl.textContent || '').trim().toLowerCase();
                    }
                    if (!labelText) {
                        let el = inp.parentElement;
                        for (let i = 0; i < 5; i++) {
                            if (!el) break;
                            const lbl = el.querySelector('label');
                            if (lbl) {
                                labelText = (lbl.innerText || lbl.textContent || '').trim().toLowerCase();
                                break;
                            }
                            el = el.parentElement;
                        }
                    }
                    if (!labelText) {
                        // Dernier recours: placeholder
                        labelText = (inp.placeholder || '').toLowerCase();
                    }
                    results.push({id: inp.id || '', name: inp.name || '',
                                  label: labelText, inputType: inp.type || 'text'});
                }
                return results;
            }
        """)

        for field in fields_info:
            label = field.get("label", "").lower()
            field_id = field.get("id", "")
            input_type = field.get("inputType", "text")

            # Classifier le champ
            fill_value = None
            if any(kw in label for kw in _PHONE_KEYWORDS) or input_type == "tel":
                fill_value = phone_value or "+33600000000"
            elif any(kw in label for kw in _SALARY_KEYWORDS):
                fill_value = salary_value
            elif any(kw in label for kw in _ZIP_KEYWORDS):
                fill_value = profile.get("postal_code", "75001")
            else:
                # Ne pas remplir les champs non identifiés avec données de contact
                continue

            try:
                if field_id:
                    inp = session.page.locator(f"#{field_id}").first
                else:
                    name = field.get("name", "")
                    inp = session.page.locator(f"input[name='{name}']").first
                if inp.count() and inp.is_visible(timeout=500):
                    inp.fill(fill_value)
                    session.log("info", f"Contact auto-fill: '{label[:50]}' → '{fill_value[:20]}'")
                    filled += 1
                    _t.sleep(0.2)
            except Exception as e:
                session.log("debug", f"Contact fill error ({label[:30]}): {e}")

    except Exception as e:
        session.log("debug", f"_autofill_contact_fields: {e}")
    return filled


def _autofill_checkbox_fields(session: BrowserSession) -> int:
    """Coche les checkboxes requises non cochées (consentements, CGU...).

    Retourne le nombre de checkboxes cochées.
    """
    import time as _t
    filled = 0
    try:
        checkboxes = session.page.evaluate("""
            () => {
                const root = document.querySelector("[role='dialog']") || document.body;
                const results = [];
                const cbs = Array.from(root.querySelectorAll('input[type="checkbox"]'));
                for (const cb of cbs) {
                    if (cb.checked) continue;
                    const style = window.getComputedStyle(cb);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    const isRequired = cb.required || cb.getAttribute('aria-required') === 'true';
                    if (!isRequired) continue;
                    results.push({id: cb.id || '', name: cb.name || ''});
                }
                return results;
            }
        """)
        for cb_info in checkboxes:
            cb_id = cb_info.get("id", "")
            try:
                if cb_id:
                    cb = session.page.locator(f"#{cb_id}").first
                else:
                    cb = session.page.locator(f"input[type='checkbox'][name='{cb_info.get('name','')}']").first
                if cb.count() and not cb.is_checked(timeout=500):
                    cb.check(timeout=3000)
                    session.log("info", f"Checkbox auto-checked (id={cb_id})")
                    filled += 1
                    _t.sleep(0.2)
            except Exception as e:
                session.log("debug", f"Checkbox check error (id={cb_id}): {e}")
    except Exception as e:
        session.log("debug", f"_autofill_checkbox_fields: {e}")
    return filled


def _dismiss_confirmation(session: BrowserSession) -> None:
    """Ferme le modal de confirmation post-soumission si présent."""
    for sel in (
        "button[aria-label='Dismiss']",
        "button[aria-label='Ignorer']",
        "button[aria-label*='close' i]",
    ):
        try:
            btn = session.page.locator(sel).first
            if btn.count() and btn.is_visible():
                btn.click()
                return
        except Exception:
            continue
