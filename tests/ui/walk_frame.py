"""The frame around the pages: the login in its bare frame and what it says, the menu, the page that does not exist, a
session that ends under a page, and the public answers to a visit."""

import sqlite3

from kit import PASSWORD, Live, running, state
from playwright.sync_api import expect


def login_page(live: Live) -> None:
    page = live.page
    page.goto("/admin/qrcodes?qr=abc")
    expect(page).to_have_url(f"{live.base}/login?next=/admin/qrcodes?qr%3Dabc")
    expect(page.locator(".card-title")).to_have_text("Log in")
    expect(page.locator("input[name='password']")).to_be_focused()
    live.shot("login")

    page.locator("input[name='password']").fill("not the password")
    page.locator(".auth-submit").click()
    expect(page.locator(".field-error")).to_have_text("Wrong password. Try again.")
    live.shot("login-wrong-password")

    # An attempt within a second of a failed one is braked, whatever it holds
    page.locator("input[name='password']").fill(PASSWORD)
    page.locator(".auth-submit").click()
    expect(page.locator(".form-error")).to_have_text("Too many attempts. Try again in 1 s.")
    live.shot("login-braked")

    page.goto("/login?expired=1&next=/admin/nanourls")
    expect(page.locator(".auth-notice")).to_have_text("Your session has ended. Log in again to continue.")
    live.shot("login-expired")
    page.wait_for_timeout(1100)
    page.locator("input[name='password']").fill(PASSWORD)
    page.locator(".auth-submit").click()
    expect(page).to_have_url(f"{live.base}/admin/nanourls")
    state(page, "loaded")


def menu_and_not_found(live: Live) -> None:
    page = live.page
    page.locator("#nav-sections a", has_text="QR codes").click()
    expect(page).to_have_url(f"{live.base}/admin/qrcodes")
    expect(page.locator("#page-title")).to_have_text("QR codes")
    expect(page.locator(".nav-item[aria-current='page']")).to_have_text("QR codes")
    page.go_back()
    expect(page.locator("#page-title")).to_have_text("NanoURLs")

    live.open("/admin/nowhere/at-all", state="not-found")
    expect(page.locator("#page-title")).to_have_text("Page not found")
    expect(page.locator("#page .state-path")).to_have_text("/admin/nowhere/at-all")
    expect(page.locator(".nav-item[aria-current='page']")).to_have_count(0)
    live.shot("not-found")
    page.locator("#page .btn-accent").click()
    expect(page).to_have_url(f"{live.base}/admin/links")
    state(page, "loaded")

    # The sidebar's foot: no settings section in the menu, Settings and Log out as glyphs named for every reader
    expect(page.locator(".nav-section-label")).to_have_text(["Redirect"])
    settings = page.locator("#nav-foot-links .nav-icon")
    expect(settings).to_have_attribute("aria-label", "Settings")
    expect(settings).to_have_attribute("title", "Settings")
    expect(settings).not_to_have_attribute("aria-current", "page")
    settings.click()
    expect(page).to_have_url(f"{live.base}/admin/settings")
    state(page, "loaded")
    # Settings is headed by its title alone, its eyebrow empty
    expect(page.locator("#page-section")).to_have_text("")
    expect(page.get_by_text("Administration")).to_have_count(0)
    expect(settings).to_have_attribute("aria-current", "page")
    expect(page.locator(".nav-item[aria-current='page']")).to_have_count(0)
    settings_current = settings.evaluate("(el) => getComputedStyle(el).backgroundColor")
    # From the keyboard, the glyphs show the focus ring of every control, set apart from the current page's fill
    settings.focus()
    page.keyboard.press("Tab")
    expect(page.locator("#logout")).to_be_focused()
    live.shot("foot-keyboard-focus")
    page.go_back()
    expect(page).to_have_url(f"{live.base}/admin/links")
    state(page, "loaded")
    # The two glyph buttons share the sidebar's width, and the one under the pointer takes the hover background
    logout = page.locator("#logout")
    settings_box, logout_box = settings.bounding_box(), logout.bounding_box()
    assert settings_box["width"] == logout_box["width"]
    assert settings_box["width"] > 2 * settings_box["height"]
    resting = logout.evaluate("(el) => getComputedStyle(el).backgroundColor")
    # The focus left on Log out above would draw its ring over the hover
    logout.blur()
    logout.hover()
    expect(logout).not_to_have_css("background-color", resting)
    hovered = logout.evaluate("(el) => getComputedStyle(el).backgroundColor")
    live.shot("foot-hover", full_page=False)
    page.mouse.move(0, 0)

    # The menu's items are buttons of the same family: the same rest, hover and focus as the foot's glyphs
    current = page.locator(".nav-item[aria-current='page']")
    other = page.locator(".nav-item", has_text="NanoURLs")
    expect(current).to_have_text("Links")
    # One current-page style: the gear on Settings is filled as the menu's current item is
    expect(current).to_have_css("background-color", settings_current)
    for prop in ("background-color", "border-top-color", "border-top-left-radius"):
        expect(other).to_have_css(prop, logout.evaluate(f"(el) => getComputedStyle(el).getPropertyValue('{prop}')"))
    other.hover()
    expect(other).to_have_css("background-color", hovered)
    live.shot("nav-hover", full_page=False)
    page.mouse.move(0, 0)
    # The current page is a fill, the keyboard focus a ring outside the border: both show on the current item at once
    other.focus()
    page.keyboard.press("Shift+Tab")
    expect(current).to_be_focused()
    expect(current).to_have_css("outline-style", "solid")
    expect(current).not_to_have_css("background-color", resting)
    live.shot("nav-keyboard-focus", full_page=False)
    current.blur()


def session_ends(live: Live) -> None:
    """A session gone under a page: the next call goes to the login, which comes back to that page."""
    page = live.page
    live.open("/admin/qrcodes?new=1")
    live.context.clear_cookies()
    page.locator("#reload").click()
    expect(page).to_have_url(f"{live.base}/login?expired=1&next=%2Fadmin%2Fqrcodes%3Fnew%3D1")
    expect(page.locator(".auth-notice")).to_be_visible()

    page.locator("input[name='password']").fill(PASSWORD)
    page.locator(".auth-submit").click()
    expect(page).to_have_url(f"{live.base}/admin/qrcodes?new=1")
    state(page, "loaded")

    expect(page.locator("#logout")).to_have_attribute("title", "Log out")
    page.locator("#logout").click()
    expect(page).to_have_url(f"{live.base}/login?out=1")
    expect(page.locator(".auth-notice")).to_have_text("You are logged out.")
    live.shot("login-logged-out")


def public(live: Live) -> None:
    page = live.page
    page.goto("/redirect/no-such-link")
    expect(page.locator(".state-hero")).to_have_text("404")
    live.shot("public-not-found")

    store = live.app.extensions["store"]

    def unreadable(*_args):
        raise sqlite3.OperationalError("disk I/O error")

    store.hop = unreadable
    page.goto("/redirect/any")
    expect(page.locator(".state-hero")).to_have_text("503")
    live.shot("public-unavailable")
    del store.hop


def no_password(live: Live) -> None:
    with running(live.browser, live.playwright, live.run, live.walk, password=False) as bare:
        page = bare.page
        page.goto("/login")
        page.locator("input[name='password']").fill("anything")
        page.locator(".auth-submit").click()
        said = "No password is configured: set MOONIE_REDIRECT_PASSWORD_FILE."
        expect(page.locator(".form-error")).to_have_text(said)
        bare.shot("login-no-password")


def walk(live: Live) -> None:
    login_page(live)
    menu_and_not_found(live)
    session_ends(live)
    public(live)
    no_password(live)
