# Déployer LEBANI (CV Builder) en ligne

Ce guide met l'appli en ligne sur **Streamlit Community Cloud** (gratuit). Une
fois déployée, tu obtiens une **URL publique** partageable, utilisable depuis
n'importe quel navigateur — ordinateur ou téléphone.

> ℹ️ L'App Store (Apple) / Google Play ne peut PAS héberger cette appli
> directement : c'est un serveur Python + un moteur LaTeX, qui ne tournent pas
> dans le bac à sable d'un téléphone. L'hébergement web ci-dessous est le vrai
> chemin de publication. (Étape bonus « installable comme une app » en fin de doc.)

---

## Ce qui est réinstallé à zéro à chaque build (ta question)

Streamlit Cloud reconstruit tout depuis le dépôt GitHub. Trois sources décrivent
les dépendances — **tout est déjà prévu dans le dépôt** :

| Quoi | Fichier | Contenu |
|---|---|---|
| **Bibliothèques Python** | `requirements.txt` | streamlit, openai, langchain, pymupdf, python-docx… |
| **Logiciels système (LaTeX)** | `packages.txt` | TeX Live + **`texlive-lang-french`** (indispensable pour le français) |
| **« Agent IA » (clés + modèle)** | Secrets Streamlit | `DEEPSEEK_API_KEY` ou `GOOGLE_API_KEY`, modèle, `LLM_PROVIDER` |

⚠️ Le fichier `.env` **n'est pas** déployé (il est dans `.gitignore`, pour ne pas
publier tes clés). En ligne, les clés se mettent dans **Secrets** (étape 4).

---

## Étapes

### 1. Pousser le code à jour sur GitHub
Le dépôt existe déjà : `github.com/fight5/CV-Builder`.
```bash
git push origin main
```

### 2. Ouvrir Streamlit Cloud
Va sur **https://share.streamlit.io** → connecte-toi avec ton compte **GitHub**.

### 3. Créer l'app
- Clique **« Create app »** → **« Deploy a public app from GitHub »**.
- **Repository** : `fight5/CV-Builder`
- **Branch** : `main`
- **Main file path** : `app/streamlit_app.py`
  *(la racine du dépôt `fight5/CV-Builder` est déjà le dossier du projet)*
- (**Advanced settings** → **Python version** : `3.11`)

### 4. Configurer l'agent IA (Secrets)
Toujours dans **Advanced settings → Secrets**, colle ceci (remplace par TES clés) :
```toml
DEPLOYMENT_MODE = "cloud"
LLM_PROVIDER    = "deepseek"

DEEPSEEK_API_KEY = "sk-xxxxxxxxxxxxxxxx"
DEEPSEEK_MODEL   = "deepseek-chat"

# Fallback Gemini (recommandé — utilisé si DeepSeek échoue) :
GOOGLE_API_KEY = "AIza-xxxxxxxxxxxx"
GEMINI_MODEL   = "gemini-2.5-flash"
```

### 5. Déployer
Clique **« Deploy »**. Le **premier build prend plusieurs minutes** (il télécharge
et installe TeX Live, ~500 Mo). Les suivants sont plus rapides (cache).

### 6. C'est en ligne
Tu obtiens une URL du type `https://cv-builder-xxxx.streamlit.app`.
- La page **CV | Lettre de motivation** fonctionne.
- La page **Candidature automatique** est **volontairement désactivée** en ligne
  (`DEPLOYMENT_MODE=cloud`) car elle utilise Playwright, indisponible sur
  Streamlit Cloud.

---

## Dépannage

| Symptôme | Cause / solution |
|---|---|
| Build échoue sur `babel`/`french` | `texlive-lang-french` manque → déjà corrigé dans `packages.txt`, vérifie que le dernier commit est poussé. |
| « Aucune clé LLM configurée » | Secrets non renseignés → étape 4. |
| PDF ne se génère pas | Regarde les logs (menu « Manage app » → logs) ; souvent un paquet LaTeX manquant. |
| Les logos par défaut n'apparaissent pas | `templates/assets/*.png` ne sont pas committés (voir note Confidentialité). Les uploads manuels fonctionnent quand même. |

---

## Note confidentialité (logos / photo)
`templates/assets/` contient une **photo d'identité** et des logos. S'ils sont
committés dans un dépôt **public**, ils deviennent publics. Pour un dépôt public,
laisse-les hors de git (l'utilisateur upload sa photo via l'interface), ou mets
le dépôt en **privé** (Streamlit Cloud gère aussi les dépôts privés).

---

## Bonus : rendre l'appli « installable » comme une app (PWA)
Une fois l'URL en ligne, sur iPhone (Safari) ou Android (Chrome) :
**Partager → « Sur l'écran d'accueil »**. L'appli s'ouvre alors en plein écran,
avec une icône, comme une vraie app — sans passer par un store.
(On peut aller plus loin avec un manifeste PWA + icône dédiée si tu veux.)
