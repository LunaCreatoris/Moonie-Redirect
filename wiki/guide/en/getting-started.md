---
title: Getting started
description: Start the instance with Docker Compose, create the store key and the password, then sign in the first time.
order: 1
---

## What you need {#requirements}

- A host with Docker and Docker Compose.
- [just](https://github.com/casey/just): every step is a recipe, and every recipe runs in Docker.
- A reverse proxy that reaches the container on a Docker network. `compose.yml` is made for Traefik, on an external
  network named `proxy` by default. The app listens on port 8080 and publishes no port.
- A fixed address for the instance, for example `https://redirect.example.test`. Every link and every QR code is
  written with it.

The instance is made for the local network. For links reachable from the Internet, see [Cloudflare](cloudflare.md).

## Get the repository {#get-the-code}

```sh
git clone https://github.com/LunaCreatoris/Moonie-Redirect.git
cd Moonie-Redirect
```

## The links' address {#public-url}

Copy `.env.example` to `.env` and give the instance's address:

```sh
MOONIE_REDIRECT_PUBLIC_BASE_URL=https://redirect.example.test
```

It is required: without it, the app refuses to start. It is never taken from the request.

**Choose it before you print.** A printed QR code keeps the address of the moment: if it changes, the code leads
nowhere.

`MOONIE_REDIRECT_PROXY_NETWORK` names Traefik's network, `proxy` by default. The Traefik labels are in `compose.yml`,
commented out: uncomment them and put the instance's host name in them.

## The secrets {#secrets}

Three files, in the `secrets/` folder, next to `compose.yml`:

```sh
install -d -m 0700 secrets
just store-key > secrets/store_key
printf '%s\n' 'a long password' > secrets/password
python3 -c "import secrets; print(secrets.token_hex(32))" > secrets/api_token
sudo chown 10001:10001 secrets/*
sudo chmod 0400 secrets/*
```

- `store_key` is the **store key**: 64 hexadecimal characters. On a host without the repository,
  `openssl rand -hex 32` gives one too.
- `password` is the admin password, on one line.
- `api_token` is an API token with every right. It stays optional: once signed in, you will usually make
  scoped keys instead, in the settings. To do without it, comment its lines out in `compose.yml`.

The files must belong to the app's user, 10001, and be readable by it only.

### The store key {#store-key}

The store key encrypts, in the database, the two values the app must read back: the Cloudflare token and the webhook's
secret. It stays outside the data volume.

**Keep a copy of it apart**, in a password manager for example, away from the backups of the `data` volume: the
database alone gives no readable secret. Without the key, you will have to enter those two values again.

## Start {#start}

```sh
just run
```

`just run` builds the `moonie-redirect:local` image, then starts the stack from `compose.yml` with `.env`. The SQLite
database lives in the `data` volume. The container runs read-only, with no capability, and restarts by itself.

Check that `https://redirect.example.test/health` answers `{"status": "ok", "version": "9.3.1"}`.

## First sign-in {#first-login}

1. Open `https://redirect.example.test/admin/links`: the sign-in page shows.
2. Enter the password from `secrets/password`.
3. Open **Settings** (the gear at the bottom left), tab **Security**, and change the password. The new one is kept in
   the database and wins over the file.

The interface is in English. A session lasts 12 hours. Next:
[create the first links](links-nanourls-qrcodes.md).

Every step and every variable is in the
[Deploying](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#deploying) section of the README.
