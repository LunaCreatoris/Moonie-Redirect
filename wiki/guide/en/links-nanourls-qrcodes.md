---
title: Links, NanoURLs and QR codes
description: Create a link, a NanoURL or a QR code, change its target without breaking what was shared, and know what it answers.
order: 3
---

## The pages {#pages}

The menu on the left, under Redirect, opens three pages: **Links**, **NanoURLs** and **QR codes**. Each one shows the
list, with its search, next to the form of the chosen link or of a new one. The most recently modified come first. A
button copies each address, and a dialog asks for confirmation before a delete or before losing a form being edited.

## A link {#a-link}

1. Open **Links**, then **New link**.
2. Give a name, the target (a full address in `http://` or `https://`) and the path (**Slug**). A free path is
   suggested, and **Random** draws another one.
3. If you want, give a last day (**Expiry**, as `YYYY-MM-DD`). The link works until the end of that day, in universal
   time (UTC), then answers "not found".
4. Save.

The link answers at `https://redirect.example.test/redirect/<path>`, and also at its short link,
`https://redirect.example.test/links/<id>`, where `<id>` is 8 letters and digits.

**Changing the path breaks the old one.** Changing the target, on the other hand, breaks nothing: that is the whole
point.

## A NanoURL {#a-nanourl}

A NanoURL has only a name and a target. The path comes from the name: `/redirect/NanoURL/<name>`, without accents,
other characters becoming dashes. Renaming a NanoURL changes that path, but its short link stays the same: that is the
one to share.

## A QR code {#a-qr-code}

A QR code is created like a NanoURL, under `/redirect/QRcodes/<name>`, with a design on top:

- the colors of the modules, the corners and the background (the background can be transparent);
- the shape of the modules and the corners, and the margin;
- a logo in the center, in PNG, JPEG, WebP or SVG, of 256 KiB at most, with its size.

The preview is drawn again at every change. If the colors are too close, the design is refused: a scanner might not
read the code. **Download SVG** downloads the file to print.

The code holds the short link, not the target: you can change the target after printing. The same link and the same
design always give the same file.

## What a link answers {#what-a-link-answers}

- A `302` redirect to the target, which the browser does not cache. A link set to `301` through the API, or brought
  over from an earlier install, keeps it, and its form says so.
- The visit's parameters are never passed on: `/redirect/promo?utm_source=x` leads to the stored target, alone.
- An unknown or expired link answers `404`.
- Each visit writes one log line with the path and the code, never the target, which may hold a token.

## Automate {#automate}

Everything the pages do goes through a JSON API. A script sends an API key in `Authorization: Bearer <key>`; keys are
made in the [settings](settings.md#api-keys). The calls and the rules for paths, names and targets are in the
[JSON API](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#json-api) and
[Rules](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#rules) sections of the README.
