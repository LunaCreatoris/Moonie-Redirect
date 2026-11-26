# Decisions

Each decision says what was chosen, why, and what undoing it would take. Newest last. Versions 7.0.1 and earlier, and
the plugins they mention, are the earlier app this one replaces (see the README's History).

## D1 · 9.0.0: the admin is 7.0.1's own pages, ported

- **What**: the admin is the moonie-redirect 7.0.1 UI (its shell, kit and Redirect pages), copied into
  `static/ui` as plain ES modules and trimmed: no plugins, zones, languages, optimistic concurrency or drafts. Flask
  serves one frame (`templates/app.html`) for every `/admin/...` address; the pages call the JSON API.
- **Source**: taken from the 7.0.1 image. Each copied file names its source on its first line.
- **Why**: a faithful copy of 7.0.1's UI; the look is the output of the kit and the page modules, so
  copying them reproduces every state, where server-rendered pages would rewrite each one.
- **Undo**: restore 8.1.0's `form.html`, `list.html`, `app.css` and the `/admin/<section>/...` routes.

## D2 · The session reaches the API, with a CSRF header

- **What**: with no `Authorization` header, `/api/*` accepts the admin session. A change also needs `X-CSRF-Token`
  equal to the session's token and `Sec-Fetch-Site` absent or `same-origin`, else `403 csrf`. Any `Authorization`
  header, valid or not, is the only proof read.
- **Why**: the pages run in the browser and must not hold the API token; header token, JSON-only bodies, fetch metadata
  and `SameSite=Lax` together keep another site from changing links through the cookie.

## D3 · The server's error words become 7.0.1's texts in the browser

- **What**: the API keeps its English field messages; `static/ui/lib.js` (`fieldCode`) reads each as the key of the
  7.0.1 sentence for that refusal, and a path taken is said under the field that makes it (`slug`, or `name`). A message
  no rule knows reads as "This value is not valid."
- **Why**: the API does not change for its other clients, and the pages say what 7.0.1 said.
- **Slugs**: the server tells an empty segment, a `.`/`..` segment and any other bad character apart, so the page
  says 7.0.1's three sentences (8.x had one message for all three).

## D4 · Unknown admin addresses get the frame with a 404

- **What**: `/admin/<anything else>` answers the frame with status `404`; the shell draws 7.0.1's in-frame not-found
  page.
- **Why**: the 8.x form addresses (`/admin/links/new`, `/admin/links/<id>`) are gone; a bookmark lands on a page that
  says so, in the frame, with a status that says so too.

## D5 · Goldens: pinned Chromium, fixed draws, one raster thread

- **What**: `tests/ui/screenshots.py` runs the walks of `tests/ui/walk_*.py` (shared parts in `tests/ui/kit.py`) in
  `mcr.microsoft.com/playwright/python:v1.52.0-noble` pinned by digest, on `linux/arm64`, with Playwright 1.52.0 pinned
  in `tests/ui/requirements.txt`. The app runs in the same process on one thread, with `app.now` replaced by a fixed
  clock and `app.draw_code` by 7.0.1's fixed series (the n-th id or suggested slug is the number 2n + 2 in the code
  alphabet, lowest digit first: `62222222`, `82222222`...), and its version pinned to `9.0.0` in the captures. The
  browser runs in UTC, `en-US`, 1440 × 980, with its clock paused. Chromium runs with `--disable-gpu --disable-lcd-text
  --font-render-hinting=none --num-raster-threads=1 --disable-partial-raster --force-color-profile=srgb`.
- **Why**: without the raster flags, antialiased edges came out one step apart between runs. LCD text off and no
  hinting give 7.0.1's greyscale glyphs and fractional advances: with hinting, text came out wider, so buttons, columns
  and wrapped lines differed from 7.0.1's goldens. A pinned version keeps a release from changing every golden.
- **Capture failures**: a script error (`pageerror`) or a refusal of the page's policy (`securitypolicyviolation`) at
  any point of a walk fails the run: a golden of a broken page is no golden.
- **Names**: 7.0.1's golden names less `-en-desktop`. The link-address states (`*-public`, `*-ip`, `*-no-public`,
  `link-host-same`), `*-error-link-changed`, `drafts-*`, `qrcodes-link-too-long`, phone and French captures are gone with
  what they showed (see `ROADMAP.md`). The login, its states, the in-frame not-found page and the public 404/503 are
  captured by the `frame` walk.

## D6 · The texts are one JSON module

- **What**: `static/ui/en.json` holds every text the pages use and no other, imported by `shell.js` as a JSON module
  (`with { type: 'json' }`). A test checks both ways.
- **Why**: no fetch to wait for before the first draw. It needs a browser from 2024 or later (Chromium 123, Firefox 138,
  Safari 17.2).

## D7 · Admin sessions are kept on the server

- **What**: a login writes a row in `admin_sessions` (schema version 3: a random id and the login time); the signed
  cookie names it. `/admin/*` and the session's `/api/*` need the row, under 12 hours old. A logout deletes its row, a
  new login in the same browser deletes the one it replaces, and each login drops the rows already over.
- **Why**: with a signed cookie alone, a copy of it (a shared machine, a proxy log, a profile backup) outlived the
  logout, and a cookie signed again on each answer never reached its 12 hours. One row per session ends only the one
  logged out; a new password still signs everyone out through the key.
- **Cost**: one indexed read per admin call. A database restored from a backup signs everyone out.
- **Undo**: drop the table and `signed_in()`, check `session["admin"]` again.

## D8 · A name must show something

- **What**: a name is refused (`holds control or invisible characters`) when it holds a character of Unicode category
  C, one of the blanks Unicode files as a letter, symbol or mark (U+034F, U+115F, U+1160, U+17B4, U+17B5, U+2800,
  U+3164, U+FFA0), or no letter, digit, punctuation or symbol at all.
- **Why**: those names show empty in the list, or two links look alike. The list of blanks is short and explicit, so
  variation selectors stay allowed and an emoji such as U+2764 U+FE0F is still a name.

## D9 · The list sends logos unopened

- **What**: `GET /api/links` checks each QR code's design as usual, but its logo by shape alone (`data:image/...;
  base64,...`), never decoded nor parsed. One QR code read alone, `qr.svg` and the preview check it whole.
- **Why**: the QR page needs each design, logo included, to open its form without another call; decoding and parsing
  up to 256 KiB per row on every load was the cost, and the stored logo was checked whole when it was written. A row
  changed by hand with a broken logo shows in the list, and its thumbnail and preview say it cannot be drawn.
- **Undo**: drop `listed=True` in `api_list`.

## D10 · A page takes a replaced CSRF token afresh

- **What**: when a change from a page is refused `403 csrf`, the page reads the session's token from `GET /api/session`
  (session only: `404` with a bearer token then;
  `403 needs_admin` since D28), writes it into its `csrf-token` meta and its logout form, and sends the
  change once more. A second refusal is shown as before.
- **Why**: a login in another tab replaces the session, and its token, under every open tab. The old tab's next save was
  refused as "from another origin" and the form was left with that message. The refused call changed nothing, so
  sending it again is safe, and the typed form is saved instead of lost. Another site still cannot read the token: the
  answer carries no CORS header, and a cross-site change still lacks it and `Sec-Fetch-Site: same-origin`.
- **Undo**: drop `renewToken` in `shell.js` and the `/api/session` route.

## D11 · 9.1.0: the Cloudflare page is the Cloudflare plugin's own, ported

- **What**: `/admin/cloudflare` is the page of 7.0.1's Cloudflare plugin (`ui/cloudflare.js`, `ui/logic.js`,
  `ui/cloudflare.css`, `ui/moonie-mark-cloudflare.svg`), copied into `static/ui/cloudflare.js`,
  `static/ui/cloudflare-logic.js`, `static/cloudflare.css` and `static/ui/moonie-mark-cloudflare.svg`, under 7.0.1's
  ADMINISTRATION section of the menu. Trimmed: the Links, NanoURLs and QR codes tabs and their forms (a link carries its
  address in the Redirect pages), the tab bar left with one tab, held hosts and their removal (hosts are folded once),
  the link to the plugin's settings (the token is a secret file: the texts say so). Added: the page Cloudflare off
  shows, in the shell's state card, naming the setting.
- **Source**: 7.0.1's Cloudflare plugin, its `ui/` folder. Text keys built at run time
  (`cloudflare.error.<code>`) are written out as a table, so every key a module uses is checked against `en.json`.
- **Why**: the plugin's page with its look and dialogs; copying it reproduces its states.
- **Undo**: drop the four files, the menu section and `/admin/cloudflare` from `ADMIN_PAGES`.

## D12 · A link's address: in the list answer, a select in each form, a line under each name

- **What**: `GET /api/links` also answers `addresses` (the LAN, then each host set up while Cloudflare is on), so a
  Redirect page loads with one call, as before, and never waits on a token check. The forms show an **Address** select
  with 7.0.1's link address look (select and help line), the lists show where each link answers and its state on a line
  under its name. Both only once a host exists: a LAN-only instance looks as 9.0.0 did.
- **Why**: an Address column after the target pushed the Copy and Download buttons out of the list card at 1440 px.
  `GET /api/cloudflare` checks the token (a call to Cloudflare, cached 10 minutes): too slow for every Links load.
- **Undo**: drop `addresses` and the helpers at the end of `static/ui/common.js`.

## D13 · Any address given up asks first, every kind

- **What**: a change of a link's address away from a Cloudflare host (to the LAN or another host), for links as for
  NanoURLs and QR codes, a new slug for a link on a host (its source `<host>/<slug>` moves), and the delete of a link
  that has one, need `confirm_break: true` (`400 confirm_break` without it); a `DELETE` takes it in its JSON body or as
  `?confirm_break=true`. The pages ask in the kit's dialog and send it.
- **Why**: printed NanoURLs and QR codes were the first case; a link's `https://<host>/<slug>` shared elsewhere stops
  just the same. One rule is simpler to hold in the API.
  A key may not move a link to a new path of an adopted host either, by address or by slug, without
  `cloudflare:setup` (`403 scope_denied` since D25): the check runs on every change of the source.
- **Undo**: limit the check in `api_update` to `kind != "link"`.

## D14 · Cloudflare's failures on the admin endpoints are codes

- **What**: a call of the page that Cloudflare refuses or does not answer gets `502` with the sync's own code
  (`unreachable`, `refused`, `permission`, `token_invalid`, `internal`), or `429 rate_limited`; a long `Retry-After`
  holds the handlers' calls too, as it holds the sync. Compare's report names its rows by `sources` (`https://...`),
  its pages for unknown paths `fallback:<host>`, and gives its `fingerprint` to the session only.
- **Why**: the page says what to do from a code; Cloudflare's own message may echo a target, and stays in the log only
  as its status and codes.

## D15 · import-v7 and a lost setup answer: what is ours, and what is refused

- **What**: `import-v7` does not take a 7.0.1 install id that no item marker can hold (1 to 64 of `[0-9A-Za-z_-]`): the
  app draws its own, the rest is imported, and the output warns that 7.0.1's items are now foreign (Compare lists them).
  Its other rows go through the admin's own checks: a host that is the admin's or no host name is refused with its
  links, a page for unknown paths through `check_fallback`, a link under `.well-known` refused, and a row of the wrong
  type left out and counted (`damaged`). A setup finding, at its name, only one proxied `A` record to `192.0.2.1` with
  the comment `moonie-redirect` reuses it as the record it made (`use_record` then `keep_ours`): the host stays created
  here and keeps its page for unknown paths. Zone names that make no host name are refused at the plan.
- **Why**: a refused install id would be kept for good and make every later item write fail; a damaged row crashed the
  whole Cloudflare step. The placeholder serves nothing, so it cannot be a live site to protect: adopting it (the apply
  whose answer was lost) left the host without its page and the bearer token without it.
- **Undo**: take `old_id` as it is in `import_v7_cloudflare`, drop `_texts`, and drop `is_our_placeholder` from
  `record_verdict`.

## D16 · 9.1.0 visual review: what moved, and what stays as the plugin had it

- **What**: the quota chips hide while Cloudflare refuses the token (nothing is synced, so the count is an old
  reading). The Address select reads **Link address**, and on the LAN says `Through the public URL: <url>`, as 7.0.1
  did. The goldens show the app's own `VERSION` in the brand, no longer a pinned 9.0.0. Kept as they are: **New host**
  stays enabled when DNS Write is missing (the plugin disabled it only for a token not `ok`; the plan's
  permission step then says what is missing), and the status chip counts every kind of link ("8 redirects" beside "4
  links" counts the NanoURLs and QR codes too, as 7.0.1 did).
- **Why**: the visual review of 9.1.0 against the plugin and 7.0.1 listed these as minors.
- **Undo**: `quotaChipAccounts` back to `accountsWithList`, the two texts in `en.json`, and the VERSION pin in
  `tests/ui/kit.py`.

## D17 · A request never waits on Cloudflare's retries

- **What**: the Cloudflare calls of a request (`Cloudflare.bounded`) are tried once, never sleep a `Retry-After`
  (`429 rate_limited` at once), wait `REQUEST_TIMEOUT` (3 s to connect, 5 s between bytes) or the time left, and none
  starts once 10 s have passed (30 s for `POST /api/cloudflare/apply`, whose plan is read again before it is done). A
  token check that failed is cached 60 s as `unchecked`. The sync's thread keeps 4 attempts, back-off and short
  `Retry-After` sleeps.
- **Why**: waitress runs 4 threads. `GET /api/cloudflare` checked the token in the request with the full retry
  ladder, holding a thread over a minute on an unreachable Cloudflare; four page loads blocked the whole app, the LAN
  redirects included.
- **Undo**: drop `bounded()` from `calling` and `api_cloudflare`, and the `unchecked` caching in `Sync.token_state`.

## D18 · The admin's own host takes no link, at save and in the sync

- **What**: the setup plan's rule that the admin's host takes no Cloudflare item now holds after setup too. A link's
  `address` that is the host of `MOONIE_REDIRECT_PUBLIC_BASE_URL` or of the request is refused (`400 invalid`, field
  `address`), unless the link already has it. The sync sends nothing for a host that has become the admin's (the base
  URL moved onto a host set up earlier): its pending links and its pending page for unknown paths go to error
  `admin_host`, and so does its account, every pass, Sync now included. Items already sent stay until their links move.
- **Why**: a list item on the admin's host answers before the admin, so the admin pages would vanish behind
  Cloudflare. The plan already refused such a host; a base URL changed later went unchecked.
- **Undo**: drop the `serving_hosts` check in `asked_address` and `Sync._refuse_admin`.

## D19 · The goldens are checked on linux/arm64, by `just ci`

- **What**: `just goldens-check` runs in `just ci`, captured on linux/arm64 in the pinned Playwright image,
  before every merge, with the lint, the guide check, the tests and the front's tests (D33: `just ci` is the only CI).
- **Why**: the goldens are byte-exact and captured on one platform, `linux/arm64`, and captures on amd64 differ by
  bytes. Contributors on an amd64 host run `just ci` under QEMU emulation, and their captures may differ.
- **Undo**: capture and compare the goldens on every platform `just ci` may run on, one golden set per platform.

## D20 · The admin pages offer no status code: links made there are 302

- **What**: 9.1.1 drops the 301/302 select from the link form and the Code column from the list. A save from the
  pages sends no `http_status`: a new link takes the server's default, `302`, and an edit keeps the stored code. A link
  that answers `301` (set through the API, or imported from 7.0.1) shows a read-only note on its form saying a save
  there keeps it and only the API changes it. The JSON API still accepts `http_status` `301` or `302`, unchanged.
- **Why**: the 301 leaves the UI. A browser caches a 301 for good, so a target changed later never
  reaches those who followed it; a 302 can always be moved. Not sending the field, rather than sending `302`, means an
  existing 301 is never flipped behind the user's back, and the note means it is never hidden either.
- **Undo**: bring back the select (`http_status` in `linkBody` and `OWN_FIELDS`), the Code column, and the
  `redirect.code_301`, `code_302`, `col_code`, `f_code` and `http_status_invalid` texts, and drop
  `redirect.status_kept`.

## D21 · 9.2.0: one Settings page with three tabs

- **What**: `/admin/settings`, the item **Settings** (glyph `instance`) under Administration after Cloudflare, holds
  three tabs with 7.0.1's `ui.tabs`, the tab kept in the address (`?tab=security`, the default, `webhook`,
  `cloudflare`), so Back and a reload keep it. **Security** ports 7.0.1's instance page (sign-in card, Change password,
  End all sessions; its Versions card dropped, the frame shows the version) and says where the password comes from.
  **Webhook & API** ports 7.0.1's webhook and keys pages on one tab (the incoming calls card replaced by the keys; the
  token file as a fixed row). **Cloudflare** ports the Cloudflare plugin's credential and integer rows (token, item limit),
  with the Cloudflare page's own token check and the four permissions of its README. The Cloudflare page's off card
  and refused-token banner point to Settings instead of a file and a restart. Each tab reads only its own calls, and a
  change draws the tab again from the server's answer. A webhook test and the last delivery show 7.0.1's result lines.
- **Why**: 7.0.1 had the three as separate pages of its base and of the Cloudflare plugin; this app has one admin, so
  one page with tabs keeps the menu to five items and the three settings in one place. The tab in the address follows
  the plugin page's rule. Porting the pages, rather than drawing new ones, keeps the look of 7.0.1 (D1).
- **Undo**: drop `static/ui/settings*.js`, `settings.css`, the menu item, the `admin.*` actions, the settings texts,
  `"settings"` from `ADMIN_PAGES`, `tests/ui/walk_settings.py` and its goldens; the API can stay.

## D22 · 9.2.0: the database wins, the file is the fallback

- **What**: every value the Settings page sets is read from the database first; the file or variable of 9.1 counts
  only while the database has none. The admin password (`settings.admin_password`, else
  `MOONIE_REDIRECT_PASSWORD_FILE`), the Cloudflare token (sealed `cloudflare_token`, else
  `MOONIE_REDIRECT_CLOUDFLARE_TOKEN_FILE`), the item limit (`settings.cloudflare_item_limit`, else
  `MOONIE_REDIRECT_CLOUDFLARE_ITEM_LIMIT`, else 10 000). The token file stays a fixed key with every scope (`*`),
  listed in Settings as `Token file` with no prefix shown and no Revoke. Nothing is copied at the upgrade.
- **Why**: an upgrade from 9.1 must change nothing until the admin sets a value; files keep working and show as
  `From file`. Clearing a value in the UI goes back to the file, so the fallback is always the one the admin wrote.
- **Undo**: read the files only (9.1's `create_app`); the tables of version 4 can stay, 9.1 ignores them.

## D23 · Readable secrets are sealed with AES-256-GCM and a store key apart

- **What**: the values the app must read back (`cloudflare_token`, `webhook_secret`) are rows of `secrets`, sealed
  with AES-256-GCM (`cryptography`), a 12-byte random nonce per write, `moonie-redirect:<name>` as associated data, and
  `key_id` = the first 8 hex of HMAC-SHA256(key, `key id`). The key is `MOONIE_REDIRECT_STORE_KEY_FILE` (64 hex
  characters, a compose secret outside the data volume); unset, `store.key` is drawn once beside the database (mode
  0600, written whole then linked, as `session.key`) and every start logs that a backup of the volume then holds both.
  A key file named but unreadable or malformed stops the start. A row sealed with another key, or damaged, reads as
  `unreadable`, never as an error: Cloudflare falls back to the file, else goes off. `SealedSecrets` (`state`, `read`,
  `write`, `delete` by name) is what the rest of the app uses. No rotation command (ROADMAP).
- **Why**: SQLCipher would mean a native build per architecture; row-level AEAD keeps the database a plain SQLite file
  that 9.1 still opens, and a copied database alone gives no readable secret. The associated data stops a value from
  being moved to another row; the key id tells a lost key from a damaged row without trying to decrypt.
- **Undo**: store the two values in the clear in `settings` (file mode 0600) and drop `cryptography`.

## D24 · The admin password: scrypt 2^14, one hash at a time, `reset-password`

- **What**: a password changed in Settings is stored as `scrypt$16384$8$1$<salt>$<hash>` (16-byte salt, 32-byte hash,
  base64), hashed and checked under one lock, behind the 1 s login brake, which the login and every password check of
  the settings share (`429 too_many_attempts` from the API). New passwords are 12 to 1024 characters. A change ends
  every other session (D7); the cookie key is unchanged. `python app.py reset-password`, run in the deployed
  container, drops the stored hash and ends every session, so the file's password counts again.
- **Why**: 7.0.1's 2^17 takes 128 MiB, the whole of the container's `mem_limit`; 2^14 takes 16 MiB. One hash at a time
  keeps four threads from taking 64 MiB at once. A command in the container is the way back when the UI password is
  lost, without touching the database by hand.
- **Undo**: drop the `admin_password` setting and the command; the file's password counts as in 9.1.

## D25 · API keys with scopes; the setup opens to keys

- **What**: keys are `mrk_` + 32 random bytes (url-safe base64), made in Settings with a name, scopes and the
  admin's password, shown once; the database keeps the SHA-256 of the token, its first 8 characters, the name and the
  scopes, and the last use, written at most once a minute. Scopes are 7.0.1's: `redirect:{links,nanourls,qrcodes}.
  {read,write}`, `cloudflare:{read,write,setup}`, and the wildcards `*`, `redirect:*`, `cloudflare:*`. The session
  holds every scope. A missing scope answers `403 scope_denied`; a link of a kind the key cannot read answers `404`;
  a list with no `kind` holds only the kinds the key reads (`403` when it reads none). A link on a Cloudflare host,
  before or after the change, is created, changed or deleted with `cloudflare:write` too, since the write reaches
  Cloudflare; an adopted host's new path needs `cloudflare:setup`. A QR code's preview at a Cloudflare address writes
  nothing and needs only `redirect:qrcodes.read`. The setup endpoints (zones, proposals, plan, apply, fallback,
  Compare's fingerprint and apply) need `cloudflare:setup` where 9.1 refused every key (`needs_admin`).
- **Why**: n8n and scripts get only what they need, and a key can be revoked alone. The token is high-entropy, so one
  SHA-256 suffices and no KDF runs on every call. With scopes, the setup no longer needs to be the session's alone: a
  key that holds `cloudflare:setup` was given it on purpose. The token file keeps `*` so 9.1 scripts keep working.
- **Undo**: drop `api_keys` and the `needs()` calls; `admin_only()` and `address_needs_admin` come back.

## D26 · The n8n webhook: signed events from an outbox, sent only where the guard allows

- **What**: each link created, changed or deleted through the API (session or key) raises `redirect.link.created`,
  `updated` or `deleted` when the webhook has a URL, a readable secret, that event ticked and is not disabled: one row
  of `webhook_outbox`, written after the link's commit, which never fails the request. The body is 7.0.1's
  `{"id","event","source":"redirect","at","data"}`, `data` holding `id, kind, slug, name, target, http_status,
  expires_on, address, updated_at` (never the design), at most 64 KiB. The headers are 7.0.1's: `X-Moonie-Event`,
  `X-Moonie-Event-Id`, `X-Moonie-Timestamp`, `X-Moonie-Signature: sha256=<HMAC-SHA256(secret, "<id>.<ts>." + body)>`,
  plus `User-Agent: moonie-redirect/<version>`. One `webhook` thread, started in `main()`, sends the oldest due row,
  one at a time, and sleeps until the next due row (at most 60 s) or a new one. A row stays `pending` until its attempt
  is recorded: at least once, the event id dedups. Retried: no answer, `408`, `429`, `5xx`, after 10 s, 60 s, 5 min,
  30 min (+-20 %), then `failed`. `2xx` delivers; `410` sets `webhook_disabled_reason = gone` and keeps the rows until a
  Save; any other status, `3xx` included, fails the row at once, and redirects are never followed. An answer that comes
  back after the URL changed, or for a row deleted meanwhile, records nothing. At most 10 000 waiting rows (the next
  event is dropped, logged); finished rows go after 7 days, checked hourly; Delete webhook drops the waiting rows. An
  unreadable secret holds the rows with no attempt counted. The last attempt is kept as the `webhook_last_delivery`
  setting. `POST /api/settings/webhook/test` sends one `moonie.webhook.test`, one at a time (`429 busy`), outside the
  outbox. The four `/api/settings/webhook` routes answer the session only (`403 needs_admin` to every key).
- **Guard**: `http`/`https`, ASCII, at most 2048 characters, no user or password, port 1-65535. Open: global unicast
  and 10/8, 172.16/12, 192.168/16, 100.64/10, fc00::/7; closed: loopback, `localhost` and `*.localhost`, link-local
  (the metadata address with it), multicast, unspecified, reserved, the known metadata services, and IPv6 forms that
  carry a closed IPv4 (mapped, 6to4, Teredo, NAT64). A numeric host, in any spelling the system reads (`2130706433`,
  `0177.0.0.1`), is judged at save (`url_closed`); a name is resolved at each attempt, every answer must pass, and the
  socket connects to the address judged, with `Host` and the TLS SNI set to the name. TLS is checked against the system
  store. Limits: 5 s to connect, 30 s for the whole attempt (a watchdog cuts the socket; name resolution cannot be cut),
  64 KiB of reply read. Logs give the receiver's origin, never its path or query. The tests open loopback through the
  `Webhook` constructor's `allow` and give names through its `resolver`, never through the environment.
- **Why**: 7.0.1's n8n workflows check these headers and this signature, so they keep working. The outbox makes a
  restart cost one more delivery, never a lost event. The guard keeps the webhook, which an admin points anywhere, from
  becoming a way into loopback or a cloud's metadata, and judging the resolved address once, then connecting to it,
  leaves no rebinding gap. The LAN stays open because n8n is usually on it (`http://n8n:5678` is on a Docker network).
- **Undo**: drop the `# --- Webhook ---` section of `app.py`, its four routes and the three `hook.emit` calls; the
  `webhook_*` settings and the `webhook_outbox` table can stay, unread.

## D27 · The Cloudflare token and item limit change while the app runs

- **What**: `Sync.use(client | None)` swaps the client under a lock, drops the token's cached check (or takes the one
  just made), forgets the back-off, and starts the thread if `main()` started the sync and none runs; the loop idles
  while the client is None. A pass in flight ends with the client it started with, and a check of a token swapped out
  meanwhile is not cached. Setting a token checks it first: `400 token_invalid` when Cloudflare says it is not active
  (nothing stored); missing permissions or no answer store it, answered with the check. `Store.item_limit` reads the
  setting at each use.
- **Why**: a restart to change a token or a limit was what the files forced; the page now does it. Keeping the pass's
  own client means one pass never mixes two accounts' tokens.
- **Undo**: read the token and limit once in `create_app` again, and drop `Sync.use`.

## D28 · The settings are the session's alone

- **What**: every `/api/settings/**` call and `/api/session` answer any bearer key, `*` and the token file included,
  `403 needs_admin` (`/api/session` answered `404` in 9.1). Changes there need the CSRF token as every change (D2).
  Nothing secret is ever answered: a password, token or secret is told only by where it comes from (`stored`, `file`,
  `missing`, `unreadable`).
- **Why**: a key that could make keys or change the password would be worth as much as the session; keeping the
  settings to the session means a leaked key never grows.
- **Undo**: drop the path check in `api_guard`.

## D29 · 9.3.0: the Cloudflare page moves into Settings > Cloudflare

- **What**: the menu's Administration section holds **Settings** alone. The Cloudflare tab of Settings shows the token
  and the item limit first, as in 9.2, then the whole Cloudflare page under them: its head (mark, intro, quota and
  count chips, **Sync now**, **Compare with Cloudflare**), its banners and notice, the hosts with their page for unknown
  paths, **New host** with its plan, and the resync dialogs. `static/ui/cloudflare.js` is mounted into the tab
  (`mountDomains`, `loadDomains`) instead of being rewritten; the tab reads `GET /api/settings/cloudflare` and
  `GET /api/cloudflare` together, and a token or limit change reads the domains again with its answer. The token's
  check (its chip and lines) is said once: in the token's row whenever the row has one (a token set here or from the
  file), in the domains' head otherwise (a token that cannot be read, with the file's in force). Cloudflare off shows
  its card in the domains' place, and its button, like the refused token's banner link, moves the focus to the token's
  row of the same tab, never to another address. `GET /admin/cloudflare` answers `302` to
  `/admin/settings?tab=cloudflare` after the login, and the shell sends an entry of its history at that address to the
  same tab, in place (`movedTo`), so Back never finds it again. The goldens of the page are captured inside the tab as
  `settings-cloudflare-*` (walk `settings-cloudflare`); its loading, error and off states are the Settings page's own
  and are checked there, not captured again. No API changes.
- **Why**: Cloudflare goes under Settings > Cloudflare, domains included: the token and the hosts it
  serves are one setting, and the menu keeps one item per job. Mounting the page keeps its look and behaviour as they
  were (D1, D11); saying the token's check once keeps two lines from telling the same thing on one screen.
- **Undo**: put the Cloudflare item back in `NAV` with a default export of `cloudflare.js` (load `loadDomains`, render
  `mountDomains` with no options), `"cloudflare"` back in `ADMIN_PAGES` instead of the redirect route and `MOVED`, the
  Cloudflare tab's load back to `admin.cloudflare` alone, and the walk back under its old name.

## D30 · 9.3.0: Settings and Log out are glyphs at the foot of the sidebar

- **What**: the menu has no Administration section: it lists Links, NanoURLs and QR codes under Redirect. The sidebar's
  foot, at its bottom-left, holds a gear link to `/admin/settings` (`aria-current="page"` while Settings is open,
  coloured as the menu's current item) and, to its right, the Log out button, still the template's form posted to
  `/logout` with its CSRF field. Both are named by `aria-label` and `title` ("Settings", "Log out") and take the focus
  ring of every control. Since 9.3.1 they are two buttons sharing the sidebar's inner width in equal halves, a
  `--space-2` gap between them, and every button of the sidebar (the menu's Links, NanoURLs and QR codes, and the two
  glyphs) is one family, with one style per state, from existing tokens only: at rest `--surface-raised` background,
  `--line-strong` border, `--radius-md`, `--ink-soft` text; under the pointer `--line` background, `--faint` border,
  `--ink` text; the current page (a menu item, or the gear while Settings is open) filled with an accent tint
  (`color-mix` of 16% `--accent` into `--surface-raised`), its border 45% `--accent` into `--line-strong`, its text
  `--accent`, unchanged under the pointer; keyboard focus the shell's ring on every button, 2px of `--focus-ring` drawn
  2px outside the border. The current page is a fill inside the border, the focus a line with a gap outside it, so the
  two cannot be mistaken, even on the same button. The menu's items keep their icon and label, a `--space-2` gap
  between them. Chosen: the full width, a background and a hover colour on the foot, then the menu's
  items matching it and one focus style (9.3.0's gear showed the current page as an accent border, read as a
  second focus ring). Goldens `frame-foot-hover`, `frame-foot-keyboard-focus` (gear current, Log out focused; was
  `frame-foot-focus`), `frame-nav-hover` and `frame-nav-keyboard-focus` (the current item focused) pin the states.
  The foot sticks to the bottom of the window while a long page scrolls, so a full-page golden shows it where the
  window ended. The word Administration is gone from the interface: the Settings page (`FOOT` in `shell.js`, found by
  `findRoute`, with no label) is headed by its title alone, its eyebrow empty but keeping its line, so the title does
  not move between pages. The text button **Log out** is gone.
- **Glyphs**: Material Symbols Outlined `settings` and `logout`, weight 400, fill 0, grade 0, from the npm package
  `@material-symbols/svg-400` 0.48.3 (the latest release at least two weeks old; 0.49.0 was twelve days old), its files
  `outlined/settings.svg` and `outlined/logout.svg`, path data copied as it is into `GLYPH` in `static/ui/icons.js` with
  its source line, and the package's Apache-2.0 licence in `static/ui/LICENSE-material-symbols.txt`. The package ships
  one optical size, 48, not 24, whose strokes are thin at small sizes: drawn at the stroked icons' 18 px they read
  smaller and lighter than them, so they are drawn at 20 px, which brings their shape and stroke to the weight of the
  18 px stroked icons (in their 44 px buttons). `glyphNode` draws them filled with `currentColor`, no stroke, in their
  own `0 -960 960 960` box; the stroked icons and `iconNode` are unchanged, and an unknown glyph throws instead of
  standing in for another.
- **Why**: the two jobs as icons at the foot of the sidebar, and missing icons from
  Google Material Symbols, the family of the fonts' source. Vendoring two paths keeps the page free of any font or
  network load (`img-src`, `font-src` unchanged).
- **Undo**: put `{ path: '/admin/settings', label: 'settings.page', icon: 'instance', page: settings }` back in `NAV`
  under a `cloudflare.section` label (`"Administration"` back in `en.json`), drop the `#page-section:empty` rule, drop
  `FOOT`, `renderFoot` and the foot of `templates/app.html` for the old `btn nav-logout` button (its rule back in
  `components.css`), and drop `GLYPH`, `glyphNode`, the licence file and the foot's rules in `redirect.css`. To undo
  only 9.3.1's buttons, put back 9.3.0's `.nav-foot` and `.nav-icon` rules (transparent 44 px squares at the bottom-left),
  drop the shared `.nav-item, .nav-icon` rules and the `.nav-section` gap from `redirect.css` (the kit's flat menu items
  come back), and drop the hover and keyboard-focus captures from `walk_frame.py` and their goldens.

## D31 · AGPL-3.0-or-later, and a SiteLuna guide checked by SiteLuna's own checker

- **What**: the repository is licensed AGPL-3.0-or-later: `LICENSE` holds the FSF's text unmodified, the README names
  the licence by its SPDX id and its copyright holder, and lists the bundled third-party licences (OFL fonts,
  Apache-2.0 Material Symbols). `app.py`, the main source file, opens with the copyright line and the SPDX id; the
  ported front files keep their `Source:` first line instead. The user guide lives in `wiki/guide/{fr,en}` in the
  format of SiteLuna, the site that publishes this guide, French as the reference, with
  `wiki/index.md` leading into both languages and `wiki/guide/mark.svg` a byte copy of `static/mark.svg`.
  `tools/guide_check.py` is SiteLuna's checker (format 1, SHA-256 `d74b84b0…`), vendored byte for byte and excluded
  from ruff; `just guide-check` runs it in the pinned Python image with its pinned Markdown, and `just ci` runs that.
  The private word list is read from `GUIDE_CHECK_PRIVATE_WORDS_FILE` or the git-ignored
  `.guide-check-private-words`, never committed; without it the checker says that check did not run.
  `tests/test_guide.py` holds the checker's and the licence's digests, the mark, the page sets and the status.
- **Why**: the repository goes public, and the site that publishes the guide refuses what its checker refuses: the
  same file, run at the gate, catches it before a merge. A copy rather than a rewrite keeps one judge of the format.
- **Undo**: drop `wiki/guide`, `wiki/index.md`, `tools/guide_check.py`, `tests/test_guide.py`, the `guide-check`
  recipe and its place in `ci`, the ruff exclude and the ignore line; the licence goes only with every contributor's
  agreement.

## D32 · No real host's address in the repository, whatever its digits

- **What**: `tests/test_no_private_addresses.py` reads every text file of the repository (local data, caches and the
  git-ignored files left out), folds it through NFKC and `unicodedata.digit`, and refuses any IPv4 address that is
  not a documentation range (RFC 5737), loopback, link-local, multicast, reserved, benchmarking or unspecified, a
  network constant (a network address with a prefix of 16 bits or less, such as an RFC 1918 block), a well-known
  public service the webhook guard's tests name, or one of the tests' few LAN stand-ins. Examples use
  `192.0.2.0/24`, `198.51.100.0/24` and `203.0.113.0/24`.
- **Why**: the repository is public, and an example or a fixture copied from a real setup would publish that
  network's addresses. Folding the digits first means an address spelled in full-width or Arabic-Indic digits, which
  a plain text search reads past, is caught too. The guide checker (D31) holds its own private list, but it reads the
  guide only and is vendored unchanged, so this check lives in the tests.
- **Undo**: drop the test file.

## D33 · `just ci` is the only CI: no hosted pipeline

- **What**: the merge gate is a green `just ci`, run locally: `just lint`, `just guide-check`, `just compose-check`
  (D34), `just test`, `just test-js` and `just goldens-check`. The repository carries no hosted pipeline file of any forge and needs no
  hosted runner.
- **Why**: the hosted job ran a subset of `just ci` (no guide check, no goldens) on another platform, so a green job
  proved less than the gate already run before every merge, and kept a second copy of the steps to hold in step. One
  command, the same for everyone, is the whole check.
- **Undo**: add a hosted job that runs `just ci` itself, on an arm64 runner with Docker, so the goldens match (D19).

## D34 · Two ways to deploy, Docker Compose or just, and no published image

- **What**: no image is published on any registry. `compose.yml` builds the image from the repository (`build: .`,
  tagged `MOONIE_REDIRECT_IMAGE`, `moonie-redirect:local` by default), every variable it reads has a default but the
  public address, and the secret files sit in `MOONIE_REDIRECT_SECRETS_DIR` (`./secrets` by default). The guide and
  the README offer two ways: plain `docker compose up -d --build` (or a Portainer stack), and `just run`, which runs
  the same command. just is otherwise the contributors' tool. In Portainer the image is built on the host first, and
  the stack is added with the web editor, its `build: .` line dropped and the secrets' folder given as an absolute
  path. `just compose-check`, in `just ci`, runs `docker compose config` with only the public address set, and
  `tests/test_compose.py` pins the rest.
- **Why**: the owner chose not to publish images, and someone deploying with Docker Compose or Portainer should not
  need just. Portainer documents building from a Git stack as not fully implemented and build steps as failing on
  remote environments, and resolves a Git stack's relative paths only in its Business Edition: an image built on the
  host and absolute secret paths are what works in its Community Edition.
- **Undo**: drop `build: .` and the secrets' folder variable from `compose.yml`, the `compose-check` recipe and
  `tests/test_compose.py`, and point the guide back to `just run` alone.

## D35 · 9.4.0: LAN mode by default, the reverse proxy as an overlay

- **What**: `compose.yml` alone is LAN mode: it publishes the app's port on the host,
  `${MOONIE_REDIRECT_BIND:-0.0.0.0}:${MOONIE_REDIRECT_PORT:-8080}:8080`, and names no network, so a plain
  `docker compose up -d --build` runs with nothing made beforehand, in plain http on the host's address. Reverse-proxy
  mode is `compose.proxy.yml`, laid over it (`docker compose -f compose.yml -f compose.proxy.yml up -d --build`, or
  `just run-proxy`): it drops the published port (`ports: !reset []`), joins the proxy's external network under the
  alias `moonie-redirect`, and carries Traefik labels as the example, its host required (`MOONIE_REDIRECT_HOST`). Any
  other proxy is pointed at `moonie-redirect:8080` on that network, or at `127.0.0.1:8080` with LAN mode bound to
  loopback when it runs on the host. `just compose-check` checks both modes, and that the first publishes 8080 and the
  second nothing. The app itself changes nothing: the session cookie is already `Secure` only on an `https` public
  base URL, a missing `Sec-Fetch-Site` (what a browser sends from an insecure context) already passes like an old
  browser's, links never come from the request's host, and no HSTS header is sent; `tests/test_lan_mode.py` pins a
  full login, a create and the links followed over http on an IP, and that https keeps its Secure cookie.
- **Why**: the owner wants Redirect on a LAN IP with no reverse proxy as a first-class mode. Before, a plain
  `docker compose up` stopped on the missing external `proxy` network and published no port. An overlay keeps the
  proxy setup one flag away without a second copy of the service. LAN mode is plain http, so the guide and the README
  say it is meant for a trusted LAN.
- **Undo**: put the `proxy` network, the commented labels and a commented `ports` line back in `compose.yml`, drop
  `compose.proxy.yml`, `just run-proxy`, the second check of `just compose-check` and `tests/test_lan_mode.py`, and
  point the guide back to the single path.

## D36 · The guide's screenshots are the goldens, copied byte for byte

- **What**: the guide shows 13 screenshots of the admin, all on one page, `usage.md` ("Usage" / "Utilisation"), a
  walk through the screens in order; the other pages carry no image, only a link to it. Each image in
  `wiki/guide/img` is a byte copy of a full 1440-pixel golden from `tests/goldens`, mapped in `tools/guide_images.py`
  (`IMAGES`). `just guide-images` copies them, `just goldens` runs that copy after every capture, and
  `just guide-images-check` (in `just ci`, with `tests/test_guide_images.py` in `just test`) fails when an image
  differs from its golden, is missing or unmapped, has a name SiteLuna refuses, weighs over 2,000,000 bytes, or is not
  shown by a page in both `fr` and `en`.
- **Why**: the goldens are already deterministic, made of invented fixture data, and checked byte for byte, so a copy
  needs no capture of its own and cannot drift from the UI it shows. SiteLuna opens guide images in a full-screen
  viewer, so the full screens are kept uncropped. One page keeps the screenshots together, as the owner asked, and
  leaves the reference pages as text.
- **Undo**: drop `wiki/guide/img`, both `usage.md` pages and their lines in `index.md` and `getting-started.md` (and
  shift the pages' `order` back down by one), `tools/guide_images.py`, `tests/test_guide_images.py`, the
  `guide-images` and `guide-images-check` recipes, the copy at the end of `just goldens`, and the `img` exception in
  `tests/test_guide.py`.
