---
title: Dépannage
description: Les problèmes courants, de l'instance qui ne démarre pas au lien Cloudflare en erreur, et ce qui les règle.
order: 6
---

## L'instance ne démarre pas {#does-not-start}

`docker compose logs moonie` donne la raison en une ligne.

- **L'adresse des liens manque** : Docker Compose s'arrête sur `set MOONIE_REDIRECT_PUBLIC_BASE_URL in .env`.
  Donnez-la dans `.env`, voir [Démarrer](getting-started.md#public-url).
- **Un fichier de secret manque** : Docker Compose s'arrête avant de lancer le conteneur. Créez le fichier, ou
  commentez ses lignes dans `compose.yml`.
- **La clé de stockage est illisible ou mal formée** : le fichier doit contenir 64 caractères hexadécimaux et être
  lisible par l'utilisateur 10001.
- **`the API token must be at least 32 characters`** : le fichier `api_token` est trop court. Tirez-en un nouveau, comme
  dans [Démarrer](getting-started.md#secrets).

## Mot de passe perdu {#lost-password}

Depuis le dossier du dépôt, sur l'hôte :

```sh
just reset-password
```

La recette efface le mot de passe réglé dans **Settings** et ferme toutes les sessions : le mot de passe de
`secrets/password` compte de nouveau. Connectez-vous avec lui, puis changez-le.

## La connexion répond « Too many attempts » {#too-many-attempts}

Après un mot de passe faux, toute tentative dans la seconde qui suit est refusée, pour tout le monde. Si cela dure, un
client du réseau essaie sans cesse un mauvais mot de passe : trouvez-le et arrêtez-le. Les liens, l'API et les
sessions ouvertes ne sont pas touchés.

## Une valeur affiche « Cannot be read » {#cannot-be-read}

La base a été restaurée sans sa clé de stockage, ou la clé a changé. Le jeton Cloudflare revient au fichier s'il y en a
un, sinon Cloudflare se coupe ; le webhook n'envoie plus rien et ses événements attendent. Saisissez de nouveau le jeton
et le secret du webhook dans les [réglages](settings.md).

## Un lien Cloudflare reste en erreur {#cloudflare-error}

L'état du lien dit pourquoi :

- **Une entrée que l'application n'a pas faite** tient déjà cette adresse dans la liste Cloudflare : retirez-la dans
  Cloudflare, ou choisissez un autre chemin, puis **Sync now**.
- **Ce nom est maintenant l'adresse de l'instance** : `MOONIE_REDIRECT_PUBLIC_BASE_URL` pointe sur ce nom. Rien n'y est
  envoyé : déplacez ses liens vers une autre adresse.
- **La liste est pleine** : le lien attend une place. Voir [le quota](cloudflare.md#quota).
- **Le jeton manque d'une permission ou est refusé** : l'onglet Cloudflare dit laquelle. Voir
  [le jeton](cloudflare.md#token).

En cas de doute, **Compare with Cloudflare** montre les écarts entre l'instance et Cloudflare.

## Le webhook n'envoie rien {#webhook-silent}

- **« This address is closed »** : l'adresse est une adresse de bouclage, link-local, multicast ou réservée. Utilisez
  le nom du service sur le réseau Docker, par exemple `http://receiver:8080/...`, ou une adresse du réseau local.
- **« Webhook disabled »** : le récepteur a répondu `410 Gone`. Les événements attendent ; **Save** rallume le webhook.
- **Le récepteur refuse la signature** : il doit la vérifier sur les octets bruts du corps, avant de les lire comme
  du JSON : un JSON lu puis réécrit n'a plus forcément les mêmes octets.

## Plus d'aide {#more-help}

Ce qui a été laissé de côté exprès, et ce qui est prévu, est dans la
[feuille de route](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/ROADMAP.md). Le reste est dans le
[README](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md).
