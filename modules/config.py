"""Configuration centrale du module Auto Apply.

Centralise :
- les chemins du dossier `JobAgentAI/` (créé dans le HOME de l'utilisateur),
- la liste des plateformes supportées et leurs métadonnées,
- les paramètres du LLM (Gemini, hérité de l'app CV).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# ── Racine du dossier données ────────────────────────────────────────────────
# Surchargeable via la variable d'env JOB_AGENT_HOME (utile pour tests/Docker).
JOB_AGENT_HOME = Path(os.getenv("JOB_AGENT_HOME") or (Path.home() / "JobAgentAI"))

# ── Arborescence ─────────────────────────────────────────────────────────────
DATA_DIR = JOB_AGENT_HOME / "data"
COOKIES_DIR = JOB_AGENT_HOME / "cookies"
CVS_DIR = JOB_AGENT_HOME / "cvs"
CVS_ORIGINAL_DIR = CVS_DIR / "original"
CVS_GENERATED_DIR = CVS_DIR / "generated"
LETTERS_DIR = JOB_AGENT_HOME / "letters"
SCREENSHOTS_DIR = JOB_AGENT_HOME / "screenshots"
LOGS_DIR = JOB_AGENT_HOME / "logs"
TEMP_DIR = JOB_AGENT_HOME / "temp"

APPLICATIONS_CSV = DATA_DIR / "applications.csv"
USER_PROFILE_JSON = DATA_DIR / "user_profile.json"
SETTINGS_JSON = DATA_DIR / "settings.json"

# Fichier que le subprocess Playwright met à jour pendant son exécution.
# Le UI Streamlit le poll pour streamer les logs.
RUN_STATE_JSON = TEMP_DIR / "run_state.json"
RUN_LOG_JSONL = TEMP_DIR / "run_log.jsonl"
# Touch ce fichier depuis l'UI pour demander l'arrêt du subprocess.
STOP_FLAG = TEMP_DIR / "STOP"


# ── Plateformes ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PlatformSpec:
    key: str             # identifiant interne (= nom de fichier cookies)
    label: str           # affichage UI
    base_url: str        # URL de login pour la 1re connexion
    implemented: bool    # True = automation présente, False = bouton grisé
    notes: str = ""


PLATFORMS: dict[str, PlatformSpec] = {
    "linkedin": PlatformSpec(
        key="linkedin",
        label="LinkedIn",
        base_url="https://www.linkedin.com/login",
        implemented=True,
        notes="Easy Apply uniquement. Postuler en automatique viole les CGU LinkedIn.",
    ),
    "jobteaser": PlatformSpec(
        key="jobteaser",
        label="JobTeaser",
        base_url="https://www.jobteaser.com/fr/users/sign_in",
        implemented=True,
        notes="Candidature rapide pour les offres compatibles.",
    ),
    "indeed": PlatformSpec(
        key="indeed",
        label="Indeed",
        base_url="https://secure.indeed.com/account/login",
        implemented=False,
        notes="À implémenter.",
    ),
    "wttj": PlatformSpec(
        key="wttj",
        label="Welcome to the Jungle",
        base_url="https://www.welcometothejungle.com/fr/signin",
        implemented=False,
        notes="À implémenter.",
    ),
    "apec": PlatformSpec(
        key="apec",
        label="APEC",
        base_url="https://www.apec.fr/candidat/identification.html",
        implemented=False,
        notes="À implémenter.",
    ),
}


# ── LLM ──────────────────────────────────────────────────────────────────────
# Réutilise la même clé que l'app CV. Pas besoin de configurer deux LLM.
def get_gemini_api_key() -> str | None:
    return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


# ── Comportement runtime ─────────────────────────────────────────────────────
# Délai entre actions Playwright (humanisation minimale). Pas une protection
# anti-bot — juste pour éviter de cliquer plus vite que le DOM ne rend.
HUMAN_DELAY_MS_MIN = 600
HUMAN_DELAY_MS_MAX = 1800

# Timeout par défaut sur les attentes Playwright (sélecteurs, clics...).
# Les page.goto ont leur propre timeout (60s) défini dans linkedin_apply.py.
DEFAULT_TIMEOUT_MS = 30000

# Mode headless par défaut. La 1re connexion par plateforme passe TOUJOURS
# en headed (l'utilisateur doit se connecter manuellement).
DEFAULT_HEADLESS = False
