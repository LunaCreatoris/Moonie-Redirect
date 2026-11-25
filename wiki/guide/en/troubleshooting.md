---
title: Troubleshooting
description: Common problems, from an instance that does not start to a Cloudflare link in error, and what fixes them.
order: 6
---

## The instance does not start {#does-not-start}

`docker compose logs moonie` gives the reason in one line.

- **The links' address is missing**: Docker Compose stops on `set MOONIE_REDIRECT_PUBLIC_BASE_URL in .env`. Give
  it in `.env`, see [Getting started](getting-started.md#public-url).
- **A secret file is missing**: Docker Compose stops before starting the container. Create the file, or comment its
  lines out in `compose.yml`.
- **The store key cannot be read or is malformed**: the file must hold 64 hexadecimal characters and be readable by
  user 10001.
- **`the API token must be at least 32 characters`**: the `api_token` file is too short. Generate a new one, as in
  [Getting started](getting-started.md#secrets).

## Lost password {#lost-password}

From the repository's folder, on the host:

```sh
just reset-password
```

The recipe drops the password set in **Settings** and ends every session: the password from `secrets/password` counts
again. Sign in with it, then change it.

## Sign-in answers "Too many attempts" {#too-many-attempts}

After a wrong password, any attempt within the next second is refused, for everyone. If it lasts, a client on the
network keeps trying a wrong password: find it and stop it. Links, the API and open sessions are not affected.

## A value shows "Cannot be read" {#cannot-be-read}

The database was restored without its store key, or the key changed. The Cloudflare token falls back to its file if
there is one, otherwise Cloudflare goes off; the webhook sends nothing and its events wait. Enter the token and the
webhook's secret again in the [settings](settings.md).

## A Cloudflare link stays in error {#cloudflare-error}

The link's state says why:

- **An item this app did not make** already holds that address in the Cloudflare list: remove it in Cloudflare, or
  choose another path, then **Sync now**.
- **This host is now the address of this instance**: `MOONIE_REDIRECT_PUBLIC_BASE_URL` points at that host. Nothing is
  sent there: move its links to another address.
- **The list is full**: the link waits for a free place. See [the quota](cloudflare.md#quota).
- **The token lacks a permission or is refused**: the Cloudflare tab says which. See [the token](cloudflare.md#token).

When in doubt, **Compare with Cloudflare** shows the gaps between the instance and Cloudflare.

## The webhook sends nothing {#webhook-silent}

- **"This address is closed"**: the address is a loopback, link-local, multicast or reserved one. Use the service's
  name on the Docker network, for example `http://receiver:8080/...`, or an address on the local network.
- **"Webhook disabled"**: the receiver answered `410 Gone`. The events wait; **Save** turns the webhook back on.
- **The receiver refuses the signature**: it must check it on the body's raw bytes, before parsing them as JSON: JSON
  parsed and written again may not keep the same bytes.

## More help {#more-help}

What was left out on purpose, and what is planned, is in the
[roadmap](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/ROADMAP.md). The rest is in the
[README](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md).
