---
title: Démarrer
description: Choisir le mode, sur l'IP du LAN ou derrière un reverse proxy, lancer l'instance avec Docker Compose, en pile Portainer ou avec just, créer la clé de stockage et le mot de passe, puis se connecter la première fois.
order: 1
---

## Ce qu'il faut {#requirements}

- Un hôte avec Docker et Docker Compose. Aucune image n'est publiée : Docker Compose la construit à partir du dépôt.
- Un des deux modes : sur l'IP du réseau local, sans rien d'autre, ou derrière un proxy inverse. Voir
  [Choisir le mode](#mode).
- Une adresse fixe pour l'instance, par exemple `http://192.0.2.10:8080` sur le réseau local, ou
  `https://redirect.example.test` derrière un proxy inverse. Chaque lien et chaque QR code est écrit avec elle.

[just](https://github.com/casey/just) n'est pas nécessaire pour déployer. C'est l'outil des contributeurs : tests,
captures et `just ci`, la vérification qui précède chaque fusion. Il offre aussi une
[deuxième façon de lancer l'instance](#with-just).

L'instance est faite pour le réseau local. Pour des liens joignables depuis Internet, voir [Cloudflare](cloudflare.md).

## Récupérer le dépôt {#get-the-code}

```sh
git clone https://github.com/LunaCreatoris/Moonie-Redirect.git
cd Moonie-Redirect
```

Sans Git, téléchargez l'archive de la branche `main` depuis la page du dépôt (**Code**, puis **Download ZIP**) et
décompressez-la sur l'hôte.

## Choisir le mode {#mode}

L'application écoute sur le port 8080 du conteneur. Deux façons de la joindre, au choix.

### Sur l'IP du LAN {#lan}

Le mode par défaut : `compose.yml` seul. L'instance répond en `http` sur un port de l'hôte, 8080 par défaut, sans
proxy inverse ni réseau Docker à créer avant. L'adresse des liens est celle de l'hôte et de ce port, par exemple
`http://192.0.2.10:8080`.

Dans `.env`, `MOONIE_REDIRECT_PORT` change le port de l'hôte, et `MOONIE_REDIRECT_BIND` l'adresse de l'hôte où il
écoute : toutes par défaut (`0.0.0.0`).

**Ce mode est en `http` simple, sans chiffrement** : le mot de passe et le cookie de session passent en clair sur le
réseau. Il est fait pour un réseau local de confiance. Le cookie de session n'y est pas marqué `Secure`, sans quoi le
navigateur ne le renverrait pas sur une adresse en `http`.

### Derrière un reverse proxy {#behind-proxy}

Un proxy inverse sert l'instance en `https` sous un nom, et la joint sur son propre réseau Docker. Le fichier
`compose.proxy.yml`, posé sur `compose.yml`, retire le port publié sur l'hôte et rejoint ce réseau externe :
`proxy` par défaut, ou celui que donne `MOONIE_REDIRECT_PROXY_NETWORK`. Créez-le une fois s'il n'existe pas encore :

```sh
docker network create proxy
```

Le conteneur y répond à l'adresse `moonie-redirect:8080`. L'adresse des liens est celle du proxy, par exemple
`https://redirect.example.test`.

- **Traefik** : les étiquettes de `compose.proxy.yml` lui sont destinées. Donnez dans `.env` le nom public dans
  `MOONIE_REDIRECT_HOST`, le même que celui de l'adresse des liens, et au besoin le point d'entrée dans
  `MOONIE_REDIRECT_ENTRYPOINT`, `websecure` par défaut.
- **Un autre proxy inverse dans Docker** : il ignore ces étiquettes. Faites-le pointer vers
  `http://moonie-redirect:8080`, sur le même réseau. `MOONIE_REDIRECT_HOST` reste à donner, `compose.proxy.yml`
  s'arrête sans lui.
- **Un proxy inverse installé sur l'hôte lui-même** : gardez le mode LAN, avec `MOONIE_REDIRECT_BIND=127.0.0.1`, et
  faites-le pointer vers `http://127.0.0.1:8080`. Le port ne répond alors qu'à l'hôte.

Le proxy transmet les requêtes telles quelles : l'application n'a besoin d'aucun en-tête particulier, et n'écrit
jamais ses liens à partir de la requête.

## L'adresse des liens {#public-url}

Copiez `.env.example` en `.env` et donnez l'adresse de l'instance, selon le mode :

```sh
MOONIE_REDIRECT_PUBLIC_BASE_URL=http://192.0.2.10:8080
```

ou, derrière un proxy inverse :

```sh
MOONIE_REDIRECT_PUBLIC_BASE_URL=https://redirect.example.test
```

Elle est obligatoire : sans elle, l'application refuse de démarrer. Elle n'est jamais déduite de la requête.

**Choisissez-la avant d'imprimer.** Un QR code imprimé garde l'adresse du moment : si elle change, il ne mène plus
nulle part. Sur le réseau local, donnez à l'hôte une adresse fixe, réservée dans le routeur.

## Les secrets {#secrets}

Trois fichiers, dans le dossier `secrets/`, à côté de `compose.yml`. Depuis le dossier du dépôt, sur l'hôte :

```sh
install -d -m 0700 secrets
openssl rand -hex 32 > secrets/store_key
printf '%s\n' 'un long mot de passe' > secrets/password
openssl rand -hex 32 > secrets/api_token
sudo chown 10001:10001 secrets/*
sudo chmod 0400 secrets/*
```

- `store_key` est la **clé de stockage** : 64 caractères hexadécimaux. `just store-key > secrets/store_key` en tire
  une aussi.
- `password` est le mot de passe de l'administrateur, sur une ligne.
- `api_token` est un jeton d'API qui a tous les droits. Il reste facultatif : une fois connecté, vous ferez plutôt des
  clés limitées dans les réglages. Pour vous en passer, commentez ses lignes dans `compose.yml`.

Les fichiers doivent appartenir à l'utilisateur de l'application, 10001, et n'être lisibles que par lui. Sur Docker
Desktop (macOS, Windows), où ce propriétaire ne s'applique pas, rendez-les lisibles avec `chmod 0444 secrets/*`. Sur
un hôte sans `openssl`, Docker en tire un aussi :
`docker run --rm python:3.13.18-slim python -c "import secrets; print(secrets.token_hex(32))"`.

Le dossier peut être ailleurs : `MOONIE_REDIRECT_SECRETS_DIR`, dans `.env`, en donne le chemin, par exemple
`/opt/moonie-redirect/secrets`. Une pile Portainer en a besoin, avec un chemin absolu.

### La clé de stockage {#store-key}

La clé de stockage chiffre dans la base les deux valeurs que l'application doit relire : le jeton Cloudflare et le
secret du webhook. Elle reste hors du volume de données.

**Gardez-en une copie à part**, dans un gestionnaire de mots de passe par exemple, loin des sauvegardes du volume
`data` : la base seule ne donne aucun secret lisible. Sans la clé, il faudra saisir de nouveau ces deux valeurs.

## Lancer {#start}

Deux façons, au choix : Docker Compose, directement ou en pile Portainer, sans rien d'autre ; ou les recettes `just`.
Chacune a ses deux modes, [sur l'IP du LAN](#lan) ou [derrière un reverse proxy](#behind-proxy). Dans tous les cas, la
base SQLite est dans le volume `data`, et le conteneur tourne en lecture seule, sans aucune capacité, et redémarre de
lui-même.

### Avec Docker Compose {#with-compose}

Depuis le dossier du dépôt, sur l'IP du LAN :

```sh
docker compose up -d --build
```

Derrière un reverse proxy :

```sh
docker compose -f compose.yml -f compose.proxy.yml up -d --build
```

Docker Compose construit l'image `moonie-redirect:local` à partir du `Dockerfile` du dépôt, puis lance la pile avec
`.env`. `MOONIE_REDIRECT_IMAGE` change ce nom si besoin. `compose.proxy.yml` demande Docker Compose 2.24 ou plus
récent.

Pour ne pas répéter les deux `-f`, ajoutez à `.env` les deux lignes suivantes : chaque commande `docker compose` lit
alors les deux fichiers.

```sh
COMPOSE_PATH_SEPARATOR=,
COMPOSE_FILE=compose.yml,compose.proxy.yml
```

### En pile Portainer {#with-portainer}

Portainer ne construit pas l'image de façon fiable : sa documentation dit la construction depuis une pile Git
incomplète, et en échec sur un environnement distant. Il ne voit pas non plus les chemins relatifs du dépôt, réservés
à son édition Business. L'image se construit donc une fois sur l'hôte, et la pile la trouve toute prête.

Sur l'hôte que gère Portainer, récupérez le dépôt, créez les secrets dans un dossier absolu, par exemple
`/opt/moonie-redirect/secrets`, comme dans [Les secrets](#secrets), puis, depuis le dossier du dépôt, construisez
l'image :

```sh
docker build -t moonie-redirect:local .
```

Ensuite :

1. Dans Portainer, ouvrez **Stacks**, puis **Add stack**, et choisissez **Web editor**. Collez-y le contenu de
   `compose.yml` et supprimez la ligne `build: .`.
   - Sur l'IP du LAN, rien d'autre : la ligne `ports` publie le port.
   - Derrière un reverse proxy, remplacez les lignes `ports` du service par les lignes `networks` et `labels` de
     `compose.proxy.yml`, et ajoutez à la fin son bloc `networks`.
2. Dans **Environment variables**, ajoutez :
   - `MOONIE_REDIRECT_PUBLIC_BASE_URL`, l'adresse des liens, par exemple `http://192.0.2.10:8080` ;
   - `MOONIE_REDIRECT_SECRETS_DIR`, le dossier des secrets, par exemple `/opt/moonie-redirect/secrets` ;
   - au besoin `MOONIE_REDIRECT_PORT` sur l'IP du LAN, ou `MOONIE_REDIRECT_HOST` et `MOONIE_REDIRECT_PROXY_NETWORK`
     derrière un reverse proxy, comme dans `.env.example`.
3. Lancez **Deploy the stack**.

Le type **Repository** de Portainer lit `compose.yml` tel qu'il est dans le dépôt, sans rien y changer : il ne sert
qu'avec une copie du dépôt dont le `compose.yml` vous convient déjà, sur l'environnement local de Portainer, et une
fois l'image construite sur l'hôte. Donnez alors l'adresse du dépôt, la référence `refs/heads/main`, le chemin
`compose.yml`, et les mêmes variables d'environnement. Le plus simple reste l'éditeur web.

### Avec just {#with-just}

Depuis le dossier du dépôt, avec [just](https://github.com/casey/just) installé, sur l'IP du LAN :

```sh
just run
```

Derrière un reverse proxy :

```sh
just run-proxy
```

`just run` lance `docker compose up -d --build`, et `just run-proxy` la même commande avec les deux fichiers : la même
chose qu'à la main.

### Vérifier {#check}

Vérifiez que l'adresse des liens suivie de `/health`, par exemple `http://192.0.2.10:8080/health`, répond
`{"status": "ok", "version": "9.4.0"}`.

## Première connexion {#first-login}

1. Ouvrez l'adresse des liens suivie de `/admin/links`, par exemple `http://192.0.2.10:8080/admin/links` : la
   page de connexion s'affiche.
2. Saisissez le mot de passe de `secrets/password`.
3. Ouvrez **Settings** (la roue dentée en bas à gauche), onglet **Security**, et changez le mot de passe. Le nouveau
   est gardé dans la base et l'emporte sur le fichier.

L'interface est en anglais. Une session dure 12 heures. Ensuite :
[créer les premiers liens](links-nanourls-qrcodes.md).

Un tour de chaque écran, en captures d'écran, est dans [Utilisation](usage.md).

Toutes les étapes et toutes les variables sont dans la section
[Deploying](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#deploying) du README.
