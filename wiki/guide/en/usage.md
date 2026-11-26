---
title: Usage
description: A walk through the admin interface, screen by screen: sign in, links, NanoURLs, QR codes, settings and Cloudflare hosts.
order: 2
---

## Sign in {#sign-in}

The links' address followed by `/admin/links` opens the sign-in page. Enter the administrator password: the one set in
Settings, else the one from `secrets/password`. A session lasts 12 hours.

![The sign-in page: a Log in panel with the Password field and the Log in button](../img/sign-in.png)

## The links {#links}

**Links**, in the menu on the left, lists the fixed links, most recently modified first, with their path, name,
target, last day and change date. Choosing a row opens its form on the right; **Copy** copies its address.

![The Links page: four links in the list, and the edit form of /redirect/resume with its name, slug, target URL and expiry](../img/links-list.png)

## A new link {#new-link}

**New link** opens an empty form. A free path is already suggested in **Slug**, and **Random** draws another one. Give
a name and the target, and a last day in **Expiry** if the link must stop. **Save** creates it. See
[A link](links-nanourls-qrcodes.md#a-link).

![The New link form beside the list: an empty name, the suggested slug and its path, the Random button, the target URL and the expiry](../img/link-new.png)

## A link's address {#link-address}

Once a Cloudflare host is set up, the form has a **Link address** choice: the local network or a host. The list shows
where each link answers and its state, here pending, error and active. See
[A link's address](cloudflare.md#link-address).

![The Links page with Cloudflare: each link shows its host and its state, and the form offers the Link address choice with the pending state](../img/link-address.png)

## The NanoURLs {#nanourls}

**NanoURLs** lists the short links: a name and a target each, with the short link `/links/<id>` to share. The form
needs only the name and the target URL.

![The NanoURLs page: three short links in the list, and the edit form of one with its name and target URL](../img/nanourls-list.png)

## A QR code and its design {#qr-code}

**QR codes** lists the codes with a thumbnail, **Copy** and **Download SVG**. The form adds a **Design** part: the
colors of the modules, the corners and the background, their shapes and the margin. The preview above the settings is
drawn again at every change.

![A new QR code: the name, the target URL and the design with its live preview, in blue dots and red circle corners](../img/qrcode-design.png)

## A logo in the center {#qr-logo}

**Choose a file** puts a logo in the center (PNG, JPEG, WebP or SVG, 256 KiB at most); **Logo size** sets how much
room it takes, and the preview shows it at once. See [A QR code](links-nanourls-qrcodes.md#a-qr-code).

![The QR code design with a logo set: the preview shows the logo in the center, with the Remove button and a logo size of 30 %](../img/qrcode-logo.png)

## Settings: Security {#settings-security}

The gear at the bottom left opens **Settings**. The **Security** tab says where the password comes from, how long
sessions last and how many are open, and offers **Change password** and **End all sessions**.

![The Security tab of Settings: the Sign-in panel with the password set here, the session count, Change password and End all sessions](../img/settings-security.png)

## Settings: the webhook {#settings-webhook}

The **Webhook & API** tab holds the receiver's URL, the signing secret and the events to send. **Send test** sends one
test event; **Delivery** shows the last delivery and what waits. See [The webhook](settings.md#webhook).

![The Webhook and API tab: a saved webhook with its URL, the secret set, the three link events ticked, and the Delivery panel](../img/settings-webhook.png)

## Settings: API keys {#settings-api-keys}

Under the webhook, **API keys** lists the keys with their prefix, scopes and last use. **Revoke** ends one at once.

![The API keys list: the token file that allows everything, and an Automation key with two read scopes and its Revoke button](../img/settings-api-keys.png)

**New key** asks for a name, the scopes (the known ones are offered below the field) and your password. The key shows
once, after **Create key**. See [API keys](settings.md#api-keys).

![The New key dialog: the name, the chosen scopes, the known scopes to pick from and the password field](../img/settings-new-key.png)

## Cloudflare hosts {#cloudflare-hosts}

The **Cloudflare** tab holds the API token and its state, the list item limit, **Sync now**, **Compare with
Cloudflare**, and the hosts already set up, with their zone, account, DNS record and page for unknown paths.

![The Cloudflare tab: the token from file and checked, the account's quota, and two hosts in the Hosts list](../img/cloudflare-hosts.png)

**New host** asks for a zone and a name, then shows the plan: what will be done in Cloudflare, step by step. Nothing
changes before **Confirm the plan**; a name that already serves something asks for a tick first. See
[Add a host](cloudflare.md#add-a-host).

![The New host dialog: the zone, the suggested names, the other name www, the plan in four steps, the warning and its ticked confirmation](../img/cloudflare-new-host.png)
