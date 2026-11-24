---
title: Moonie Redirect
description: Fixed links that redirect to a target you change whenever you want, so shared links and printed QR codes always keep working.
status: Version 9.3.1
github: https://github.com/LunaCreatoris/Moonie-Redirect
order: 2
---

## What it is for {#what-it-is-for}

A printed QR code or a link already sent can no longer be corrected. Redirect gives them a fixed address that answers
with a redirect to the current target. When the target changes, you edit it in one place, and everything that was
printed or shared keeps working.

Redirect never serves the target and never relays it: it only answers "go over there". It all fits in one Python
application, one container and one SQLite database.

## The three kinds of links {#link-kinds}

- **Links**: a path chosen by hand, `/redirect/<path>`, with a last valid day if you want one.
- **NanoURLs**: the path comes from the name, `/redirect/NanoURL/<name>`.
- **QR codes**: like a NanoURL, under `/redirect/QRcodes/<name>`, with a design of your choice and a logo if you want
  one. The printed code holds the short link, not the target.

Every link also answers at its short link, `/links/<id>`. See
[Links, NanoURLs and QR codes](links-nanourls-qrcodes.md).

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
