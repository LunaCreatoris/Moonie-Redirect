"""The Links page: every state of 7.0.1's walk that 9.0.0 keeps, against what the API then holds."""

import re

from kit import (
    LONG_TARGET,
    PATH_255,
    Live,
    control,
    dialog,
    error_of,
    form_title,
    form_top,
    held,
    loading_and_error,
    moment,
    notice,
    refuse_copies,
    row_of,
    rows,
    save,
    selected_row,
    state,
    until_held,
    window_at_bottom,
    window_on,
)
from playwright.sync_api import expect

PAGE = "/admin/links"
SLUG = re.compile(r"^[A-Za-z2-9]{6}$")
# Four links, oldest first, each with the moment it was last changed
LINKS = (
    {
        "slug": "trade-show",
        "name": "Trade show flyer",
        "target": "https://cloud.example/flyer.pdf",
        "http_status": 302,
        "expires_on": "2026-11-15",
        "at": moment(10, 20, 10, 31),
    },
    {
        "slug": "chat",
        "name": "Community chat",
        "target": "https://chat.example/invite",
        "http_status": 301,
        "expires_on": None,
        "at": moment(10, 28, 21, 2),
    },
    {
        "slug": "team/Week1",
        "name": "Team schedule",
        "target": "https://sheets.example/schedule.xlsx",
        "http_status": 302,
        "expires_on": None,
        "at": moment(11, 1, 18, 40),
    },
    {
        "slug": "resume",
        "name": "Résumé 2026",
        "target": "https://cloud.example/resume-2026.pdf",
        "http_status": 302,
        "expires_on": "2027-06-30",
        "at": moment(11, 2, 9, 15),
    },
)


def fill(page, *, name: str, slug: str, target: str, expires: str = "") -> None:
    control(page, "name").fill(name)
    control(page, "slug").fill(slug)
    control(page, "target").fill(target)
    control(page, "expires_on").fill(expires)


def empty(live: Live) -> None:
    page = live.page
    live.log_in()
    expect(page).to_have_url(f"{live.base}{PAGE}")
    expect(rows(page)).to_have_count(0)
    expect(form_title(page)).to_have_text("New link")
    expect(control(page, "slug")).to_have_value(SLUG)
    live.shot("empty")


def listed(live: Live) -> None:
    page = live.page
    live.open(PAGE)
    expect(page.locator("#status")).to_have_text("Running · 4 redirects")
    expect(rows(page).locator(".redirect-path")).to_have_text(
        ["/redirect/resume", "/redirect/team/Week1", "/redirect/chat", "/redirect/trade-show"]
    )
    expect(selected_row(page).locator(".redirect-path")).to_have_text("/redirect/resume")
    expect(control(page, "slug")).to_have_value("resume")
    live.shot("list")

    search = page.locator("#page .redirect-search")
    search.fill("FLYER")
    expect(rows(page)).to_have_count(1)
    live.shot("search")
    search.fill("nothing-matches-this")
    expect(rows(page)).to_have_count(0)
    expect(page.locator("#page .redirect-none")).to_have_text("No links match this search.")
    live.shot("search-none")
    search.fill("")

    row_of(page, "/redirect/chat").locator(".redirect-name").click()
    expect(selected_row(page).locator(".redirect-path")).to_have_text("/redirect/chat")
    # No code to choose (decision D20): a 301 set through the API is said, and a save keeps it
    expect(page.locator("#page [name='http_status']")).to_have_count(0)
    expect(page.locator("#page .redirect-status-kept")).to_have_text(
        "This link answers 301, a permanent redirect. Saving here keeps it; only the API changes it."
    )
    live.shot("selected")
    row_of(page, "/redirect/resume").locator(".redirect-name").click()
    expect(page.locator("#page .redirect-status-kept")).to_have_count(0)


def new_and_errors(live: Live) -> None:
    page = live.page
    live.open(PAGE)
    page.locator("#page .redirect-new").click()
    expect(form_title(page)).to_have_text("New link")
    expect(control(page, "slug")).to_have_value(SLUG)
    suggested = control(page, "slug").input_value()
    page.locator("#page .redirect-random").click()
    expect(control(page, "slug")).not_to_have_value(suggested)
    expect(control(page, "slug")).to_have_value(SLUG)
    live.shot("new")

    fill(page, name="", slug="a//b", target="ftp://files.example/x", expires="2026-13-40")
    save(page).click()
    expect(error_of(page, "name")).to_have_text("Enter a name.")
    expect(error_of(page, "slug")).to_be_visible()
    expect(error_of(page, "target")).to_have_text("Enter a full URL that starts with http:// or https://.")
    expect(error_of(page, "expires_on")).to_have_text("Enter a valid date as YYYY-MM-DD, or leave it empty.")
    expect(control(page, "name")).to_be_focused()
    live.shot("error-fields")

    fill(page, name="Another", slug="resume", target="https://files.example/other.pdf")
    save(page).click()
    expect(error_of(page, "slug")).to_have_text("This slug is already used by another link.")
    expect(error_of(page, "name")).to_be_hidden()
    expect(control(page, "slug")).to_be_focused()
    live.shot("error-slug-taken")

    control(page, "slug").fill("another")
    page.route("**/api/links", lambda route: route.abort())
    save(page).click()
    expect(form_top(page)).to_have_text("The instance did not respond. Try again.")
    expect(save(page)).to_be_enabled()
    live.shot("error-no-answer")
    page.unroute("**/api/links")


def created_and_saved(live: Live) -> None:
    page = live.page
    live.clock = moment(11, 3, 10, 0)
    page.locator("#page .redirect-search").fill("cloud")
    fill(page, name="Budget 2026", slug="finance/budget", target="  https://files.example/budget.xlsx  ")
    save(page).click()
    expect(notice(page)).to_have_text("Link “Budget 2026” created.")
    assert live.named("link", "Budget 2026")["http_status"] == 302
    expect(rows(page)).to_have_count(5)
    expect(page.locator("#status")).to_have_text("Running · 5 redirects")
    expect(selected_row(page).locator(".redirect-path")).to_have_text("/redirect/finance/budget")
    live.shot("created")

    warning = page.locator("#page .redirect-slug-warning")
    control(page, "slug").fill("finance/budget-2027")
    control(page, "target").fill("https://files.example/budget-2027.xlsx")
    control(page, "expires_on").fill("2027-12-31")
    expect(warning).to_have_text(
        "Changing the slug breaks any link you have already shared: the old one will answer “not found”."
    )
    live.shot("slug-warning")

    live.clock = moment(11, 3, 11, 0)
    page.locator("#page .redirect-search").fill("budget")
    save(page).click()
    expect(notice(page)).to_have_text("Link “Budget 2026” saved.")
    expect(rows(page)).to_have_count(1)
    expect(warning).to_have_text("")
    live.shot("saved")

    # An emptied expiry goes as none, as 7.0.1's walk left the row before its delete
    page.locator("#page .redirect-search").fill("")
    control(page, "expires_on").fill("")
    save(page).click()
    expect(notice(page)).to_have_text("Link “Budget 2026” saved.")
    expect(control(page, "expires_on")).to_have_value("")
    saved = live.named("link", "Budget 2026")
    assert saved["expires_on"] is None and saved["http_status"] == 302, saved
    # A notice lasts one draw
    page.reload()
    state(page, "loaded")
    expect(notice(page)).to_be_hidden()
    expect(selected_row(page).locator(".redirect-path")).to_have_text("/redirect/finance/budget-2027")


def deleted(live: Live) -> None:
    page = live.page
    page.locator("#page .redirect-delete").click()
    expect(dialog(page).locator(".card-title")).to_have_text("Delete “Budget 2026”?")
    expect(dialog(page).locator("p")).to_have_text(
        "http://redirect.lan:8420/redirect/finance/budget-2027 will stop working for everyone who has it."
    )
    window_at_bottom(page)
    live.shot("delete-confirm", full_page=False)
    page.keyboard.press("Escape")
    expect(dialog(page)).to_have_count(0)

    page.locator("#page .redirect-delete").click()
    dialog(page).locator(".btn-danger").click()
    expect(notice(page)).to_have_text("Link “Budget 2026” deleted.")
    expect(rows(page)).to_have_count(4)
    expect(page.locator("#status")).to_have_text("Running · 4 redirects")
    live.shot("deleted")


def copies(live: Live) -> None:
    page = live.page
    copy = row_of(page, "/redirect/chat").locator(".redirect-copy")
    copy.click()
    expect(copy).to_have_text("Copied")
    assert page.evaluate("() => navigator.clipboard.readText()") == "http://redirect.lan:8420/redirect/chat"
    live.shot("copied")

    live.open(PAGE)
    refuse_copies(page)
    copy = row_of(page, "/redirect/chat").locator(".redirect-copy")
    copy.click()
    expect(copy).to_have_text("Copy failed")
    live.shot("copy-failed")


def focus(live: Live) -> None:
    page = live.page
    live.open(PAGE)
    row = row_of(page, "/redirect/chat")
    copy = row.locator(".redirect-copy")
    copy.focus()
    page.keyboard.press("Shift+Tab")
    expect(row).to_be_focused()
    live.shot("focus-row")
    page.keyboard.press("Tab")
    expect(copy).to_be_focused()
    live.shot("focus-copy")


def saving(live: Live) -> None:
    page = live.page
    live.open(PAGE)
    stopped = held(page, "**/api/links/*")
    save(page).click()
    until_held(page, stopped)
    expect(save(page)).to_be_disabled()
    row_of(page, "/redirect/chat").locator(".redirect-name").click()
    page.locator("#page .redirect-new").click()
    expect(dialog(page)).to_have_count(0)
    expect(selected_row(page).locator(".redirect-path")).to_have_text("/redirect/resume")
    live.shot("saving")
    stopped[0].continue_()
    expect(notice(page)).to_be_visible()
    page.unroute("**/api/links/*")


def discard(live: Live) -> None:
    page = live.page
    live.open(PAGE)
    row_of(page, "/redirect/chat").locator(".redirect-name").click()
    control(page, "name").fill("Typed and never saved")
    row_of(page, "/redirect/resume").locator(".redirect-name").click()
    expect(dialog(page).locator(".card-title")).to_have_text("Discard your changes?")
    page.mouse.move(0, 0)
    window_on(row_of(page, "/redirect/resume").locator(".redirect-name"))
    live.shot("discard-confirm", full_page=False)
    dialog(page).locator(".btn").first.click()
    expect(control(page, "name")).to_have_value("Typed and never saved")


def vanished(live: Live) -> None:
    page = live.page
    live.open(PAGE)
    row_of(page, "/redirect/chat").locator(".redirect-name").click()
    live.remove(live.named("link", "Community chat")["id"])
    save(page).click()
    expect(notice(page)).to_have_text("This link no longer exists.")
    expect(rows(page)).to_have_count(3)
    expect(selected_row(page).locator(".redirect-path")).to_have_text("/redirect/resume")
    live.shot("edit-gone")

    page.route("**/api/links/*", lambda route: route.abort())
    page.locator("#page .redirect-delete").click()
    dialog(page).locator(".btn-danger").click()
    expect(form_top(page)).to_be_visible()
    expect(page.locator("#page .redirect-delete")).to_be_focused()
    live.shot("delete-failed")
    page.unroute("**/api/links/*")

    for row in live.rows("link"):
        live.remove(row["id"])
    alone = live.add({"name": "Alone", "slug": "alone", "target": "https://a.example/x", "at": moment(11, 3, 12, 0)})
    live.open(PAGE)
    live.remove(alone["id"])
    control(page, "target").fill("https://typed.example/kept")
    save(page).click()
    expect(rows(page)).to_have_count(0)
    state(page, "loaded")
    expect(notice(page)).to_have_text("This link no longer exists.")
    expect(form_title(page)).to_have_text("New link")
    expect(control(page, "target")).to_have_value("")
    expect(control(page, "slug")).to_have_value(SLUG)
    live.shot("gone-last")


def long_values(live: Live) -> None:
    page = live.page
    live.add(
        {
            "slug": PATH_255,
            "name": "N" * 100,
            "target": LONG_TARGET,
            "http_status": 302,
            "expires_on": "2030-01-01",
            "at": moment(11, 3, 12, 0),
        }
    )
    live.open(PAGE)
    expect(control(page, "target")).to_have_value(LONG_TARGET)
    overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0, f"the page scrolls sideways by {overflow} px"
    live.shot("long-values")


def walk(live: Live) -> None:
    empty(live)
    for link in LINKS:
        live.add(link)
    loading_and_error(live, PAGE, "link")
    listed(live)
    new_and_errors(live)
    created_and_saved(live)
    deleted(live)
    copies(live)
    focus(live)
    saving(live)
    discard(live)
    vanished(live)
    long_values(live)
