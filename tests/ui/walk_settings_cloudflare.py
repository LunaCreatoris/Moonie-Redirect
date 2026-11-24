"""The domains of Settings > Cloudflare, the Cloudflare page up to 9.2 (D29): the states of the Cloudflare plugin's
walks that 9.1.0 keeps (setup, domains, quota, resync), on the in-memory fake of the tests, never the real API, captured
inside the tab. Its Links, NanoURLs and QR codes tabs and its held hosts are gone: a link carries its address in the
Redirect pages (walk_address.py). The token's own states are walk_settings.py's; the tab's loading and error states
are the Settings page's own, so they are checked here and not captured again."""

import re
import sqlite3
import sys

from kit import ROOT, Live, dialog, held, moment, running, state, until_held, window_at_bottom
from playwright.sync_api import expect

sys.path.insert(0, str(ROOT / "tests"))

from fake_cloudflare import FakeCloudflare  # noqa: E402

import app as redirect  # noqa: E402

PAGE = "/admin/settings?tab=cloudflare"
# The old page's address, which bookmarks still hold
OLD_PAGE = "/admin/cloudflare"
GO, WWW = "go.example.com", "www.example.com"
WIKI = "Wikipedia (HTTP 404)"


def world() -> tuple[FakeCloudflare, str, str]:
    """One account and its zone, no list or rule yet: a proxied site at www, a record that is not proxied at link."""
    fake = FakeCloudflare()
    account = fake.add_account("Main account")
    zone = fake.add_zone("example.com", account)
    fake.add_record(zone, "A", WWW, "203.0.113.7")
    fake.add_record(zone, "A", "link.example.com", "203.0.113.8", proxied=False)
    return fake, account, zone


def notice(page):
    return page.locator("#page .cf-notice")


def recheck_token(live: Live) -> None:
    """The token is checked again at the next load, as ten minutes later."""
    live.app.extensions["sync"]._token = None


def write(live: Live, statement: str, *args) -> None:
    with sqlite3.connect(live.db) as conn:
        conn.execute(statement, args)
    conn.close()


def off(live: Live) -> None:
    """A bookmark of the old page lands on the tab, once; Cloudflare off points at the token's row above it. The screen
    is settings-cloudflare-missing's, so it is not captured again."""
    page = live.page
    live.log_in()
    live.open(OLD_PAGE)
    expect(page).to_have_url(f"{live.base}{PAGE}")
    expect(page.locator(".nav-icon[aria-current='page']")).to_have_attribute("aria-label", "Settings")
    expect(page.locator("#page [role='tab'][aria-selected='true']")).to_have_text("Cloudflare")
    expect(page.locator(".nav-item", has_text="Cloudflare")).to_have_count(0)
    expect(page.locator("#page .cf-off .state-title")).to_have_text("Cloudflare is off")
    page.locator("#page .cf-to-token").click()
    expect(page.locator("#page .settings-token input[name='token']")).to_be_focused()
    expect(page).to_have_url(f"{live.base}{PAGE}")
    # Back leaves the tab for the page before it: the old address is no entry of the history
    page.go_back()
    expect(page).to_have_url(f"{live.base}/admin/links")
    state(page, "loaded")
    # An entry of the history the server never saw again, such as a tab kept open across the update, goes there too
    page.evaluate(
        "() => { history.pushState(null, '', '/admin/cloudflare?keys=1');"
        " dispatchEvent(new PopStateEvent('popstate')) }"
    )
    expect(page).to_have_url(f"{live.base}/admin/settings?keys=1&tab=cloudflare")
    state(page, "loaded")
    expect(page.locator("#page [role='tab'][aria-selected='true']")).to_have_text("settings.tab_cloudflare")


def loading_and_error(live: Live) -> None:
    """The tab reads the domains with its settings: it waits on both, and fails as the Settings page does."""
    page = live.page
    pattern = re.compile(r".*/api/cloudflare$")
    stopped = held(page, pattern)
    page.goto(PAGE)
    state(page, "loading")
    until_held(page, stopped)
    stopped[0].fulfill(status=500, content_type="application/json", body='{"error": "internal"}')
    state(page, "error")
    expect(page.locator("#page .state-request")).to_have_text("GET /api/cloudflare → 500")
    page.unroute(pattern)


def new_host(live: Live) -> None:
    page = live.page
    live.open(PAGE)
    expect(page.locator("#page .cf-none")).to_have_text("No host yet. Add one, then give it to links as their address.")
    live.shot("domains-empty")

    page.locator("#page .cf-new-host").click()
    box = dialog(page)
    expect(box.locator(".cf-proposal")).to_have_count(3)
    expect(box.locator(".cf-proposal-off .cf-proposal-name")).to_have_text("link.example.com")
    live.shot("new-host", full_page=False)

    box.locator(".cf-proposal input[value='go']").check()
    expect(box.locator(".cf-steps li")).to_have_count(3)
    expect(box.locator(".dialog-actions .btn-accent")).to_be_enabled()
    live.shot("plan-bootstrap", full_page=False)

    box.locator("select[name='fallback']").select_option("wikipedia")
    expect(box.locator(".cf-steps li")).to_have_count(4)
    live.shot("plan-page-chosen", full_page=False)

    # A page on the very host being set up would send its unknown paths round in a loop
    box.locator("select[name='fallback']").select_option("other")
    box.locator(".cf-fallback-address").fill(f"https://{GO}/lost")
    box.locator(".cf-fallback-address").dispatch_event("change")
    expect(box.locator(".form-error")).to_contain_text("go round in a loop")
    expect(box.locator(".dialog-actions .btn-accent")).to_be_disabled()
    live.shot("plan-page-refused", full_page=False)
    box.locator("select[name='fallback']").select_option("none")

    box.locator("input[name='label']").fill("Go Go")
    box.locator(".cf-show-plan").click()
    expect(box.locator("input[name='label']")).to_have_attribute("aria-invalid", "true")
    live.shot("label-invalid", full_page=False)

    box.locator("input[name='label']").fill("link")
    box.locator(".cf-show-plan").click()
    expect(box.locator(".cf-plan-blocked")).to_be_visible()
    expect(box.locator(".dialog-actions .btn-accent")).to_be_disabled()
    live.shot("plan-conflict", full_page=False)

    box.locator("input[name='label']").fill("www")
    box.locator(".cf-show-plan").click()
    expect(box.locator(".cf-plan-live")).to_be_visible()
    expect(box.locator(".dialog-actions .btn-accent")).to_be_disabled()
    live.shot("plan-live", full_page=False)
    box.locator("input[name='confirm_live']").check()
    expect(box.locator(".dialog-actions .btn-accent")).to_be_enabled()
    live.shot("plan-live-ticked", full_page=False)

    box.locator(".cf-proposal input[value='go']").check()
    box.locator("select[name='fallback']").select_option("wikipedia")
    expect(box.locator(".cf-steps li")).to_have_count(4)
    live.clock = moment(11, 2, 9, 30)
    box.locator(".dialog-actions .btn-accent").click()
    expect(notice(page)).to_have_text(f"{GO} is set up. Links can take it as their address now.")
    expect(page.locator("#page .cf-hosts [role='row']:has([role='cell'])")).to_have_count(1)
    live.shot("host-added")

    # The site already there, adopted: no page for unknown paths
    page.locator("#page .cf-new-host").click()
    box = dialog(page)
    box.locator("input[name='label']").fill("www")
    box.locator(".cf-show-plan").click()
    box.locator("input[name='confirm_live']").check()
    live.clock = moment(11, 3, 8, 0)
    box.locator(".dialog-actions .btn-accent").click()
    expect(page.locator("#page .cf-hosts [role='row']:has([role='cell'])")).to_have_count(2)
    expect(page.locator("#page .cf-fallback-none")).to_be_visible()
    live.shot("hosts")


def fallback(live: Live) -> None:
    page = live.page
    choice = page.locator(f"#page .cf-fallback select[data-host='{GO}']")
    choice.select_option("other")
    address = page.locator(f"#page .cf-fallback-address[data-host='{GO}']")
    expect(address).to_be_focused()
    address.fill(f"http://{WWW}")
    live.shot("fallback-other")

    page.locator(f"#page .cf-fallback-save[data-host='{GO}']").click()
    expect(notice(page)).to_have_class(re.compile("cf-notice-error"))
    expect(address).to_have_attribute("aria-invalid", "true")
    live.shot("fallback-other-refused")

    choice.select_option("google")
    expect(notice(page)).to_have_text(f"The unknown paths of {GO} will go to Google (home page) after the next sync.")
    live.shot("fallback-changed")

    choice.select_option("none")
    expect(notice(page)).to_have_text(f"{GO} has no page for unknown paths any more: its item goes with the next sync.")
    live.shot("fallback-none")
    choice.select_option("wikipedia")
    expect(notice(page)).to_contain_text(WIKI)


def synced(live: Live) -> None:
    page = live.page
    sync = live.app.extensions["sync"]
    for _ in range(4):
        sync.run_pass()
    live.open(PAGE)
    expect(page.locator("#page .cf-quota")).to_have_text("Main account: 1 of 10,000 items")
    page.locator("#page .cf-sync").click()
    expect(notice(page)).to_have_text("Sync started. Links in error are tried again.")
    live.shot("sync-now")


def token_states(live: Live, fake: FakeCloudflare) -> None:
    page = live.page
    fake.token_status = "disabled"
    recheck_token(live)
    live.open(PAGE)
    expect(page.locator("#page .cf-token")).to_have_text("Token refused")
    expect(page.locator("#page .cf-new-host")).to_be_disabled()
    expect(page.locator("#page .cf-quota")).to_have_count(0)
    live.shot("token-invalid")

    fake.token_status = "active"
    fake.fault("timeout", path="^/user/tokens/verify$", times=8)
    recheck_token(live)
    live.open(PAGE)
    expect(page.locator("#page .cf-token")).to_have_text("Token not checked")
    live.shot("token-unchecked")
    fake._faults.clear()

    fake.denied = {"dns"}
    recheck_token(live)
    live.open(PAGE)
    expect(page.locator("#page .cf-token")).to_have_text("Permissions missing")
    # From the token file, where settings-cloudflare-permissions-missing has it set here
    live.shot("token-permissions-missing")
    fake.denied = set()
    recheck_token(live)


def quota_and_errors(live: Live, account: str) -> None:
    page = live.page
    write(live, "UPDATE cf_accounts SET items_used = 9100 WHERE id = ?", account)
    live.open(PAGE)
    expect(page.locator("#page .cf-banner-warning")).to_contain_text("uses 9,100 of its 10,000 list items")
    live.shot("quota-near")

    write(live, "UPDATE cf_accounts SET items_used = 10000 WHERE id = ?", account)
    live.open(PAGE)
    expect(page.locator("#page .cf-banner-danger")).to_contain_text("uses all 10,000 of its list items")
    live.shot("quota-full")
    write(live, "UPDATE cf_accounts SET items_used = 1 WHERE id = ?", account)

    error = redirect.error_text("unreachable", "timeout")
    write(live, "UPDATE cf_accounts SET last_error = ? WHERE id = ?", error, account)
    live.open(PAGE)
    expect(page.locator("#page .cf-banner-danger")).to_contain_text("The last sync of Main account failed.")
    live.shot("account-error")
    write(live, "UPDATE cf_accounts SET last_error = NULL WHERE id = ?", account)

    origin = redirect.error_text("origin_live")
    write(live, "UPDATE cf_hosts SET fallback_state = 'error', fallback_error = ? WHERE host = ?", origin, GO)
    live.open(PAGE)
    expect(page.locator("#page .cf-fallback-blocked")).to_be_visible()
    live.shot("hosts-live")
    write(live, "UPDATE cf_hosts SET fallback_state = 'active', fallback_error = NULL WHERE host = ?", GO)


def resync(live: Live, fake: FakeCloudflare, account: str) -> None:
    page = live.page
    live.open(PAGE)
    page.locator("#page .cf-resync").click()
    expect(notice(page)).to_have_text("Cloudflare holds exactly what this instance holds.")
    live.shot("resync-clean")

    live.clock = moment(11, 3, 9, 0)
    live.add({"slug": "promo", "name": "Promo", "target": "https://shop.example/", "address": GO, "at": live.clock})
    live.add({"slug": "menu", "name": "Menu", "target": "https://cafe.example/", "address": GO, "at": live.clock})
    sync = live.app.extensions["sync"]
    for _ in range(4):
        sync.run_pass()
    list_id = next(iter(fake.state.lists[account]))
    items = fake.sources(account, list_id)
    del fake.state.lists[account][list_id]["items"][items[f"{GO}/promo"]["id"]]
    items[f"{GO}/menu"]["redirect"]["target_url"] = "https://old-menu.example/"
    fake.add_item(account, list_id, f"{GO}/left-behind", "https://elsewhere.example/")
    # One of ours whose link is gone here, so the "Made by this app" badge is pinned beside the foreign one
    install = live.app.extensions["store"].install_id()
    fake.add_item(account, list_id, f"{GO}/gone", "https://gone.example/", comment=f"moonie:{install}:gone1234")
    live.open(PAGE)
    page.locator("#page .cf-resync").click()
    box = dialog(page)
    expect(box.locator(".cf-tick")).to_have_count(4)
    expect(box.locator(".cf-tick", has_text="/gone")).to_contain_text("Made by this app")
    window_at_bottom(page)
    live.shot("resync-gaps", full_page=False)

    box.locator(".cf-tick", has_text="left-behind").locator("input").check()
    box.locator(".dialog-actions .btn-accent").click()
    expect(dialog(page).locator(".card-title")).to_have_text("Remove 1 item from Cloudflare?")
    live.shot("resync-remove-confirm", full_page=False)
    dialog(page).locator(".btn-danger").click()
    expect(notice(page)).to_have_text("2 sent again, 1 removal(s) on their way.")
    live.shot("resync-applied")


def walk(live: Live) -> None:
    off(live)
    fake, account, _zone = world()
    with running(live.browser, live.playwright, live.run, live.walk, cloudflare=fake) as on:
        on.log_in()
        loading_and_error(on)
        new_host(on)
        fallback(on)
        synced(on)
        token_states(on, fake)
        quota_and_errors(on, account)
        resync(on, fake, account)
