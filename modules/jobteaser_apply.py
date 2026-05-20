"""JobTeaser — candidature rapide.

Scaffold de candidature. Les sélecteurs sont à vérifier sur le site car
JobTeaser change régulièrement son DOM (et a un mode candidat / mode école
qui change selon ton compte).

Stratégie de base :
1. Aller sur la page de recherche.
2. Récupérer les cards d'offres.
3. Pour chaque offre, ouvrir la fiche puis cliquer "Postuler".
4. Sur la modale : uploader le CV, coller la lettre, soumettre.
"""

from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass

from .browser_manager import BrowserSession, StopRequested
from .letter_generator import clean_title

logger = logging.getLogger(__name__)

LOGIN_URL = "https://www.jobteaser.com/fr/users/sign_in"
READY_SELECTOR = "button[data-testid='user-menu-button'], a[href*='/users/profile']"

SEARCH_URL_TEMPLATE = (
    "https://www.jobteaser.com/fr/job-offers?query={keywords}&location={location}"
)


@dataclass
class Job:
    job_id: str
    title: str
    company: str
    url: str


def search_jobs(
    session: BrowserSession,
    *,
    keywords: str,
    location: str = "",
    max_results: int = 10,
) -> list[Job]:
    url = SEARCH_URL_TEMPLATE.format(
        keywords=urllib.parse.quote(keywords or ""),
        location=urllib.parse.quote(location or ""),
    )
    session.log("info", f"JobTeaser — recherche : {url}")
    session.page.goto(url, wait_until="domcontentloaded")
    session.human_pause()

    jobs: list[Job] = []
    cards = session.page.locator("a[href*='/job-offers/'], a[data-testid*='job-card']")
    count = min(cards.count(), max_results * 2)  # marge si certains sont des liens "vide"
    for i in range(count):
        if len(jobs) >= max_results:
            break
        c = cards.nth(i)
        try:
            href = c.get_attribute("href") or ""
            if "/job-offers/" not in href:
                continue
            full_url = href if href.startswith("http") else f"https://www.jobteaser.com{href}"
            job_id = full_url.rstrip("/").split("/")[-1]
            title = clean_title(c.inner_text(timeout=1500)) or "(sans titre)"
            jobs.append(Job(job_id=job_id, title=title[:120], company="", url=full_url))
        except Exception as e:
            session.log("debug", f"card parse: {e}")
        session.check_stop()

    session.log("info", f"JobTeaser — {len(jobs)} offre(s) candidates")
    return jobs


def apply_to_job(
    session: BrowserSession,
    job: Job,
    *,
    cv_path: str = "",
    letter_text: str = "",
    auto_submit: bool = True,
) -> tuple[str, str]:
    session.log("info", f"JobTeaser — ouverture : {job.title}")
    session.page.goto(job.url, wait_until="domcontentloaded")
    session.human_pause()
    session.check_stop()

    # Récupère le nom d'entreprise si possible.
    try:
        comp_el = session.page.locator(
            "[data-testid='company-name'], a[href*='/companies/']"
        ).first
        if comp_el.count():
            job.company = clean_title(comp_el.inner_text(timeout=1500))
    except Exception:
        pass

    apply_btn = session.page.locator(
        "button:has-text('Postuler'), a:has-text('Postuler')"
    ).first
    if not apply_btn.count():
        return "skipped", "Bouton Postuler introuvable (offre externe ?)"

    try:
        apply_btn.click()
    except Exception as e:
        return "failed", f"Click Postuler: {e}"
    session.human_pause()
    session.check_stop()

    # Upload CV.
    if cv_path:
        try:
            file_input = session.page.locator("input[type='file']").first
            if file_input.count():
                file_input.set_input_files(cv_path)
                session.log("info", "CV uploadé")
                session.human_pause()
        except Exception as e:
            session.log("warning", f"Upload CV: {e}")

    # Lettre de motivation : textarea visible.
    if letter_text:
        try:
            ta = session.page.locator("textarea").first
            if ta.count() and ta.is_visible():
                ta.fill(letter_text[:3500])
                session.human_pause()
        except Exception as e:
            session.log("warning", f"Fill lettre: {e}")

    # Soumission.
    submit = session.page.locator(
        "button[type='submit']:has-text('Envoyer'), "
        "button:has-text('Envoyer ma candidature'), "
        "button:has-text('Postuler')"
    ).last  # le dernier bouton "Postuler" est en général celui de soumission
    if not submit.count() or not submit.is_visible():
        screenshot = session.screenshot(f"jt_skipped_{job.job_id}")
        return "skipped", f"Bouton Envoyer introuvable. Screenshot: {screenshot.name}"

    if not auto_submit:
        return "skipped", "Soumission désactivée (mode semi-auto)"

    try:
        submit.click()
        session.log("info", "Candidature envoyée")
        session.human_pause()
        return "submitted", "OK"
    except Exception as e:
        return "failed", f"Submit: {e}"
