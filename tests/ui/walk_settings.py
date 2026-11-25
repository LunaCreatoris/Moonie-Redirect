"""The Settings page: its three tabs (Security, Webhook & API, Cloudflare) and every state of their cards and dialogs.
The domains under the Cloudflare settings have their own walk, walk_settings_cloudflare.py.

The webhook reaches a receiver on loopback through the Webhook constructor's resolver and allow-list, as its tests
do: `receiver:8080` resolves to that receiver, so the address on screen never shows its free port. Cloudflare is the
in-memory fake of the tests. The new key's secret and every id are fixed, and the clocks are the walk's, so two runs
write the same bytes. Rows no screen can make (a delivery that failed, a webhook a 410 turned off, a token sealed under
another key) are written as fixtures."""

import json
import re
import socket
import sqlite3
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from kit import PASSWORD, ROOT, Live, dialog, held, moment, running, state, until_held, window_on
from playwright.sync_api import expect

sys.path.insert(0, str(ROOT / "tests"))

from fake_cloudflare import FakeCloudflare  # noqa: E402

import app as redirect  # noqa: E402

PAGE = "/admin/settings"
NEW_PASSWORD = "a much longer admin password"
HOOK_URL = "http://receiver:8080/test-hook"
HOOK_SECRET = "receiver-shared-signing-secret"
CF_TOKEN = "settings-token-abcdefghijklmnopqrstuvwxyz0123"
# What `new_api_key` draws in this walk: the secret is shown once, so it must read the same on every run
KEY_SECRET = "mrk_G0ldenKeyShownOnceAbcdefghijklmnopqrstuvwxy"
# The webhook's clock: when a test or a delivery is said to have run
HOOK_TIME = datetime(2026, 11, 3, 11, 45, tzinfo=UTC)
FAILED_DELIVERY = {
    "event_id": "evt_6c1f0a9e2b7d4c3a8e5f1b0d9c2a7e44",
    "event": "redirect.link.updated",
    "status": 503,
    "at": "2026-11-03T11:40:00Z",
    "error": None,
}


# --- Fakes ------------------------------------------------------------------------------------------------------------


class Receiver:
    """A webhook receiver on loopback: answers each POST with `status`, a JSON body when it is a 2xx."""

    def __init__(self) -> None:
        self.status = 200
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = b'{"ok": true}' if 200 <= receiver.status < 300 else b""
                self.send_response(receiver.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def resolve(self, host, port, type=0, **_kwargs):
        """Every name is the receiver, whatever port the URL says: the screen keeps the URL's address."""
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", self.server.server_address[1]))]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class Ticks:
    """A monotonic clock that moves 7 ms each time it is read: a test always lasts the same number of readings."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        self.now += 0.007
        return self.now


class Factory:
    """What makes a client of a token set in the settings: the fake with one account. `refuse` makes Cloudflare say the
    token is not active; `denied` takes permissions away."""

    def __init__(self) -> None:
        self.refuse = False
        self.denied: set[str] = set()

    def __call__(self, token: str) -> FakeCloudflare:
        fake = FakeCloudflare(token)
        fake.setup()
        fake.denied = set(self.denied)
        if self.refuse:
            fake.token = "another-token-entirely"
        return fake


def webhook_options(receiver: Receiver) -> dict:
    def build(store, secrets):
        return redirect.Webhook(
            store,
            secrets,
            resolver=receiver.resolve,
            allow=("127.0.0.0/8",),
            clock=lambda: HOOK_TIME,
            monotonic=Ticks(),
        )

    return {"webhook": build}


# --- Fixtures written in the database ---------------------------------------------------------------------------------


def write_setting(live: Live, key: str, value: str) -> None:
    with sqlite3.connect(live.db) as conn:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value, live.clock),
        )
    conn.close()


def drop_setting(live: Live, key: str) -> None:
    with sqlite3.connect(live.db) as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    conn.close()


def waiting_rows(live: Live, count: int) -> None:
    """Deliveries waiting for their next attempt, as a receiver that answers 503 leaves them."""
    with sqlite3.connect(live.db) as conn:
        for index in range(count):
            conn.execute(
                "INSERT INTO webhook_outbox (id, event, body, created_at, status, attempts, next_attempt_at,"
                " last_status) VALUES (?, 'redirect.link.updated', '{}', ?, 'pending', 1, ?, 503)",
                (f"evt_{index:032d}", "2026-11-03T11:40:00Z", "2026-11-03T11:50:00Z"),
            )
    conn.close()


def sealed_elsewhere(db: Path) -> None:
    """A Cloudflare token sealed under a store key this run does not have: a database restored without its key."""
    store = redirect.Store(db)
    store.write_sealed(redirect.SecretBox(bytes(range(32))), "cloudflare_token", CF_TOKEN)


# --- The page ---------------------------------------------------------------------------------------------------------


def notice(page):
    return page.locator("#page .redirect-notice")


def tab(page, name: str):
    return page.locator("#page [role='tab']", has_text=name)


def field_error(scope, name: str):
    return (
        scope.locator(f"[name='{name}']")
        .locator("xpath=ancestor::*[contains(concat(' ', @class, ' '), ' field ')][1]")
        .locator(".field-error")
    )


def no_failed_login() -> None:
    """The login brake is the process's: a check the walk failed on purpose must not hold the next one a second."""
    redirect._last_failure = float("-inf")


def loading_and_error(live: Live) -> None:
    page = live.page
    pattern = re.compile(r".*/api/settings/security$")
    stopped = held(page, pattern)
    page.goto(PAGE)
    state(page, "loading")
    until_held(page, stopped)
    live.shot("loading")
    stopped[0].fulfill(status=500, content_type="application/json", body='{"error": "internal"}')
    state(page, "error")
    expect(page.locator("#page .state-request")).to_have_text("GET /api/settings/security → 500")
    live.shot("load-error")
    page.unroute(pattern)


def security(live: Live) -> None:
    page = live.page
    live.open(PAGE)
    expect(page.locator(".nav-icon[aria-current='page']")).to_have_attribute("aria-label", "Settings")
    expect(page.locator("#page .instance-origin-chip")).to_have_text("From file")
    live.shot("security-file")

    page.locator("#page .instance-password").click()
    box = dialog(page)
    expect(box.locator("input[name='password']")).to_be_visible()
    live.shot("password-dialog", full_page=False)

    box.locator("input[name='password']").fill("not the password at all")
    box.locator("input[name='new_password']").fill(NEW_PASSWORD)
    box.locator("input[name='new_password_confirm']").fill(NEW_PASSWORD)
    box.locator("[type='submit']").click()
    expect(field_error(box, "password")).to_have_text("Wrong password. Try again.")
    no_failed_login()
    live.shot("password-errors", full_page=False)

    box.locator("input[name='password']").fill(PASSWORD)
    box.locator("[type='submit']").click()
    expect(dialog(page)).to_have_count(0)
    expect(notice(page)).to_have_text("Password changed. Every other session has ended.")
    expect(page.locator("#page .instance-origin-chip")).to_have_text("Set here")
    live.shot("password-done")

    live.open(PAGE)
    expect(notice(page)).to_be_hidden()
    live.shot("security")

    page.locator("#page .instance-end").click()
    expect(dialog(page).locator(".card-title")).to_have_text("End all sessions?")
    live.shot("end-sessions-confirm", full_page=False)
    dialog(page).locator(".btn:not(.btn-danger)").click()
    expect(dialog(page)).to_have_count(0)


def webhook(live: Live, receiver: Receiver) -> None:
    page = live.page
    tab(page, "Webhook & API").click()
    expect(page).to_have_url(re.compile(r"\?tab=webhook$"))
    state(page, "loaded")
    expect(page.locator("#page .webhook-empty .state-title")).to_have_text("Webhook not configured")
    expect(page.locator("#page .keys-empty-title")).to_have_text("No API keys")
    live.shot("webhook-empty")
    live.shot("keys-empty", full_page=False)

    page.locator("#page .webhook-configure").click()
    expect(page.locator("#page input[name='url']")).to_be_focused()
    live.shot("webhook-form")

    form = page.locator("#page .webhook-form")
    form.locator("input[name='url']").fill("http://169.254.169.254/latest/meta-data")
    form.locator("input[name='secret']").fill(HOOK_SECRET)
    for box in form.locator("input[data-event]").all():
        box.check()
    form.locator("[type='submit']").click()
    expect(field_error(form, "url")).to_be_visible()
    live.shot("webhook-url-closed")

    form.locator("input[name='url']").fill(HOOK_URL)
    form.locator("[type='submit']").click()
    expect(page.locator("#page .webhook-result")).to_contain_text("Saved")
    expect(page.locator("#page .webhook-secret-state")).to_have_text("Secret set")
    live.shot("webhook-saved")

    page.locator("#page .webhook-test").click()
    expect(page.locator("#page .webhook-result")).to_contain_text("Test delivered")
    live.shot("webhook-test-ok")

    receiver.status = 503
    page.locator("#page .webhook-test").click()
    expect(page.locator("#page .webhook-result")).to_contain_text("Test failed")
    expect(page.locator("#page .webhook-result")).to_contain_text("503")
    live.shot("webhook-test-failed")
    receiver.status = 200

    write_setting(live, redirect.SETTING_LAST, json.dumps(FAILED_DELIVERY))
    waiting_rows(live, 2)
    live.open(f"{PAGE}?tab=webhook")
    expect(page.locator("#page .webhook-delivery")).to_contain_text("503")
    expect(page.locator("#page .webhook-waiting")).to_contain_text("2")
    live.shot("webhook-last-failed")

    write_setting(live, redirect.SETTING_DISABLED, "gone")
    live.open(f"{PAGE}?tab=webhook")
    expect(page.locator("#page .webhook-disabled-title")).to_have_text("Webhook disabled")
    live.shot("webhook-disabled")
    drop_setting(live, redirect.SETTING_DISABLED)
    live.open(f"{PAGE}?tab=webhook")


def keys(live: Live) -> None:
    page = live.page
    page.locator("#page .keys-new").click()
    box = dialog(page)
    box.locator("input[name='name']").fill("automation")
    box.locator(".keys-scope", has_text="redirect:links.write").click()
    box.locator(".keys-scope", has_text="redirect:qrcodes.read").click()
    expect(box.locator("input[name='scopes']")).to_have_value("redirect:links.write, redirect:qrcodes.read")
    live.shot("keys-new", full_page=False)

    box.locator("input[name='password']").fill("not the password at all")
    box.locator("[type='submit']").click()
    expect(field_error(box, "password")).to_have_text("Wrong password. Try again.")
    no_failed_login()
    live.shot("keys-new-wrong-password", full_page=False)

    box.locator("input[name='password']").fill(NEW_PASSWORD)
    box.locator("[type='submit']").click()
    expect(box.locator(".keys-secret")).to_have_text(KEY_SECRET)
    live.shot("keys-secret", full_page=False)

    box.locator(".keys-done").click()
    expect(dialog(page)).to_have_count(0)
    expect(notice(page)).to_have_text("Key automation created.")

    row = page.locator("#page .keys-card [role='row']:has([role='cell'])", has_text="automation")
    row.locator(".btn-danger").click()
    expect(dialog(page).locator(".card-title")).to_have_text("Revoke automation?")
    live.shot("keys-revoke-confirm", full_page=False)
    dialog(page).locator(".btn-danger").click()
    expect(notice(page)).to_have_text("Key automation revoked.")

    page.locator("#page .webhook-clear").click()
    expect(dialog(page).locator(".card-title")).to_have_text("Delete this webhook?")
    live.shot("webhook-clear-confirm", full_page=False)
    dialog(page).locator(".btn-danger").click()
    expect(notice(page)).to_have_text("Webhook deleted.")


def cloudflare(live: Live, factory: Factory) -> None:
    page = live.page
    tab(page, "Cloudflare").click()
    expect(page).to_have_url(re.compile(r"\?tab=cloudflare$"))
    state(page, "loaded")
    token = page.locator("#page .settings-token")
    expect(token.locator(".token-state")).to_have_text("Not set")
    # The domains under the token wait for one (D29)
    expect(page.locator("#page .settings-cf-domains .cf-off .state-title")).to_have_text("Cloudflare is off")
    live.shot("cloudflare-missing")

    factory.refuse = True
    token.locator("input[name='token']").fill(CF_TOKEN)
    token.locator(".token-save").click()
    expect(field_error(token, "token")).to_have_text("Cloudflare does not accept this token. Nothing was stored.")
    live.shot("cloudflare-refused")
    factory.refuse = False

    token.locator(".token-save").click()
    expect(notice(page)).to_have_text("Token saved.")
    expect(token.locator(".token-state")).to_have_text("Set here")
    expect(token.locator(".cf-token")).to_have_text("Token OK")
    # The new token turns the domains on at once, their head leaving the token's check to its row
    expect(page.locator("#page .settings-cf-domains .cf-none")).to_be_visible()
    expect(page.locator("#page .cf-token")).to_have_count(1)
    live.shot("cloudflare-stored")

    token.locator(".token-replace").click()
    expect(token.locator("input[name='token']")).to_be_focused()
    live.shot("cloudflare-replace")

    factory.denied = {"dns"}
    token.locator("input[name='token']").fill(CF_TOKEN)
    token.locator(".token-save").click()
    expect(token.locator(".cf-token")).to_have_text("Permissions missing")
    live.shot("cloudflare-permissions-missing")
    factory.denied = set()

    token.locator(".token-clear").click()
    expect(dialog(page).locator(".card-title")).to_have_text("Clear the API token?")
    live.shot("cloudflare-clear-confirm", full_page=False)
    dialog(page).locator(".btn-danger").click()
    expect(token.locator(".token-state")).to_have_text("Not set")

    limit = page.locator("#page .settings-limit-form")
    limit.locator("input[name='value']").fill("0")
    limit.locator(".settings-limit-save").click()
    expect(field_error(limit, "value")).to_be_visible()
    window_on(limit)
    live.shot("cloudflare-limit-error")

    limit.locator("input[name='value']").fill("25000")
    limit.locator(".settings-limit-save").click()
    expect(notice(page)).to_have_text("Item limit saved.")
    live.shot("cloudflare-limit-saved")


def from_files(live: Live) -> None:
    """The token file and the API token file in force, and a key made here already used once."""
    page = live.page
    store = live.app.extensions["store"]
    live.clock = moment(10, 20, 9, 15)
    made = store.add_api_key(
        "Automation", ["redirect:links.read", "cloudflare:read"], redirect.key_digest(KEY_SECRET), KEY_SECRET[:8]
    )
    store.touch_api_key(made["id"], moment(11, 2, 18, 5))
    live.clock = moment(11, 3, 7, 30)
    live.call("GET", "/api/status", status=200)
    live.log_in()
    live.open(f"{PAGE}?tab=webhook")
    expect(page.locator("#page .keys-file")).to_have_text("Token file")
    live.shot("keys-list")

    live.open(f"{PAGE}?tab=cloudflare")
    token = page.locator("#page .settings-token")
    expect(token.locator(".token-state")).to_have_text("From file")
    expect(token.locator(".cf-token")).to_have_text("Token OK")
    live.shot("cloudflare-file")


def unreadable(live: Live) -> None:
    page = live.page
    live.log_in()
    live.open(f"{PAGE}?tab=cloudflare")
    expect(page.locator("#page .settings-token .token-state")).to_have_text("Cannot be read")
    live.shot("cloudflare-unreadable")


def walk(live: Live) -> None:
    # The run of the frame has the token file: this walk opens its own runs, each with what its screens need
    drawn = redirect.new_api_key
    redirect.new_api_key = lambda: KEY_SECRET
    receiver = Receiver()
    factory = Factory()
    no_token = {"MOONIE_REDIRECT_API_TOKEN_FILE": ""}
    try:
        live.log_in()
        loading_and_error(live)
        with running(
            live.browser,
            live.playwright,
            live.run,
            live.walk,
            env=no_token,
            app_options=webhook_options(receiver) | {"cloudflare_factory": factory},
        ) as bare:
            bare.log_in()
            security(bare)
            webhook(bare, receiver)
            keys(bare)
            cloudflare(bare, factory)
        fake = FakeCloudflare()
        fake.setup()
        with running(live.browser, live.playwright, live.run, live.walk, cloudflare=fake) as files:
            from_files(files)
        with running(
            live.browser, live.playwright, live.run, live.walk, env=no_token, prepare=sealed_elsewhere
        ) as lost:
            unreadable(lost)
    finally:
        redirect.new_api_key = drawn
        receiver.close()
