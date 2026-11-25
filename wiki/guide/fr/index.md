---
title: Moonie Redirect
description: Redirect fait des liens figés dont la cible, elle, peut changer.
status: Version 9.3.1
github: https://github.com/LunaCreatoris/Moonie-Redirect
order: 2
---

## À quoi ça sert {#what-it-is-for}

Redirect fait des liens figés dont la cible, elle, peut changer. Le lien que vous publiez ne bouge plus jamais ;
l'adresse vers laquelle il renvoie, vous la changez quand vous voulez.

## Trois façons de publier un lien {#link-kinds}

Chacune a sa page dans l'interface d'administration :

- **Une URL fixe** : vous choisissez le chemin, `/redirect/<chemin>`, par exemple `/redirect/promo`, avec un dernier
  jour de validité si vous voulez.
- **Un lien court, à la TinyURL** : une NanoURL n'a qu'un nom et une cible. Elle répond sous
  `/redirect/NanoURL/<nom>` et surtout à son lien court, `/links/<id>`, fait de 8 lettres et chiffres. C'est ce
  lien court qu'il vaut mieux partager : il reste le même si vous renommez la NanoURL.
- **Un QR code** : il se crée comme une NanoURL, sous `/redirect/QRcodes/<nom>`, avec un dessin à votre goût et un
  logo si vous voulez. Le code imprimé contient le lien court, pas la cible.

Chaque lien, quelle que soit sa façon, répond aussi à son lien court `/links/<id>`. Voir
[Liens, NanoURL et QR codes](links-nanourls-qrcodes.md).

## Ce qui change reste à un seul endroit {#one-place}

Un QR code imprimé ou un lien déjà envoyé ne se corrige plus. Quand la cible change, vous la modifiez une seule fois,
dans Redirect, et tout ce qui a été imprimé ou partagé continue de marcher.

Redirect ne sert jamais la cible et ne la relaie pas : il répond seulement « allez là-bas ». Tout tient dans une
application Python, un conteneur et une base SQLite.

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
