# Exploitation de Sol-0 / Operating Sol-0

*English summary at the end of each section.*

## Le workflow `sol`
- Fichier : `.github/workflows/sol.yml`. Déclencheurs : `schedule` (cron `17 1,7,13,19 * * *`, 4 sols par jour, heures UTC) et `workflow_dispatch` seulement.
- Modes manuels (`gh workflow run sol.yml -R <propriétaire>/<dépôt> -f mode=<mode>`) :
  - `sol` : un sol (par défaut pour le planning) ;
  - `check` : valide l'état publié, n'écrit rien ;
  - `refs` : calcule les empreintes de référence (imprimées dans le journal du job, entre `REFS-BEGIN` et `REFS-END`, et dans le résumé) ;
  - `restore` avec `-f checkpoint=sol-NNNNNN` : republie un checkpoint nommé après validation, `epoch + 1` ; ne supprime jamais la branche `state`.
- Ordre de publication : branche `state` (source de vérité), tags, puis `journal/ atlas/ firsts/` sur `main`.
- Codes de `publish.sh` : 0 succès ; 1 rouge après publication (3 sols passifs de suite, ou `main` refusé avec `main_lag` ≥ 2) ; 4 push de `state` impossible après 4 essais ; 5 `state` modifié par un autre écrivain (bail refusé), rien d'autre n'est poussé.
- *EN: schedule + manual dispatch only; modes sol, check, refs, restore; state first, then tags, then main.*

## Réactivation (règle des 60 jours de GitHub)
GitHub désactive les workflows planifiés d'un dépôt public sans activité pendant 60 jours. Décision F1 : **aucun commit vide, aucune réactivation par l'API** ; la seule activité est le vrai produit (commit d'état, commit du journal). Si le workflow est désactivé :
- interface : Actions, `sol`, « Enable workflow » ;
- ligne de commande : `gh workflow enable sol.yml -R <propriétaire>/<dépôt>`, puis `gh workflow run sol.yml -R <propriétaire>/<dépôt> -f mode=sol`.
Condition : aucune protection de `main` qui exige une PR (ou une exception pour `github-actions[bot]`). Sinon le push du journal est refusé : l'entrée reste dans `journal_tail` et le run devient rouge au 3e échec de suite.
La date du dernier contact figure dans `console.gif` et `status.svg`.
*EN: re-enable with `gh workflow enable`; no empty commits, ever (decision F1, to be re-validated by the owner).*

## Restauration
1. Lister les checkpoints : branche `state`, dossier `state/checkpoints/` (5 gardés).
2. `gh workflow run sol.yml -R <propriétaire>/<dépôt> -f mode=restore -f checkpoint=sol-000123`.
3. Vérifier le run, puis `status.json` (`det.restored_from`) sur la branche `state`.
Un état corrompu est restauré automatiquement par `rover sol` (checkpoint sain le plus récent, `epoch + 1`). Un état plus récent que le code (schéma, stade) est refusé (code 3) : sortie par `mode=restore` ou par un nouveau code.
*EN: restore with mode=restore and the checkpoint name.*

## Écrivain extérieur sur `state`
Un commit manuel sur `state` pendant un run fait refuser le bail (code 5, run rouge, rien d'autre poussé). Le run suivant lit l'état modifié et le réécrit : tout fichier ajouté à la main sur `state` disparaît. Ne pas écrire sur `state` à la main.

## Taille du dépôt
`publish.sh` relève `gh api repos/<dépôt> --jq .size` (Ko) : `::notice::` sinon `::warning::` au-delà de `repo_size_alert_kb` (1 048 576 Ko = 1 Go, `config/run.toml`). La valeur renvoyée par GitHub est différée. Parades au-delà de 1 Go : demander un nettoyage au support GitHub, ou espacer les checkpoints. La purge des anciens commits orphelins de `state` prend des semaines (non documentée, non mesurée).

## Mise en ligne sur le profil (jamais lancée par un agent ; seulement avec l'accord de l'utilisateur)
1. Copie datée du README de profil ; relecture des protections (`gh api repos/<compte>/<compte>/rulesets`, protection de `main`).
2. `.venv/bin/python tools/export_public.py --out out/prod` ; l'utilisateur relit la liste (`--list`).
3. PR 1, branche `sol-0-setup` issue du `main` du profil : code et workflow, **sans** la section README (le commit sans historique de l'export ne sert pas de base : GitHub refuse une PR sans ancêtre commun). Après fusion par l'utilisateur : `gh workflow run sol.yml -R <compte>/<compte> -f mode=sol`, vérifier `state` et les URL brutes.
4. PR 2 : `tools/set_repo.py --prod --repo <compte>/<compte> --readme README.md --out README.md` sur une copie, section entre `<!-- SOL0:BEGIN -->` et `<!-- SOL0:END -->`. `pages/` doit être à la racine de `main` (liens relatifs de la section).
5. 14 jours de suivi ; noter ici la date de mise en ligne et celle du dernier contact.
*EN: go-live is two PRs, after the owner's approval; never run by an agent.*

Note : `tools/compare_refs.py --run` appelle `gh` ; le lancer avec le `HOME` normal (avec un `HOME` temporaire, `gh` n'est pas authentifié et sort en code 4).
*EN: run compare_refs --run with the real HOME so gh is authenticated.*
