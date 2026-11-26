---
title: Getting started
description: Choose the mode, on the LAN's IP or behind a reverse proxy, start the instance with Docker Compose, as a Portainer stack or with just, create the store key and the password, then sign in the first time.
order: 1
---

## What you need {#requirements}

- A host with Docker and Docker Compose. No image is published: Docker Compose builds it from the repository.
- One of two modes: on the local network's IP, with nothing else, or behind a reverse proxy. See
  [Choose the mode](#mode).
- A fixed address for the instance, for example `http://192.0.2.10:8080` on the local network, or
  `https://redirect.example.test` behind a reverse proxy. Every link and every QR code is written with it.

[just](https://github.com/casey/just) is not needed to deploy. It is the contributors' tool: tests, captures and
`just ci`, the check that comes before every merge. It also offers a
[second way to start the instance](#with-just).

The instance is made for the local network. For links reachable from the Internet, see [Cloudflare](cloudflare.md).

## Get the repository {#get-the-code}

```sh
git clone https://github.com/LunaCreatoris/Moonie-Redirect.git
cd Moonie-Redirect
```

Without Git, download the archive of the `main` branch from the repository's page (**Code**, then **Download ZIP**)
and unpack it on the host.

## Choose the mode {#mode}

The app listens on the container's port 8080. Two ways to reach it, your choice.

### On the LAN's IP {#lan}

The default mode: `compose.yml` alone. The instance answers in `http` on a port of the host, 8080 by default, with no
reverse proxy and no Docker network to create first. The links' address is the host's address and that port, for
example `http://192.0.2.10:8080`.

In `.env`, `MOONIE_REDIRECT_PORT` changes the host's port, and `MOONIE_REDIRECT_BIND` the host address it listens on:
every one by default (`0.0.0.0`).

**This mode is plain `http`, with no encryption**: the password and the session cookie cross the network in clear. It
is meant for a trusted local network. The session cookie is not marked `Secure` there, or the browser would not send
it back to an `http` address.

### Behind a reverse proxy {#behind-proxy}

A reverse proxy serves the instance in `https` under a name, and reaches it on its own Docker network. The
`compose.proxy.yml` file, laid over `compose.yml`, drops the port published on the host and joins that external
network: `proxy` by default, or the one `MOONIE_REDIRECT_PROXY_NETWORK` names. Create it once if it does not exist
yet:

```sh
docker network create proxy
```

The container answers there at `moonie-redirect:8080`. The links' address is the proxy's, for example
`https://redirect.example.test`.

- **Traefik**: the labels of `compose.proxy.yml` are meant for it. In `.env`, give the public name in
  `MOONIE_REDIRECT_HOST`, the same as the links' address's, and if needed the entrypoint in
  `MOONIE_REDIRECT_ENTRYPOINT`, `websecure` by default.
- **Another reverse proxy in Docker**: it ignores those labels. Point it at `http://moonie-redirect:8080`, on the same
  network. `MOONIE_REDIRECT_HOST` must still be given, as `compose.proxy.yml` stops without it.
- **A reverse proxy installed on the host itself**: keep the LAN mode, with `MOONIE_REDIRECT_BIND=127.0.0.1`, and point
  it at `http://127.0.0.1:8080`. The port then answers the host alone.

The proxy passes the requests on as they are: the app needs no particular header, and never writes its links from the
request.

## The links' address {#public-url}

Copy `.env.example` to `.env` and give the instance's address, for the mode chosen:

```sh
MOONIE_REDIRECT_PUBLIC_BASE_URL=http://192.0.2.10:8080
```

or, behind a reverse proxy:

```sh
MOONIE_REDIRECT_PUBLIC_BASE_URL=https://redirect.example.test
```

It is required: without it, the app refuses to start. It is never taken from the request.

**Choose it before you print.** A printed QR code keeps the address of the moment: if it changes, the code leads
nowhere. On the local network, give the host a fixed address, reserved in the router.

## The secrets {#secrets}

Three files, in the `secrets/` folder, next to `compose.yml`. From the repository's folder, on the host:

```sh
install -d -m 0700 secrets
openssl rand -hex 32 > secrets/store_key
printf '%s\n' 'a long password' > secrets/password
openssl rand -hex 32 > secrets/api_token
sudo chown 10001:10001 secrets/*
sudo chmod 0400 secrets/*
```

- `store_key` is the **store key**: 64 hexadecimal characters. `just store-key > secrets/store_key` draws one too.
- `password` is the admin password, on one line.
- `api_token` is an API token with every right. It stays optional: once signed in, you will usually make
  scoped keys instead, in the settings. To do without it, comment its lines out in `compose.yml`.

The files must belong to the app's user, 10001, and be readable by it only. On Docker Desktop (macOS, Windows), where
that owner does not apply, make them readable with `chmod 0444 secrets/*`. On a host without `openssl`, Docker draws
one too:
`docker run --rm python:3.13.18-slim python -c "import secrets; print(secrets.token_hex(32))"`.

The folder can be elsewhere: `MOONIE_REDIRECT_SECRETS_DIR`, in `.env`, gives its path, for example
`/opt/moonie-redirect/secrets`. A Portainer stack needs it, with an absolute path.

### The store key {#store-key}

The store key encrypts, in the database, the two values the app must read back: the Cloudflare token and the webhook's
secret. It stays outside the data volume.

**Keep a copy of it apart**, in a password manager for example, away from the backups of the `data` volume: the
database alone gives no readable secret. Without the key, you will have to enter those two values again.

## Start {#start}

Two ways, your choice: Docker Compose, directly or as a Portainer stack, with nothing else; or the `just` recipes. Each
has both modes, [on the LAN's IP](#lan) or [behind a reverse proxy](#behind-proxy). In every case, the SQLite database
lives in the `data` volume, and the container runs read-only, with no capability, and restarts by itself.

### With Docker Compose {#with-compose}

From the repository's folder, on the LAN's IP:

```sh
docker compose up -d --build
```

Behind a reverse proxy:

```sh
docker compose -f compose.yml -f compose.proxy.yml up -d --build
```

Docker Compose builds the `moonie-redirect:local` image from the repository's `Dockerfile`, then starts the stack with
`.env`. `MOONIE_REDIRECT_IMAGE` changes that name if needed. `compose.proxy.yml` needs Docker Compose 2.24 or newer.

So as not to repeat both `-f`, add the two lines below to `.env`: every `docker compose` command then reads both
files.

```sh
COMPOSE_PATH_SEPARATOR=,
COMPOSE_FILE=compose.yml,compose.proxy.yml
```

### As a Portainer stack {#with-portainer}

Portainer does not build the image reliably: its documentation calls building from a Git stack incomplete, and failing
on a remote environment. Nor does it see the repository's relative paths, which are kept for its Business Edition. So
the image is built once on the host, and the stack finds it ready.

On the host Portainer manages, get the repository, create the secrets in an absolute folder, for example
`/opt/moonie-redirect/secrets`, as in [The secrets](#secrets), then, from the repository's folder, build the image:

```sh
docker build -t moonie-redirect:local .
```

Then:

1. In Portainer, open **Stacks**, then **Add stack**, and choose **Web editor**. Paste the content of `compose.yml` and
   delete the `build: .` line.
   - On the LAN's IP, nothing else: the `ports` line publishes the port.
   - Behind a reverse proxy, replace the service's `ports` lines with the `networks` and `labels` lines of
     `compose.proxy.yml`, and add its `networks` block at the end.
2. In **Environment variables**, add:
   - `MOONIE_REDIRECT_PUBLIC_BASE_URL`, the links' address, for example `http://192.0.2.10:8080`;
   - `MOONIE_REDIRECT_SECRETS_DIR`, the secrets' folder, for example `/opt/moonie-redirect/secrets`;
   - if needed, `MOONIE_REDIRECT_PORT` on the LAN's IP, or `MOONIE_REDIRECT_HOST` and `MOONIE_REDIRECT_PROXY_NETWORK`
     behind a reverse proxy, as in `.env.example`.
3. Run **Deploy the stack**.

Portainer's **Repository** type reads `compose.yml` as it is in the repository, changing nothing: it only serves with a
copy of the repository whose `compose.yml` already suits you, on Portainer's local environment, and once the image is
built on the host. Then give the repository's address, the reference `refs/heads/main`, the path `compose.yml`, and the
same environment variables. The web editor stays the simplest.

### With just {#with-just}

From the repository's folder, with [just](https://github.com/casey/just) installed, on the LAN's IP:

```sh
just run
```

Behind a reverse proxy:

```sh
just run-proxy
```

`just run` runs `docker compose up -d --build`, and `just run-proxy` the same command with both files: the same as by
hand.

### Check {#check}

Check that the links' address followed by `/health`, for example `http://192.0.2.10:8080/health`, answers
`{"status": "ok", "version": "9.4.0"}`.

## First sign-in {#first-login}

1. Open the links' address followed by `/admin/links`, for example `http://192.0.2.10:8080/admin/links`: the
   sign-in page shows.
2. Enter the password from `secrets/password`.
3. Open **Settings** (the gear at the bottom left), tab **Security**, and change the password. The new one is kept in
   the database and wins over the file.

The interface is in English. A session lasts 12 hours. Next:
[create the first links](links-nanourls-qrcodes.md).

A tour of every screen, with screenshots, is in [Usage](usage.md).

Every step and every variable is in the
[Deploying](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#deploying) section of the README.
