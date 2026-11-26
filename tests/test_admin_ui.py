"""The admin pages of 9.0.0: the 7.0.1 frame served for the browser, the JSON API reached with the session cookie, the
login that brings a session back to its page, and what the shipped front files may hold."""

# The fixtures of test_app.py are imported, and every test names them as its arguments
# ruff: noqa: F811

import json
import re
from pathlib import Path

import pytest
from test_app import AUTH, PASSWORD, client, clock, create, csrf_of, env, flask_app, login, store  # noqa: F401

import app

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "static" / "ui"
TEMPLATES = ROOT / "templates"
LINK = {"slug": "promo", "name": "Promo", "target": "https://example.test/"}


def session_json(client, method, path, *, csrf=None, site="same-origin", **kwargs):
    headers = {}
    if csrf is not None:
        headers["X-CSRF-Token"] = csrf
    if site is not None:
        headers["Sec-Fetch-Site"] = site
    return client.open(path, method=method, headers=headers | kwargs.pop("headers", {}), **kwargs)


def csrf_meta(page: str) -> str:
    return re.search(r'<meta name="csrf-token" content="([^"]+)"', page).group(1)


# --- The JSON API with the session -----------------------------------------------------------------------------------


def test_the_session_reads_the_api(client):
    login(client)
    create(client, **LINK)
    answer = client.get("/api/links?kind=link")
    assert answer.status_code == 200 and [row["slug"] for row in answer.get_json()["links"]] == ["promo"]


def test_a_change_through_the_session_needs_the_csrf_header(client, store):
    csrf = login(client)
    for token in (None, "", "x" + csrf):
        refused = session_json(client, "POST", "/api/links", csrf=token, json=LINK)
        assert refused.status_code == 403 and refused.get_json() == {"error": "csrf"}
    assert store.list() == []
    created = session_json(client, "POST", "/api/links", csrf=csrf, json=LINK)
    assert created.status_code == 201
    id_ = created.get_json()["id"]
    body = {"target": "https://other.test/"}
    assert session_json(client, "PATCH", f"/api/links/{id_}", json=body).status_code == 403
    assert session_json(client, "PATCH", f"/api/links/{id_}", csrf=csrf, json=body).status_code == 200
    assert session_json(client, "DELETE", f"/api/links/{id_}").status_code == 403
    assert session_json(client, "POST", "/api/qrcodes/preview", json={}).status_code == 403
    assert session_json(client, "DELETE", f"/api/links/{id_}", csrf=csrf).status_code == 204


@pytest.mark.parametrize("site", ["cross-site", "same-site", "none", ""])
def test_a_change_from_another_origin_is_refused_even_with_the_token(client, store, site):
    csrf = login(client)
    refused = session_json(client, "POST", "/api/links", csrf=csrf, site=site, json=LINK)
    assert refused.status_code == 403
    assert store.list() == []


def test_a_browser_that_sends_no_fetch_metadata_still_works(client):
    csrf = login(client)
    assert session_json(client, "POST", "/api/links", csrf=csrf, site=None, json=LINK).status_code == 201


@pytest.mark.parametrize("header", ["Bearer wrong", "", "Basic x", "Bearer"])
def test_a_bearer_header_never_falls_back_to_the_cookie(client, header):
    login(client)
    answer = client.get("/api/links", headers={"Authorization": header})
    assert answer.status_code == 401 and answer.get_json() == {"error": "unauthorized"}


def test_the_bearer_token_needs_no_csrf_header(client):
    login(client)
    assert client.post("/api/links", json=LINK, headers=AUTH).status_code == 201


def test_no_session_is_401_json(client):
    answer = client.get("/api/status")
    assert answer.status_code == 401
    assert answer.get_json() == {"error": "unauthorized"}
    assert answer.headers["WWW-Authenticate"] == "Bearer"


def test_an_expired_session_is_401_json_and_its_pages_go_to_the_login(client, monkeypatch):
    login(client)
    assert client.get("/api/status").status_code == 200
    later = app.time.time() + 13 * 3600
    monkeypatch.setattr("itsdangerous.timed.time.time", lambda: later)
    answer = client.get("/api/status")
    assert answer.status_code == 401 and answer.get_json() == {"error": "unauthorized"}
    assert client.get("/admin/nanourls").headers["Location"] == "/login?next=/admin/nanourls"


def test_status_says_the_version_and_counts_every_kind(client):
    login(client)
    create(client, **LINK)
    create(client, kind="nano", name="N", target="https://example.test/")
    assert client.get("/api/status").get_json() == {"version": app.VERSION, "links": 2}
    assert client.get("/api/status", headers=AUTH).get_json() == {"version": app.VERSION, "links": 2}


def test_the_list_sends_a_logo_as_stored_without_opening_it(client, monkeypatch):
    """A list of QR codes never decodes nor parses their logos (each was checked whole when written); one QR code read
    alone, its drawing and its preview still check the logo whole."""
    logo = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4="
    row = create(client, kind="qrcode", name="Q", target="https://example.test/", design={"logo": logo})
    opened = []
    real = app._logo_ok
    monkeypatch.setattr(app, "_logo_ok", lambda kind, content: opened.append(kind) or real(kind, content))
    listed = client.get("/api/links", headers=AUTH).get_json()["links"]
    assert listed[0]["design"]["logo"] == logo and opened == []
    assert client.get(f"/api/links/{row['id']}", headers=AUTH).get_json()["design"]["logo"] == logo
    assert opened == ["svg+xml"]


def test_the_list_still_says_a_broken_design_is_unreadable(client, store):
    row = create(client, kind="qrcode", name="Q", target="https://example.test/")
    with store.write() as conn:
        conn.execute(f"UPDATE {app.TABLE} SET design = ? WHERE id = ?", ('{"logo": "nope"}', row["id"]))
    assert client.get("/api/links", headers=AUTH).get_json()["links"][0]["design"] is None


def test_a_page_whose_token_a_new_login_replaced_takes_the_new_one(client, store):
    """Another tab signed in again: this page's token is refused, /api/session gives the session's, and it works."""
    stale = login(client)
    login(client)
    answer = session_json(client, "POST", "/api/links", csrf=stale, json=LINK)
    assert answer.status_code == 403 and answer.get_json() == {"error": "csrf"}
    fresh = client.get("/api/session").get_json()["csrf"]
    assert fresh != stale
    assert session_json(client, "POST", "/api/links", csrf=fresh, json=LINK).status_code == 201
    assert len(store.list()) == 1


def test_the_session_token_is_for_the_session_only(client):
    assert client.get("/api/session").status_code == 401
    assert client.get("/api/session", headers=AUTH).status_code == 403  # a key never has a session (D28)
    login(client)
    answer = client.get("/api/session")
    assert answer.headers["Cache-Control"] == "no-store"
    assert not any(name.lower().startswith("access-control-") for name in answer.headers.keys())


def test_version_is_9_4_0():
    assert app.VERSION == "9.4.0"


# --- The frame --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["links", "nanourls", "qrcodes", "settings"])
def test_each_page_gets_the_frame_with_its_csrf_token_and_policy(client, page):
    csrf = login(client)
    answer = client.get(f"/admin/{page}?link=abc")
    assert answer.status_code == 200
    html = answer.get_data(as_text=True)
    assert csrf_meta(html) == csrf
    assert '<script type="module" src="/static/ui/shell.js"></script>' in html
    assert '<link rel="stylesheet" href="/static/settings.css" />' in html
    assert f"redirect {app.VERSION}" in html
    policy = answer.headers["Content-Security-Policy"]
    assert answer.headers["Content-Security-Policy"] == app.PAGE_POLICY
    for directive in (
        "script-src 'self'",
        "connect-src 'self'",
        "worker-src 'none'",
        "require-trusted-types-for 'script'",
        "trusted-types 'none'",
        "style-src 'self'",
        "img-src 'self' data:",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
    ):
        assert directive in policy
    assert "unsafe" not in policy
    assert answer.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("page", ["links", "settings"])
def test_the_sidebar_foot_holds_the_logout_glyph_with_its_form(client, page):
    csrf = login(client)
    html = client.get(f"/admin/{page}").get_data(as_text=True)
    foot = re.search(r'<div class="nav-foot">(.*?)</form>\s*</div>', html, re.S).group(1)
    assert '<div class="nav-foot-links" id="nav-foot-links"></div>' in foot
    assert '<form class="logout-form" method="post" action="/logout">' in foot
    assert f'<input type="hidden" name="csrf" value="{csrf}" />' in foot
    assert '<button class="nav-icon" id="logout" type="submit" aria-label="Log out" title="Log out"></button>' in foot
    # The text button and the Administration section are gone: the shell draws the menu and the glyphs
    assert "nav-logout" not in html
    assert ">Log out<" not in html
    assert "Administration" not in html


def test_the_logout_glyph_still_posts_the_logout(client):
    login(client)
    html = client.get("/admin/links").get_data(as_text=True)
    token = re.search(r'<input type="hidden" name="csrf" value="([^"]+)" />', html).group(1)
    answer = client.post("/logout", data={"csrf": token})
    assert answer.headers["Location"] == "/login?out=1"
    assert client.get("/api/status").status_code == 401


def test_the_material_symbols_licence_ships_with_its_glyphs():
    licence = (UI / "LICENSE-material-symbols.txt").read_text(encoding="utf-8")
    assert "Apache License" in licence
    assert "Version 2.0, January 2004" in licence
    icons = (UI / "icons.js").read_text(encoding="utf-8")
    source = "// Source: @material-symbols/svg-400 0.48.3 (outlined/settings.svg, outlined/logout.svg), Apache-2.0"
    assert source in icons
    assert "LICENSE-material-symbols.txt" in icons


def test_the_cloudflare_page_is_the_cloudflare_tab_of_settings(client):
    """A bookmark of the 9.2 page lands on the tab (D29), whatever it carried, and the tab is a page that stays."""
    login(client)
    for path in ("/admin/cloudflare", "/admin/cloudflare?keys=1", "/admin/cloudflare?tab=security"):
        answer = client.get(path)
        assert answer.status_code == 302, path
        assert answer.headers["Location"] == "/admin/settings?tab=cloudflare", path
    landed = client.get("/admin/cloudflare", follow_redirects=True)
    assert landed.status_code == 200
    assert landed.request.path == "/admin/settings" and landed.request.args["tab"] == "cloudflare"
    assert '<main class="page" id="page"' in landed.get_data(as_text=True)
    assert "cloudflare" not in app.ADMIN_PAGES


def test_the_cloudflare_page_asks_for_a_login_then_lands_on_the_tab(client):
    answer = client.get("/admin/cloudflare")
    assert answer.status_code == 302
    assert answer.headers["Location"] == "/login?next=/admin/cloudflare"
    csrf = csrf_of(client, "/login?next=/admin/cloudflare")
    back = client.post("/login", data={"password": PASSWORD, "csrf": csrf, "next": "/admin/cloudflare"})
    assert back.headers["Location"] == "/admin/cloudflare"
    assert client.get("/admin/cloudflare").headers["Location"] == "/admin/settings?tab=cloudflare"


def test_home_and_admin_go_to_links(client):
    assert client.get("/").headers["Location"] == "/admin/links"
    login(client)
    assert client.get("/admin").headers["Location"] == "/admin/links"


@pytest.mark.parametrize(
    "path",
    [
        "/admin/cloudflares",
        "/admin/cloudflare/",
        "/admin/cloudflare/x",
        "/admin/settings/security",
        "/admin/links/new",
        "/admin/links/abc",
        "/admin/qrcodes/x.svg",
    ],
)
def test_any_other_admin_address_is_the_frame_with_a_404(client, path):
    login(client)
    answer = client.get(path)
    assert answer.status_code == 404
    assert '<main class="page" id="page"' in answer.get_data(as_text=True)


def test_the_server_rendered_forms_are_gone(client, store):
    csrf = login(client)
    row = create(client, **LINK)
    form = {"csrf": csrf} | LINK
    for path in ("/admin/links/new", f"/admin/links/{row['id']}", f"/admin/links/{row['id']}/delete"):
        assert client.post(path, data=form).status_code == 405
    assert store.get(row["id"])["target"] == LINK["target"]
    for name in ("form.html", "list.html"):
        assert not (TEMPLATES / name).exists()


def test_the_admin_needs_a_login_and_keeps_where_it_was(client):
    answer = client.get("/admin/qrcodes?qr=abc&new=1")
    assert answer.status_code == 302
    assert answer.headers["Location"] == "/login?next=/admin/qrcodes?qr%3Dabc%26new%3D1"


def test_the_shell_module_and_strings_are_served_as_what_they_are(client):
    assert client.get("/static/ui/shell.js").mimetype == "text/javascript"
    assert client.get("/static/ui/en.json").mimetype == "application/json"


# --- Login ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "kept"),
    [
        ("/admin/links", True),
        ("/admin/qrcodes?qr=abc&new=1", True),
        ("/admin/links#top", True),
        ("/admin", False),
        ("/adminx/links", False),
        ("//evil.test/admin/", False),
        ("/admin/../login", False),
        ("/admin/%2e%2e/login", False),
        ("/admin/%2E%2E/%2E%2E/x", False),
        ("/admin/..%2flogin", False),
        ("/admin/\\evil", False),
        ("/admin/%5cevil", False),
        ("/admin/ links", False),
        ("/admin/\nlinks", False),
        ("https://evil.test/admin/", False),
        (None, False),
        (["/admin/links"], False),
    ],
)
def test_safe_next(value, kept):
    assert app.safe_next(value) == (value if kept else None)


def test_the_login_goes_back_to_next(client):
    csrf = csrf_of(client, "/login?next=/admin/qrcodes?qr%3Dabc")
    page = client.get("/login?next=/admin/qrcodes?qr%3Dabc").get_data(as_text=True)
    assert '<input type="hidden" name="next" value="/admin/qrcodes?qr=abc" />' in page
    answer = client.post("/login", data={"password": PASSWORD, "csrf": csrf, "next": "/admin/qrcodes?qr=abc"})
    assert answer.status_code == 302 and answer.headers["Location"] == "/admin/qrcodes?qr=abc"


@pytest.mark.parametrize("next_", ["//evil.test/", "https://evil.test/", "/admin/../login", "/login"])
def test_the_login_never_goes_elsewhere(client, next_):
    csrf = csrf_of(client)
    answer = client.post("/login", data={"password": PASSWORD, "csrf": csrf, "next": next_})
    assert answer.headers["Location"] == "/admin/links"
    assert 'name="next"' not in client.get("/login", query_string={"next": next_}).get_data(as_text=True)


def test_the_login_says_why_it_is_shown(client):
    expired = client.get("/login?expired=1").get_data(as_text=True)
    assert "Your session has ended. Log in again to continue." in expired and "dot-warning" in expired
    out = client.get("/login?out=1").get_data(as_text=True)
    assert "You are logged out." in out and "dot-success" in out
    assert "auth-notice" not in client.get("/login").get_data(as_text=True)


def test_the_login_help_names_the_settings_password_before_the_file(client):
    # A password changed in Settings wins over the file, so the help must not send the reader to the file alone
    page = client.get("/login").get_data(as_text=True)
    help_text = re.search(r'<span class="field-help" id="password-help">([^<]*)</span>', page).group(1)
    assert help_text == (
        "The administrator password: the one set in Settings, else the one line of the file"
        " MOONIE_REDIRECT_PASSWORD_FILE names."
    )


def test_a_wrong_password_is_said_under_its_field(client):
    answer = client.post("/login?expired=1", data={"password": "nope", "csrf": csrf_of(client)})
    page = answer.get_data(as_text=True)
    assert answer.status_code == 401
    assert '<span class="field-error" id="password-error">Wrong password. Try again.</span>' in page
    assert 'aria-invalid="true"' in page
    # What the notice said is no longer the news
    assert "auth-notice" not in page


def test_a_braked_login_is_said_at_the_top_of_the_form(client):
    csrf = csrf_of(client)
    client.post("/login", data={"password": "nope", "csrf": csrf})
    answer = client.post("/login", data={"password": "nope", "csrf": csrf})
    assert answer.status_code == 429
    said = '<p class="form-error" role="alert">Too many attempts. Try again in 1 s.</p>'
    assert said in answer.get_data(as_text=True)


def test_logout_says_so_on_the_login(client):
    csrf = login(client)
    answer = client.post("/logout", data={"csrf": csrf})
    assert answer.headers["Location"] == "/login?out=1"
    assert client.get("/api/status").status_code == 401


# --- What the shipped front files hold --------------------------------------------------------------------------------

MODULES = sorted(UI.glob("*.js"))
HTML_SINKS = re.compile(
    r"\.(innerHTML|outerHTML|insertAdjacentHTML|srcdoc)\b|document\.write|\beval\s*\(|new Function\b"
    r"|DOMParser|createContextualFragment|setTimeout\(\s*['\"`]"
)
KEY = re.compile(r"'((?:redirect|cloudflare|common|state|notfound|errors|settings|instance|keys|webhook)\.[a-z0-9_]+)'")


def test_the_modules_exist():
    assert {path.name for path in MODULES} == {
        "cloudflare.js",
        "cloudflare-logic.js",
        "common.js",
        "icons.js",
        "kit.js",
        "lib.js",
        "links.js",
        "nanourls.js",
        "qrcodes.js",
        "settings.js",
        "settings-cloudflare.js",
        "settings-logic.js",
        "settings-security.js",
        "settings-webhook.js",
        "shell.js",
    }


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_no_module_writes_html(path):
    assert not HTML_SINKS.search(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", sorted(TEMPLATES.glob("*.html")), ids=lambda path: path.name)
def test_no_template_holds_a_script_or_a_handler(path):
    html = path.read_text(encoding="utf-8")
    assert not re.search(r"\son[a-z]+\s*=", html, re.I)
    assert not re.search(r"\sstyle\s*=", html, re.I)
    for script in re.findall(r"<script\b[^>]*>", html, re.I):
        assert re.fullmatch(r'<script type="module" src="[^"]+">', script), script
    assert "javascript:" not in html.lower()


@pytest.mark.parametrize(
    "path",
    [*MODULES, *(ROOT / "static").glob("*.css")],
    ids=lambda path: path.name,
)
def test_each_front_file_says_where_it_comes_from(path):
    first = path.read_text(encoding="utf-8").splitlines()[0]
    if path.name in ("tokens.css",):
        return
    assert "Source:" in first, f"{path.name} starts with {first!r}"


def test_every_text_a_module_names_exists_and_every_text_is_used():
    strings = json.loads((UI / "en.json").read_text(encoding="utf-8"))
    used = set()
    for path in MODULES:
        used |= set(KEY.findall(path.read_text(encoding="utf-8")))
    assert sorted(used - set(strings)) == []
    assert sorted(set(strings) - used) == []


def test_the_texts_are_english_only():
    assert sorted(path.name for path in UI.glob("*.json")) == ["en.json"]
