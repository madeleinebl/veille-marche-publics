# Veille marchés publics — BDGS Associés

Veille automatique des appels d'offres français et européens intéressant un cabinet d'avocats en **Finance, Project Finance, Infrastructure & Énergie, Corporate/M&A, LBO, Capital Markets, Restructuring et PPP/Concessions**.

Chaque jour, GitHub interroge les **sources officielles** (BOAMP et TED), attribue à chaque avis un **score de pertinence BDGS** expliqué, et met à jour un **tableau de bord** consultable dans le navigateur.

> Aucune donnée inventée : le tableau de bord n'affiche que des avis réellement collectés sur les API officielles, ou des avis que vous avez saisis vous-même (signalés « Saisie manuelle »).

---

## Sommaire

1. [Ce que fait le système](#1-ce-que-fait-le-système)
2. [Mise en place (15 minutes, sans compétence technique)](#2-mise-en-place-15-minutes-sans-compétence-technique)
3. [Activer la veille quotidienne](#3-activer-la-veille-quotidienne)
4. [Consulter le tableau de bord](#4-consulter-le-tableau-de-bord)
5. [Utilisation au quotidien](#5-utilisation-au-quotidien)
6. [Personnaliser (mots-clés, seuils, fréquence)](#6-personnaliser)
7. [Sources intégrées et limites](#7-sources-intégrées-et-limites)
8. [Dépannage](#8-dépannage)
9. [Organisation des fichiers](#9-organisation-des-fichiers)

---

## 1. Ce que fait le système

| Étape | Détail |
|---|---|
| **Collecte** | BOAMP (Open Data officiel de la DILA) et TED (API de l'Office des publications de l'UE). Recherche par **codes CPV** (services juridiques, conseil financier) **et par mots-clés** en français et en anglais. |
| **Rattrapage** | Chaque exécution rebalaye les **10 derniers jours** (60 jours au premier lancement) pour récupérer les avis indexés tardivement, notamment les MAPA. |
| **Fusion** | Un même marché publié au BOAMP **et** à TED n'apparaît qu'une fois, avec les deux liens officiels. |
| **Rectificatifs** | Un avis rectificatif est rattaché à l'avis initial ; la nouvelle échéance est appliquée et l'historique conservé. |
| **Mises à jour** | Si un avis change (titre, échéance, valeur…), le changement est enregistré dans son historique. |
| **Score BDGS** | Score sur 100 environ, priorité **Haute / Moyenne / Faible**, domaines de pratique, mots-clés trouvés, et une phrase expliquant pourquoi l'avis est remonté. |
| **Historique** | Rien n'est supprimé : tous les avis restent dans `data/notices.json`, et chaque exécution est journalisée dans `data/runs.json` (durée, erreurs, nombre d'avis). |
| **Alertes** | Si BOAMP ou TED est indisponible, GitHub vous envoie un e-mail ; les données précédentes restent affichées. |

### Comment est calculé le score

Le score additionne des points visibles dans le tableau de bord (bouton **« Détail du score & vérification »** sous chaque avis) :

| Critère | Points |
|---|---|
| Mission juridique : CPV 791xxxxx (services juridiques) | +25 |
| Mission de conseil financier : CPV 66171000, 7941xxxx | +12 |
| Mots « conseil juridique », « assistance juridique », « legal advice », « avocat »… | jusqu'à +20 (plafond juridique total : 30) |
| Mots-clés de chaque domaine BDGS (ex. « sûretés », « financement de projet », « LBO », « émission obligataire », « BESS »…) | jusqu'à +25 par domaine (total plafonné à 50) |
| Acheteur stratégique (Bpifrance, Caisse des Dépôts, EDF, SNCF, APE…) | +6 |
| Valeur estimée ≥ 300 k€ / ≥ 1 M€ | +4 / +8 |
| Hors cible (nettoyage, traduction, formation…) | −6 à −15 |
| Avis d'attribution (marché déjà attribué) | −10 |

**Priorité Haute** : score ≥ 50 **et** présence d'une mission juridique ou de conseil.
**Moyenne** : score ≥ 36. **Faible** : en dessous. Les avis sous 10 points ne sont pas conservés.
Tout est réglable dans `config/scoring.json`.

---

## 2. Mise en place (15 minutes, sans compétence technique)

Vous n'avez besoin que d'un navigateur. Aucun logiciel à installer, aucune clé d'API : BOAMP et TED sont en accès libre.

### Étape 1 — Créer un compte GitHub
Allez sur <https://github.com/signup> et créez un compte (gratuit).

### Étape 2 — Créer le dépôt
1. En haut à droite, cliquez sur **+** → **New repository**.
2. Nom : `veille-marches-publics`.
3. Choisissez la visibilité :
   - **Public** : gratuit, tableau de bord en ligne via GitHub Pages. Les avis sont des données publiques, mais votre liste de mots-clés sera visible.
   - **Private** : recommandé pour la confidentialité. La collecte fonctionne pareil ; pour avoir le tableau de bord en ligne il faut un abonnement GitHub Pro/Team, sinon vous le téléchargez après chaque collecte (voir §4).
4. Cliquez sur **Create repository**.

### Étape 3 — Déposer les fichiers
1. Dans le nouveau dépôt, cliquez sur **uploading an existing file** (ou **Add file → Upload files**).
2. Décompressez le fichier `veille-bdgs.zip` sur votre ordinateur, ouvrez le dossier `veille-bdgs`, sélectionnez **tout son contenu** et glissez-le dans la page GitHub.
3. Cliquez sur **Commit changes**.

> ⚠️ **Le dossier `.github` est invisible sur Mac et Windows** (son nom commence par un point) et n'est souvent pas envoyé. Vérifiez qu'il apparaît dans le dépôt. Sinon :
> **Add file → Create new file**, tapez exactement `.github/workflows/veille.yml` comme nom, collez le contenu du fichier `veille.yml` fourni, puis **Commit changes**.
> Sur Mac, `Cmd + Maj + .` affiche les fichiers cachés dans le Finder.

### Étape 4 — Autoriser GitHub à enregistrer les résultats
**Settings → Actions → General →** tout en bas, *Workflow permissions* : cochez **Read and write permissions** → **Save**.

---

## 3. Activer la veille quotidienne

1. Onglet **Actions** du dépôt. Si un message le demande, cliquez sur **I understand my workflows, go ahead and enable them**.
2. À gauche, cliquez sur **Veille marchés publics** → bouton **Run workflow** → **Run workflow**.
3. Attendez 2 à 5 minutes : une coche verte ✅ indique le succès. Ce premier lancement remonte 60 jours en arrière.

C'est tout : la collecte se lance ensuite **automatiquement chaque jour vers 6 h–7 h (heure de Paris)**.

Options du bouton **Run workflow** :
- **Nombre de jours à remonter** : par exemple `30` pour rattraper un mois.
- **Identifiant(s) BOAMP à ajouter** : par exemple `26-106060` pour forcer l'ajout d'un avis précis que vous avez repéré.

> **Alertes e-mail** : en cas d'échec (croix rouge ❌), GitHub envoie un e-mail au propriétaire du dépôt. Pour le vérifier : avatar → **Settings → Notifications → Actions**.

---

## 4. Consulter le tableau de bord

### Dépôt public (ou abonnement GitHub Pro/Team) : en ligne
1. **Settings → Pages**.
2. *Source* : **Deploy from a branch** ; *Branch* : `main`, dossier **`/docs`** → **Save**.
3. Après une minute, l'adresse s'affiche, du type `https://VOTRE-NOM.github.io/veille-marches-publics/`. Ajoutez-la à vos favoris : elle se met à jour toute seule après chaque collecte.

### Dépôt privé sans abonnement : en téléchargement
- **Actions** → cliquez sur la dernière exécution → en bas, **Artifacts → tableau-de-bord-veille** → décompressez puis ouvrez `index.html` dans votre navigateur.
- Ou bien, dans le dépôt : dossier `docs` → `index.html` → bouton **Download raw file**.

Le fichier est autonome : il fonctionne hors ligne et peut être transmis par e-mail.

---

## 5. Utilisation au quotidien

**Les cartes du haut sont cliquables** et servent de filtres rapides :
🆕 nouveaux depuis la dernière collecte · ⚑ haute pertinence en cours · ⏰ échéance ≤ 7 jours · 📅 ≤ 30 jours · ✎ rectificatifs.

**Pour chaque avis** :
- score et priorité ; phrase « pourquoi » ; domaines ; mots-clés trouvés ;
- badges **BOAMP ✓ / TED ✓** cliquables vers l'**avis officiel** (vérification à la source) ;
- **Détail du score & vérification** : calcul point par point, modifications détectées, date de collecte, requête qui l'a trouvé ;
- **Suivi** (À analyser, Intéressant, Candidature en cours, Déposé, Remporté, Perdu, Écarté) et **Note**.

**Statuts et notes** : ils sont enregistrés **dans votre navigateur** et sont conservés à chaque actualisation des données (chaque avis garde le même identifiant). Ils ne sont pas visibles par vos collègues et ne sont pas envoyés à GitHub.
→ Bouton **Exporter le suivi** pour les sauvegarder ou les transmettre ; **Importer** pour les recharger sur un autre poste.
Les statuts saisis dans l'ancienne version du tableau de bord sont repris automatiquement s'il s'agit du même navigateur et de la même adresse.

**Export CSV** : exporte la liste filtrée (avec score, domaines, statut et note) pour Excel.

### Ajouter un avis à la main
Pour un avis repéré ailleurs (MAPA sur un profil d'acheteur, avis pas encore indexé…) :
1. Dans le dépôt, ouvrez `data/manual_notices.json` → icône crayon ✏️.
2. Copiez un bloc existant et adaptez-le. Pour un avis BOAMP, indiquez `"source": "BOAMP"` et `"source_id": "26-106060"` : la collecte officielle le **confirmera et le complétera** automatiquement (badge vert « BOAMP ✓ »).
3. **Commit changes**. L'avis apparaîtra à la prochaine collecte (ou relancez le workflow).

Pour retirer un avis manuel, supprimez son bloc.

---

## 6. Personnaliser

Tout se modifie dans le navigateur (icône crayon ✏️ sur le fichier, puis **Commit changes**). Faites attention aux virgules et guillemets : en cas d'erreur, les tests automatiques bloquent la collecte et GitHub vous prévient.

| Je veux… | Fichier | Quoi modifier |
|---|---|---|
| ajouter/retirer un mot-clé de scoring | `config/scoring.json` | le domaine concerné dans `practices`, ex. `"titrisation": 12` |
| changer les seuils Haute/Moyenne | `config/scoring.json` | `thresholds` |
| ajouter un acheteur stratégique | `config/scoring.json` | `strategic_buyers.names` |
| chercher un nouveau mot sur BOAMP/TED | `config/sources.json` | `boamp.keyword_queries` / `ted.keyword_queries` |
| ajouter un code CPV | `config/sources.json` | `cpv_legal` ou `cpv_advisory` |
| rebalayer plus de jours | `config/sources.json` | `lookback_days_daily` |
| collecter plus souvent | `.github/workflows/veille.yml` | ligne `cron`, ex. `"17 5,11,16 * * 1-5"` = 3 fois par jour en semaine |

Les heures `cron` sont en **UTC** (Paris = UTC+1 en hiver, UTC+2 en été). GitHub peut retarder une exécution planifiée de quelques minutes.

---

## 7. Sources intégrées et limites

### Sources intégrées (automatiques)

| Source | Accès | Couverture |
|---|---|---|
| **BOAMP** — Open Data DILA (`boamp-datadila.opendatasoft.com`, API Explore v2.1) | Public, sans clé, licence Etalab 2.0 | Tous les avis BOAMP : MAPA ≥ 90 k€, procédures formalisées, rectificatifs, attributions |
| **TED** — Search API v3 (`api.ted.europa.eu`) | Public, recherche anonyme sans clé | Avis européens (JOUE), France et autres États membres |

### Non intégrées automatiquement (action manuelle)

| Source | Pourquoi | Que faire |
|---|---|---|
| **PLACE** (marches-publics.gouv.fr) | Pas d'API publique pour les consultations en cours ; l'extraction automatique du site n'est pas autorisée. Les marchés de l'État au-dessus des seuils de publicité sont de toute façon publiés au BOAMP et/ou à TED, donc déjà couverts. | Créer des **alertes e-mail** sur PLACE (compte entreprise gratuit) pour les consultations sous 90 k€ ; ajouter un avis intéressant dans `data/manual_notices.json`. |
| **Profils d'acheteurs** (Maximilien, AWS-achat, achatpublic, marches-securises…) | Pas d'API ouverte ; conditions d'utilisation restrictives | Alertes e-mail sur chaque plateforme ; saisie manuelle si besoin. |
| **Agrégateurs privés** (France Marchés, Marchés Online…) | Données sous licence commerciale | Utilisation complémentaire seulement. |
| **API BOAMP PISTE** (api.piste.gouv.fr) | Nécessite une inscription et des clés ; n'apporte rien de plus que l'Open Data utilisé ici | Non nécessaire. |
| **DECP** (données essentielles, data.gouv.fr) | Concerne les marchés **attribués**, pas les opportunités | Extension possible pour la veille concurrentielle. |

### Limites connues
- **MAPA < 90 k€** : la publicité au BOAMP n'est pas obligatoire ; ces avis peuvent n'exister que sur le profil d'acheteur et échapper à la collecte.
- **Délai** : un avis est visible à la collecte suivant son indexation dans l'Open Data (en général sous 24 h).
- **Valeur estimée** : souvent absente des avis, ou extraite automatiquement des données structurées ; à vérifier sur l'avis officiel.
- **Fusion BOAMP ↔ TED** : par identifiant de procédure, sinon par similarité de titre et d'acheteur. Une fusion manquée produit un doublon visible ; une mauvaise fusion est très improbable mais possible.
- **Statuts et notes** : stockés par navigateur ; utilisez l'export/import pour les partager.
- **Score** : il repose sur les mots présents dans l'avis. Un avis rédigé très sobrement (« prestations juridiques ») sera classé Faible même s'il cache une mission de financement : parcourez aussi les avis « Moyenne ».

### Tests
- `python -m pytest` : 15 tests automatiques hors réseau (analyse des réponses BOAMP et TED, score, fusion, rectificatifs, mises à jour, saisies manuelles, panne d'une source, panne de toutes les sources). Ils tournent **avant chaque collecte** sur GitHub.
- `tests/dashboard_check.js` : test du tableau de bord dans un navigateur simulé (affichage, filtres, tri, statuts, notes, reprise des anciens statuts).
- Les fichiers `tests/fixtures/SYNTHETIC_*.json` sont des **données de test synthétiques** (titres préfixés « TEST ») : ils ne sont jamais publiés dans le tableau de bord.

---

## 8. Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| L'onglet **Actions** ne montre pas « Veille marchés publics » | Dossier `.github` non envoyé | Voir l'avertissement de l'étape 3 |
| Erreur `Permission denied` / `403` à l'étape « Enregistrer » | Droits d'écriture non activés | Étape 4 (Read and write permissions) |
| ❌ à l'étape « Tests automatiques » | Erreur de saisie dans un fichier `config/*.json` ou `manual_notices.json` | Ouvrir le détail : la ligne fautive est indiquée ; corriger la virgule ou le guillemet |
| ❌ à l'étape « Contrôle de santé » | BOAMP ou TED indisponible ce jour-là | Rien à faire : les données sont conservées et la collecte suivante rattrape les 10 derniers jours |
| Bandeau bleu « Aucune collecte automatique n'a encore abouti » | Workflow jamais lancé | Section 3 |
| Le tableau de bord en ligne n'est pas à jour | Cache du navigateur ou Pages en cours de publication | Recharger la page (Ctrl/Cmd + Maj + R) après 1–2 minutes |
| Les workflows planifiés se sont arrêtés | GitHub suspend les tâches planifiées après 60 jours sans activité sur un dépôt **public** | Onglet Actions → **Enable workflow** (les collectes quotidiennes génèrent elles-mêmes de l'activité, en principe cela n'arrive pas) |

---

## 9. Organisation des fichiers

```
veille-bdgs/
├── README.md                     ← ce guide
├── config/
│   ├── sources.json              ← requêtes BOAMP/TED, CPV, nombre de jours
│   └── scoring.json              ← grille de pertinence BDGS
├── data/
│   ├── notices.json              ← base des avis (historique complet, mise à jour automatique)
│   ├── runs.json                 ← journal des exécutions
│   └── manual_notices.json       ← vos saisies manuelles
├── docs/
│   ├── index.html                ← le tableau de bord (généré)
│   └── data.json                 ← les mêmes données en JSON
├── dashboard/template.html       ← gabarit du tableau de bord
├── veille/                       ← code Python
│   ├── boamp.py  ted.py          ← collecteurs
│   ├── scoring.py                ← calcul du score
│   ├── store.py                  ← fusion, rectificatifs, historique
│   ├── run.py                    ← exécution complète
│   ├── build_dashboard.py        ← génération du tableau de bord
│   └── health.py                 ← contrôle et alerte
├── tests/                        ← tests automatiques + données synthétiques
└── .github/workflows/veille.yml  ← planification GitHub Actions
```

### Lancer sur un ordinateur (facultatif, pour un développeur)
```bash
pip install -r requirements-dev.txt
python -m pytest              # tests
python -m veille.run          # collecte réelle + tableau de bord dans docs/index.html
python -m veille.run --offline   # recalcul des scores sans réseau
```

**Sécurité** : aucune clé ni mot de passe n'est nécessaire ou stocké. Si une source à clé est ajoutée un jour, la clé devra être placée dans **Settings → Secrets and variables → Actions**, jamais dans un fichier du dépôt.
