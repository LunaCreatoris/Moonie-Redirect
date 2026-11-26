# moonie-redirect

Redirect makes fixed links whose target can change, published three ways: a fixed URL whose path you choose, a short
TinyURL-style link, or a QR code that holds that short link. When the target moves, you change it in one place and every
link and printed code keeps working. It never serves or proxies the target. One Python file (`app.py`): Flask and Jinja
for the pages and the API, waitress as the server, the standard library's `sqlite3` for the one table, `segno` for the
QR codes and `idna` for international host names. The admin pages are plain ES modules in `static/ui`, with no build
step.

## History

Versions before 8 were an earlier, unpublished app built on a plugin framework, whose last release was 7.0.1.
Version 8 rewrote it as this plain standalone app, with no framework under it, keeping its public paths, its table and
its codes, so links and QR codes printed with 7.0.1 keep working once its rows are imported. Version 9 brought back
its admin pages, 9.1 its Cloudflare plugin, 9.2 its settings, 9.3 moved the Cloudflare page under Settings, and 9.4
made the LAN's IP, with no reverse proxy, the default deployment. The `import-v7` command and the upgrade and rollback
notes below only matter to those earlier installs; a new install can skip them. Files ported from 7.0.1 name their source on their first line.

## What it does

Three kinds of links, one table (`redirect_links`, in `/data/redirect.db`):

- **Links**: a path typed by hand, `/redirect/<slug>`, answering `302` (`301` only through the API) with an optional
  last day.
- **NanoURLs**: the path comes from the name, `/redirect/NanoURL/<name>` (accents dropped, other characters made
  dashes).
- **QR codes**: the same, under `/redirect/QRcodes/<name>`, plus a design. The code itself holds the short link.

Every link also answers at its short link, `/links/<id>`, where `<id>` is 8 letters and digits.

### The public routes

`GET` and `HEAD` on `/redirect/<slug>` and `/links/<id>`, with no authentication:

- A redirect with the link's status and `Location` set to the stored target, byte for byte, and
  `Cache-Control: no-store`, so a browser never keeps an old target.
- The visit's query string is never forwarded: `/redirect/promo?utm_source=x` goes to the stored target alone.
- Unknown, invalid or expired (a link works through the whole of its last day, in UTC): `404` with
  `Cache-Control: no-store`. The body never shows the path: `404` in plain text, or a small page when the browser asks
  for HTML. A database that cannot be read answers `503` with `Retry-After: 5`.
- A visit only reads, on a read-only connection. Each visit logs one line with the path and the status, never the
  target, which may carry a token.

`GET /health` answers `{"status": "ok", "version": "9.4.0"}`, or `503` when the database cannot be read.

### Admin pages

`/admin/links`, `/admin/nanourls` and `/admin/qrcodes` are the pages of 7.0.1 (and `/admin/settings`, below, whose
Cloudflare tab holds the Cloudflare plugin's page), ported from its shell and its Redirect plugin: the frame with its
menu, status and **Reload**, a list with its search beside the form of the selected row or of a new one, the QR
designer with its live preview, thumbnails and **Download SVG**, copy buttons, dialogs before a delete or before
typed text is lost, and the loading, error and not-found states. The menu lists the three pages under Redirect; at
the bottom-left of the sidebar, a gear opens **Settings** (highlighted while it is open)
and the glyph beside it logs out, both named for screen readers and in their tooltips. The pages run in the browser,
so they need JavaScript, and call the JSON API below with the session cookie. English only.

- **Sign in** at `/login` with the admin password; the login comes back to the page that sent you there. The session is
  a signed cookie (`HttpOnly`, `SameSite=Lax`) naming a session kept in the database: it ends 12 hours after the login,
  however much it is used, or at its **Log out** (the glyph at the bottom of the sidebar), which ends it on the server
  too, so a copy of the cookie stops working with it. Other browsers signed in stay signed in. A page whose session
  ended goes to the login, which says so.
- Any sign-in attempt within one second of a failed one is answered `429`. The brake is global, not per client: a LAN
  client that keeps trying wrong passwords keeps admin sign-in on `429` for everyone while it tries. Redirects, the API
  and sessions already signed in are unaffected. The Settings page's password checks (a new password, a new key) share
  the same brake (`429 too_many_attempts`).
- **Suggested path**: a new link's form comes with a free random path, 6 letters and digits from the short links'
  alphabet, as 7.0.1 drew them; **Random** draws another. A suggestion is not held, so the save still refuses it if
  someone took it in between.
- **QR preview**: every change of the design draws the code again through `POST /api/qrcodes/preview`, writing nothing.
  On an edit form the preview holds the code's own short link; on a new one, a placeholder of the same length
  (`Preview0`) until the save draws its id. A refused logo or design is said under the preview, and the last good one
  stays.
- **Status code**: the pages offer none. A link made on them answers `302`, and a save sends no `http_status`, so an
  edit keeps the stored code. A link set to `301` through the API (or imported from 7.0.1) says so on its form, and
  keeps its `301` when saved there; only the API changes it. The list has no Code column.
- Every other address under `/admin` shows the frame with a not-found page and answers `404`.

The pages hold no inline script and write no HTML: their policy is `script-src 'self'` with Trusted Types required and
no policy allowed, `style-src 'self'`, `connect-src 'self'`, `frame-ancestors 'none'`. The 8.x server-rendered forms
(`/admin/<section>/new`, `/admin/<section>/<id>` and its `delete`, `/admin/qrcodes/<id>.svg`) are gone: a script that
posted to them uses the API.

### JSON API

Every call sends `Authorization: Bearer <key>`: a key made in Settings, or the token of `MOONIE_REDIRECT_API_TOKEN_FILE`,
which holds every scope (`*`). Bodies and answers are JSON.

A key holds scopes, 7.0.1's names: `redirect:links.read|write`, `redirect:nanourls.read|write`,
`redirect:qrcodes.read|write`, `cloudflare:read|write|setup`, and the wildcards `*`, `redirect:*` and `cloudflare:*`. A
call that needs a scope the key lacks answers `403 {"error": "scope_denied"}`; a link of a kind the key cannot read
answers `404`, as if it were not there. The admin session holds every scope.

| Call | Scope |
| ---- | ----- |
| `GET /api/status` | any valid key |
| `GET /api/links` | `<kind>.read`; with no `kind`, only the kinds the key reads |
| `GET /api/links/suggest` | `redirect:links.write` (or the `kind` given) |
| `POST /api/links` | `<kind>.write`; an `address` other than `lan` also `cloudflare:write`; an adopted host `cloudflare:setup` |
| `GET /api/links/<id>`, `qr.svg` | the row's `<kind>.read` |
| `PATCH`, `DELETE /api/links/<id>` | the row's `<kind>.write`; a link on a Cloudflare host, before or after the change, also `cloudflare:write`; an adopted host `cloudflare:setup` |
| `POST /api/qrcodes/preview` | `redirect:qrcodes.read` |
| `GET /api/cloudflare`, `/api/cloudflare/compare` | `cloudflare:read` (the report's `fingerprint` with `cloudflare:setup`) |
| `POST /api/cloudflare/sync` | `cloudflare:write` |
| zones, proposals, plan, apply, compare/apply, a host's page for unknown paths | `cloudflare:setup` |
| `/api/session`, `/api/settings/**` | the admin session only: every key, `*` included, answers `403 needs_admin` |

The admin pages call it with the session cookie instead, and no `Authorization` header: a change (`POST`, `PATCH`,
`DELETE`) then also sends the session's token in `X-CSRF-Token` (the pages read it from their `csrf-token` meta), and
must not come from another site (`Sec-Fetch-Site` absent or `same-origin`), else `403 {"error": "csrf"}`. An
`Authorization` header, valid or not, is the only proof read: it never falls back to the cookie. With neither, or an
expired session, `401 {"error": "unauthorized"}`. A page whose change is refused `403 csrf` reads the session's token from
`/api/session` and sends the change once more: a login in another tab replaced the token, and the typed form is kept.

| Method | Path                    | Does                                                          |
| ------ | ----------------------- | ------------------------------------------------------------- |
| GET    | `/api/status`           | `{"version": ..., "links": n}`: the count of links of every kind, for the admin frame |
| GET    | `/api/links?kind=`      | every link, or those of `link`, `nano` or `qrcode`, newest first |
| POST   | `/api/links`            | create: `kind` (default `link`), `name`, `target`, and `slug`, `http_status`, `expires_on` for a link, `design` for a QR code |
| GET    | `/api/links/<id>`       | one link                                                      |
| PATCH  | `/api/links/<id>`       | change the fields given; a new name moves a NanoURL's or QR code's path |
| DELETE | `/api/links/<id>`       | delete (`204`)                                                |
| GET    | `/api/links/<id>/qr.svg`| a QR code's SVG                                               |
| GET    | `/api/links/suggest?kind=` | a free random slug: `{"slug": ...}` (not held until a create); `kind` is `link` by default |
| POST   | `/api/qrcodes/preview`  | the SVG a QR code would have, writing nothing: `name` and `design` checked as on create, and `id` (a string, else `400`) to draw that QR code's short link (its stored design when `design` is absent), `address` to draw it at that address; answers `{"svg": ...}` |
| GET    | `/api/session`          | the admin session only: its CSRF token, `{"csrf": ...}`, for a page whose token a login in another tab replaced (`403 needs_admin` with a key) |

A link answers its fields plus `public_url` (`<base>/redirect/<slug>`), `short_url` (`<base>/links/<id>`), `address`
(`lan` or a Cloudflare host), `address_url` (the address to share, the one a QR code holds) and `cloudflare`
(`{"state", "error"}`, or `null` on the LAN). The list also answers `addresses`, what a link's `address` may be. In the
list, a QR code's `design` is the stored one, its `logo` sent as stored and not checked again: one QR code read alone,
its SVG and its preview check the logo whole. Errors are `{"error": ..., "fields": {field: reason}}` with `400`, `401`,
`403` (CSRF, `scope_denied`), `404`, `409` (path taken) or `422` (a preview of a QR code whose stored design breaks the
rules, with no `design` given).

A QR code's `design` takes `color`, `eye_color` and `background` (`#rrggbb`, or `transparent` for the background, with a
contrast of 3:1 at least), `module_style` (`square`, `rounded`, `dots`), `eye_style` (`square`, `rounded`, `circle`),
`margin` (0 to 10 modules), and `logo`, a PNG, JPEG, WebP or SVG data URI of 256 KiB at most, sized by `logo_size`
(0.1 to 0.3). An SVG logo is one well-formed document whose root is `svg` in the SVG namespace, with no DOCTYPE. The
same link and design always give the same SVG bytes.

### Rules

- A slug: at most 255 characters, `/`-separated segments of letters, digits, `.`, `_`, `-`, no `.` or `..` segment, and
  not starting with `Api`, `NanoURL` or `QRcodes` in any case.
- A name: at most 100 characters, trimmed, with at least one letter, digit, punctuation or symbol, and no control or
  invisible character (Unicode category C, and the blanks filed elsewhere: Hangul fillers, the braille blank, the
  combining grapheme joiner, the Khmer inherent vowels). Emoji and their variation selector are kept.
- A target: an absolute `http` or `https` URL with a valid host, at most 2048 characters, no space or control character.
  An international host is stored in its ASCII form and other non-ASCII characters percent-encoded, so `javascript:`,
  `data:`, relative and protocol-relative targets are refused.

## Cloudflare

Off by default. With a Cloudflare API token, a link can also answer on a host of your own Cloudflare zones, such as
`https://go.example.com/promo`, served by Cloudflare Bulk Redirects with no request reaching this instance. It is the
7.0.1 Cloudflare plugin's job, now inside the app; its hosts, list and items carry over through `import-v7`.

- **Hosts**: **Settings > Cloudflare** sets up a host, `<name>.<zone>`, through a plan shown first and done only once
  confirmed: it may create the account's `moonie_redirect` list, add one rule for it beside the account's own (or
  create the Bulk Redirects ruleset), and create a proxied placeholder record (`A <host> → 192.0.2.1`). A name that
  already has proxied records is adopted as it is: it may serve a site, so a link there takes its path over, the plan
  asks for a tick, and only the admin or a key holding `cloudflare:setup` may give it to a link. A host created here
  may have a page for its unknown paths (Wikipedia's 404, Google, or any address not on a host set up here): it is the
  host's root item, so it answers every path with no link, `/.well-known/...` included, as the plugin did. A record
  found again with the placeholder's address and comment is the one an earlier setup made: it is reused and the host
  stays created here. Nothing else in Cloudflare is ever changed or deleted: no record, rule or list, only the list's
  items. A host cannot be removed here yet (`ROADMAP.md`).
- **A link's address**: each form of the three Redirect pages has an **Address** select, the LAN first, then each host,
  once a host is set up. A link on a host is one item of the list: `<host>/<slug>` for a link, `<host>/<id>` for a
  NanoURL or a QR code, whose code then holds `https://<host>/<id>`. The lists show where each link answers and its
  state (pending, active, error, expired). The LAN routes keep answering every link whatever its address.
- **Sync**: one background thread sends what changed (at most 500 items per call, one call at a time per account),
  removes what was deleted, moved or expired (after its last day, in UTC), and only ever writes or deletes items that
  carry this install's marker in their comment. An item someone else made at a link's address is never written over:
  the link waits in error. **Sync now** tries the links in error again. A host that has become this instance's own
  (`MOONIE_REDIRECT_PUBLIC_BASE_URL` moved onto it) gets nothing: its pending links, its page for unknown paths and its
  account show the error `admin_host` until its links move to another address.
- **A slow Cloudflare**: the page's calls never wait on the sync's retries: each is tried once, with short timeouts,
  within 10 s (30 s to set a host up), and a token check Cloudflare did not answer is kept a minute.
- **Compare with Cloudflare** lists what Cloudflare lacks, holds differently, or holds that nothing here does, and fixes
  what you tick; removing an item takes a second confirmation with its count.
- **Stopping an address**: changing a link's address away from a Cloudflare host, changing the slug of a link on one,
  or deleting a link that has one, stops what was printed or shared with that address. The pages ask first; the API
  wants `"confirm_break": true` (a `DELETE` sends it in its body or as `?confirm_break=true`), else
  `400 confirm_break`.
- **Quota**: a list holds `MOONIE_REDIRECT_CLOUDFLARE_ITEM_LIMIT` items (10 000 on the free plan, links and pages
  together). The page warns from 90 %; at the limit a link cannot take a host of that account (`409 quota_full`).

The token needs four permissions: **Account · Account Rule Lists: Write**, **Account · Account Rulesets: Write**,
**Zone · Zone: Read** and **Zone · DNS: Write**, on the account and zones to use. The page says which one is missing.
It is set in **Settings > Cloudflare** and used at once, with no restart (`MOONIE_REDIRECT_CLOUDFLARE_TOKEN_FILE` is
the fallback while none is set there). The container must reach `api.cloudflare.com` (HTTPS); the app reads no proxy
from the environment.

Cloudflare's JSON API, with the bearer token or the session:

| Method | Path                             | Does                                                                     |
| ------ | -------------------------------- | ------------------------------------------------------------------------ |
| GET    | `/api/cloudflare`                | the token's state, each account's list, quota, last sync and last error, the hosts, the links by state |
| POST   | `/api/cloudflare/sync`           | Sync now (`202`)                                                         |
| GET    | `/api/cloudflare/compare`        | Compare's report, read only (its `fingerprint` only for the session)     |

With the admin session or a key holding `cloudflare:setup` (else `403 scope_denied`), as the page uses them:

| Method | Path                                    | Does                                                              |
| ------ | --------------------------------------- | ----------------------------------------------------------------- |
| GET    | `/api/cloudflare/zones`                 | the zones the token sees                                          |
| GET    | `/api/cloudflare/proposals?zone=<id>`   | the usual names of a zone, with what a plan would find there      |
| POST   | `/api/cloudflare/plan`                  | the plan for `{zone_id, label, fallback}`, with its `fingerprint`  |
| POST   | `/api/cloudflare/apply`                 | do that plan: the same body, its `fingerprint`, `confirm_live` for a name that serves a site (`409 plan_stale` when Cloudflare changed since) |
| POST   | `/api/cloudflare/hosts/<host>/fallback` | a created host's page for unknown paths: `{"fallback": <address or null>}` |
| POST   | `/api/cloudflare/compare/apply`         | fix what was ticked: `{fingerprint, push: [ids], remove: [remote ids], confirm_remove: <count of remove>}` |

A link's `address` on `POST` and `PATCH` `/api/links` is `lan` (the default) or a host set up here: `400` for any other
value, for a path under `.well-known` on a host, or for the host this instance is reached on (its
`MOONIE_REDIRECT_PUBLIC_BASE_URL`, or the request's), `403 scope_denied` for a host with a key lacking
`cloudflare:write`, or for a new path on an adopted host (its address or its slug) with a key lacking `cloudflare:setup`,
`409 slug_taken` (on `address`) when another link holds that path on the host, `409 quota_full`, and
`409 cloudflare_off` while there is no token. Cloudflare's own failures answer `502` with a code (`unreachable`,
`refused`, `permission`, `token_invalid`) or `429 rate_limited`.

## Settings

`/admin/settings` holds three tabs, the tab in the address (`?tab=security|webhook|cloudflare`):

- **Security**: where the admin password comes from (`Set here`, `From file`, `Not set`), **Change password** (the
  current one, then a new one of 12 to 1024 characters; every other session ends, this one stays) and **End all
  sessions** (you included).
- **Webhook & API**: the webhook (URL, signing secret, events, **Send test**, the last delivery and what waits),
  then the API keys: **New key** (a name, scopes, your password), whose secret is shown once, and **Revoke**. The token
  file shows as a fixed `Token file` row with every scope: remove the file and restart to revoke it.
- **Cloudflare**: the API token (**Replace**, **Clear**), checked by Cloudflare before it is kept (refused, nothing is
  stored; a permission missing, it is kept and the page says which), used at once with no restart; and the list item
  limit (empty for the environment's or the default 10 000). Under them, the domains (the Cloudflare page up to 9.2):
  the quota, **Sync now**, **Compare with Cloudflare**, the hosts with their page for unknown paths, and **New host**
  (Cloudflare above). `/admin/cloudflare`, the old page's address, now opens this tab.

Every call under `/api/settings` is the admin session's alone: every key, `*` included, answers `403 needs_admin`.

### What wins: the database, then the file

A value set on the page is kept in the database and wins; the file or variable counts only while the database has
none. Clearing a value on the page goes back to the file. Nothing is copied at an upgrade, so an install that used the
files alone (before 9.2) changes nothing until a value is set here.

| Value | Kept as | Fallback |
| ----- | ------- | -------- |
| Admin password | a scrypt hash (2^14, 16 MiB) | `MOONIE_REDIRECT_PASSWORD_FILE` |
| API keys | the SHA-256 of each key, its first 8 characters, its name and scopes | `MOONIE_REDIRECT_API_TOKEN_FILE`, a key with every scope |
| Cloudflare token | sealed (below) | `MOONIE_REDIRECT_CLOUDFLARE_TOKEN_FILE` |
| Item limit | a setting | `MOONIE_REDIRECT_CLOUDFLARE_ITEM_LIMIT`, then 10 000 |
| Webhook URL and events | settings | none |
| Webhook secret | sealed (below) | none |

A lost UI password: `just reset-password` (or `python app.py reset-password` in the container) drops the stored hash
and ends every session, so the file's password counts again.

### The store key, and backups

The two values the app must read back, the Cloudflare token and the webhook's secret, are sealed in the database with
AES-256-GCM under the **store key**: 64 hexadecimal characters in `MOONIE_REDIRECT_STORE_KEY_FILE`, a compose secret
kept outside the data volume (`openssl rand -hex 32 > secrets/store_key`, or `just store-key > secrets/store_key`).
Without that variable the app draws `store.key` once beside the database and logs at each start that a backup of the
volume then holds both the secrets and their key. A key file named but unreadable or malformed stops the start.

- Back the key file up apart from the database (a password manager): the database alone gives no readable secret.
  The password hash and the keys' digests need no key.
- A database restored without its key, or a changed key: the sealed values show as `Cannot be read`. Cloudflare falls
  back to its file, else goes off; the webhook sends nothing and its events wait. Enter the Cloudflare token and the
  webhook's secret again. There is no command to change the key (`ROADMAP.md`).

### The webhook

Each link, NanoURL or QR code created, changed or deleted through the API (the pages or a key) sends the event ticked,
7.0.1's names: `redirect.link.created`, `redirect.link.updated`, `redirect.link.deleted`. The body is
`{"id", "event", "source": "redirect", "at", "data"}`, `data` holding `id, kind, slug, name, target, http_status,
expires_on, address, updated_at` (never the design), at most 64 KiB. The headers are 7.0.1's, so receivers written for it keep
working:

| Header | Holds |
| ------ | ----- |
| `X-Moonie-Event` | the event's name |
| `X-Moonie-Event-Id` | `evt_` and 32 hex characters, the same on every retry: drop a copy you already have |
| `X-Moonie-Timestamp` | the time of the attempt, in Unix seconds |
| `X-Moonie-Signature` | `sha256=` and the hex HMAC-SHA256, keyed with the secret, of `<event id>.<timestamp>.` followed by the body's bytes |
| `User-Agent` | `moonie-redirect/<version>` |

A receiver checks it on the raw body's bytes, before parsing them (re-encoding the JSON may change its bytes), and also refuses a timestamp more than a few minutes off:

```js
const crypto = require('crypto')

// headers: the request's headers, lower-cased; body: the raw body as a Buffer
function signedByRedirect(secret, headers, body) {
  const signed = `${headers['x-moonie-event-id']}.${headers['x-moonie-timestamp']}.`
  const expected = 'sha256=' + crypto.createHmac('sha256', secret).update(signed).update(body).digest('hex')
  const given = String(headers['x-moonie-signature'] ?? '')
  return given.length === expected.length && crypto.timingSafeEqual(Buffer.from(given), Buffer.from(expected))
}
```

- **Delivery**: one at a time, oldest first, at least once. A `2xx` answer delivers. No answer, `408`, `429` and `5xx`
  are tried again after 10 s, 60 s, 5 min and 30 min (+-20 %), five attempts in all. `410 Gone` turns the webhook off
  until the next Save (the events wait). Any other status, `3xx` included, fails the event at once: redirects are never
  followed. Each attempt has 5 s to connect and 30 s in all, and reads 64 KiB of the answer at most. At most 10 000
  events wait; finished ones are dropped after 7 days. **Delete webhook** drops the waiting ones.
- **Where it may send**: `http` or `https`, no user or password in the URL. Global addresses and the LAN's (10/8,
  172.16/12, 192.168/16, 100.64/10, fc00::/7) are open; loopback, `localhost`, link-local (so the cloud metadata
  address), multicast and reserved addresses are closed, also when an IPv6 form carries them. A numeric host is judged
  when saved (`This address is closed`); a name at each attempt, on every address it resolves to, and the connection goes
  to the address judged. `http://receiver:8080/...` on a Docker network passes. TLS is checked against the system's
  authorities, with no way to turn it off. The logs name the receiver's origin, never its path or query, which may hold
  a token.
- The secret is 16 to 256 characters, write-only: the page never shows it again; an empty field keeps it.

### The settings API (session only)

| Method | Path | Does |
| ------ | ---- | ---- |
| GET | `/api/settings/security` | `{password: {origin}, sessions: {active, hours}, login_brake_seconds}` |
| POST | `/api/settings/password` | `{password, new_password}`: `204`; `400 login_failed`, `400 invalid`, `429 too_many_attempts` |
| POST | `/api/settings/sessions/end` | ends every session, this one included (`204`) |
| GET | `/api/settings/keys` | `{keys: [{id, name, prefix, scopes, created_at, last_used_at, origin}], known_scopes}` |
| POST | `/api/settings/keys` | `{name, scopes, password}`: `201 {id, name, prefix, scopes, secret}`, the secret this once |
| DELETE | `/api/settings/keys/<id>` | revoke (`204`, `404`) |
| GET, PUT, DELETE | `/api/settings/webhook` | the webhook, `{url, events, secret?}` to save (`400 invalid` with `url_closed` or `secret_required`) |
| POST | `/api/settings/webhook/test` | one `moonie.webhook.test` now: `{status, duration_ms, error, reply_is_json}`; `409 not_configured`, `429 busy` |
| GET | `/api/settings/cloudflare` | `{token: {origin, state, missing, unverified, checked_at}, item_limit: {value, origin}}` |
| PUT, DELETE | `/api/settings/cloudflare/token` | `{token}` to set (`400 token_invalid` when Cloudflare refuses it), or clear |
| PUT | `/api/settings/cloudflare/item-limit` | `{value}`: a whole number, or `null` for the fallback |

### Variables

| Variable                           | Meaning                                                                    |
| ---------------------------------- | -------------------------------------------------------------------------- |
| `MOONIE_REDIRECT_PUBLIC_BASE_URL`  | the address links and QR codes are written with, such as `https://go.example.test`; required, the app refuses to start without it (never the request's host) |
| `MOONIE_REDIRECT_STORE_KEY_FILE`   | the store key (above), 64 hexadecimal characters; with none, `store.key` is drawn beside the database |
| `MOONIE_REDIRECT_PASSWORD_FILE`    | fallback: a file holding the admin password, while none is set in Settings; with neither, nobody can sign in |
| `MOONIE_REDIRECT_API_TOKEN_FILE`   | fallback: a file holding an API token with every scope, 32 characters or more; optional once keys are made in Settings |
| `MOONIE_REDIRECT_SECRET_KEY_FILE`  | optional: the key that signs the session cookie; otherwise 32 random bytes drawn once into `session.key` beside the database (mode 0600), mixed with the file's password |
| `MOONIE_REDIRECT_DB`               | the database file, `/data/redirect.db` in the image                         |
| `MOONIE_REDIRECT_CLOUDFLARE_TOKEN_FILE` | fallback: a file holding a Cloudflare API token, while none is set in Settings; with neither, Cloudflare is off and the Address select hidden |
| `MOONIE_REDIRECT_CLOUDFLARE_ITEM_LIMIT` | fallback: the list items allowed per Cloudflare account, while none is set in Settings; `10000` by default (the free plan) |
| `MOONIE_HTTP_PORT`                 | the port, `8080`                                                           |

`compose.yml` also reads these from `.env`:

| Variable                           | Meaning                                                                    |
| ---------------------------------- | -------------------------------------------------------------------------- |
| `MOONIE_REDIRECT_IMAGE`            | the name compose builds the image under and runs, `moonie-redirect:local` by default |
| `MOONIE_REDIRECT_SECRETS_DIR`      | the folder holding the secret files, `./secrets` by default; an absolute host path for a Portainer stack |
| `MOONIE_REDIRECT_PORT`             | LAN mode: the host's port, `8080` by default                               |
| `MOONIE_REDIRECT_BIND`             | LAN mode: the host address the port listens on, `0.0.0.0` (every one) by default; `127.0.0.1` for a proxy on the host |
| `MOONIE_REDIRECT_PROXY_NETWORK`    | proxy mode: the reverse proxy's external network, `proxy` by default       |
| `MOONIE_REDIRECT_HOST`             | proxy mode: the public host in the Traefik router's rule; required by `compose.proxy.yml` |
| `MOONIE_REDIRECT_ENTRYPOINT`       | proxy mode: the Traefik entrypoint of that router, `websecure` by default   |
| `TZ`                               | the container's time zone, `UTC` by default; links expire by UTC days whatever it is |

The session cookie is `Secure` when the public base URL is `https`, and not over plain `http` (LAN mode), where a
browser would drop a `Secure` cookie. The app sends no HSTS header: on `https`, that is the reverse proxy's call.

## Recipes

just is the contributors' tool: deploying needs only Docker Compose (see Deploying). Every recipe runs in a pinned
image, the same on macOS, Linux and Windows. `just` lists them.

- `just ci`: the merge gate: `just lint`, `just guide-check` (the guide in `wiki/guide`, checked by
  `tools/guide_check.py`), `just guide-images-check` (the guide's screenshots), `just compose-check` (`docker compose config` on both modes with `.env.example`: LAN mode
  with only the public address set, which must publish 8080, and proxy mode with the proxy's host too, which must
  publish nothing; in a pinned Docker CLI image, so the stack deploys with no just), `just test` (pytest), `just test-js` (the front's logic under Node) and
  `just goldens-check`. `just format` formats. It is the only CI: there is no hosted pipeline, and a change merges
  only on a green local `just ci` (D33).
- `just goldens [WALK ...]`: capture the GUI goldens into `tests/goldens` (walks `frame`, `links`, `nanourls`,
  `qrcodes`, `address`, `settings`, `settings-cloudflare`; the last three on the in-memory Cloudflare of the tests,
  `settings` with a webhook receiver on loopback), in the pinned Playwright image on `linux/arm64`, from the real app on a
  fixed clock and fixed draws. `just goldens-check` fails when one byte differs from the committed ones;
  `just goldens-stability` captures twice and compares. A UI change regenerates them, and the images are looked at
  before they are committed.
- `just guide-images`: copy the guide's screenshots, `wiki/guide/img`, from the goldens, byte for byte, as
  `tools/guide_images.py` maps them. `just goldens` runs it after every capture, so a UI change refreshes the guide
  too; `just guide-images-check` fails when an image differs from its golden, has a name or a weight SiteLuna
  refuses, or is not shown by a page in both languages.
- The goldens are byte-exact on `linux/arm64` only, so `just ci` expects an arm64 Docker host (an Apple silicon Mac, or
  an arm64 Linux machine). An amd64 host runs that image under QEMU emulation, which must be installed, and its
  captures may differ by bytes.
- `just build`: the image `moonie-redirect:local`.
- `just run`: the stack in LAN mode, from `compose.yml` and `.env`, `docker compose up -d --build`.
- `just run-proxy`: the stack behind a reverse proxy, the same command with `-f compose.yml -f compose.proxy.yml`.
- `just lock`: re-pin `requirements*.txt` (needs `uv` on the host).
- `just import-v7 <path>`: import a 7.0.1 database (below).
- `just store-key`: print a new store key; `just store-key > secrets/store_key` makes the compose secret.
- `just reset-password`: in the running stack, drop the password set in Settings and end every session, so the
  password file counts again.

## Deploying

No image is published on any registry: compose builds it from this repository (`build: .`, tagged
`MOONIE_REDIRECT_IMAGE`, `moonie-redirect:local` by default). `compose.yml` runs it read-only, with every capability
dropped, `no-new-privileges`, a 16 MiB `/tmp`, 128 MiB of memory and 64 processes at most. The data lives in the
`data` volume, and the store key, the password and the token come in as secrets. The app is meant for the LAN only.

Two modes (D35):

- **On the LAN's IP** (the default, `compose.yml` alone): the port is published on the host,
  `${MOONIE_REDIRECT_BIND:-0.0.0.0}:${MOONIE_REDIRECT_PORT:-8080}`, and no network has to exist beforehand. The public
  base URL is the host's address and port, such as `http://192.0.2.10:8080`. **This is plain http, with no
  encryption: the password and the session cookie cross the network in clear, so it is meant for a trusted LAN.** The
  session cookie is not `Secure` there; the CSRF token, the `Sec-Fetch-Site` check (a browser sends none from an
  insecure context, and that is accepted, as from an old browser) and the content security policy work the same.
- **Behind a reverse proxy** (`compose.proxy.yml` laid over it, Docker Compose 2.24 or newer for its `!reset`): no port
  is published, and the container joins the proxy's external network (`MOONIE_REDIRECT_PROXY_NETWORK`, `proxy` by
  default, made with `docker network create proxy` if it does not exist), where it answers at `moonie-redirect:8080`.
  The overlay carries Traefik labels as the example, with the router's host in `MOONIE_REDIRECT_HOST` (required) and
  its entrypoint in `MOONIE_REDIRECT_ENTRYPOINT`. Any other proxy in Docker ignores the labels and is pointed at
  `http://moonie-redirect:8080` on that network; a proxy installed on the host keeps LAN mode with
  `MOONIE_REDIRECT_BIND=127.0.0.1` and points at `http://127.0.0.1:8080`. The app needs no forwarded header: it never
  builds its links from the request. The public base URL is the proxy's `https` address.

1. Get the repository (`git clone`, or its archive). Copy `.env.example` to `.env` and set
   `MOONIE_REDIRECT_PUBLIC_BASE_URL` for the mode chosen (and `MOONIE_REDIRECT_HOST` behind a proxy).
2. Create the secrets, owned by uid 10001, mode 0400 (on Docker Desktop, mode 0444 instead), as `.env.example` says:

   ```sh
   install -d -m 0700 secrets
   openssl rand -hex 32 > secrets/store_key
   printf '%s\n' 'a long admin password' > secrets/password
   openssl rand -hex 32 > secrets/api_token
   sudo chown 10001:10001 secrets/* && sudo chmod 0400 secrets/*
   ```

   Keep a copy of the store key apart from the backups of the `data` volume. `MOONIE_REDIRECT_SECRETS_DIR` moves the
   folder elsewhere.
3. The API token file is an optional fallback: once signed in, make scoped keys in Settings instead, and comment the
   `api_token` lines of `compose.yml` out to do without the file. The Cloudflare token file is optional too: set the
   token in Settings, or create its file the same way and uncomment its lines in `compose.yml`.
4. Start the stack one of two ways, then check `/health`, sign in and change the password in **Settings > Security**:
   - **Docker Compose**, with nothing else: on the LAN's IP `docker compose up -d --build`; behind a reverse proxy
     `docker compose -f compose.yml -f compose.proxy.yml up -d --build`. `COMPOSE_PATH_SEPARATOR=,` and
     `COMPOSE_FILE=compose.yml,compose.proxy.yml` in `.env` make every `docker compose` command (`exec`, `logs`,
     `down`) read both files. Upgrading is `git pull` and the same command.
   - **just**: `just run` on the LAN's IP, `just run-proxy` behind a reverse proxy, which run those same commands.

**As a Portainer stack.** Portainer documents building images from a Git stack as not fully implemented, and build
steps as failing on remote environments; relative paths in a Git stack are a Business Edition option. So: on the
Docker host, build the image (`docker build -t moonie-redirect:local .`) and put the secrets in an absolute folder;
then add a stack with the **Web editor**, paste `compose.yml` without its `build: .` line (behind a reverse proxy,
replace its `ports` lines with the `networks` and `labels` lines of `compose.proxy.yml`, and add that file's
`networks` block), and set `MOONIE_REDIRECT_PUBLIC_BASE_URL` and `MOONIE_REDIRECT_SECRETS_DIR` (that absolute folder)
in its environment variables. To upgrade, rebuild the image on the host and update the stack, with re-pulling off. A
**Repository** stack reads `compose.yml` unchanged, so it only suits a copy whose `compose.yml` already fits, on
Portainer's local environment, with the image built beforehand. The guide's Getting started page walks through it.

### Upgrading and rolling back

The database is migrated on start, from schema v1 (8.0.0) to v4 (the Cloudflare address and state, the admin sessions,
then the settings, sealed secrets, API keys and the webhook's outbox), with no step to run. An earlier install that
kept its settings in files (before 9.2) moves nothing else: the files keep working and Settings shows them as
`From file`. This `compose.yml` names a `store_key` secret: create it before the first start, or comment its
`store_key` lines to let the app draw `store.key` in the volume.

Rolling back to 9.1 works on a version 4 database: 9.1 ignores the new tables and reads the files again. A password
changed in Settings, the keys made there, and the Cloudflare token and webhook set there do not exist for 9.1: sign in
with the file's password, and scripts with the token file. Back on 9.2 or later, they all count again.

Rolling back to 8.1.0 works on a migrated database: every link keeps answering on the LAN. While 8.1.0 runs, though,
an edit or a delete of a link that has a Cloudflare address is not queued for Cloudflare, so the list keeps the old
item: back on 9.1 or later, run **Compare with Cloudflare** and fix what it lists. Restoring a backup of the database
signs everyone out, as the admin sessions live in it (`admin_sessions`).

## Importing 7.0.1

Only for an install of the earlier app (see History). 7.0.1 kept its links in the `redirect_links` table of
`moonie.db`, in its `data` volume. 8 uses the same table with
the same columns, so the rows go over unchanged, ids and paths included, and printed QR codes keep working.

1. Stop 7.0.1 cleanly, so its write-ahead log is folded into the file, and copy `moonie.db` out of its volume.
   A copy with a pending `moonie.db-wal` beside it is refused.
2. Make the copy readable by uid 10001 (`chmod 0644`).
3. `just import-v7 path/to/moonie.db`. It opens the file read-only and inserts every row whose id and path are free
   and that keeps the rules (id code, path, `http`/`https` target, kind, status). It prints how many rows it imported,
   how many were duplicates (id or path already here) and how many it refused. Running it again changes nothing. A
   file that is not a 7.0.1 database stops it with one line and exit code 1.

Without just, step 3 is `docker compose run --rm --no-deps -v /srv/import/moonie.db:/import/moonie.db:ro moonie
python app.py import-v7 /import/moonie.db`, with the copy's absolute path.

Outside the stack, the command is `python app.py import-v7 <path>`, with `MOONIE_REDIRECT_DB` naming the new database.

A NanoURL or QR code that 7.0.1 wrote with its IP address (`link_host` `ip`) keeps that address in the printed code:
the app must stay reachable at it, or the printed code breaks. The import prints how many such rows it brought in. The
admin pages and the API write every link with the public base URL.

When 7.0.1 ran the Cloudflare plugin, the import also copies its install id (so the items it wrote stay this app's),
its accounts with their list and rule, its hosts and their pages for unknown paths, its entries and its pending
removals, and prints what it brought. It checks them as the admin page does: no host that is the admin's or no host
name, no page for unknown paths that loops or is not an http(s) address, no link under `.well-known`; a row of a wrong
type is left out and counted. An install id that no item marker can hold is not taken: the app draws its own, and the
output warns that the items 7.0.1 wrote are then foreign (Compare lists them to remove). Run **Compare with
Cloudflare** once afterwards.

`ROADMAP.md` lists what 7.0.1 had and this app does not, yet.

## Licence

`SPDX-License-Identifier: AGPL-3.0-or-later`

Copyright (C) 2026 LunaCreatoris. This program is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of
the License, or (at your option) any later version. It comes with no warranty. The full text is in
[`LICENSE`](LICENSE).

The bundled third-party files keep their own licences, shipped beside them:

- the Manrope and IBM Plex Mono fonts, in `static/fonts`: SIL Open Font License 1.1 (`OFL-Manrope.txt`,
  `OFL-IBM-Plex-Mono.txt`);
- the Google Material Symbols paths, in `static/ui/icons.js`, copyright Google LLC: Apache License 2.0
  (`static/ui/LICENSE-material-symbols.txt`).
