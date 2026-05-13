# AI ATS Resume Generator Agent

Un pipeline multi-agents propulsé par GPT-4o qui génère automatiquement un CV optimisé pour les systèmes ATS (Applicant Tracking Systems), exporté en PDF via LaTeX.

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
ATSOptimizerAgent       → Réécriture ATS-optimisée par GPT-4o
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
- Une clé API OpenAI (GPT-4o)
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
# Éditez .env et renseignez votre OPENAI_API_KEY
```

### Lancement de l'interface Streamlit

```bash
streamlit run app/streamlit_app.py
```

Ouvrez ensuite [http://localhost:8501](http://localhost:8501) dans votre navigateur.

### Utilisation via Docker

```bash
cp .env.example .env
# Renseignez OPENAI_API_KEY dans .env

docker-compose up --build
```

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
│   ├── ats_optimizer_agent.py  Réécriture ATS par GPT-4o
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

Le sidebar gauche permet de :
- Coller ou uploader une offre d'emploi (PDF ou texte)
- Uploader votre CV (PDF ou DOCX)
- Choisir une couleur d'accentuation pour le CV
- Sélectionner un style de template (Modern / Executive / Classic)
- Choisir la langue du CV (Français / Anglais)
- Régler le niveau de concision (concis / équilibré / détaillé)
- Inclure une photo (upload JPG/PNG)

Après génération, la zone principale affiche :
- **Métriques** : Score ATS, Couverture mots-clés, Mots-clés ajoutés, Alertes QC
- **Onglet LaTeX Preview** : code source `.tex` + boutons de téléchargement (.tex, .pdf, rapport)
- **Onglet Keywords** : tableau interactif de tous les mots-clés avec statut "trouvé / manquant"
- **Onglet Gap Analysis** : compétences manquantes, correspondances, termes reformulés
- **Onglet Executive Report** : rapport markdown complet avec recommandations
- **Onglet Diff Report** : comparaison avant/après pour chaque section

Le mode démo (sans clé API) affiche des résultats illustratifs pour tester l'interface.

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
| LLM | OpenAI GPT-4o via langchain-openai |
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
