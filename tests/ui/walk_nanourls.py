"""The NanoURL page: every state of 7.0.1's walk that 9.0.0 keeps, against what the API then holds. The states of the
link address (IP or public URL) are gone with it."""

from kit import (
    LONG_TARGET,
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
    rows,
    save,
    selected_row,
    state,
    until_held,
    window_at_bottom,
    window_on,
)
from playwright.sync_api import expect

PAGE = "/admin/nanourls"
# Three NanoURLs, oldest first, each with the moment it was last changed
NANOS = (
    {"kind": "nano", "name": "Café menu", "target": "https://cafe.example/menu.pdf", "at": moment(10, 20, 10, 31)},
    {
        "kind": "nano",
        "name": "Trade show flyer",
        "target": "https://cloud.example/flyer.pdf",
        "at": moment(10, 28, 21, 2),
    },
    {"kind": "nano", "name": "Team lunch", "target": "https://wiki.example/lunch", "at": moment(11, 2, 9, 15)},
)


def row_named(page, name: str):
    return rows(page).filter(has=page.locator(".redirect-name", has_text=name))


def empty(live: Live) -> None:
    page = live.page
    live.log_in()
    live.open(PAGE)
    expect(rows(page)).to_have_count(0)
    expect(page.locator("#page .redirect-none")).to_have_text(
        "No NanoURLs yet. Enter a name and a target in the form, and the application makes the short link."
    )
    expect(form_title(page)).to_have_text("New NanoURL")
    live.shot("empty")


def listed(live: Live) -> None:
    page = live.page
    live.open(PAGE)
    expect(rows(page).locator(".redirect-name")).to_have_text(["Team lunch", "Trade show flyer", "Café menu"])
    expect(selected_row(page).locator(".redirect-name")).to_have_text("Team lunch")
    live.shot("list")

    search = page.locator("#page .redirect-search")
    search.fill("FLYER")
    expect(rows(page)).to_have_count(1)
    live.shot("search")
    search.fill("NanoURL")
    expect(rows(page)).to_have_count(0)
    expect(page.locator("#page .redirect-none")).to_have_text("No NanoURLs match this search.")
    live.shot("search-none")
    search.fill("")

    row_named(page, "Trade show flyer").locator(".redirect-name").click()
    expect(selected_row(page).locator(".redirect-name")).to_have_text("Trade show flyer")
    expect(form_title(page)).to_have_text(f"Edit · /links/{live.named('nano', 'Trade show flyer')['id']}")
    live.shot("selected")


def new_and_errors(live: Live) -> None:
    page = live.page
    page.locator("#page .redirect-new").click()
    expect(form_title(page)).to_have_text("New NanoURL")
    expect(control(page, "name")).to_be_focused()
    live.shot("new")

    control(page, "name").fill("")
    control(page, "target").fill("ftp://files.example/x")
    save(page).click()
    expect(error_of(page, "name")).to_have_text("Enter a name.")
    expect(error_of(page, "target")).to_have_text("Enter a full URL that starts with http:// or https://.")
    live.shot("error-fields")

    control(page, "name").fill("Team  lunch!")
    control(page, "target").fill("https://wiki.example/other")
    save(page).click()
    expect(error_of(page, "name")).to_have_text("This name is already used on this page.")
    expect(error_of(page, "target")).to_be_hidden()
    live.shot("error-name-taken")

    control(page, "name").fill("Another")
    page.route("**/api/links", lambda route: route.abort())
    save(page).click()
    expect(form_top(page)).to_have_text("The instance did not respond. Try again.")
    live.shot("error-no-answer")
    page.unroute("**/api/links")


def created_and_saved(live: Live) -> None:
    page = live.page
    live.clock = moment(11, 3, 10, 0)
    page.locator("#page .redirect-search").fill("cloud")
    control(page, "name").fill("Budget 2026")
    control(page, "target").fill("  https://files.example/budget.xlsx  ")
    save(page).click()
    created = live.named("nano", "Budget 2026")
    expect(notice(page)).to_have_text(f"NanoURL “Budget 2026” created: {created['short_url']}")
    expect(page.locator("#page .redirect-search")).to_have_value("")
    expect(selected_row(page).locator(".redirect-name")).to_have_text("Budget 2026")
    live.shot("created")

    live.clock = moment(11, 3, 11, 0)
    page.locator("#page .redirect-search").fill("budget")
    control(page, "name").fill("Budget 2027")
    control(page, "target").fill("https://files.example/budget-2027.xlsx")
    save(page).click()
    expect(notice(page)).to_have_text("NanoURL “Budget 2027” saved.")
    expect(rows(page)).to_have_count(1)
    live.shot("saved")
    page.locator("#page .redirect-search").fill("")
    # A notice lasts one draw: the delete below starts from the page read again, as in 7.0.1's walk
    page.reload()
    state(page, "loaded")
    expect(notice(page)).to_be_hidden()


def deleted(live: Live) -> None:
    page = live.page
    short_url = live.named("nano", "Budget 2027")["short_url"]
    page.locator("#page .redirect-delete").click()
    expect(dialog(page).locator(".card-title")).to_have_text("Delete “Budget 2027”?")
    expect(dialog(page).locator("p")).to_have_text(f"{short_url} will stop working for everyone who has it.")
    window_at_bottom(page)
    live.shot("delete-confirm", full_page=False)
    page.keyboard.press("Escape")
    page.locator("#page .redirect-delete").click()
    dialog(page).locator(".btn-danger").click()
    expect(notice(page)).to_have_text("NanoURL “Budget 2027” deleted.")
    expect(rows(page)).to_have_count(3)
    live.shot("deleted")


def copies(live: Live) -> None:
    page = live.page
    copy = row_named(page, "Trade show flyer").locator(".redirect-copy")
    copy.click()
    expect(copy).to_have_text("Copied")
    assert page.evaluate("() => navigator.clipboard.readText()") == live.named("nano", "Trade show flyer")["short_url"]
    live.shot("copied")

    live.open(PAGE)
    refuse_copies(page)
    copy = row_named(page, "Trade show flyer").locator(".redirect-copy")
    copy.click()
    expect(copy).to_have_text("Copy failed")
    live.shot("copy-failed")


def guarded(live: Live) -> None:
    page = live.page
    live.open(PAGE)
    team = live.named("nano", "Team lunch")
    control(page, "name").fill("Team dinner")
    expect(page.locator("#page .redirect-slug-warning")).to_have_text(
        "Renaming changes the path: /redirect/NanoURL/Team-lunch stops working, and another NanoURL may take it later."
        " The short link stays the same."
    )
    live.shot("rename-warning")
    assert team["slug"] == "NanoURL/Team-lunch"

    row_named(page, "Trade show flyer").locator(".redirect-name").click()
    expect(dialog(page).locator(".card-title")).to_have_text("Discard your changes?")
    page.mouse.move(0, 0)
    window_on(row_named(page, "Trade show flyer").locator(".redirect-name"))
    live.shot("discard-confirm", full_page=False)
    dialog(page).locator(".btn").first.click()
    expect(control(page, "name")).to_have_value("Team dinner")
    page.locator("#page .redirect-cancel").click()

    stopped = held(page, "**/api/links/*")
    save(page).click()
    until_held(page, stopped)
    row_named(page, "Trade show flyer").locator(".redirect-name").click()
    page.locator("#page .redirect-new").click()
    expect(dialog(page)).to_have_count(0)
    expect(save(page)).to_be_disabled()
    live.shot("saving")
    stopped[0].continue_()
    expect(notice(page)).to_be_visible()
    page.unroute("**/api/links/*")

    page.route("**/api/links/*", lambda route: route.abort())
    page.locator("#page .redirect-delete").click()
    dialog(page).locator(".btn-danger").click()
    expect(form_top(page)).to_be_visible()
    expect(page.locator("#page .redirect-delete")).to_be_focused()
    live.shot("delete-failed")
    page.unroute("**/api/links/*")


def vanished(live: Live) -> None:
    page = live.page
    live.open(PAGE)
    row_named(page, "Trade show flyer").locator(".redirect-name").click()
    live.remove(live.named("nano", "Trade show flyer")["id"])
    save(page).click()
    expect(notice(page)).to_have_text("This NanoURL no longer exists.")
    expect(rows(page)).to_have_count(2)
    live.shot("edit-gone")

    for row in live.rows("nano"):
        live.remove(row["id"])
    alone = live.add({"kind": "nano", "name": "Alone", "target": "https://a.example/x", "at": moment(11, 3, 12, 0)})
    live.open(PAGE)
    live.remove(alone["id"])
    control(page, "target").fill("https://typed.example/kept")
    save(page).click()
    expect(rows(page)).to_have_count(0)
    state(page, "loaded")
    expect(notice(page)).to_have_text("This NanoURL no longer exists.")
    expect(form_title(page)).to_have_text("New NanoURL")
    expect(control(page, "target")).to_have_value("")
    live.shot("gone-last")


def long_values(live: Live) -> None:
    page = live.page
    live.add({"kind": "nano", "name": "N" * 100, "target": LONG_TARGET, "at": moment(11, 3, 12, 0)})
    live.open(PAGE)
    expect(control(page, "target")).to_have_value(LONG_TARGET)
    overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0, f"the page scrolls sideways by {overflow} px"
    live.shot("long-values")


def walk(live: Live) -> None:
    empty(live)
    for nano in NANOS:
        live.add(nano)
    loading_and_error(live, PAGE, "nano")
    listed(live)
    new_and_errors(live)
    created_and_saved(live)
    deleted(live)
    copies(live)
    guarded(live)
    vanished(live)
    long_values(live)
