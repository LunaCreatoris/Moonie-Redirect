---
title: Troubleshooting
description: Common problems, from an instance that does not start to a Cloudflare link in error, and what fixes them.
order: 7
---

## The instance does not start {#does-not-start}

`docker compose logs moonie` gives the reason in one line; in Portainer, the container's **Logs** page does.

- **The links' address is missing**: Docker Compose stops on `set MOONIE_REDIRECT_PUBLIC_BASE_URL in .env`. Give
  it in `.env`, see [Getting started](getting-started.md#public-url).
- **A secret file is missing**: Docker Compose stops before starting the container. Create the file, or comment its
  lines out in `compose.yml`.
- **The store key cannot be read or is malformed**: the file must hold 64 hexadecimal characters and be readable by
  user 10001.
- **`the API token must be at least 32 characters`**: the `api_token` file is too short. Generate a new one, as in
  [Getting started](getting-started.md#secrets).
- **`pull access denied for moonie-redirect`**, in Portainer: the image is not built on the host, and no registry
  holds it. Build it there first, as in [Getting started](getting-started.md#with-portainer).
- **`network proxy declared as external, but could not be found`**, behind a reverse proxy: create it, or give the
  proxy's network in `MOONIE_REDIRECT_PROXY_NETWORK`. See [Behind a reverse proxy](getting-started.md#behind-proxy).
  On the LAN's IP, run `compose.yml` alone, without `compose.proxy.yml`.
- **`set MOONIE_REDIRECT_HOST in .env`**: `compose.proxy.yml` needs the proxy's public name. Give it in `.env`.
- **`port is already allocated`** or **`address already in use`**: the host's port 8080 is taken. Give another one
  in `MOONIE_REDIRECT_PORT`, and change the links' address to match.

## Lost password {#lost-password}

From the repository's folder, on the host:

```sh
docker compose exec moonie python app.py reset-password
```

With just, it is `just reset-password`. In a Portainer stack, open the container, then **Console**, and run
`python app.py reset-password`.

The command drops the password set in **Settings** and ends every session: the password from `secrets/password` counts
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
