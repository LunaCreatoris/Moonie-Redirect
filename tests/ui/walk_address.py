"""A link's address in the three Redirect pages, once Cloudflare is on and a host is set up: the Address select of each
form with what it means, the Address column with each link's state, an error under an edited link, the question a
change that stops a Cloudflare address asks, and a QR code previewed at its host. On the in-memory fake of the tests.
With Cloudflare off, the pages are those of the other walks, unchanged."""

import sys

from kit import (
    PUBLIC_URL,
    ROOT,
    Live,
    control,
    dialog,
    form_title,
    moment,
    rows,
    running,
    selected_row,
    window_at_bottom,
)
from playwright.sync_api import expect

sys.path.insert(0, str(ROOT / "tests"))

from fake_cloudflare import FakeCloudflare  # noqa: E402

import app as redirect  # noqa: E402

GO, WWW = "go.example.com", "www.example.com"


def set_up(live: Live, fake: FakeCloudflare) -> None:
    """go created here, www adopted (a proxied site was there), both through the plan the admin confirms."""
    _account, zone, _list_id = fake.setup()
    fake.add_record(zone, "A", WWW, "203.0.113.7")
    serving = {"redirect.lan"}
    store = live.app.extensions["store"]
    for label, live_ok in (("go", False), ("www", True)):
        plan, _ = redirect.plan_for(fake, store, zone, label, None, serving)
        redirect.apply_plan(
            fake,
            store,
            zone_id=zone,
            label=label,
            fallback=None,
            fingerprint_sent=plan["fingerprint"],
            confirm_live=live_ok,
            serving=serving,
        )


def seed(live: Live, fake: FakeCloudflare) -> None:
    rows_ = (
        {
            "slug": "promo",
            "name": "Promo",
            "target": "https://shop.example/promo",
            "address": GO,
            "at": moment(10, 20, 9, 0),
        },
        {"slug": "wiki", "name": "Wiki", "target": "https://wiki.example/", "at": moment(10, 21, 9, 0)},
        {
            "slug": "taken",
            "name": "Taken",
            "target": "https://shop.example/taken",
            "address": GO,
            "at": moment(10, 22, 9, 0),
        },
        {
            "kind": "nano",
            "name": "Menu",
            "target": "https://cafe.example/menu.pdf",
            "address": GO,
            "at": moment(10, 23, 9, 0),
        },
        {"kind": "nano", "name": "Agenda", "target": "https://cal.example/", "at": moment(10, 24, 9, 0)},
        {
            "kind": "qrcode",
            "name": "Flyer",
            "target": "https://shop.example/flyer",
            "address": GO,
            "at": moment(10, 25, 9, 0),
        },
        {"kind": "qrcode", "name": "Poster", "target": "https://shop.example/poster", "at": moment(10, 26, 9, 0)},
    )
    for row in rows_:
        live.add(row)
    # An item someone made by hand holds one link's address: that link waits in error, the others go
    account = next(iter(fake.state.accounts))
    list_id = next(iter(fake.state.lists[account]))
    fake.add_item(account, list_id, f"{GO}/taken", "https://elsewhere.example/")
    sync = live.app.extensions["sync"]
    for _ in range(4):
        sync.run_pass()
    # A link saved since the last pass is still on its way
    live.clock = moment(10, 27, 9, 0)
    live.add(
        {"slug": "fresh", "name": "Fresh", "target": "https://shop.example/fresh", "address": GO, "at": live.clock}
    )


def links(live: Live) -> None:
    page = live.page
    live.open("/admin/links")
    expect(rows(page).locator(".redirect-address-host")).to_have_text([GO, GO, "LAN", GO])
    expect(selected_row(page).locator(".redirect-name")).to_have_text("Fresh")
    live.shot("links-list")

    rows(page).filter(has_text="Taken").locator(".redirect-name").click()
    expect(page.locator("#page .redirect-address-error")).to_be_visible()
    live.shot("links-edit-error")

    page.locator("#page .redirect-new").click()
    expect(form_title(page)).to_have_text("New link")
    control(page, "slug").fill("summer")
    control(page, "address").select_option(GO)
    expect(page.locator("#page .redirect-host-help")).to_contain_text(f"https://{GO}/summer")
    live.shot("links-new")

    control(page, "slug").fill(".well-known/security.txt")
    control(page, "name").fill("Security")
    control(page, "target").fill("https://example.org/security.txt")
    page.locator("#page .redirect-save").click()
    expect(page.locator("#page .redirect-form [name='address']")).to_have_attribute("aria-invalid", "true")
    live.shot("links-well-known")

    page.locator("#page .redirect-cancel").click()
    rows(page).filter(has_text="Promo").locator(".redirect-name").click()
    control(page, "address").select_option("lan")
    page.locator("#page .redirect-save").click()
    expect(dialog(page).locator(".card-title")).to_have_text("Stop this address?")
    expect(dialog(page).locator("p")).to_contain_text(f"https://{GO}/promo stops working")
    window_at_bottom(page)
    live.shot("links-break-confirm", full_page=False)
    page.keyboard.press("Escape")
    expect(dialog(page)).to_have_count(0)

    page.locator("#page .redirect-cancel").click()
    page.locator("#page .redirect-delete").click()
    expect(dialog(page).locator("p")).to_have_text(f"https://{GO}/promo will stop working for everyone who has it.")
    window_at_bottom(page)
    live.shot("links-delete-confirm", full_page=False)
    dialog(page).locator(".btn-danger").click()
    expect(rows(page)).to_have_count(3)


def nanourls(live: Live) -> None:
    page = live.page
    live.open("/admin/nanourls")
    menu = live.named("nano", "Menu")
    expect(rows(page).filter(has_text="Menu").locator(".redirect-path")).to_have_text(f"https://{GO}/{menu['id']}")
    rows(page).filter(has_text="Menu").locator(".redirect-name").click()
    live.shot("nanourls-list")

    page.locator("#page .redirect-new").click()
    # 7.0.1's link address hint: the public URL a new NanoURL answers on
    expect(page.locator("#page .redirect-host-help")).to_have_text(f"Through the public URL: {PUBLIC_URL}/links/<code>")
    live.shot("nanourls-new-lan")
    control(page, "address").select_option(WWW)
    expect(page.locator("#page .redirect-host-help")).to_contain_text(f"https://{WWW}/<code>")
    live.shot("nanourls-new")


def qrcodes(live: Live) -> None:
    page = live.page
    live.open("/admin/qrcodes")
    flyer = live.named("qrcode", "Flyer")
    expect(selected_row(page).locator(".redirect-name")).to_have_text("Poster")
    rows(page).filter(has_text="Flyer").locator(".redirect-name").click()
    expect(page.locator("#page .redirect-host-help")).to_contain_text(f"https://{GO}/{flyer['id']}")
    live.shot("qrcodes-list")

    # The code moved to another address is another image: the preview shows it before the save
    rows(page).filter(has_text="Poster").locator(".redirect-name").click()
    before = page.locator("#page .redirect-qr-frame img").get_attribute("src")
    control(page, "address").select_option(GO)
    expect(page.locator("#page .redirect-qr-frame img")).not_to_have_attribute("src", before or "")
    live.shot("qrcodes-preview-host")


def walk(live: Live) -> None:
    fake = FakeCloudflare()
    with running(live.browser, live.playwright, live.run, live.walk, cloudflare=fake) as on:
        set_up(on, fake)
        seed(on, fake)
        on.log_in()
        links(on)
        nanourls(on)
        qrcodes(on)
