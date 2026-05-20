# AI ATS Resume Generator Agent

Un pipeline multi-agents propulsé par Gemini qui génère automatiquement un CV optimisé pour les systèmes ATS (Applicant Tracking Systems), exporté en PDF via LaTeX.

---

## Ce que fait ce projet

Vous collez une offre d'emploi et uploadez votre CV existant. En moins de deux minutes, le pipeline :

1. Analyse l'offre et extrait tous les mots-clés ATS, les compétences requises et le niveau d'expérience attendu.
2. Structure votre CV existant section par section.
3. Identifie les écarts entre votre profil et l'offre : compétences manquantes, expériences sous-valorisées, formulations à améliorer.
4. Réécrit chaque section de votre CV pour intégrer naturellement les mots-clés ATS, avec des verbes d'action forts et des métriques quantifiées.
5. Génère un fichier LaTeX compilable dans le style que vous choisissez : Modern, Executive ou Classic.
6. Compile le PDF (si pdflatex est disponible sur votre système).
7. Calcule un score de compatibilité ATS et une couverture de mots-clés.
8. Produit un rapport d'optimisation détaillé avec comparaison avant/après.

---

## Le pipeline en 8 agents

```
JobParserAgent          → Extraction structurée de l'offre d'emploi
ResumeParserAgent       → Structuration du CV existant
GapAnalysisAgent        → Analyse des écarts et opportunités
ATSOptimizerAgent       → Réécriture ATS-optimisée par Gemini
LaTeXTemplateAgent      → Injection du contenu dans le template
PDFCompilerAgent        → Compilation pdflatex (×2 passes)
QualityControlAgent     → Score de compatibilité ATS
ReportAgent             → Rapport exécutif + diff avant/après + CSV
```

Chaque agent hérite de `BaseAgent`, dispose de son propre logger, et intègre un mécanisme de fallback en cas d'indisponibilité du LLM. Le tout est orchestré via un `StateGraph` LangGraph avec gestion conditionnelle des erreurs.

---

## Démarrage rapide

### Prérequis

- Python 3.11+
- Une clé API Google Gemini ([obtenir une clé](https://aistudio.google.com/app/apikey))
- pdflatex (optionnel, pour la compilation PDF) — inclus dans TeX Live ou MiKTeX

### Installation

```bash
git clone <repo-url>
cd project_2_ai_ats_resume_generator

python -m venv venv
source venv/bin/activate        # Linux/macOS
# ou : venv\Scripts\activate    # Windows

pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
# Éditez .env et renseignez votre GOOGLE_API_KEY (clé Gemini)
```

### Lancement de l'interface Streamlit

```bash
streamlit run app/streamlit_app.py
```

Ouvrez ensuite [http://localhost:8501](http://localhost:8501) dans votre navigateur.

### Utilisation via Docker

```bash
cp .env.example .env
# Renseignez GOOGLE_API_KEY dans .env

docker-compose up --build
```

### Déploiement sur Streamlit Community Cloud

1. Pousser le projet sur un dépôt GitHub public.
2. Aller sur [share.streamlit.io](https://share.streamlit.io) et cliquer **New app**.
3. Renseigner :
   - **Repository** : `votre-org/votre-repo`
   - **Branch** : `main`
   - **Main file path** : `app/streamlit_app.py`
4. Cliquer **Advanced settings → Secrets** et coller :
   ```toml
   GOOGLE_API_KEY = "votre_vraie_cle_gemini"
   GEMINI_MODEL = "gemini-2.5-flash"
   ```
5. **Deploy**. Le premier build dure 5 à 10 minutes (installation de TeX Live pour la compilation PDF). Les redéploiements suivants sont rapides grâce au cache.

Fichiers de configuration cloud déjà inclus à la racine du dépôt :
- [`packages.txt`](packages.txt) — paquets APT (`texlive-*`, `lmodern`) installés par Streamlit Cloud
- [`runtime.txt`](runtime.txt) — version Python (`python-3.11`)
- [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example) — modèle de secrets

### Utilisation en Python pur

```python
from core.orchestrator import run_pipeline

result = run_pipeline(
    job_text="Senior Data Scientist — Python, MLOps, Docker...",
    resume_text="Marie Dupont, Data Analyst, 6 ans d'expérience...",
    preferences={
        "color": "#2E86AB",
        "template": "modern",
        "language": "French",
        "conciseness": "balanced",
    },
)

print(f"Score ATS : {result['matching_score']}%")
print(f"Couverture mots-clés : {result['keyword_coverage']}%")
print(f"PDF généré : {result['pdf_path']}")
```

---

## Structure du projet

```
project_2_ai_ats_resume_generator/
├── agents/
│   ├── base_agent.py           Classe abstraite commune
│   ├── job_parser_agent.py     Analyse de l'offre d'emploi
│   ├── resume_parser_agent.py  Structuration du CV existant
│   ├── gap_analysis_agent.py   Analyse des écarts
│   ├── ats_optimizer_agent.py  Réécriture ATS par Gemini
│   ├── latex_template_agent.py Injection dans le template LaTeX
│   ├── pdf_compiler_agent.py   Compilation pdflatex
│   ├── quality_control_agent.py Scoring ATS
│   └── report_agent.py         Génération des rapports
├── core/
│   ├── orchestrator.py         LangGraph StateGraph
│   ├── state.py                Schéma ATSState
│   └── tools.py                Utilitaires (PDF, DOCX, LaTeX, keywords)
├── templates/
│   ├── modern.tex              Template moderne avec couleurs
│   ├── executive.tex           Template formel et conservateur
│   └── classic.tex             Template minimal et épuré
├── app/
│   └── streamlit_app.py        Interface utilisateur Streamlit
├── outputs/                    Fichiers générés (PDF, .tex, rapports)
├── tests/
│   └── test_agents.py          Tests unitaires (unittest + mock)
├── docs/
│   └── architecture.md         Documentation technique détaillée
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Interface Streamlit

La page principale présente trois étapes côte à côte :
- **1. Offre d'emploi** : coller le texte ou téléverser un PDF
- **2. Votre CV** : téléverser un PDF ou DOCX
- **3. Personnalisez** : style de template (Modern / Executive / Classic), langue (Français / Anglais), niveau de concision (concis / équilibré / détaillé), couleur d'accentuation, photo optionnelle

Après génération, les boutons de téléchargement (PDF, .tex, rapport) apparaissent en haut, suivis de cinq onglets :
- **Aperçu LaTeX** : code source `.tex`
- **Mots-clés** : tableau interactif de tous les mots-clés avec statut "trouvé / manquant"
- **Analyse des écarts** : compétences manquantes, correspondances, termes reformulés
- **Rapport exécutif** : rapport markdown complet avec recommandations
- **Modifications** : comparaison avant/après pour chaque section

---

## Exemples de sorties

Fichiers générés dans le dossier `outputs/` :

| Fichier | Description |
|---|---|
| `optimized_resume.tex` | Source LaTeX compilable |
| `optimized_resume.pdf` | CV PDF final (si pdflatex installé) |
| `matching_report.md` | Rapport exécutif d'optimisation |
| `diff_report.md` | Comparaison avant/après section par section |
| `ats_keywords.csv` | Tableau de couverture des mots-clés ATS |

---

## Technologies utilisées

| Composant | Technologie |
|---|---|
| Orchestration | LangGraph (StateGraph) |
| LLM | Google Gemini via langchain-google-genai |
| Parsing PDF | PyMuPDF (fitz) |
| Parsing DOCX | python-docx |
| Export PDF | pdflatex (TeX Live / MiKTeX) |
| Interface | Streamlit |
| Configuration | python-dotenv |
| Tests | unittest + unittest.mock |
| Conteneurisation | Docker + docker-compose |

---

## Roadmap

- Support multi-langue étendu (Espagnol, Allemand, Portugais)
- Stockage des sessions en SQLite avec historique des générations
- Intégration d'un score sémantique (embeddings) pour le matching
- Support des formats LinkedIn PDF
- API REST FastAPI pour intégration dans des workflows tiers
- Génération d'une lettre de motivation ATS-optimisée
- Comparaison de plusieurs offres d'emploi simultanément
- Mode batch pour optimiser un CV contre plusieurs offres à la fois

---

## Profil

Ce projet a été conçu et développé dans le cadre d'un portfolio de Data Science appliquée à l'automatisation de processus RH. Le développeur a travaillé sur des projets de traitement de données et de machine learning dans des contextes industriels exigeants (Safran, Sanofi, Thales Alenia Space), avec une spécialisation en MLOps, NLP et pipelines de données à grande échelle.

---

## Licence

MIT License — libre d'utilisation, de modification et de distribution.
