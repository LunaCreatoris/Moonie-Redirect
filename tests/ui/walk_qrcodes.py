"""The QR page: the designer and its preview, and every state of 7.0.1's walk that 9.0.0 keeps, against what the API
then holds. The states of the link address (IP or public URL) are gone with it. The logos are made here from real image
bytes and handed to the file chooser from memory: no file is kept."""

import struct
import zlib

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
    row_of,
    rows,
    save,
    selected_row,
    state,
    until,
    until_held,
    window_at_bottom,
    window_on,
)
from playwright.sync_api import expect

PAGE = "/admin/qrcodes"
PREVIEW = "**/api/qrcodes/preview"
DESIGNED = {
    "color": "#0b3d91",
    "eye_color": "#c2185b",
    "background": "#ffffff",
    "module_style": "dots",
    "eye_style": "circle",
    "logo": None,
    "logo_size": 0.22,
    "margin": 2,
}
# Three QR codes, oldest first, each with the moment it was last changed
QR_CODES = (
    {
        "kind": "qrcode",
        "name": "Trade show poster",
        "target": "https://cloud.example/poster.pdf",
        "design": {},
        "at": moment(10, 20, 10, 31),
    },
    {
        "kind": "qrcode",
        "name": "Business card",
        "target": "https://cloud.example/resume-2026.pdf",
        "design": DESIGNED,
        "at": moment(10, 28, 21, 2),
    },
    {
        "kind": "qrcode",
        "name": "Café menu",
        "target": "https://cloud.example/menu.pdf",
        "design": {"background": "transparent", "module_style": "rounded", "eye_style": "rounded"},
        "at": moment(11, 2, 9, 15),
    },
)
# A name is text wherever it shows, and a page that took it for markup would run this
HOSTILE_NAME = "<img src=x onerror=window.__ranFromName=1>"
LOGO_RGB = (194, 24, 91)
LOGO_MAX_BYTES = 256 * 1024


def png_logo() -> bytes:
    """A real PNG: a disc on white."""
    side = 48

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    lines = bytearray()
    for y in range(side):
        lines.append(0)
        for x in range(side):
            inside = (x - side / 2) ** 2 + (y - side / 2) ** 2 <= (side * 0.42) ** 2
            lines += bytes(LOGO_RGB if inside else (255, 255, 255))
    header = struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(lines), 9))
        + chunk(b"IEND", b"")
    )


PNG = {"name": "logo.png", "mimeType": "image/png", "buffer": png_logo()}
TEXT = {"name": "notes.txt", "mimeType": "text/plain", "buffer": b"This is no image."}
FALSE_PNG = {"name": "false.png", "mimeType": "image/png", "buffer": b"This is no image, whatever its name says."}
HUGE = {"name": "huge.png", "mimeType": "image/png", "buffer": png_logo() + b"\0" * LOGO_MAX_BYTES}


def frame(page):
    return page.locator("#page .redirect-qr-frame")


def design_error(page):
    return page.locator("#page .redirect-design-error")


def preview_ready(page) -> None:
    """Nothing asked is still on its way, and what came is drawn."""
    expect(frame(page)).to_have_attribute("aria-busy", "false")


def set_range(page, name: str, value: int) -> None:
    """A range cannot be filled: set it, then send the event the page follows."""
    control(page, name).evaluate(
        "(input, value) => { input.value = value; input.dispatchEvent(new Event('input', { bubbles: true })) }",
        str(value),
    )


def choose_logo(page, file: dict) -> None:
    page.locator("#page .redirect-file input").set_input_files(file)


def thumbnails_drawn(page) -> None:
    until(
        page,
        "() => [...document.querySelectorAll('#page .redirect-qr-thumb img')]"
        ".every((img) => img.complete && img.naturalWidth > 0)",
    )


def empty(live: Live) -> None:
    page = live.page
    live.log_in()
    live.open(PAGE)
    expect(rows(page)).to_have_count(0)
    expect(form_title(page)).to_have_text("New QR code")
    preview_ready(page)
    expect(control(page, "logo_size")).to_be_disabled()
    expect(page.locator("#page output[for='qr-logo-size']")).to_have_text("22%")
    live.shot("empty")


def listed(live: Live) -> None:
    page = live.page
    live.open(PAGE)
    preview_ready(page)
    thumbnails_drawn(page)
    expect(rows(page).locator(".redirect-name")).to_have_text(["Café menu", "Business card", "Trade show poster"])
    live.shot("list")

    search = page.locator("#page .redirect-search")
    search.fill("POSTER")
    expect(rows(page)).to_have_count(1)
    live.shot("search")
    search.fill("qrcodes")
    expect(rows(page)).to_have_count(0)
    expect(page.locator("#page .redirect-none")).to_have_text("No QR codes match this search.")
    live.shot("search-none")
    search.fill("")

    row_of(page, "/redirect/QRcodes/Business-card").locator(".redirect-name").click()
    preview_ready(page)
    expect(control(page, "module_style")).to_have_value("dots")
    expect(page.locator("#page output[for='qr-margin']")).to_have_text("2")
    live.shot("selected")


def designed(live: Live) -> None:
    page = live.page
    page.locator("#page .redirect-new").click()
    preview_ready(page)
    control(page, "name").fill("Dish of the day")
    control(page, "target").fill("https://cloud.example/plat.pdf")
    control(page, "color").fill("#0b3d91")
    control(page, "eye_color").fill("#c2185b")
    control(page, "module_style").select_option("dots")
    control(page, "eye_style").select_option("circle")
    set_range(page, "margin", 2)
    preview_ready(page)
    live.shot("designed")

    control(page, "transparent").check()
    preview_ready(page)
    expect(control(page, "background")).to_be_disabled()
    live.shot("transparent")
    control(page, "transparent").uncheck()
    preview_ready(page)

    choose_logo(page, PNG)
    preview_ready(page)
    set_range(page, "logo_size", 30)
    preview_ready(page)
    expect(page.locator("#page .redirect-logo-state")).to_have_text("Logo set")
    expect(page.locator("#page output[for='qr-logo-size']")).to_have_text("30%")
    live.shot("logo")

    choose_logo(page, TEXT)
    preview_ready(page)
    expect(design_error(page)).to_have_text("The logo must be a PNG, JPEG, WebP or SVG image.")
    expect(page.locator("#page .redirect-logo-state")).to_have_text("Logo set")
    live.shot("logo-refused")

    choose_logo(page, HUGE)
    preview_ready(page)
    expect(design_error(page)).to_have_text("The logo must be 256 KB or smaller.")
    live.shot("logo-too-big")

    choose_logo(page, FALSE_PNG)
    preview_ready(page)
    expect(design_error(page)).to_have_text("The logo must be a PNG, JPEG, WebP or SVG image.")
    live.shot("logo-bad-bytes")

    choose_logo(page, PNG)
    preview_ready(page)
    expect(design_error(page)).to_be_hidden()


def form_errors(live: Live) -> None:
    page = live.page
    name, target = control(page, "name").input_value(), control(page, "target").input_value()
    control(page, "name").fill("")
    control(page, "target").fill("ftp://files.example/x")
    save(page).click()
    expect(error_of(page, "name")).to_have_text("Enter a name.")
    expect(error_of(page, "target")).to_have_text("Enter a full URL that starts with http:// or https://.")
    live.shot("error-fields")

    control(page, "name").fill("Trade show poster")
    control(page, "target").fill(target)
    save(page).click()
    expect(error_of(page, "name")).to_have_text("This name is already used on this page.")
    expect(error_of(page, "target")).to_be_hidden()
    live.shot("error-name-taken")

    control(page, "name").fill(name)
    page.route("**/api/links", lambda route: route.abort())
    save(page).click()
    expect(form_top(page)).to_have_text("The instance did not respond. Try again.")
    live.shot("error-no-answer")
    page.unroute("**/api/links")


def created_and_saved(live: Live) -> None:
    page = live.page
    live.clock = moment(11, 3, 10, 0)
    page.locator("#page .redirect-search").fill("poster")
    save(page).click()
    expect(notice(page)).to_have_text("QR code “Dish of the day” created.")
    expect(selected_row(page).locator(".redirect-name")).to_have_text("Dish of the day")
    assert live.named("qrcode", "Dish of the day")["design"]["logo"].startswith("data:image/png;base64,")
    preview_ready(page)
    thumbnails_drawn(page)
    live.shot("created")

    control(page, "color").fill("#eeeeee")
    preview_ready(page)
    expect(design_error(page)).to_have_text(
        "The colors are too close to the background: scanners may not be able to read the QR code."
    )
    live.shot("contrast-error")
    control(page, "color").fill("#0b3d91")
    preview_ready(page)

    page.route(PREVIEW, lambda route: route.abort())
    control(page, "eye_color").fill("#123456")
    preview_ready(page)
    expect(design_error(page)).to_have_text("The instance did not respond. Try again.")
    live.shot("preview-no-answer")
    page.unroute(PREVIEW)
    control(page, "eye_color").fill("#c2185b")
    preview_ready(page)

    live.clock = moment(11, 3, 11, 0)
    page.locator("#page .redirect-search").fill("plat")
    control(page, "eye_style").select_option("rounded")
    control(page, "target").fill("https://cloud.example/plat-2.pdf")
    preview_ready(page)
    save(page).click()
    expect(notice(page)).to_have_text("QR code “Dish of the day” saved.")
    preview_ready(page)
    thumbnails_drawn(page)
    live.shot("saved")
    page.locator("#page .redirect-search").fill("")
    # A notice lasts one draw: the delete below starts from the page read again, as in 7.0.1's walk
    page.reload()
    state(page, "loaded")
    expect(notice(page)).to_be_hidden()
    preview_ready(page)


def deleted(live: Live) -> None:
    page = live.page
    short_url = live.named("qrcode", "Dish of the day")["short_url"]
    page.locator("#page .redirect-delete").click()
    expect(dialog(page).locator("p")).to_have_text(f"{short_url} will stop working for everyone who has it.")
    window_at_bottom(page)
    live.shot("delete-confirm", full_page=False)
    page.keyboard.press("Escape")
    page.locator("#page .redirect-delete").click()
    dialog(page).locator(".btn-danger").click()
    expect(notice(page)).to_have_text("QR code “Dish of the day” deleted.")
    expect(rows(page)).to_have_count(3)
    preview_ready(page)
    thumbnails_drawn(page)
    live.shot("deleted")


def copies(live: Live) -> None:
    page = live.page
    copy = row_of(page, "/redirect/QRcodes/Trade-show-poster").locator(".redirect-copy")
    copy.click()
    expect(copy).to_have_text("Copied")
    assert (
        page.evaluate("() => navigator.clipboard.readText()") == live.named("qrcode", "Trade show poster")["short_url"]
    )
    preview_ready(page)
    live.shot("copied")

    live.open(PAGE)
    refuse_copies(page)
    copy = row_of(page, "/redirect/QRcodes/Trade-show-poster").locator(".redirect-copy")
    copy.click()
    expect(copy).to_have_text("Copy failed")
    preview_ready(page)
    thumbnails_drawn(page)
    live.shot("copy-failed")


def guarded(live: Live) -> None:
    page = live.page
    waiting = held(page, PREVIEW)
    page.goto(PAGE)
    state(page, "loaded")
    until_held(page, waiting)
    thumbnails_drawn(page)
    expect(frame(page)).to_have_attribute("aria-busy", "true")
    live.shot("preview-waiting")
    waiting[0].continue_()
    preview_ready(page)
    page.unroute(PREVIEW)

    other = row_of(page, "/redirect/QRcodes/Business-card")
    control(page, "name").fill("Typed and never saved")
    other.locator(".redirect-name").click()
    expect(dialog(page).locator(".card-title")).to_have_text("Discard your changes?")
    page.mouse.move(0, 0)
    window_on(other.locator(".redirect-name"))
    live.shot("discard-confirm", full_page=False)
    dialog(page).locator(".btn").first.click()
    page.locator("#page .redirect-cancel").click()
    preview_ready(page)

    stopped = held(page, "**/api/links/*")
    save(page).click()
    until_held(page, stopped)
    other.locator(".redirect-name").click()
    page.locator("#page .redirect-new").click()
    expect(dialog(page)).to_have_count(0)
    expect(save(page)).to_be_disabled()
    live.shot("saving")
    stopped[0].continue_()
    expect(notice(page)).to_be_visible()
    page.unroute("**/api/links/*")


def vanished(live: Live) -> None:
    page = live.page
    live.open(PAGE)
    row_of(page, "/redirect/QRcodes/Business-card").locator(".redirect-name").click()
    preview_ready(page)
    live.remove(live.named("qrcode", "Business card")["id"])
    control(page, "color").fill("#222222")
    preview_ready(page)
    expect(design_error(page)).to_have_text("This QR code no longer exists.")
    live.shot("preview-gone")
    save(page).click()
    expect(notice(page)).to_have_text("This QR code no longer exists.")
    preview_ready(page)
    thumbnails_drawn(page)
    live.shot("edit-gone")

    page.route("**/api/links/*", lambda route: route.abort())
    page.locator("#page .redirect-delete").click()
    dialog(page).locator(".btn-danger").click()
    expect(form_top(page)).to_be_visible()
    preview_ready(page)
    thumbnails_drawn(page)
    live.shot("delete-failed")
    page.unroute("**/api/links/*")

    for row in live.rows("qrcode"):
        live.remove(row["id"])
    alone = live.add(
        {"kind": "qrcode", "name": "Seul", "target": "https://a.example/x", "design": {}, "at": moment(11, 3, 12, 0)}
    )
    live.open(PAGE)
    preview_ready(page)
    live.remove(alone["id"])
    control(page, "target").fill("https://typed.example/kept")
    save(page).click()
    expect(rows(page)).to_have_count(0)
    state(page, "loaded")
    expect(notice(page)).to_have_text("This QR code no longer exists.")
    expect(form_title(page)).to_have_text("New QR code")
    preview_ready(page)
    live.shot("gone-last")


def no_drawing(live: Live) -> None:
    page = live.page
    bad = live.add(
        {
            "kind": "qrcode",
            "name": "No design",
            "target": "https://a.example/x",
            "design": {},
            "at": moment(11, 3, 12, 0),
        }
    )
    live.write_design(bad["id"], "not json")
    live.open(f"{PAGE}?qr={bad['id']}")
    preview_ready(page)
    row = row_of(page, "/redirect/QRcodes/No-design")
    expect(row.locator(".redirect-qr-none")).to_have_text("—")
    expect(row.locator(".redirect-download")).to_be_disabled()
    expect(design_error(page)).to_have_text("The saved design of this QR code is not valid. Save a new design.")
    live.shot("unreadable")
    live.remove(bad["id"])


def long_values(live: Live) -> None:
    """The longest name and target beside a name that is markup: it shows as text, in the list, the form and the
    question before a delete, and runs nothing (a script error would fail the capture)."""
    page = live.page
    live.add({"kind": "qrcode", "name": "N" * 100, "target": LONG_TARGET, "design": {}, "at": moment(11, 3, 12, 0)})
    live.add(
        {
            "kind": "qrcode",
            "name": HOSTILE_NAME,
            "target": "https://files.example/a",
            "design": {},
            "at": moment(11, 3, 12, 1),
        }
    )
    live.open(PAGE)
    preview_ready(page)
    expect(rows(page).first.locator(".redirect-name")).to_have_text(HOSTILE_NAME)
    expect(control(page, "name")).to_have_value(HOSTILE_NAME)
    page.locator("#page .redirect-delete").click()
    expect(dialog(page).locator(".card-title")).to_have_text(f"Delete “{HOSTILE_NAME}”?")
    page.keyboard.press("Escape")
    expect(page.locator("#page [src='x'], dialog [src='x']")).to_have_count(0)
    assert page.evaluate("() => window.__ranFromName === undefined")
    rows(page).filter(has_text="N" * 20).first.locator(".redirect-name").click()
    expect(control(page, "target")).to_have_value(LONG_TARGET)
    preview_ready(page)
    thumbnails_drawn(page)
    overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0, f"the page scrolls sideways by {overflow} px"
    live.shot("long-values")
    # The walk then visits the page once more under its policy, with one more code: the later captures hold it
    live.add(
        {
            "kind": "qrcode",
            "name": "Under the policy",
            "target": "https://files.example/p",
            "design": {},
            "at": moment(11, 3, 13, 0),
        }
    )


def walk(live: Live) -> None:
    empty(live)
    for qr in QR_CODES:
        live.add(qr)
    loading_and_error(live, PAGE, "qrcode")
    listed(live)
    designed(live)
    form_errors(live)
    created_and_saved(live)
    deleted(live)
    copies(live)
    guarded(live)
    vanished(live)
    long_values(live)
    no_drawing(live)
