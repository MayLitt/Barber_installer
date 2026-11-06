# Installer : moteur d'onboarding (équipe 06, rôle 4)

Principe : **ne jamais demander ce qu'on peut trouver.** Le moteur cherche le commerce, lit ses pages publiques,
extrait des faits typés, filtre les données personnelles, décide « trouvé / à valider / conflit / manquant »,
ne pose que les questions utiles, puis exporte une **config v1.0 versionnée avec la provenance de chaque champ**.

## Installation

```
pip install -r requirements.txt
```

Clés (jamais dans le code, jamais dans git, jamais dans une slide) :

```
# PowerShell (Windows)
$env:ANTHROPIC_API_KEY = "<clé d'équipe>"
$env:GOOGLE_MAPS_API_KEY = "AIzaSy..."      # optionnelle : sans elle, passer les URL à la main avec --url

# bash
export ANTHROPIC_API_KEY=...; export SERPER_API_KEY=...
```

## Utilisation

```
# 1) Cas d'usage fictif : Maison Lemoine importé depuis son fichier (aucun appel réseau)
python -m installer import fixtures/maison_lemoine.json --tag v1.0

# 2) Commerce réel : recherche + lecture des pages + extraction
python -m installer run --name "The barber by Lacrim" --city Nanterre --url https://thebarberbylacrim.com --tag v1.0

# 3) Voir, reprendre les questions, comparer deux versions (PLM)
python -m installer show out/<fichier>.json
python -m installer ask  out/<fichier>.json --tag v1.1
python -m installer diff out/a.v1.0.json out/a.v1.1.json

# 4) Fiche commerce à coller dans la base de connaissances de l'agent (ElevenLabs)
python -m installer kb out/<fichier>.json --out fiche.md
```

La fiche ne contient que des données `found` ou `confirmed` (option `--include-suggested` pour le reste) et la liste « informations non fournies ».
Elle ne contient pas le comportement de l'agent (ton, « je ne sais pas », rappel) : c'est le travail de l'Agent trainer, qui applique ensuite tout cela sur ElevenLabs.

Options utiles : `--no-ask` (génère la config sans poser les questions), `--url` (répétable, pages à lire), `--out`.
Les résultats d'extraction sont mis en cache (`.cache/`, texte nettoyé seulement) : relancer ne coûte pas de jetons.
Le nombre de jetons consommés est écrit dans `meta.tokens` de la config : surveille le budget de 18 $ de l'équipe.

## Ce que fait chaque fichier

| Fichier | Rôle | Section du document |
|---|---|---|
| `sanitize.py` | HTML -> texte visible (le texte caché n'atteint jamais le modèle), e-mails nominatifs masqués, signaux d'injection | 6 |
| `fetch.py` | Anti-SSRF (hôtes publics seulement), robots.txt, taille et durée limitées | 6 |
| `extract.py` | Extraction par Claude via un schéma typé ; la page est une donnée non fiable ; aucun champ pour avis, noms de famille ou comptes perso | 4, 6 |
| `validators.py` | Rejet : numéros surtaxés, noms complets, prix absurdes, horaires incohérents, texte d'injection | 6 |
| `build.py` | Fusion multi-sources, statuts, conflits (ex. 107 € vs 55 €), questions de calibration, liste « ce que l'agent ne saura pas » | 4, 5 |
| `registry.py` | API Recherche d'entreprises ; le nom d'un entrepreneur individuel n'est pas conservé | 5, 6 |
| `export.py` | Config versionnée, hash du contenu, diff entre versions | 4, 9 |
| `agent_export.py` | Fiche commerce en français : données validées seulement, sans prompt | 10 |
| `cli.py` | Écrans de validation et de questions en terminal | 4 |

Statuts : `found` (2 sources indépendantes d'accord), `suggested` (1 source, à valider), `conflict`, `confirmed` (validé par le commerçant), `missing`.
Les durées « par défaut du métier » sont toujours `suggested` avec la source `defaut_metier` : ce sont des valeurs de départ, jamais présentées comme trouvées.

## Tests

```
python -m pytest -q      # 28 tests, hors ligne, sans clé
```

Couverts : texte caché et injection, e-mails, anti-SSRF, validation (téléphone, horaires, prénoms, prix),
fusion (conflit de prix, sous-ensemble d'horaires, 06 à confirmer), Maison Lemoine, questions interactives,
export reproductible, diff entre versions, pipeline complet avec extracteur simulé.

## Ce qui n'est PAS vérifié (à faire au premier passage chez vous)

- Les appels réels : API Claude, Serper (`places` et `search`), API Recherche d'entreprises. Les noms de champs
  des réponses (`phoneNumber`, `nature_juridique`, `siege.adresse`...) sont écrits de mémoire : s'il manque une
  donnée, regarder d'abord la réponse brute.
- Le modèle par défaut est `claude-haiku-5-5` (variable `INSTALLER_MODEL` pour en changer).
- Pas encore d'interface web : les écrans de validation et de questions sont en terminal.
- Les avis ne sont pas traités (par conception : le schéma n'a pas de champ pour eux). Les thèmes d'avis restent à ajouter.
- Anti-SSRF : la résolution DNS est vérifiée avant chaque requête, mais pas contre le rebinding DNS.

## Suite possible

1. Écran web (validation en un clic + les 3 questions) au-dessus de ce moteur.
2. Import d'un export Planity / CSV de tarifs avec consentement.
3. Thèmes d'avis agrégés (seuil minimal, sans auteur ni texte).
4. Journal de versions branché sur `diff` pour le PLM manager.
