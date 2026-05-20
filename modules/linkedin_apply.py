"""LinkedIn — Easy Apply.

Stratégie : ne tenter que les offres "Easy Apply" (filtre `f_AL=true`).
Pour les formulaires multi-étapes complexes ou avec questions custom, on
abandonne proprement (status='skipped') plutôt que de soumettre du contenu
inventé.

⚠ ATTENTION : automatiser LinkedIn viole les CGU (User Agreement §8.2).
Risque réel de bannissement définitif du compte. À tes risques et périls.

⚠ Les sélecteurs LinkedIn changent souvent. Vérifie-les si tu observes
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
def search_jobs(
    session: BrowserSession,
    *,
    keywords: str,
    location: str = "",
    max_results: int = 10,
) -> list[Job]:
    """Récupère jusqu'à `max_results` offres Easy Apply correspondant aux critères."""
    url = SEARCH_URL_TEMPLATE.format(
        keywords=urllib.parse.quote(keywords or ""),
        location=urllib.parse.quote(location or ""),
    )
    session.log("info", f"LinkedIn — recherche : {url}")
    session.page.goto(url, wait_until="domcontentloaded")
    session.human_pause()

    # Scroll progressif dans la liste de gauche pour charger les cards en lazy-load.
    jobs: dict[str, Job] = {}
    last_count = -1
    rounds = 0
    while len(jobs) < max_results and rounds < 8:
        session.check_stop()
        rounds += 1
        # Itère les cards visibles.
        cards = session.page.locator("li[data-occludable-job-id], div.job-card-container")
        count = cards.count()
        for i in range(count):
            card = cards.nth(i)
            try:
                job_id = card.get_attribute("data-occludable-job-id") or ""
                if not job_id:
                    # Fallback : extraire de l'attribut data-job-id du parent.
                    job_id = card.get_attribute("data-job-id") or ""
                title_el = card.locator("a.job-card-list__title, a.job-card-container__link").first
                comp_el = card.locator(
                    "h4.job-card-container__company-name, span.job-card-container__primary-description"
                ).first
                title = clean_title(title_el.inner_text(timeout=2000)) if title_el.count() else ""
                company = clean_title(comp_el.inner_text(timeout=2000)) if comp_el.count() else ""
                href = title_el.get_attribute("href") if title_el.count() else None
                if not href:
                    continue
                full_url = href if href.startswith("http") else f"https://www.linkedin.com{href}"
                key = job_id or full_url
                if key not in jobs:
                    jobs[key] = Job(job_id=job_id or key, title=title, company=company, url=full_url)
                    if len(jobs) >= max_results:
                        break
            except Exception as e:
                session.log("debug", f"card parse error: {e}")

        if len(jobs) == last_count:
            break  # plus rien ne charge
        last_count = len(jobs)
        # Scroll le panneau gauche pour charger la suite.
        try:
            scroller = session.page.locator("div.jobs-search-results-list").first
            if scroller.count():
                scroller.evaluate("el => el.scrollBy(0, 1200)")
        except Exception:
            session.page.mouse.wheel(0, 1200)
        session.human_pause()

    result = list(jobs.values())[:max_results]
    session.log("info", f"LinkedIn — {len(result)} offre(s) Easy Apply trouvée(s)")
    return result


# ── Candidature ──────────────────────────────────────────────────────────────
def apply_to_job(
    session: BrowserSession,
    job: Job,
    *,
    cv_path: str = "",
    letter_text: str = "",
    auto_submit: bool = True,
) -> tuple[str, str]:
    """Tente Easy Apply sur une offre. Retourne (status, notes).

    status ∈ {"submitted", "skipped", "failed"}.
    - submitted : formulaire envoyé.
    - skipped   : modal multi-étapes ou questions non remplies — pas de soumission.
    - failed    : erreur Playwright (timeout, sélecteur introuvable, etc.).
    """
    session.log("info", f"LinkedIn — ouverture : {job.title} @ {job.company}")
    session.page.goto(job.url, wait_until="domcontentloaded")
    session.human_pause()
    session.check_stop()

    # Bouton "Postuler" Easy Apply.
    apply_btn = session.page.locator(
        "button.jobs-apply-button:not(.artdeco-button--disabled), "
        "button[aria-label*='Easy Apply' i], button[aria-label*='Postuler' i]"
    ).first
    if not apply_btn.count():
        return "skipped", "Bouton Easy Apply introuvable (offre externe ?)"

    try:
        apply_btn.click()
    except Exception as e:
        return "failed", f"Click Apply: {e}"
    session.human_pause()
    session.check_stop()

    # Boucle "Suivant" → "Soumettre". On limite à N étapes pour éviter une boucle infinie.
    MAX_STEPS = 6
    for step in range(MAX_STEPS):
        session.check_stop()
        # Si CV requis et un input file existe, on uploade.
        if cv_path:
            try:
                file_input = session.page.locator("input[type='file']").first
                if file_input.count() and file_input.is_visible():
                    file_input.set_input_files(cv_path)
                    session.log("info", "CV uploadé")
                    session.human_pause()
            except Exception:
                pass

        # Lettre : si un textarea "Cover letter" est visible.
        if letter_text:
            try:
                ta = session.page.locator(
                    "textarea[id*='cover' i], textarea[id*='message' i], textarea[id*='motivation' i]"
                ).first
                if ta.count() and ta.is_visible():
                    ta.fill(letter_text[:3500])
                    session.human_pause()
            except Exception:
                pass

        # Détecte le bouton actif : Submit / Review / Next.
        submit_btn = session.page.locator(
            "button[aria-label='Submit application'], "
            "button[aria-label='Envoyer ma candidature'], "
            "button[aria-label*='Submit' i]"
        ).first
        if submit_btn.count() and submit_btn.is_visible():
            if not auto_submit:
                return "skipped", "Soumission désactivée (mode semi-auto)"
            try:
                submit_btn.click()
                session.log("info", "Candidature soumise")
                session.human_pause()
                # Ferme modal de confirmation.
                _dismiss_confirmation(session)
                return "submitted", f"OK en {step + 1} étape(s)"
            except Exception as e:
                return "failed", f"Submit failed: {e}"

        next_btn = session.page.locator(
            "button[aria-label='Continue to next step'], "
            "button[aria-label='Continuer vers l’étape suivante'], "
            "button[aria-label*='Next' i], button[aria-label*='Suivant' i], "
            "button[aria-label*='Review' i], button[aria-label*='Vérifier' i]"
        ).first
        if next_btn.count() and next_btn.is_visible() and not _looks_disabled(next_btn):
            try:
                next_btn.click()
            except Exception as e:
                return "failed", f"Next click failed: {e}"
            session.human_pause()
            continue

        # Ni Submit ni Next exploitable → questions custom non remplies.
        screenshot = session.screenshot(f"skipped_{job.job_id}")
        return "skipped", f"Étape bloquée (questions custom). Screenshot: {screenshot.name}"

    return "skipped", f"Plus de {MAX_STEPS} étapes — abandon (formulaire long)"


def _looks_disabled(locator) -> bool:
    try:
        return (locator.get_attribute("aria-disabled") or "").lower() == "true" or \
               locator.is_disabled()
    except Exception:
        return False


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
