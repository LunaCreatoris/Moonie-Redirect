# Roadmap

What the earlier app (7.0.1, see the README's History) had and this one left out on purpose, to stay small, and what
is planned. Each one comes back only when a real need asks for it.

- **Removing a Cloudflare host**: 9.1 sets hosts up but never removes one (as the 7.0.1 plugin). To stop using one,
  move its links back to the LAN, set its page for unknown paths to None, wait for the sync, then delete its row from
  `cf_hosts` by hand and its DNS record in Cloudflare.
- **The Cloudflare plugin's held hosts**: 7.0.1's plugin kept hosts saved in several spellings apart; 9.1 folds every
  host once and refuses a collision at import.
- **Extension points in the pages**: 7.0.1's Links page let other add-ons place their own filters, columns and
  buttons in it. This app has no add-ons, so its pages have none.
- **LAN address detection**: 7.0.1 wrote links with the container's LAN address when no public URL was set. 8 requires
  `MOONIE_REDIRECT_PUBLIC_BASE_URL` and never uses the request's host.
- **i18n**: the French translation, the language chip of the admin frame and the language picked from
  `Accept-Language`. 8 and 9 are in English only. The admin pages keep 7.0.1's `t()` calls over one
  `static/ui/en.json`: French comes back as a `fr.json`, the chip, its goldens and the server's own strings.
- **Optimistic concurrency** on updates (`expected_updated_at`, `expected_values`, `409 link_changed`): the last write
  wins, and the admin form has no "changed in another tab" state.
- **Drafts across a login**: 7.0.1 kept what a form held when the session ended, and poured it back after the login.
  9's login is a server page, so the typed text of an expired session is lost (sessions last 12 hours).
- **QR code too long for its link**: 7.0.1 said so under the preview. With a very long public base URL, 9's preview and
  file answer `500` rather than a field error.
- **Login rate limit**: one global brake, an attempt within one second of a failed password check (the login, or a
  check in Settings) is answered `429`; no per-client limit or lockout.
- **Store key rotation**: 9.2 has no command to seal the Cloudflare token and the webhook secret again under a new
  store key. To change the key: stop the app, set the new key, start, and enter both values again in Settings.
- **Webhook delivery log page**: 7.0.1 showed the last delivery only, and so does 9.2 (plus how many events wait). A
  page listing the outbox's rows, with a resend, would come back here.
- **Import of 7.0.1's keys and webhook**: 7.0.1 kept its API keys and its webhook in its encrypted store; `import-v7`
  brings the links and the Cloudflare plugin's state only. Make the keys and set the webhook again in Settings.
- **Webhook events of the base**: 7.0.1's `moonie.instance.started`, `plugin.*` and `key.denied` events, replies
  routed to plugins and incoming `/api/{plugin}/{action}` calls: 9.2 sends the three link events only.
- **Keys made by keys**: 7.0.1's child keys (`parent`, `revoke_children`); 9.2's keys are made by the admin session
  only.
