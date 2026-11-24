---
title: Mettre à jour
description: Passer à une nouvelle version, reprendre les liens et les noms Cloudflare d'une installation antérieure, et revenir en arrière.
order: 5
---

## Une nouvelle version {#new-version}

```sh
git pull
just run
```

`just run` reconstruit l'image et relance la pile. La base est migrée au démarrage, sans étape à lancer.

### Depuis une installation antérieure {#earlier-install}

Une installation d'avant la page **Settings** (la 9.1 ou plus ancienne) ne bouge pas : les fichiers de secrets
continuent de servir, et les réglages les montrent **From file**.

`compose.yml` attend maintenant le secret `store_key`. Créez-le avant le premier démarrage, comme dans
[Démarrer](getting-started.md#secrets), ou commentez ses lignes `store_key` : l'application tire alors sa clé dans le
volume de données, et une sauvegarde de ce volume contient à la fois les secrets et leur clé.

## Reprendre les liens d'une installation antérieure {#import-v7}

Seulement pour une installation de l'application antérieure que celle-ci remplace, dont la dernière version était la
7.0.1. Une nouvelle installation peut passer cette partie. La 7.0.1 gardait ses liens dans le fichier `moonie.db` de son
volume `data`. Les lignes passent telles quelles, identifiants et chemins compris : les QR codes imprimés continuent de
marcher.

1. Lancez la nouvelle instance, comme dans [Démarrer](getting-started.md), avec la même adresse publique que la 7.0.1.
2. Arrêtez proprement la 7.0.1, pour que son journal d'écriture soit versé dans le fichier, puis copiez `moonie.db`
   hors de son volume. Une copie accompagnée d'un `moonie.db-wal` en attente est refusée.
3. Rendez la copie lisible par l'utilisateur 10001 (`chmod 0644`).
4. Lancez l'import :

```sh
just import-v7 chemin/vers/moonie.db
```

L'import ouvre le fichier en lecture seule, ajoute chaque ligne dont l'identifiant et le chemin sont libres, et affiche
combien de lignes il a reprises, combien étaient déjà là et combien il a refusées. Le relancer ne change rien.

- Si la 7.0.1 avait le plugin Cloudflare, l'import reprend aussi ses comptes, sa liste, sa règle, ses noms et leurs
  pages pour chemins inconnus. Lancez ensuite **Compare with Cloudflare** une fois.
- Une NanoURL ou un QR code que la 7.0.1 avait écrit avec son adresse IP garde cette adresse dans le code imprimé :
  l'instance doit rester joignable à cette adresse. L'import dit combien de lignes sont dans ce cas.
- Les clés d'API et le webhook de la 7.0.1 ne sont pas repris : refaites-les dans les [réglages](settings.md).

## Revenir en arrière {#rollback}

Gardez une sauvegarde du volume `data` avant chaque mise à jour.

- **Vers la 9.1, d'avant la page Settings** : elle marche sur une base migrée et ignore les nouvelles tables. Le mot de
  passe, les clés, le jeton Cloudflare et le webhook réglés dans **Settings** n'existent pas pour elle : connectez-vous
  avec le mot de passe du fichier, et les scripts avec le fichier `api_token`. De retour en 9.2 ou plus, tout compte de
  nouveau.
- **Vers la 8.1.0** : chaque lien continue de répondre sur le réseau local. Mais tant qu'elle tourne, une modification
  ou une suppression d'un lien posé sur un nom Cloudflare n'est pas envoyée à Cloudflare : au retour, lancez
  **Compare with Cloudflare** et corrigez ce qu'il liste.
- Restaurer une sauvegarde de la base ferme toutes les sessions.

Le détail est dans les sections
[Upgrading and rolling back](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#upgrading-and-rolling-back)
et [Importing 7.0.1](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#importing-701) du README.
