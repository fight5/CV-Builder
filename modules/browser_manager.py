"""Wrapper Playwright pour les modules de candidature.

Responsabilités :
- Lancer Chromium (headed ou headless).
- Charger/sauvegarder les cookies par plateforme (storage_state).
- Centraliser la journalisation des actions (vers UI + fichier).
- Capturer un screenshot horodaté à la demande ou sur erreur.
- Vérifier le stop-flag entre chaque action — l'utilisateur peut interrompre.

S'utilise comme context manager :

    with BrowserSession("linkedin", headless=False, logger=evt) as s:
        s.page.goto("https://www.linkedin.com/jobs/")
        ...
"""

from __future__ import annotations

import json
import logging
import random
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import config, file_manager

logger = logging.getLogger(__name__)

# Type d'un logger d'événement (UI ou stdout).
EventLogger = Callable[[str, str], None]  # (level, message)

# Profils persistants Playwright (un dossier par plateforme).
# Un profil persistant est reconnu par les sites (PerimeterX, etc.) comme un
# "vrai" navigateur car il conserve l'historique JS, localStorage, IndexedDB.
PERSISTENT_PROFILES_DIR = config.JOB_AGENT_HOME / "playwright_profiles"

# Plateformes qui BÉNÉFICIENT du profil persistant (anti-bot avancé).
PERSISTENT_PLATFORMS = {"linkedin"}


def _find_chrome_executable() -> Optional[str]:
    """Retourne le chemin de Chrome/Edge système si le Chromium bundlé Playwright manque de VC++."""
    from pathlib import Path
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for p in candidates:
        if p.exists():
            logger.debug("Navigateur systeme utilise : %s", p)
            return str(p)
    return None


def _default_event_logger(level: str, message: str) -> None:
    logger.log(getattr(logging, level.upper(), logging.INFO), message)


class StopRequested(RuntimeError):
    """Levée quand l'utilisateur clique 'Arrêter' (stop-flag détecté)."""


@dataclass
class BrowserSession:
    """Contexte Playwright persistant par plateforme.

    À utiliser comme context manager. Sauvegarde automatique du storage_state
    à la sortie si la session a abouti à un login.
    """

    platform: str
    headless: bool = config.DEFAULT_HEADLESS
    event_logger: EventLogger = field(default=_default_event_logger)
    timeout_ms: int = config.DEFAULT_TIMEOUT_MS
    user_agent: Optional[str] = None

    # Internals
    _pw = None
    _browser = None       # None si profil persistant (context = browser)
    _context = None
    _profile_dir: Optional[Path] = None  # défini si profil persistant
    page = None  # type: ignore[assignment]

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def __enter__(self) -> "BrowserSession":
        # Import différé : Playwright n'est requis qu'au runtime navigateur.
        from playwright.sync_api import sync_playwright

        file_manager.ensure_directories()
        self._pw = sync_playwright().start()

        # Args anti-détection (communs aux deux modes).
        # NOTE : pas de --no-sandbox ici — on laisse Chrome tourner avec son sandbox normal.
        stealth_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--disable-notifications",
            "--suppress-message-center-popups",
        ]

        use_persistent = (self.platform in PERSISTENT_PLATFORMS) and (not self.headless)

        if use_persistent:
            # ── Mode profil persistant ─────────────────────────────────────
            # Un seul dossier par plateforme. LinkedIn (et PerimeterX) reconnaît
            # le même "navigateur" d'une session à l'autre.
            self._profile_dir = PERSISTENT_PROFILES_DIR / self.platform
            self._profile_dir.mkdir(parents=True, exist_ok=True)

            try:
                self._context = self._pw.chromium.launch_persistent_context(
                    str(self._profile_dir),
                    executable_path=_find_chrome_executable(),
                    headless=False,
                    args=stealth_args,
                    viewport={"width": 1280, "height": 800},
                    locale="fr-FR",
                    timezone_id="Europe/Paris",
                    ignore_https_errors=True,
                )
                self.log("info", f"Profil persistant chargé : {self._profile_dir}")
            except Exception as e:
                # Fallback si le profil est verrouillé (autre process)
                self.log("warning", f"Profil persistant inaccessible ({e}) — fallback classique")
                use_persistent = False

        if not use_persistent:
            # ── Mode classique (storage_state JSON) ───────────────────────
            self._browser = self._pw.chromium.launch(
                headless=self.headless,
                executable_path=_find_chrome_executable(),
                args=stealth_args,
            )
            cookies_path = self._cookies_path()
            storage = str(cookies_path) if cookies_path.exists() else None
            context_kwargs: dict[str, Any] = {
                "viewport": {"width": 1280, "height": 800},
                "locale": "fr-FR",
                "timezone_id": "Europe/Paris",
            }
            if storage:
                context_kwargs["storage_state"] = storage
            if self.user_agent:
                context_kwargs["user_agent"] = self.user_agent

            self._context = self._browser.new_context(**context_kwargs)

        self._context.set_default_timeout(self.timeout_ms)

        # Stealth v2 : masque navigator.webdriver et autres fingerprints.
        try:
            from playwright_stealth import Stealth
            Stealth().apply_stealth_sync(self._context)
            logger.info("playwright-stealth v2 appliqué")
        except ImportError:
            logger.warning("playwright-stealth non installé")
        except Exception as e:
            logger.warning("playwright-stealth erreur : %s", e)

        # Pour le profil persistant, une page est parfois déjà ouverte.
        pages = self._context.pages
        self.page = pages[0] if pages else self._context.new_page()

        self.log("info", f"Browser ready (platform={self.platform}, headless={self.headless}, persistent={use_persistent})")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # En mode classique : sauvegarde storage_state JSON.
        # En mode persistant : le profil est auto-sauvegardé par Chromium.
        if self._profile_dir is None:
            try:
                if self._context is not None:
                    self.save_cookies()
            except Exception as e:  # pragma: no cover
                self.log("warning", f"save_cookies failed: {e}")
        try:
            if self._context is not None:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        self.log("info", "Browser closed")

    # ── Cookies / storage_state ──────────────────────────────────────────────
    def _cookies_path(self) -> Path:
        return config.COOKIES_DIR / f"{self.platform}.json"

    def save_cookies(self) -> Path:
        path = self._cookies_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=str(path))
        return path

    def has_saved_session(self) -> bool:
        """Vrai si une session sauvegardée existe (profil persistant OU storage_state JSON)."""
        profile_dir = PERSISTENT_PROFILES_DIR / self.platform
        if profile_dir.exists() and any(profile_dir.iterdir()):
            return True
        return self._cookies_path().exists()

    # ── Logging + screenshots ────────────────────────────────────────────────
    def log(self, level: str, message: str) -> None:
        self.event_logger(level, message)

    def screenshot(self, name_hint: str = "") -> Path:
        """Capture l'écran courant et retourne le chemin du PNG."""
        stamp = file_manager.utc_now_iso().replace(":", "").replace("-", "")[:13]
        slug = file_manager.slugify(name_hint or self.platform)
        path = config.SCREENSHOTS_DIR / f"{stamp}_{self.platform}_{slug}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.page.screenshot(path=str(path), full_page=True)
        except Exception as e:
            self.log("warning", f"Screenshot failed: {e}")
        return path

    # ── Humanisation + stop-flag ─────────────────────────────────────────────
    def human_pause(self) -> None:
        """Petit délai entre actions. NB : ce n'est PAS un contournement anti-bot."""
        lo, hi = config.HUMAN_DELAY_MS_MIN, config.HUMAN_DELAY_MS_MAX
        time.sleep(random.uniform(lo / 1000, hi / 1000))

    def check_stop(self) -> None:
        """À appeler entre chaque action lourde. Lève StopRequested si demandé."""
        if file_manager.stop_requested():
            self.log("warning", "Stop demandé par l'utilisateur — interruption propre.")
            raise StopRequested("Interrupted by user")

    # ── Helpers de connexion manuelle ────────────────────────────────────────
    # ── Helpers de détection login ────────────────────────────────────────────
    def _has_auth_cookie(self, cookie_name: str) -> bool:
        """Vérifie si un cookie d'authentification est présent dans le contexte.

        Fonctionne même pour les cookies HTTP-only (Playwright peut les lire).
        Ex: li_at = token d'accès LinkedIn.
        """
        try:
            cookies = self._context.cookies()
            return any(c.get("name") == cookie_name for c in cookies)
        except Exception:
            return False

    def _is_linkedin_logged_in(self) -> bool:
        """Retourne True si le contexte a un cookie li_at valide (LinkedIn)."""
        if self._has_auth_cookie("li_at"):
            return True
        # Fallback : l'URL est sur une page "connecté" (feed, jobs, mynetwork…)
        url = (self.page.url or "").lower()
        logged_in_paths = ("/feed", "/jobs", "/mynetwork", "/messaging", "/notifications")
        not_logged_paths = ("login", "authwall", "signup", "checkpoint", "uas/")
        if any(p in url for p in not_logged_paths):
            return False
        if any(p in url for p in logged_in_paths):
            return True
        return False

    def manual_login(self, login_url: str, *, ready_selector: str | None = None) -> None:
        """Ouvre une page de login en mode visible et attend que l'utilisateur termine.

        Détection de connexion (par ordre de priorité) :
        1. Cookie `li_at` présent dans le contexte (LinkedIn) — le plus fiable.
        2. Sélecteur CSS post-login (si fourni).
        3. Heuristique URL (fallback, moins fiable — LinkedIn redirige tôt).
        """
        if self.headless:
            raise RuntimeError("manual_login doit tourner en mode headed (headless=False).")
        self.log("info", f"Ouverture de {login_url} pour connexion manuelle…")
        self.page.goto(login_url)
        self.log("info", "Connectez-vous dans la fenêtre Chromium — attendez la fin de chargement après login.")

        timeout_s = 300  # 5 minutes max
        start = time.time()

        while True:
            self.check_stop()
            elapsed = time.time() - start
            if elapsed > timeout_s:
                raise TimeoutError("Pas de login détecté après 5 minutes.")

            # Méthode 1 : cookie li_at (LinkedIn spécifique, le plus fiable)
            if self._has_auth_cookie("li_at"):
                self.log("info", "Cookie li_at détecté — connexion LinkedIn confirmée.")
                break

            # Méthode 2 : sélecteur CSS post-login
            if ready_selector:
                try:
                    el = self.page.locator(ready_selector).first
                    if el.count() > 0 and el.is_visible(timeout=800):
                        self.log("info", "Sélecteur post-login visible — connexion confirmée.")
                        break
                except Exception:
                    pass

            # Méthode 3 : heuristique URL (seulement si pas de ready_selector)
            if not ready_selector:
                url = (self.page.url or "").lower()
                if "login" not in url and "signin" not in url and "sign_in" not in url:
                    time.sleep(2)
                    url2 = (self.page.url or "").lower()
                    if "login" not in url2 and "signin" not in url2 and "sign_in" not in url2:
                        self.log("info", "URL post-login détectée — connexion supposée.")
                        break

            if int(elapsed) % 30 == 0 and elapsed > 5:
                self.log("info", f"Attente login... ({int(elapsed)}s écoulées)")
            time.sleep(1.5)

        # Laisser Chromium écrire le profil avant de sauvegarder le JSON.
        time.sleep(1.5)
        self.save_cookies()
        self.log("info", f"Session sauvegardée : {self._cookies_path()}")


# ── Logger JSONL : utilisé par le subprocess pour streamer ses événements ────
class JsonlEventLogger:
    """Logger qui pousse chaque événement en ligne JSON dans run_log.jsonl.

    Le UI Streamlit lit ce fichier en mode tail.
    """

    def __init__(self, path: Path = config.RUN_LOG_JSONL):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, level: str, message: str) -> None:
        rec = {"ts": file_manager.utc_now_iso(), "level": level, "msg": message}
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass
        # Echo console aussi (utile en debug).
        print(f"[{level.upper()}] {message}", flush=True)
