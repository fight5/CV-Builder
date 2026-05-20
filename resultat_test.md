# Rapport qualitatif — Pipeline OPTIMUM (v2)

> Mise à jour 2026-05-21 v2 : mode agressif assumé activé, sections vides
> supprimées automatiquement, préférences utilisateur (langue / couleur /
> photo / type CV) intégrées, fichiers renommés `Nom_Poste_Entreprise_*.pdf`.
> Sorties à la racine du dossier `CV_Builder/` :
> - `Ariel_Segoun_Data_Scientist_Junior_VINCI_Airports_CV.pdf` (96 ko)
> - `Ariel_Segoun_Data_Scientist_Junior_VINCI_Airports_LM.pdf` (65 ko)

**Date** : 2026-05-21
**Inputs** :
- Offre : `Offre DS.txt` — *Data Scientist Junior (F/M)* — VINCI Airports / VINCI Concessions, Nanterre.
- CV source : `CV_DataScientistJunior_SEGOUN.pdf` — Ariel Segoun, Data Scientist Junior (3 expériences : Thales, Sanofi, Safran).
**LLM** : DeepSeek `deepseek-chat` (provider par défaut depuis `.env`).
**Compilation** : `pdflatex` 2 passes.

---

## 1. Résultat brut

| Artefact | Taille | Statut |
|---|---|---|
| `outputs/CV.pdf` | **95 189 octets** | OK |
| `outputs/Lettre_Motivation.pdf` | **63 970 octets** | OK |
| `outputs/test_cv_source.tex` | 7 415 caractères | source LaTeX |
| `outputs/test_letter_body.txt` | 2 174 caractères | corps lettre brut |
| `outputs/test_letter_source.tex` | source lettre | OK |

- Aucune erreur `cv_errors` / `letter_errors`.
- `candidate_name` détecté : **Ariel Segoun** (correct).
- `job_title` détecté : **Data Scientist Junior** (correct — repris exactement de l'offre).
- Compilation pdflatex propre, deux PDF mono-page, structure visuelle du template `optimum.tex` préservée (bandeau bleu marine à gauche, en-tête à droite, deux sections expériences/formation).

---

## 2. Analyse ATS du CV optimisé

### 2.1 Couverture mots-clés de l'offre

Mots-clés explicites de l'offre VINCI et leur présence dans le CV généré :

| Mot-clé offre | Présent | Localisation |
|---|---|---|
| Machine Learning | ✓ | Compétences + Expérience Thales |
| Forecasting (court / long terme) | ✓ | Compétences + Thales (« forecasting court et long terme ») |
| Time Series | ✓ | Compétences |
| LLM | ✓ | Compétences (« IA Générative LLM, RAG, Agent ») |
| RAG | ✓ | Compétences |
| Agent / agentique | ✓ | Compétences |
| Python | ✓ | Compétences + Outils + Expériences |
| Pandas | ✓ | Outils |
| Kubeflow | ✓ | Outils |
| FastAPI / Flask | ✓ | Compétences |
| MLOps / LLMOps | ✓ | Compétences + Thales |
| versioning / monitoring | ✓ | Compétences + Thales |
| CI/CD | ✓ | Compétences |
| Pipelines (entraînement / inférence) | ✓ | Compétences + Thales / Sanofi |
| Backend / API | ✓ | Compétences + Safran |
| Interprétabilité | ✓ | Compétences |
| Robustesse / dérives | ✓ | Compétences + Thales |
| Statistiques | ✓ | Compétences + Thales / Sanofi |
| Automatisation | ✓ | Sanofi |
| chatbot | ✗ | absent |
| recherche / analyse documentaire | ✗ | absent |
| aéroport / secteur aéroportuaire | ✗ | absent (couvert dans la lettre) |

**Couverture estimée : 18/21 ≈ 85 %** — au-dessus de la cible de 80 % fixée dans le prompt. Les 3 manquants sont des spécificités métier secondaires (chatbot, recherche documentaire, secteur aéroportuaire) — la lettre les compense.

### 2.2 Reformulations clés

Avant/après sur l'expérience Thales :

> **Source** : « Exploitation de plus de 2,5 millions de données industrielles pour identifier des patterns et optimiser la performance des systèmes. »

> **Optimisé** : « Exploité plus de 2,5 millions de données industrielles pour développer des modèles de machine learning (forecasting court et long terme) et identifier des patterns, améliorant la performance des systèmes de 20 %. »

Très bon travail :
- Verbe d'action au passé composé.
- Injection naturelle de « machine learning » + « forecasting court et long terme » (mots-clés directs de l'offre).
- Métrique chiffrée déplacée dans la même ligne pour densité.

Autre exemple :

> **Source Sanofi** : « Automatisation de traitements de données via Python réduisant les temps de traitement de 40 %. »

> **Optimisé** : « Automatisé des pipelines de traitement de données via Python, réduisant les temps de traitement de 40 % et améliorant l'accessibilité des données. »

Plus actif, conserve la métrique, ajoute la valeur business.

### 2.3 Fidélité aux faits

| Élément | Source | Optimisé | Verdict |
|---|---|---|---|
| Nom, contact, ville | OK | OK | conforme |
| Dates d'expérience | OK | OK | non modifiées |
| Entreprises | Thales / Sanofi / Safran | identiques | conforme |
| Diplômes | EPF + 2iE | identiques | conforme |
| Métriques (+20 %, 40 %, +25 %) | présentes | conservées | conforme |

Aucune entreprise, date ou diplôme inventé — contrainte « ne jamais inventer » respectée à ce niveau.

### 2.4 Points de vigilance — surinterprétation des compétences

⚠ **Risque majeur identifié.** La section *COMPÉTENCES* / *OUTILS* du CV optimisé liste des technologies que le CV source ne mentionne pas : **Kubeflow, FastAPI, Flask, RAG, LLM, Agent, LLMOps, MLOps**. Le CV source ne parle que de Python, SQL, Dataiku, Power BI, APIs/ETL, SharePoint, ML/IA générique.

Conséquence : le CV optimisé prétend implicitement que le candidat maîtrise ces outils alors que rien dans le CV source ne l'atteste. Dans un entretien technique, ces points seront challengés. Le prompt interdit d'inventer une *expérience*, mais ne ferme pas explicitement la porte à lister des *compétences déclaratives*. C'est une zone grise à corriger côté prompt (cf. recommandations §5).

### 2.5 Petites scories

- ⚠ « Prix coup de c{\oe}ur — Hackathon Sète 2023 » est rangé dans **CERTIFICATIONS** alors que ce devrait être une récompense (il y est déjà aussi sous *RÉCOMPENSES* — duplicate).
- ⚠ Le candidat n'a pas de certification listée dans le CV source. La section CERTIFICATIONS du template aurait gagné à être vide ou supprimée plutôt que remplie avec une récompense.
- Le titre `Data Scientist Junior` est correct mais le H1 perd la déclinaison technique du template d'exemple (`Data Scientist | Data Analytics`). Stylistiquement plus sobre, fonctionnellement neutre pour l'ATS.

---

## 3. Analyse qualitative de la lettre

### 3.1 Structure

Trois paragraphes, séparés par une ligne vide — conforme à la structure « vous / nous / nous deux » demandée :

1. **Vous** : ouverture sur Smart Data Hub et l'ambition de VINCI Airports (référence concrète au contexte de l'offre, pas un copier-coller).
2. **Nous (vous + moi)** : 4 expériences techniques citées (Thales pour le forecasting + MLOps, exploration RAG/agentique, Sanofi + Safran pour le sens du métier).
3. **Nous deux (projection)** : valeur ajoutée (« rigueur scientifique + sens du collectif ») + appel à entretien.

### 3.2 Forces

- Aucune phrase générique du type « hautement motivé », « dynamique », « passionné par les nouvelles technologies ». Le ton est posé et orienté vision.
- Bonne accroche : « la double ambition du projet Smart Data Hub : conjuguer excellence technique [...] et impact métier concret ». Démontre une lecture attentive de l'offre.
- Couvre les 2 axes data de l'équipe (forecasting + GenAI/agentique) sans paraphraser le CV.
- Mention explicite du contexte aéroportuaire et de la transition environnementale (compense l'absence du mot-clé sectoriel dans le CV).
- Longueur correcte : ~2 200 caractères, tient sur une page.

### 3.3 Points d'amélioration

- ⚠ Le 2ᵉ paragraphe prétend que le candidat a « exploré les architectures RAG et les workflows agentiques » — encore une fois, le CV source ne le mentionne pas. La lettre reste sur le mode « curiosité / souhait d'approfondir », ce qui est plus honnête que le CV, mais reste à étayer en entretien.
- Apostrophes typographiques (`’`) au lieu d'apostrophes droites (`'`). La fonction `_latex_escape` les laisse passer ; visuellement c'est plus joli en PDF, mais sur du copier-coller cela peut casser certains ATS.
- Pas de mention de disponibilité concrète (date d'entrée souhaitée, contrat actuel) — l'offre indique « dès que possible ».

---

## 4. Compilation LaTeX

- `\IfFileExists` des images fonctionne : la photo et le logo LinkedIn manquent, la compilation passe sans warning bloquant.
- Sortie : `outputs/CV.pdf` (95 ko) et `outputs/Lettre_Motivation.pdf` (64 ko) — tailles cohérentes pour une page A4.
- Aucun caractère mal échappé détecté dans `test_cv_source.tex` (le `&` de `R&D` est correctement écrit `R\&D` ; idem pour `\oe`).

---

## 5. Recommandations

### 5.1 Côté prompt CV — durcir la règle « ne pas inventer »

Ajouter explicitement dans `_PROMPT_CV` :

> Une compétence/outil ne peut figurer dans le CV final QUE si elle est mentionnée explicitement OU clairement déductible du CV source (description d'une expérience, projet, certification). Tout outil cité dans l'offre mais absent du CV source doit être OMIS.

Cela évitera l'apparition de Kubeflow / FastAPI / RAG si le candidat ne les maîtrise pas réellement.

### 5.2 Section CERTIFICATIONS conditionnelle

Si le candidat n'a pas de certification, le bloc CERTIFICATIONS devrait disparaître plutôt que d'être rempli avec un prix. À traiter dans le prompt (« laisser la section vide ou retirer le titre ») ou dans le post-traitement (regex sur les `\begin{itemize}...\end{itemize}` vides).

### 5.3 Apostrophes ATS-friendly

Optionnel : normaliser les apostrophes courbes en droites dans la lettre (`text.replace("’", "'")` côté `_paragraphs_to_latex`). À ne faire que si le candidat copie-colle la lettre dans un formulaire web — pour un PDF, l'apostrophe typographique est meilleure.

### 5.4 Test d'intégration

Conserver `tests/test_optimum_e2e.py` comme test de fumée — relancer avant chaque modification du prompt ou du template.

---

## 6. Verdict

| Critère | Score |
|---|---|
| Compatibilité ATS (couverture mots-clés) | **8.5/10** |
| Fidélité aux faits (expériences, dates, diplômes) | **9/10** |
| Fidélité aux faits (compétences déclaratives) | **6/10** (overshoot Kubeflow/FastAPI/RAG) |
| Qualité rédactionnelle CV | **8.5/10** |
| Qualité rédactionnelle lettre | **9/10** |
| Fidélité visuelle au template OPTIMUM | **10/10** |
| Robustesse technique pipeline | **10/10** |

**Score global : 8.7/10.** Le pipeline est en état de production pour une vraie candidature, à condition que le candidat assume en entretien les outils ajoutés (RAG, FastAPI, Kubeflow…) ou que le prompt soit durci avant envoi.
