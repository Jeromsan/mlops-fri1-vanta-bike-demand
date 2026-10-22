# Semaine 3 — Labs 5 et 6

## Lab 5 — Déployer et vérifier le service

Le service du Lab 4 fonctionne maintenant dans une image qui permet de vérifier
le modèle et le code utilisés. `/health` conserve ses champs et ajoute
`model_sha256` et `source_commit`. Le SHA-256 est calculé sur les mêmes octets que
ceux transmis à joblib. Le service ne réentraîne pas le modèle.

Chaque requête produit un événement `request_completed` sur une seule ligne
JSON. Il contient l'heure UTC, un identifiant généré, la méthode, la route, le
statut, la durée et les identités disponibles. Les corps, paramètres d'URL,
en-têtes d'authentification et adresses clients ne sont pas journalisés. Les
routes inconnues sont remplacées par `<unmatched>`. Les événements de démarrage
sont distincts et les logs d'accès Uvicorn sont désactivés dans l'image.

Le contrôle externe utilise HTTP depuis l'hôte. Ses attentes sont fournies en
arguments, à partir du dossier évalué du Lab 4 et du commit de construction.
Il vérifie la santé, les trois identités, une prédiction et le rejet `hr=24`.
Une seule différence suffit à produire un code de sortie 1.

### Source, image et exécutions

Vérifications locales réalisées le 22 octobre 2026, sur Windows avec Docker
Desktop et un moteur Linux. La branche est `lab5/service-deployment`, créée
sur `main` à partir de `edcc0f717b842b9c5708e3622ce4f88580193a2a`.

- Commit construit : `baee60a4dd24b4a30deb84320b6b4bc33c0e4def`.
- Image : `sha256:02615bba3ec726d316b2e73863da6bf8e52dd03a6ea74c5ed29a9ae7f7d30f65`.
- Modèle attendu et observé : `baseline-df42e666d6d6`.
- Empreinte attendue et observée : `fd98ceafc57a5babce61ce703cbf9cb8d1f83c6820b0b34fe30ad1a0fc49c304`.
- Révision attendue et observée : le commit construit ci-dessus.

Au début de la construction, aucun fichier suivi n'était modifié. Le dossier
pédagogique `lab/` et le dossier de preuves étaient non suivis et exclus du
contexte Docker. Les preuves et ce rapport sont des ajouts ultérieurs : ils ne
font pas partie du commit embarqué. Aucune publication ni fusion n'a été faite.

Le service chargé utilisait `MODEL_DIR=/models`, avec un montage en lecture
seule et le port hôte `127.0.0.1:8000`. Le service sans modèle utilisait la même
image sur `127.0.0.1:8001`, sans montage. Les identifiants de conteneurs et ces
paramètres sont dans [containers.json](lab5-20261022/containers.json).

### Résultats observés

| Contrôle | Résultat |
| --- | --- |
| Construction Docker | Code 0 |
| Ruff et formatage | Réussis |
| Preflight local | Code 0 |
| Suite complète locale | 205 réussites, 2 avertissements, code 0 |
| Suite complète dans l'image, réseau externe coupé | 205 réussites, 2 avertissements, code 0 |
| Santé et trois identités du service chargé | Concordantes, HTTP 200 |
| Prédiction valide | HTTP 200, `149.2911970908957` et version attendue |
| Entrée invalide | HTTP 422 |
| Contrôle du déploiement correct | Code 0 |
| Mauvaise révision attendue | Code 1, différence affichée pour `source_commit` |
| Sans modèle : santé / prédiction valide / entrée invalide | 503 / 503 / 422 |
| Contrôle normal face au service sans modèle | Code 1 |
| Contrôle spécial de la panne attendue | Code 0 ; cela ne certifie pas un déploiement prêt |
| Inspection ciblée de l'image | Modèle, tracking, métriques et chemins privés vérifiés absents |

La mauvaise révision attendue ne provoque pas une panne du service : les
requêtes restent valides mais le contrôle refuse son identité. Sans montage,
le fichier nécessaire au chargement manque. Le journal contient alors
`model_unavailable`, avec `FileNotFoundError` et une action de diagnostic, puis
les événements de requêtes en 503 ou 422. Aucun chemin local ni traceback
n'apparaît dans ce journal applicatif.

L'audit des lignes JSON compte 9 fins de requêtes pour le service chargé
(6 réponses 200, 3 réponses 422), et 13 pour le service sans modèle
(10 réponses 503, 3 réponses 422). Les 13 incluent les interrogations répétées
pendant l'attente bornée du contrôle normal. Le second journal comprend aussi
un événement de démarrage distinct. Chaque réponse curl sauvegardée correspond
à un seul identifiant dans les logs. L'empreinte du modèle après les essais
reste identique.

### Preuves brutes

Toutes les preuves de cette exécution sont dans [lab5-20261022](lab5-20261022/).

- Origine : [commit](lab5-20261022/source-commit.txt), [état Git](lab5-20261022/git-status.txt), [attentes indépendantes](lab5-20261022/expected.json).
- Construction : [commande](lab5-20261022/build-command.txt), [sortie brute](lab5-20261022/build.log), [code de sortie](lab5-20261022/build-exit.txt), [image](lab5-20261022/image-id.txt).
- Exécution : [commandes et codes attendus](lab5-20261022/commands.json), [santé](lab5-20261022/health.log), [prédiction](lab5-20261022/valid.log), [entrée invalide](lab5-20261022/invalid.log).
- Contrôles : [cas correct](lab5-20261022/check.log), [mauvaise révision](lab5-20261022/wrong-commit.log), [panne attendue](lab5-20261022/missing-check.log), [contrôle normal en panne](lab5-20261022/missing-normal-check.log). Chaque sortie a son fichier `*-exit.txt`.
- Sans modèle : [santé](lab5-20261022/missing-health.log), [prédiction](lab5-20261022/missing-valid.log), [entrée invalide](lab5-20261022/missing-invalid.log).
- Journaux : [service chargé](lab5-20261022/container.log), [service sans modèle](lab5-20261022/missing-container.log), [audit JSON et empreinte finale](lab5-20261022/log-audit.json).
- Qualité : [Ruff](lab5-20261022/ruff-check.log), [formatage](lab5-20261022/ruff-format.log), [preflight](lab5-20261022/preflight.log), [tests locaux](lab5-20261022/local-tests.log), [tests dans l'image](lab5-20261022/container-tests.log).
- Contenu : [audit ciblé de l'image](lab5-20261022/image-audit.log).
- Fin des essais : [arrêt et suppression des conteneurs](lab5-20261022/cleanup.log).

Les commandes Docker, curl et uv ont été exécutées depuis PowerShell ; un
petit programme Python a conservé stdout/stderr et les codes de sortie sans
les conversions de stderr de Windows PowerShell. Les arguments réellement
exécutés sont conservés. Le README donne la procédure PowerShell équivalente ;
elle n'a pas encore été suivie de bout en bout par un autre membre.
Aucune capture d'écran n'a été utilisée.

### Décisions et limites

Les dix choix et leurs alternatives sont dans la section « Deploy — Lab 5 » du
README. Nous gardons le modèle hors de l'image pour pouvoir monter la paire
approuvée sans reconstruire le code. Nous vérifions version et empreinte plutôt
qu'un simple nom. Le port est limité à localhost. Un 503 observable permet de
diagnostiquer un modèle absent, plutôt que de confondre processus vivant et
service prêt. Aucune dépendance supplémentaire ni modification du verrou
n'était nécessaire.

Le modèle vient du Lab 4. Ses métadonnées indiquent un entraînement sur un arbre
modifié : son commit d'entraînement ne décrit donc pas tout le code utilisé.
Cette limite est conservée ; le modèle n'a pas été régénéré. Les tests de
régression entraînent seulement des fixtures isolées et ne remplacent pas
l'artefact d'équipe. Aucune métrique de la période de test n'a été calculée.

La première tentative des tests API a été bloquée par les droits du dossier
temporaire Windows dans le bac à sable. La relance autorisée hors du bac à sable
a réussi. La capture de la suite locale contient aussi un message de connexion
interrompue du petit serveur HTTP de test, sous délai de 0,1 seconde ; pytest a
terminé avec 205 réussites. La suite dans l'image n'a pas ce message. Les deux
avertissements concernent TestClient et SQLAlchemy ; les assertions n'ont pas
été désactivées.

Ces essais sont locaux. Aucune exécution distante de GitHub Actions sur ce
commit n'a été observée. L'inspection de l'image est ciblée sur les chemins
annoncés ; elle ne constitue pas un audit de sécurité exhaustif. Le contrôle
valide un état à un instant donné, pas la disponibilité future ni la qualité
prédictive. Le propriétaire du contrôle final reste à désigner.

### Contributions et revues

Cette implémentation et ces vérifications ont été préparées dans la session de
travail de Jeromsan avec l'aide de Codex. Aucune contribution de Merwane ou
Yvan, aucune PR et aucune revue humaine ne sont attestées par cette exécution.
Leur participation au Lab 5 est annoncée, mais leurs contributions propres et
leurs revues restent à réaliser et à documenter. La proposition de répartition
précédente n'est pas un relevé de travail accompli.

Avant acceptation : chaque membre réalise une contribution substantielle dans
sa PR et relit une autre PR. Un autre membre suit uniquement le README,
modifie le port ou le chemin du modèle, relève un point concret et vérifie les
preuves. La personne chargée du contrôle final doit être nommée. La préparation
de PR est dans [lab5-pr.md](lab5-pr.md).

## Lab 6

Non réalisé dans cette session. Le workflow existant n'a pas été étendu.
Les preuves CI, les échecs et réparations de workflow restent à produire.
Le tag `m3` ne doit être créé qu'après revue et intégration des Labs 5 et 6.
Le rapport individuel de semaine 3 reste à préparer dans le dépôt personnel
à partir des contributions et revues réellement effectuées.
