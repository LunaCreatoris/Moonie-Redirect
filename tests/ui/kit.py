"""What the walks of the GUI goldens share: the app in this process on a fresh database, with a clock and random draws
the walk owns, a browser page logged in on it, and the locators of the pages."""

import logging
import re
import sqlite3
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, Route, expect
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import app as redirect  # noqa: E402

# The server's line per request would drown what the walks print
logging.getLogger("werkzeug").setLevel(logging.WARNING)

TOKEN = "t" * 40
PASSWORD = "correct horse battery"
# The public base URL of 7.0.1's captures, so the addresses on screen read the same
PUBLIC_URL = "http://redirect.lan:8420"
VIEWPORT = {"width": 1440, "height": 980}
# Every face the pages draw with, loaded before each capture
FACES = ("400 16px Manrope", "500 16px Manrope", "600 16px Manrope", "700 16px Manrope", "800 16px Manrope")
MONO_FACES = ('400 16px "IBM Plex Mono"', '500 16px "IBM Plex Mono"')
# The time the browser believes it is: no page shows it, and the copy feedback never times out under it
BROWSER_TIME = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
# Reports every refusal of the page's policy to the walk, as it happens, whatever the page does next
WATCH_POLICY = """
document.addEventListener('securitypolicyviolation', (event) => {
  window.reportPolicyViolation(`${event.violatedDirective} ${event.blockedURI} ${event.sourceFile}:${event.lineNumber}`)
}, true)
"""
LONG_TARGET = "https://files.example/" + "a" * (2048 - len("https://files.example/"))
PATH_255 = "/".join(["segment-of-a-long-path"] * 11)[:255].rstrip("/-")


def moment(month: int, day: int, hour: int, minute: int) -> str:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Codes:
    """The ids and suggested slugs the app draws, as 7.0.1's captures showed them: the n-th draw writes the number
    2n + 2 in the code alphabet, lowest digit first, so a series differs from its first character (`62222222`,
    `82222222`...). Everything else the app draws (session key, session id, CSRF token) stays random, and never
    shows."""

    def __init__(self) -> None:
        self.drawn = 1

    def __call__(self, length: int) -> str:
        self.drawn += 1
        number, characters = 2 * self.drawn, []
        for _ in range(length):
            number, digit = divmod(number, len(redirect.CODE_ALPHABET))
            characters.append(redirect.CODE_ALPHABET[digit])
        return "".join(characters)


class Live:
    """The app on a fresh database, served on a free port, with a browser page logged in and the API's token at hand."""

    def __init__(
        self,
        browser: Browser,
        playwright: Any,
        run: "Run",
        walk: str,
        folder: Path,
        *,
        password: bool = True,
        cloudflare: Any = None,
        env: dict[str, str] | None = None,
        prepare: Any = None,
        app_options: dict[str, Any] | None = None,
    ) -> None:
        self.browser, self.playwright = browser, playwright
        self.run = run
        self.walk = walk
        self.clock = moment(10, 1, 8, 0)
        (folder / "password").write_text(PASSWORD + "\n", encoding="utf-8")
        (folder / "token").write_text(TOKEN + "\n", encoding="utf-8")
        self.db = folder / "data" / "redirect.db"
        redirect.now = lambda: self.clock
        redirect.draw_code = Codes()
        # The login brake is the process's: a walk starts with no failed login behind it
        redirect._last_failure = float("-inf")
        self.folder = folder
        settings = {
            "MOONIE_REDIRECT_DB": str(self.db),
            "MOONIE_REDIRECT_API_TOKEN_FILE": str(folder / "token"),
            "MOONIE_REDIRECT_PUBLIC_BASE_URL": PUBLIC_URL,
        }
        if password:
            settings["MOONIE_REDIRECT_PASSWORD_FILE"] = str(folder / "password")
        settings |= env or {}
        # What the walk writes before the app opens the database: rows only an older run or another key could leave
        if prepare is not None:
            prepare(self.db)
        # Cloudflare is the in-memory fake of the tests, never the real API; with none it is off. `app_options` hand the
        # app the fakes of the settings: what makes a client of a token set there, and a webhook that reaches a loopback
        # receiver
        self.app = redirect.create_app(settings, cloudflare=cloudflare, **(app_options or {}))
        # One request at a time, in the order they come: the draws follow the walk, never a race between threads
        self.server = make_server("127.0.0.1", 0, self.app, threaded=False)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.context = browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=1,
            locale="en-US",
            timezone_id="UTC",
            reduced_motion="reduce",
            color_scheme="dark",
            base_url=self.base,
        )
        self.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=self.base)
        self.page = self.context.new_page()
        # A script error or a refusal of the policy fails the capture: a golden of a broken page is no golden
        self.errors: list[str] = []
        self.page.on("pageerror", lambda error: self.errors.append(f"pageerror: {error}"))
        self.page.expose_function("reportPolicyViolation", lambda line: self.errors.append(f"policy: {line}"))
        self.page.add_init_script(WATCH_POLICY)
        self.page.clock.install(time=BROWSER_TIME)
        self.page.clock.pause_at(BROWSER_TIME)
        self.api = playwright.request.new_context(
            base_url=self.base, extra_http_headers={"Authorization": f"Bearer {TOKEN}"}
        )

    def check_clean(self) -> None:
        """Fails on any script error or refusal of the policy seen since the walk began."""
        assert not self.errors, f"{self.walk}: " + "; ".join(self.errors)

    def close(self) -> None:
        self.api.dispose()
        self.context.close()
        self.server.shutdown()
        self.thread.join()

    # --- The API, as a script would use it

    def call(self, method: str, path: str, *, status: int, data: Any = None) -> Any:
        answer = self.api.fetch(path, method=method, data=data)
        assert answer.status == status, f"{method} {path}: {answer.status} {answer.text()}"
        return answer.json() if answer.body() else None

    def add(self, row: dict[str, Any]) -> dict[str, Any]:
        """A row created at its own moment, `at`."""
        self.clock = row["at"]
        return self.call("POST", "/api/links", status=201, data={k: v for k, v in row.items() if k != "at"})

    def rows(self, kind: str) -> list[dict[str, Any]]:
        return self.call("GET", f"/api/links?kind={kind}", status=200)["links"]

    def named(self, kind: str, name: str) -> dict[str, Any]:
        return next(row for row in self.rows(kind) if row["name"] == name)

    def remove(self, id_: str) -> None:
        self.call("DELETE", f"/api/links/{id_}", status=204)

    def write_design(self, id_: str, stored: str) -> None:
        """A design written by hand, as only an edit of the database could leave it."""
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE redirect_links SET design = ? WHERE id = ?", (stored, id_))
        conn.close()

    # --- The browser

    def log_in(self) -> None:
        self.page.goto("/login")
        self.page.locator("input[name='password']").fill(PASSWORD)
        self.page.locator(".auth-submit").click()
        expect(self.page.locator("#page")).to_have_attribute("data-state", "loaded")
        # The page the login lands on drew a suggested slug: 7.0.1's series starts with the walk's own rows
        redirect.draw_code = Codes()

    def open(self, path: str, state: str = "loaded") -> None:
        self.page.goto(path)
        expect(self.page.locator("#page")).to_have_attribute("data-state", state)

    def shot(self, name: str, *, full_page: bool = True) -> None:
        """One golden. The pointer leaves what it pressed, every face is loaded, and every image is drawn."""
        page = self.page
        if full_page:
            page.mouse.move(0, 0)
        page.evaluate(
            """async (faces) => {
              await Promise.all(faces.map((face) => document.fonts.load(face)))
              await document.fonts.ready
            }""",
            [*FACES, *MONO_FACES],
        )
        until(page, "() => [...document.images].every((img) => img.complete)")
        self.check_clean()
        self.run.save(page, f"{self.walk}-{name}", full_page=full_page)


class Run:
    """Where the goldens of this run go, and which were written."""

    def __init__(self, out: Path) -> None:
        self.out = out
        self.written: list[str] = []

    def save(self, page: Page, name: str, *, full_page: bool) -> None:
        assert name not in self.written, f"{name} captured twice"
        self.written.append(name)
        page.screenshot(
            path=str(self.out / f"{name}.png"), full_page=full_page, animations="disabled", caret="hide", scale="css"
        )


@contextmanager
def running(browser: Browser, playwright: Any, run: Run, walk: str, **options: Any) -> Iterator[Live]:
    """The app of one walk, gone with its files at the end. `options` go to Live."""
    with tempfile.TemporaryDirectory() as folder:
        live = Live(browser, playwright, run, walk, Path(folder), **options)
        try:
            yield live
            live.check_clean()
        finally:
            live.close()


# --- What every page walk shares --------------------------------------------------------------------------------------


def state(page: Page, name: str) -> None:
    expect(page.locator("#page")).to_have_attribute("data-state", name)


def rows(page: Page):
    """The rows of the list, without the row of headers."""
    return page.locator("#page .table [role='row']:has([role='cell'])")


def row_of(page: Page, path: str):
    return rows(page).filter(has=page.locator(".redirect-path", has_text=path))


def selected_row(page: Page):
    return page.locator("#page .table [role='row'][aria-current='true']")


def control(page: Page, name: str):
    return page.locator(f"#page .redirect-form [name='{name}']")


def error_of(page: Page, name: str):
    return (
        control(page, name)
        .locator("xpath=ancestor::*[contains(concat(' ', @class, ' '), ' field ')][1]")
        .locator(".field-error")
    )


def form_title(page: Page):
    return page.locator("#page .redirect-form .card-title")


def form_top(page: Page):
    return page.locator("#page .redirect-form .form-error")


def notice(page: Page):
    return page.locator("#page .redirect-notice")


def save(page: Page):
    return page.locator("#page .redirect-save")


def dialog(page: Page):
    return page.locator("dialog[open]")


def held(page: Page, pattern: "str | re.Pattern[str]") -> list[Route]:
    """Requests to `pattern` stop on their way, until the walk answers them."""
    stopped: list[Route] = []
    page.route(pattern, lambda route: stopped.append(route))
    return stopped


def until_held(page: Page, stopped: list[Route]) -> None:
    for _ in range(200):
        if stopped:
            return
        page.wait_for_timeout(25)
    raise AssertionError("no request was held")


def until(page: Page, function: str, timeout_ms: int = 5000) -> None:
    """Waits until `function` answers true in the page. Not wait_for_function: past its first try it evaluates a string,
    which the page's policy refuses, as it should."""
    for _ in range(timeout_ms // 25):
        if page.evaluate(function):
            return
        page.wait_for_timeout(25)
    raise AssertionError(f"never true: {function}")


def refuse_copies(page: Page) -> None:
    page.evaluate(
        """() => {
          navigator.clipboard.writeText = () => Promise.reject(new Error('refused'))
          document.execCommand = () => false
        }"""
    )


def window_on(locator) -> None:
    """The window scrolled so that `locator` stands in its middle, as a press there leaves it."""
    locator.evaluate(
        """(el) => {
          const box = el.getBoundingClientRect()
          window.scrollBy({ top: box.top + box.height / 2 - window.innerHeight / 2, behavior: 'instant' })
        }"""
    )


def window_at_bottom(page: Page) -> None:
    page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")


def loading_and_error(live: Live, page_path: str, list_query: str) -> None:
    """The skeleton while the list is on its way, then the error state when it fails."""
    page = live.page
    pattern = re.compile(rf".*/api/links\?kind={list_query}$")
    stopped = held(page, pattern)
    page.goto(page_path)
    state(page, "loading")
    until_held(page, stopped)
    live.shot("loading")
    stopped[0].fulfill(status=500, content_type="application/json", body='{"error": "internal"}')
    state(page, "error")
    expect(page.locator("#page .state-request")).to_have_text("GET /api/links → 500")
    live.shot("load-error")
    page.unroute(pattern)
