---
title: Moonie Redirect
description: Des liens fixes qui renvoient vers une cible que vous changez quand vous voulez, pour que les liens partagés et les QR codes imprimés marchent toujours.
status: Version 9.3.1
github: https://github.com/LunaCreatoris/Moonie-Redirect
order: 2
---

## À quoi ça sert {#what-it-is-for}

Un QR code imprimé ou un lien déjà envoyé ne se corrige plus. Redirect leur donne une adresse fixe qui répond par une
redirection vers la cible du moment. Quand la cible change, vous la modifiez à un seul endroit, et tout ce qui a été
imprimé ou partagé continue de marcher.

Redirect ne sert jamais la cible et ne la relaie pas : il répond seulement « allez là-bas ». Tout tient dans une
application Python, un conteneur et une base SQLite.

## Les trois sortes de liens {#link-kinds}

- **Liens** : un chemin choisi à la main, `/redirect/<chemin>`, avec un dernier jour de validité si vous voulez.
- **NanoURL** : le chemin vient du nom, `/redirect/NanoURL/<nom>`.
- **QR codes** : comme une NanoURL, sous `/redirect/QRcodes/<nom>`, avec un dessin à votre goût et un logo si vous
  voulez. Le code imprimé contient le lien court, pas la cible.

Chaque lien répond aussi à son lien court, `/links/<id>`. Voir
[Liens, NanoURL et QR codes](links-nanourls-qrcodes.md).

## Avec Cloudflare {#with-cloudflare}

L'instance est faite pour le réseau local. Avec un jeton d'API Cloudflare, un lien peut en plus répondre sur un nom
de vos propres zones, comme `https://go.example.test/promo` : c'est Cloudflare qui redirige, sans qu'aucune requête
n'atteigne l'instance. C'est facultatif. Voir [Cloudflare](cloudflare.md).

## Les pages du guide {#pages}

- [Démarrer](getting-started.md) : lancer l'instance, ranger ses secrets et se connecter la première fois.
- [Liens, NanoURL et QR codes](links-nanourls-qrcodes.md) : créer, modifier et partager les liens.
- [Cloudflare](cloudflare.md) : le jeton, les noms et l'adresse d'un lien.
- [Les réglages](settings.md) : la sécurité, le webhook, les clés d'API et l'onglet Cloudflare.
- [Mettre à jour](upgrading.md) : passer à une nouvelle version, reprendre les liens d'une installation antérieure, revenir en arrière.
- [Dépannage](troubleshooting.md) : les problèmes courants et leur solution.

## La référence technique {#reference}

L'API, les règles des chemins et des cibles, les variables et les recettes sont décrites dans le
[README du dépôt](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md), en anglais. Ce qui a été laissé de
côté exprès, et ce qui est prévu, est dans la
[feuille de route](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/ROADMAP.md).
