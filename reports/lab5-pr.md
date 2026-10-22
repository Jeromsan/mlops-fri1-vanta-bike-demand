# PR proposée

Titre : Lab 5 — vérifier le modèle déployé et journaliser les requêtes

## Problème et changements

Le service du Lab 4 ne permettait pas de contrôler complètement l'identité du
déploiement et ne produisait pas de logs structurés par requête. `/health`
expose maintenant la version, l'empreinte des octets chargés et le commit source,
en conservant les champs et comportements existants. Les événements JSON
résument les requêtes sans leur contenu. Le contrôle HTTP externe compare des
attentes indépendantes et échoue sur toute différence.

Le Dockerfile conserve le verrou, accepte le modèle en lecture seule et coupe
les logs d'accès Uvicorn. Les rapports d'équipe ne sont plus copiés dans l'image.
Le README décrit le lancement PowerShell, les dix décisions, les échecs
volontaires et le nettoyage. Aucun modèle n'a été réentraîné ni remplacé.

## Vérifications réalisées

- Ruff, formatage et preflight réussis.
- 205 tests réussis en local et 205 dans l'image sans réseau externe ; deux avertissements de dépréciation dans chaque suite.
- Vrai conteneur : identités concordantes, prédiction 200, entrée invalide 422, contrôle code 0.
- Mauvais commit attendu : contrôle code 1 alors que le service répond 200.
- Même image sans modèle : 503/503/422 ; contrôle normal code 1.
- Lignes applicatives JSON valides et identifiants des réponses sauvegardées présents une seule fois.
- Montage `/models` en lecture seule, ports publiés sur 127.0.0.1 seulement.

Code construit : `baee60a4dd24b4a30deb84320b6b4bc33c0e4def`.
Image : `sha256:02615bba3ec726d316b2e73863da6bf8e52dd03a6ea74c5ed29a9ae7f7d30f65`.
Les fichiers de preuves et le rapport sont ajoutés après ce commit.

Rapport : [week-03-team.md](week-03-team.md).
Preuves : [lab5-20261022](lab5-20261022/), notamment
[contrôle réussi](lab5-20261022/check.log),
[mauvaise révision](lab5-20261022/wrong-commit.log),
[logs sans modèle](lab5-20261022/missing-container.log) et
[tests dans l'image](lab5-20261022/container-tests.log).

## Limites et revue demandée

Aucune CI distante observée, aucune approbation humaine déclarée. Le modèle
hérité a été entraîné sur un arbre modifié ; cette provenance est documentée.
Le Lab 6, les contributions propres des autres membres et le contrôle final
par une personne désignée restent à faire. Aucun tag m3 n'a été créé.

Pour la revue, suivre uniquement « Deploy — Lab 5 » du README sur cette branche.
Changer le port hôte, par exemple 8000 vers 8010, puis vérifier les réponses,
les identités, les logs et le port enregistré dans les preuves. Vérifier aussi
le montage en lecture seule, les cas invalides et sans modèle. Laisser une
observation concrète ; l'auteur documentera sa réponse et sa relance.
Ne pas fusionner avant les contrôles et cette revue.
