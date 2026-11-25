---
title: Les réglages
description: Le mot de passe et les sessions, le webhook, les clés d'API et leurs portées, le jeton Cloudflare.
order: 4
---

## La page Settings {#settings-page}

La roue dentée en bas à gauche ouvre **Settings**, en trois onglets : **Security**, **Webhook & API** et
**Cloudflare**. Seul l'administrateur connecté y a accès : aucune clé d'API, même avec tous les droits, ne peut lire
ni changer les réglages.

Une valeur réglée ici est gardée dans la base et l'emporte sur le fichier de `compose.yml`. L'effacer revient au
fichier. Chaque valeur dit d'où elle vient : **Set here**, **From file** ou **Not set**.

## La sécurité {#security}

- **Change password** demande le mot de passe actuel, puis un nouveau de 12 à 1024 caractères. Toutes les autres
  sessions se ferment, la vôtre reste ouverte.
- **End all sessions** ferme toutes les sessions, la vôtre comprise.

Après un mot de passe faux, toute nouvelle tentative pendant une seconde est refusée, pour tout le monde. Les
redirections, l'API et les sessions déjà ouvertes ne sont pas touchées.

Un mot de passe oublié se remet à zéro depuis l'hôte : voir [Dépannage](troubleshooting.md#lost-password).

## Le webhook {#webhook}

Le webhook envoie un POST signé à une adresse HTTP de votre choix, le récepteur, chaque fois qu'un lien, une NanoURL
ou un QR code est créé, modifié ou supprimé, depuis les pages ou par une clé d'API.

1. Dans **Webhook & API**, donnez l'adresse du récepteur, par exemple `http://receiver:8080/links-changed` sur un
   réseau Docker partagé.
2. Donnez un secret de signature de 16 à 256 caractères. Il n'est plus jamais affiché ; un champ laissé vide garde
   l'ancien.
3. Cochez les événements, enregistrez, puis **Send test**.

Les adresses du réseau local sont permises. Les adresses de bouclage (`localhost`), link-local, multicast et réservées
sont refusées. Un envoi qui échoue est retenté plusieurs fois ; la page montre la dernière livraison et ce qui attend.

Le récepteur vérifie la signature sur les octets bruts du corps. Les en-têtes et un exemple de vérification sont dans
la section
[The webhook](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#the-webhook) du README.

## Les clés d'API {#api-keys}

**New key** crée une clé : un nom, ses portées et votre mot de passe. La clé n'est affichée qu'une fois : copiez-la
tout de suite. **Revoke** la retire ; les appels qui l'envoient sont refusés aussitôt.

Une clé n'a que les portées qu'on lui donne :

- `redirect:links.read` et `redirect:links.write` pour les liens ;
- `redirect:nanourls.read` et `redirect:nanourls.write` pour les NanoURL ;
- `redirect:qrcodes.read` et `redirect:qrcodes.write` pour les QR codes ;
- `cloudflare:read`, `cloudflare:write` (poser un lien sur un nom Cloudflare) et `cloudflare:setup` (préparer un nom,
  ou utiliser un nom repris qui sert peut-être un site) ;
- `*`, `redirect:*` et `cloudflare:*` pour tout, ou tout un côté.

Un script envoie la clé dans `Authorization: Bearer <clé>`. Le fichier `api_token`, s'il est présent, apparaît comme
une ligne **Token file** avec toutes les portées : pour le retirer, supprimez le fichier et redémarrez.

## Cloudflare {#cloudflare}

L'onglet **Cloudflare** garde le jeton (**Replace**, **Clear**), la limite d'entrées de la liste (vide pour 10 000, la
valeur de l'offre gratuite), puis les noms, le quota, **Sync now** et **Compare with Cloudflare**. Voir
[Cloudflare](cloudflare.md).

## La clé de stockage et les sauvegardes {#backups}

Le jeton Cloudflare et le secret du webhook sont chiffrés dans la base avec la
[clé de stockage](getting-started.md#store-key). Le mot de passe et les clés d'API n'y sont gardés que sous forme
d'empreinte, et n'ont pas besoin de la clé.

Une base restaurée sans sa clé, ou une clé changée : ces deux valeurs s'affichent **Cannot be read**. Saisissez-les de
nouveau. Restaurer la base ferme aussi toutes les sessions.

Le détail est dans la section
[Settings](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#settings) du README.
