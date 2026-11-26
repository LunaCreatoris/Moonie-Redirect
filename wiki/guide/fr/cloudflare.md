---
title: Cloudflare
description: Faire répondre un lien sur un nom de vos zones Cloudflare, servi par Cloudflare sans qu'aucune requête n'atteigne l'instance.
order: 4
---

## Le principe {#how-it-works}

L'instance reste sur le réseau local. Avec un jeton d'API Cloudflare, un lien peut aussi répondre sur un nom de vos
propres zones, comme `https://go.example.test/promo`. Cloudflare sert la redirection lui-même, avec ses Bulk
Redirects : chaque lien est une entrée d'une liste `moonie_redirect` du compte. Les adresses de l'instance continuent
de répondre pour chaque lien, quelle que soit son adresse Cloudflare.

Sans jeton, Cloudflare est coupé et le choix d'adresse n'apparaît pas dans les formulaires.

## Le jeton {#token}

Créez un jeton d'API dans Cloudflare (My Profile ou Manage Account, API Tokens), avec ces quatre permissions, sur le
compte et les zones à utiliser :

- **Account · Account Rule Lists: Write** : crée la liste `moonie_redirect` et écrit ses entrées ;
- **Account · Account Rulesets: Write** : ajoute la règle qui redirige depuis cette liste ;
- **Zone · Zone: Read** : liste les zones que voit le jeton ;
- **Zone · DNS: Write** : crée l'enregistrement d'un nouveau nom.

Collez-le dans **Settings**, onglet **Cloudflare**. Cloudflare le vérifie avant qu'il soit gardé : un jeton refusé
n'est pas enregistré, et s'il manque une permission, la page dit laquelle. Il sert aussitôt, sans redémarrage. Il est
chiffré dans la base avec la [clé de stockage](getting-started.md#store-key).

Le conteneur doit joindre `api.cloudflare.com` en HTTPS. L'application ne lit aucun proxy dans l'environnement.

## Ajouter un nom {#add-a-host}

Sous le jeton, l'onglet liste les noms déjà prêts. **New host** en ajoute un :

1. Choisissez la zone, par exemple `example.test`, et le nom, par exemple `go`, pour `go.example.test`.
2. **Show the plan** montre ce qui sera fait. Rien ne change dans Cloudflare avant **Confirm the plan**.
3. Le plan peut créer la liste `moonie_redirect` du compte, ajouter une règle à côté de celles du compte (qui restent
   telles quelles) et créer un enregistrement d'attente, proxifié, `A go.example.test → 192.0.2.1`.

Un nom qui a déjà des enregistrements proxifiés est repris tel quel : il sert peut-être un site, et un lien posé dessus
prendrait le pas sur ce chemin. Le plan demande alors de cocher une confirmation.

Un nom créé ici peut avoir une **page pour les chemins inconnus** : la page 404 de Wikipédia, Google ou toute autre
adresse. Tout chemin sans lien sur ce nom y mène.

Rien d'autre n'est jamais changé ni supprimé dans Cloudflare : aucun enregistrement, aucune règle, aucune liste, seules
les entrées de la liste. Un nom ne peut pas encore être retiré d'ici ; la
[feuille de route](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/ROADMAP.md) dit comment faire à la main.

## L'adresse d'un lien {#link-address}

Une fois un nom prêt, chaque formulaire de lien, de NanoURL et de QR code a un choix **Link address** : le réseau local
d'abord, puis chaque nom.

- Un lien sur un nom répond à `https://go.example.test/<chemin>`.
- Une NanoURL ou un QR code répond à `https://go.example.test/<id>`, et le QR code contient alors cette adresse.
- Les listes montrent où répond chaque lien et son état : en attente, actif, en erreur ou expiré.

Un chemin sous `.well-known` est refusé sur un nom Cloudflare : les certificats et les contacts de sécurité y sont lus.

**Changer l'adresse, changer le chemin ou supprimer un lien posé sur un nom** coupe ce qui a été imprimé ou partagé
avec cette adresse. Les pages le demandent avant de le faire.

## La synchronisation {#sync}

Une tâche de fond envoie à Cloudflare ce qui a changé, retire ce qui a été supprimé, déplacé ou qui a expiré, et ne
touche qu'aux entrées marquées comme les siennes. Une entrée faite par quelqu'un d'autre à l'adresse d'un lien n'est
jamais écrasée : le lien reste en erreur.

- **Sync now** relance tout de suite les liens en erreur.
- **Compare with Cloudflare** liste ce qui manque chez Cloudflare, ce qui y diffère et ce qui n'y correspond à rien
  ici, et corrige ce que vous cochez. Retirer une entrée demande une seconde confirmation.

## Le quota {#quota}

Une liste tient 10 000 entrées sur l'offre gratuite, liens et pages pour chemins inconnus compris. La page prévient à
partir de 90 %. À la limite, un lien ne peut plus prendre un nom de ce compte : ramenez des liens sur le réseau local.
Si votre offre en permet plus, réglez la limite dans le même onglet.

Le détail est dans la section
[Cloudflare](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#cloudflare) du README.
