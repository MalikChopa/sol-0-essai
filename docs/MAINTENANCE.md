# Maintenance de Sol-0 / Maintaining Sol-0

## Mises à jour des dépendances
- `requirements.lock` : versions exactes et hachages (roues seulement : manylinux x86-64 pour le runner, macOS arm64 pour le poste). Installation : `pip install --no-deps --only-binary=:all: --require-hashes -r requirements.lock`.
- Pour changer une version : relever les hachages sur l'API JSON de PyPI (`https://pypi.org/pypi/<paquet>/<version>/json`, champ `urls[].digests.sha256`, roues `cp312`), mettre à jour `pyproject.toml` (mêmes versions), `requirements.lock`, puis lancer `tests/workflow` (le test compare les hachages à PyPI) et régénérer les empreintes (`rover refs`, comparées Mac ↔ runner par `tools/compare_refs.py`). Un changement de numpy peut changer des empreintes : les références se refont alors des deux côtés.
- `requirements-dev.txt` : outils de test (pytest, hypothesis, PyYAML), jamais utilisés par le workflow. Il ne contient plus `-r requirements.lock` (mode hachages de pip) : installer `requirements.lock` d'abord, puis ce fichier.

## Mises à jour des actions GitHub
Deux actions seulement, épinglées par SHA de 40 caractères (commentaire = étiquette). Pour changer : `gh release view --repo actions/checkout --json tagName -q .tagName`, puis `gh api repos/actions/checkout/commits/<étiquette> --jq .sha` ; idem `actions/setup-python`. Ne jamais inventer un SHA ; aucun autre tiers (le test `test_uses_are_pinned_to_40_hex_sha` l'impose). Relevés du 2026-11-11 : checkout v7.0.1, setup-python v7.1.0.

## Écrire le YAML du workflow
Une commande qui contient `: ` (deux-points puis espace, ex. `--only-binary=:all: `) doit être un scalaire de bloc (`run: |`), sinon le YAML est invalide et GitHub n'indique que « workflow file issue » (rencontré pendant l'essai). `tests/workflow` charge le fichier avec PyYAML (la clé `on` se lit `d[True]` en YAML 1.1).

## Tests de la plateforme
`.venv/bin/python -m pytest -q tests/workflow` : `publish.sh` et `fetch_state.sh` contre un dépôt nu local, variantes du workflow, SHA des actions, hachages, absence de réseau dans `src/rover`, périmètre de publication, `set_repo`, `compare_refs`.

## Périmètre de publication
`tools/export_public.py` : liste blanche (`src/ config/ tests/ tools/ci tools/brain tools/render tools/*.py tools/chain.sh pages/ pyproject.toml requirements.lock requirements-dev.txt .github/ docs/OPERATIONS.md docs/MAINTENANCE.md`). Refus si un fichier contient un chemin de dossier personnel ou un motif privé du fichier local `.private_patterns` (ignoré par git, jamais exporté). Pour ajouter un dossier à la liste : modifier `DIRS` et son test.

## Références Mac ↔ runner
`rover refs --out out/refs-mac.json` (Mac), `gh workflow run sol.yml -f mode=refs`, puis `tools/compare_refs.py out/refs-mac.json --run <id> --repo <dépôt>` (code 0 attendu). Piège connu : un `np.arange`/`linspace` à pas flottant donne des valeurs différentes selon la machine (voir `docs/TRIAL.md`).

*EN: pinned versions with hashes, SHA-pinned actions, whitelist export, refs compared Mac vs runner.*
