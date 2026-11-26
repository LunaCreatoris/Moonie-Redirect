---
title: Liens, NanoURL et QR codes
description: Créer un lien, une NanoURL ou un QR code, changer sa cible sans casser ce qui a été partagé, et savoir ce qu'il répond.
order: 3
---

## Les pages {#pages}

Le menu de gauche, sous Redirect, ouvre trois pages : **Links**, **NanoURLs** et **QR codes**. Chacune montre la liste,
avec sa recherche, à côté du formulaire du lien choisi ou d'un nouveau lien. Les plus récemment modifiés viennent en
premier. Un bouton copie chaque adresse, et une fenêtre demande confirmation avant une suppression ou avant de perdre
un formulaire en cours.

## Un lien {#a-link}

1. Ouvrez **Links**, puis **New link**.
2. Donnez un nom, la cible (une adresse complète en `http://` ou `https://`) et le chemin (**Slug**). Un chemin libre
   est proposé, et **Random** en tire un autre.
3. Si vous voulez, donnez un dernier jour (**Expiry**, au format `AAAA-MM-JJ`). Le lien marche jusqu'à la fin de ce
   jour, en temps universel (UTC), puis répond « introuvable ».
4. Enregistrez.

Le lien répond à `https://redirect.example.test/redirect/<chemin>`, et aussi à son lien court,
`https://redirect.example.test/links/<id>`, où `<id>` fait 8 lettres et chiffres.

**Changer le chemin casse l'ancien.** Changer la cible, en revanche, ne casse rien : c'est tout l'intérêt.

## Une NanoURL {#a-nanourl}

Une NanoURL n'a qu'un nom et une cible. Le chemin vient du nom : `/redirect/NanoURL/<nom>`, sans les accents, les
autres caractères devenant des tirets. Renommer une NanoURL change ce chemin, mais son lien court reste le même :
c'est lui qu'il vaut mieux partager.

## Un QR code {#a-qr-code}

Un QR code se crée comme une NanoURL, sous `/redirect/QRcodes/<nom>`, avec un dessin en plus :

- les couleurs des modules, des coins et du fond (le fond peut être transparent) ;
- la forme des modules et des coins, et la marge ;
- un logo au centre, en PNG, JPEG, WebP ou SVG, de 256 Kio au plus, avec sa taille.

L'aperçu se redessine à chaque changement. Si les couleurs sont trop proches, le dessin est refusé : un lecteur
pourrait ne pas lire le code. **Download SVG** télécharge le fichier à imprimer.

Le code contient le lien court, pas la cible : vous pouvez changer la cible après l'impression. Le même lien et le
même dessin donnent toujours le même fichier.

## Ce que répond un lien {#what-a-link-answers}

- Une redirection `302` vers la cible, que le navigateur ne garde pas en cache. Un lien passé en `301` par l'API, ou
  repris d'une installation antérieure, le garde, et son formulaire le signale.
- Les paramètres de la visite ne sont jamais transmis : `/redirect/promo?utm_source=x` mène à la cible enregistrée,
  seule.
- Un lien inconnu ou expiré répond `404`.
- Chaque visite écrit une ligne de journal avec le chemin et le code, jamais la cible, qui peut contenir un jeton.

## Automatiser {#automate}

Tout ce que font les pages passe par une API JSON. Un script envoie une clé d'API dans `Authorization: Bearer <clé>` ;
les clés se font dans les [réglages](settings.md#api-keys). Les appels et les règles des chemins, des noms et des
cibles sont dans les sections
[JSON API](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#json-api) et
[Rules](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#rules) du README.
