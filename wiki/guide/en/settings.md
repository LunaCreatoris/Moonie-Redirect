---
title: Settings
description: The password and the sessions, the n8n webhook, API keys and their scopes, the Cloudflare token.
order: 4
---

## The Settings page {#settings-page}

The gear at the bottom left opens **Settings**, in three tabs: **Security**, **Webhook & API** and **Cloudflare**. Only
the signed-in admin has access: no API key, even one with every right, can read or change the settings.

A value set here is kept in the database and wins over the file from `compose.yml`. Clearing it goes back to the file.
Each value says where it comes from: **Set here**, **From file** or **Not set**.

## Security {#security}

- **Change password** asks for the current password, then a new one of 12 to 1024 characters. Every other session
  ends, yours stays open.
- **End all sessions** ends every session, yours included.

After a wrong password, any new attempt within one second is refused, for everyone. Redirects, the API and sessions
already open are not affected.

A forgotten password is reset from the host: see [Troubleshooting](troubleshooting.md#lost-password).

## The webhook {#webhook}

The webhook sends a signed POST to an address of your choice, an n8n workflow for example, each time a link, a NanoURL
or a QR code is created, changed or deleted, from the pages or with an API key.

1. In **Webhook & API**, give the address, for example `http://n8n:5678/webhook/links-changed` on a shared Docker network.
2. Give a signing secret of 16 to 256 characters. It is never shown again; a field left empty keeps the old one.
3. Tick the events, save, then **Send test**.

Addresses on the local network are allowed. Loopback (`localhost`), link-local, multicast and reserved addresses are
refused. A delivery that fails is tried again several times; the page shows the last delivery and what is waiting.

The receiver checks the signature on the body's raw bytes. The headers and an example check are in the
[The n8n webhook](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#the-n8n-webhook) section of the
README.

## API keys {#api-keys}

**New key** creates a key: a name, its scopes and your password. The key is shown once only: copy it right away.
**Revoke** withdraws it; calls that send it are refused at once.

A key holds only the scopes it is given:

- `redirect:links.read` and `redirect:links.write` for links;
- `redirect:nanourls.read` and `redirect:nanourls.write` for NanoURLs;
- `redirect:qrcodes.read` and `redirect:qrcodes.write` for QR codes;
- `cloudflare:read`, `cloudflare:write` (put a link on a Cloudflare host) and `cloudflare:setup` (set a host up, or use
  an adopted host that may serve a site);
- `*`, `redirect:*` and `cloudflare:*` for everything, or one whole side.

A script sends the key in `Authorization: Bearer <key>`. The `api_token` file, if present, shows as a **Token file**
row with every scope: to withdraw it, delete the file and restart.

## Cloudflare {#cloudflare}

The **Cloudflare** tab holds the token (**Replace**, **Clear**), the list item limit (empty for 10,000, the free plan's
figure), then the hosts, the quota, **Sync now** and **Compare with Cloudflare**. See [Cloudflare](cloudflare.md).

## The store key and backups {#backups}

The Cloudflare token and the webhook's secret are encrypted in the database with the
[store key](getting-started.md#store-key). The password and the API keys are kept there only as digests, and do not
need the key.

A database restored without its key, or a changed key: those two values show **Cannot be read**. Enter them again.
Restoring the database also ends every session.

The details are in the
[Settings](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#settings) section of the README.
