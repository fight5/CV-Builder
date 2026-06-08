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
    _browser = None
    _context = None
    page = None  # type: ignore[assignment]

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def __enter__(self) -> "BrowserSession":
        # Import différé : Playwright n'est requis qu'au runtime navigateur.
        from playwright.sync_api import sync_playwright

        file_manager.ensure_directories()
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            executable_path=_find_chrome_executable(),
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
        self.page = self._context.new_page()
        self.log("info", f"Browser ready (platform={self.platform}, headless={self.headless})")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Sauvegarde du state à la sortie si pas d'erreur fatale.
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
    def manual_login(self, login_url: str, *, ready_selector: str | None = None) -> None:
        """Ouvre une page de login en mode visible et attend que l'utilisateur termine.

        Stratégie : on poll un sélecteur connu (ex: la photo de profil post-login),
        sinon on attend simplement que l'URL change vers une page logged-in.
        """
        if self.headless:
            raise RuntimeError("manual_login doit tourner en mode headed (headless=False).")
        self.log("info", f"Ouverture de {login_url} pour connexion manuelle…")
        self.page.goto(login_url)
        self.log("info", "Connectez-vous dans la fenêtre Chromium, puis attendez le message de confirmation.")

        timeout_s = 240  # 4 minutes pour se logger
        start = time.time()
        while True:
            self.check_stop()
            if time.time() - start > timeout_s:
                raise TimeoutError("Pas de login détecté après 4 minutes.")
            try:
                if ready_selector and self.page.locator(ready_selector).first.is_visible(timeout=1500):
                    break
            except Exception:
                pass
            # Heuristique fallback : URL ne contient plus "login" ni "signin".
            url = (self.page.url or "").lower()
            if "login" not in url and "signin" not in url and "sign_in" not in url:
                time.sleep(1.5)
                # Confirme avec une 2e vérification après la transition.
                url2 = (self.page.url or "").lower()
                if "login" not in url2 and "signin" not in url2 and "sign_in" not in url2:
                    break
            time.sleep(1)

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
