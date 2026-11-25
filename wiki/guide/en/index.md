---
title: Moonie Redirect
description: Redirect makes fixed links whose target can change.
status: Version 9.3.1
github: https://github.com/LunaCreatoris/Moonie-Redirect
order: 2
---

## What it is for {#what-it-is-for}

Redirect makes fixed links whose target can change. The link you publish never moves again; the address it sends
people to, you change whenever you want.

## Three ways to publish a link {#link-kinds}

Each one has its page in the admin interface:

- **A fixed URL**: you choose the path, `/redirect/<path>`, for example `/redirect/promo`, with a last valid day if
  you want one.
- **A short, TinyURL-style link**: a NanoURL has only a name and a target. It answers under
  `/redirect/NanoURL/<name>` and above all at its short link, `/links/<id>`, made of 8 letters and digits. That short
  link is the one to share: it stays the same if you rename the NanoURL.
- **A QR code**: it is created like a NanoURL, under `/redirect/QRcodes/<name>`, with a design of your choice and a
  logo if you want one. The printed code holds the short link, not the target.

Every link, whichever way it is published, also answers at its short link, `/links/<id>`. See
[Links, NanoURLs and QR codes](links-nanourls-qrcodes.md).

## What changes stays in one place {#one-place}

A printed QR code or a link already sent can no longer be corrected. When the target changes, you edit it once, in
Redirect, and everything that was printed or shared keeps working.

Redirect never serves the target and never relays it: it only answers "go over there". It all fits in one Python
application, one container and one SQLite database.

## With Cloudflare {#with-cloudflare}

The instance is made for the local network. With a Cloudflare API token, a link can also answer on a name in your own
zones, such as `https://go.example.test/promo`: Cloudflare does the redirect, and no request reaches the instance. It
is optional. See [Cloudflare](cloudflare.md).

## The guide's pages {#pages}

- [Getting started](getting-started.md): start the instance, store its secrets and sign in the first time.
- [Links, NanoURLs and QR codes](links-nanourls-qrcodes.md): create, edit and share links.
- [Cloudflare](cloudflare.md): the token, the hosts and a link's address.
- [Settings](settings.md): security, the webhook, API keys and the Cloudflare tab.
- [Upgrading](upgrading.md): move to a new version, bring over the links of an earlier install, roll back.
- [Troubleshooting](troubleshooting.md): common problems and their fix.

## The technical reference {#reference}

The API, the rules for paths and targets, the variables and the recipes are described in the
[repository's README](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md). What was left out on
purpose, and what is planned, is in the
[roadmap](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/ROADMAP.md).
