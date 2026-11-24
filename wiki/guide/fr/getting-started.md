---
title: Démarrer
description: Lancer l'instance avec Docker Compose, créer la clé de stockage et le mot de passe, puis se connecter la première fois.
order: 1
---

## Ce qu'il faut {#requirements}

- Un hôte avec Docker et Docker Compose.
- [just](https://github.com/casey/just) : chaque étape est une recette, et chaque recette tourne dans Docker.
- Un proxy inverse qui joint le conteneur sur un réseau Docker. `compose.yml` est prévu pour Traefik, sur un réseau
  externe nommé `proxy` par défaut. L'application écoute sur le port 8080 et ne publie aucun port.
- Une adresse fixe pour l'instance, par exemple `https://redirect.example.test`. Chaque lien et chaque QR code est
  écrit avec elle.

L'instance est faite pour le réseau local. Pour des liens joignables depuis Internet, voir [Cloudflare](cloudflare.md).

## Récupérer le dépôt {#get-the-code}

```sh
git clone https://github.com/LunaCreatoris/Moonie-Redirect.git
cd Moonie-Redirect
```

## L'adresse des liens {#public-url}

Copiez `.env.example` en `.env` et donnez l'adresse de l'instance :

```sh
MOONIE_REDIRECT_PUBLIC_BASE_URL=https://redirect.example.test
```

Elle est obligatoire : sans elle, l'application refuse de démarrer. Elle n'est jamais déduite de la requête.

**Choisissez-la avant d'imprimer.** Un QR code imprimé garde l'adresse du moment : si elle change, il ne mène plus
nulle part.

`MOONIE_REDIRECT_PROXY_NETWORK` donne le réseau de Traefik, `proxy` par défaut. Les étiquettes Traefik sont dans
`compose.yml`, en commentaire : décommentez-les et mettez-y le nom de l'instance.

## Les secrets {#secrets}

Trois fichiers, dans le dossier `secrets/`, à côté de `compose.yml` :

```sh
install -d -m 0700 secrets
just store-key > secrets/store_key
printf '%s\n' 'un long mot de passe' > secrets/password
python3 -c "import secrets; print(secrets.token_hex(32))" > secrets/api_token
sudo chown 10001:10001 secrets/*
sudo chmod 0400 secrets/*
```

- `store_key` est la **clé de stockage** : 64 caractères hexadécimaux. Sur un hôte sans le dépôt,
  `openssl rand -hex 32` en donne une aussi.
- `password` est le mot de passe de l'administrateur, sur une ligne.
- `api_token` est un jeton d'API qui a tous les droits. Il reste facultatif : une fois connecté, vous ferez plutôt des
  clés limitées dans les réglages. Pour vous en passer, commentez ses lignes dans `compose.yml`.

Les fichiers doivent appartenir à l'utilisateur de l'application, 10001, et n'être lisibles que par lui.

### La clé de stockage {#store-key}

La clé de stockage chiffre dans la base les deux valeurs que l'application doit relire : le jeton Cloudflare et le
secret du webhook. Elle reste hors du volume de données.

**Gardez-en une copie à part**, dans un gestionnaire de mots de passe par exemple, loin des sauvegardes du volume
`data` : la base seule ne donne aucun secret lisible. Sans la clé, il faudra saisir de nouveau ces deux valeurs.

## Lancer {#start}

```sh
just run
```

`just run` construit l'image `moonie-redirect:local` puis lance la pile de `compose.yml` avec `.env`. La base SQLite
est dans le volume `data`. Le conteneur tourne en lecture seule, sans aucune capacité, et redémarre de lui-même.

Vérifiez que `https://redirect.example.test/health` répond `{"status": "ok", "version": "9.3.1"}`.

## Première connexion {#first-login}

1. Ouvrez `https://redirect.example.test/admin/links` : la page de connexion s'affiche.
2. Saisissez le mot de passe de `secrets/password`.
3. Ouvrez **Settings** (la roue dentée en bas à gauche), onglet **Security**, et changez le mot de passe. Le nouveau
   est gardé dans la base et l'emporte sur le fichier.

L'interface est en anglais. Une session dure 12 heures. Ensuite :
[créer les premiers liens](links-nanourls-qrcodes.md).

Toutes les étapes et toutes les variables sont dans la section
[Deploying](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#deploying) du README.
