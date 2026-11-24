---
title: Upgrading
description: Move to a new version, bring over the links and Cloudflare hosts of an earlier install, and roll back.
order: 5
---

## A new version {#new-version}

```sh
git pull
just run
```

`just run` rebuilds the image and restarts the stack. The database is migrated on start, with no step to run.

### From an earlier install {#earlier-install}

An install from before the **Settings** page (9.1 or earlier) moves nothing: the secret files keep working, and the
settings show them as **From file**.

`compose.yml` now expects the `store_key` secret. Create it before the first start, as in
[Getting started](getting-started.md#secrets), or comment its `store_key` lines out: the app then draws its key in the
data volume, and a backup of that volume holds both the secrets and their key.

## Bring over the links of an earlier install {#import-v7}

Only for an install of the earlier app this one replaced, whose last version was 7.0.1. A new install can skip this
part. 7.0.1 kept its links in the `moonie.db` file of its `data` volume. The rows go over unchanged, ids and paths
included: printed QR codes keep working.

1. Start the new instance, as in [Getting started](getting-started.md), with the same public address as 7.0.1.
2. Stop 7.0.1 cleanly, so its write-ahead log is folded into the file, then copy `moonie.db` out of its volume. A copy
   with a pending `moonie.db-wal` beside it is refused.
3. Make the copy readable by user 10001 (`chmod 0644`).
4. Run the import:

```sh
just import-v7 path/to/moonie.db
```

The import opens the file read-only, adds every row whose id and path are free, and prints how many rows it brought
over, how many were already there and how many it refused. Running it again changes nothing.

- If 7.0.1 had the Cloudflare plugin, the import also brings over its accounts, its list, its rule, its hosts and
  their pages for unknown paths. Then run **Compare with Cloudflare** once.
- A NanoURL or QR code that 7.0.1 wrote with its IP address keeps that address in the printed code: the instance must
  stay reachable at that address. The import says how many rows are in that case.
- The API keys and the webhook of 7.0.1 are not brought over: make them again in the [settings](settings.md).

## Roll back {#rollback}

Keep a backup of the `data` volume before every upgrade.

- **To 9.1, before the Settings page**: it works on a migrated database and ignores the new tables. The password, the
  keys, the Cloudflare token and the webhook set in **Settings** do not exist for it: sign in with the file's password,
  and scripts with the `api_token` file. Back on 9.2 or later, they all count again.
- **To 8.1.0**: every link keeps answering on the local network. But while it runs, an edit or a delete of a link put
  on a Cloudflare host is not sent to Cloudflare: once back, run **Compare with Cloudflare** and fix what it lists.
- Restoring a backup of the database ends every session.

The details are in the
[Upgrading and rolling back](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#upgrading-and-rolling-back)
and [Importing 7.0.1](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#importing-701) sections of
the README.
