---
title: Cloudflare
description: Make a link answer on a name in your Cloudflare zones, served by Cloudflare with no request reaching the instance.
order: 4
---

## How it works {#how-it-works}

The instance stays on the local network. With a Cloudflare API token, a link can also answer on a name in your own
zones, such as `https://go.example.test/promo`. Cloudflare serves the redirect itself, with its Bulk Redirects: each
link is one item of a `moonie_redirect` list in the account. The instance's own addresses keep answering for every
link, whatever its Cloudflare address.

Without a token, Cloudflare is off and the address choice does not show in the forms.

## The token {#token}

Create an API token in Cloudflare (My Profile or Manage Account, API Tokens), with these four permissions, on the
account and the zones to use:

- **Account · Account Rule Lists: Write**: creates the `moonie_redirect` list and writes its items;
- **Account · Account Rulesets: Write**: adds the rule that redirects from that list;
- **Zone · Zone: Read**: lists the zones the token sees;
- **Zone · DNS: Write**: creates the record of a new host.

Paste it in **Settings**, tab **Cloudflare**. Cloudflare checks it before it is kept: a refused token is not stored,
and if a permission is missing, the page says which one. It is used at once, with no restart. It is encrypted in the
database with the [store key](getting-started.md#store-key).

The container must reach `api.cloudflare.com` over HTTPS. The app reads no proxy from the environment.

## Add a host {#add-a-host}

Under the token, the tab lists the hosts already set up. **New host** adds one:

1. Choose the zone, for example `example.test`, and the name, for example `go`, for `go.example.test`.
2. **Show the plan** shows what will be done. Nothing changes in Cloudflare before **Confirm the plan**.
3. The plan may create the account's `moonie_redirect` list, add one rule beside the account's own (which stay as they
   are) and create a proxied placeholder record, `A go.example.test → 192.0.2.1`.

A name that already has proxied records is adopted as it is: it may serve a site, and a link put on it would take that
path over. The plan then asks you to tick a confirmation.

A host created here can have a **page for unknown paths**: Wikipedia's 404 page, Google or any other address. Every
path with no link on that host leads there.

Nothing else is ever changed or deleted in Cloudflare: no record, no rule, no list, only the list's items. A host
cannot be removed from here yet; the
[roadmap](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/ROADMAP.md) says how to do it by hand.

## A link's address {#link-address}

Once a host is set up, every link, NanoURL and QR code form has a **Link address** choice: the local network first,
then each host.

- A link on a host answers at `https://go.example.test/<path>`.
- A NanoURL or a QR code answers at `https://go.example.test/<id>`, and the QR code then holds that address.
- The lists show where each link answers and its state: pending, active, error or expired.

A path under `.well-known` is refused on a Cloudflare host: certificates and security contacts are read there.

**Changing the address, changing the path or deleting a link put on a host** stops what was printed or shared with
that address. The pages ask before doing it.

## The sync {#sync}

A background task sends Cloudflare what changed, removes what was deleted, moved or has expired, and only touches the
items marked as its own. An item made by someone else at a link's address is never written over: the link stays in
error.

- **Sync now** tries the links in error again right away.
- **Compare with Cloudflare** lists what Cloudflare lacks, what it holds differently and what matches nothing here,
  and fixes what you tick. Removing an item takes a second confirmation.

## The quota {#quota}

A list holds 10,000 items on the free plan, links and pages for unknown paths together. The page warns from 90 %. At
the limit, a link can no longer take a host of that account: move links back to the local network. If your plan
allows more, set the limit in the same tab.

The details are in the
[Cloudflare](https://github.com/LunaCreatoris/Moonie-Redirect/blob/main/README.md#cloudflare) section of the README.
