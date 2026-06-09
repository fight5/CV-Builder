"""Script de connexion LinkedIn — à lancer UNE SEULE FOIS depuis un terminal Windows.

Usage :
    python setup_linkedin_login.py

Ce script :
1. Ouvre un navigateur Playwright avec le profil persistant dédié.
2. Navigue vers linkedin.com/login.
3. Attend que tu te connectes (jusqu'à 10 minutes).
4. Sauvegarde le profil + les cookies.
5. Confirme que li_at (token LinkedIn) est bien présent.

Après ça, tous les autres scripts (test_e2e_pipeline.py --linkedin,
l'app Streamlit, le runner) réutilisent le même profil sans redemander
de connexion.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from modules.browser_manager import BrowserSession, PERSISTENT_PROFILES_DIR
from modules import config, file_manager

LOGIN_URL = "https://www.linkedin.com/login"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Setup connexion LinkedIn Playwright")
    parser.add_argument(
        "--switch", action="store_true",
        help="Forcer le changement de compte (déconnecte le compte actuel et ouvre la page de login)",
    )
    args = parser.parse_args()

    file_manager.ensure_directories()

    profile_dir = PERSISTENT_PROFILES_DIR / "linkedin"
    print("=" * 60)
    print("SETUP CONNEXION LINKEDIN")
    print("=" * 60)
    print(f"\nProfil persistant : {profile_dir}")

    # Si --switch : supprimer l'ancien profil pour forcer une vraie reconnexion
    if args.switch and profile_dir.exists():
        import shutil
        print("\n[...] Suppression de l'ancien profil (--switch)...")
        shutil.rmtree(profile_dir, ignore_errors=True)
        print(f"[OK] Ancien profil supprimé : {profile_dir}")

    def logger(level, msg):
        print(f"  [{level.upper():<7}] {msg}")

    print("\n[...] Ouverture du navigateur Playwright...")

    with BrowserSession("linkedin", headless=False, event_logger=logger) as session:

        # Vérifier si déjà connecté (seulement si pas --switch)
        if not args.switch:
            already_connected = session._is_linkedin_logged_in()
            if already_connected:
                print("\n[OK] Déjà connecté ! (cookie li_at présent)")
                print("     Pour changer de compte, relancez avec : python setup_linkedin_login.py --switch")
                _show_profile(session)
                return

        # Naviguer vers login (avec déconnexion si --switch)
        if args.switch:
            print(f"\n[...] Déconnexion du compte actuel...")
            try:
                session.page.goto("https://www.linkedin.com/m/logout/", wait_until="domcontentloaded", timeout=10000)
            except Exception:
                pass
        print(f"\n[...] Navigation vers {LOGIN_URL}...")
        session.page.goto(LOGIN_URL, wait_until="domcontentloaded")
        time.sleep(1)

        print()
        print("  ┌──────────────────────────────────────────────────────────┐")
        print("  │                  ACTION REQUISE                          │")
        print("  │                                                          │")
        print("  │  1. Regardez la fenêtre du navigateur qui vient d'ouvrir│")
        print("  │  2. Connectez-vous à LinkedIn (email + mot de passe)     │")
        print("  │  3. Complétez la 2FA / vérification si demandée          │")
        print("  │  4. Attendez d'être sur votre fil d'actualité LinkedIn   │")
        print("  │                                                          │")
        print("  │  Le script détectera la connexion AUTOMATIQUEMENT        │")
        print("  │  via le cookie li_at et continuera seul.                 │")
        print("  └──────────────────────────────────────────────────────────┘")
        print()

        # Attente automatique du cookie li_at (jusqu'à 10 minutes)
        timeout_s = 600
        start = time.time()
        dots = 0
        while True:
            elapsed = time.time() - start
            if elapsed > timeout_s:
                print("\n[ERREUR] Timeout 10 min sans détection de li_at.")
                print("  Relancez ce script et réessayez.")
                break

            if session._is_linkedin_logged_in():
                print(f"\n[OK] Cookie li_at détecté ! Connexion réussie.")
                session.save_cookies()
                print(f"[OK] Profil sauvegardé : {profile_dir}")
                _show_profile(session)
                break

            # Affichage progression toutes les 5s
            if int(elapsed) % 5 == 0 and int(elapsed) != dots:
                dots = int(elapsed)
                remaining = int(timeout_s - elapsed)
                print(f"\r  En attente de connexion... ({int(elapsed)}s écoulées, {remaining}s restantes)   ", end="", flush=True)

            time.sleep(1)


def _show_profile(session: BrowserSession) -> None:
    """Affiche les infos de profil LinkedIn si disponibles."""
    try:
        cookies = session._context.cookies()
        li_cookies = {c["name"]: c.get("domain", "") for c in cookies if "linkedin" in c.get("domain", "")}
        print(f"\n  Cookies LinkedIn : {list(li_cookies.keys())[:10]}")
    except Exception:
        pass
    print("\n[OK] Setup terminé. Tu peux maintenant lancer :")
    print("     python test_e2e_pipeline.py --no-pdf --linkedin --apply")
    print("     (ou l'app Streamlit)")


if __name__ == "__main__":
    main()
