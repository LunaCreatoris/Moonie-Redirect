"""The app in-process with Flask's test client, on a fresh SQLite file per test."""

import base64
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

import app

TOKEN = "t" * 40
PASSWORD = "correct horse battery staple"
BASE = "https://go.example.test"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TODAY = datetime.now(UTC).date()


@pytest.fixture
def env(tmp_path):
    (tmp_path / "password").write_text(PASSWORD + "\n")
    (tmp_path / "token").write_text(TOKEN + "\n")
    return {
        "MOONIE_REDIRECT_DB": str(tmp_path / "data" / "redirect.db"),
        "MOONIE_REDIRECT_PASSWORD_FILE": str(tmp_path / "password"),
        "MOONIE_REDIRECT_API_TOKEN_FILE": str(tmp_path / "token"),
        "MOONIE_REDIRECT_PUBLIC_BASE_URL": BASE + "/",
    }


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """A clock the test moves by hand, starting with no failed login behind it."""
    now = [1000.0]
    monkeypatch.setattr(app.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(app, "_last_failure", float("-inf"))
    return now


@pytest.fixture
def flask_app(env):
    return app.create_app(env)


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def store(flask_app):
    return flask_app.extensions["store"]


def create(client, **body):
    response = client.post("/api/links", json=body, headers=AUTH)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def csrf_of(client, path="/login"):
    page = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


def login(client):
    response = client.post("/login", data={"password": PASSWORD, "csrf": csrf_of(client)})
    assert response.status_code == 302
    return csrf_of(client, "/admin/links")


# --- Redirects -------------------------------------------------------------------------------------------------------


def test_redirect_by_slug_sends_the_stored_target(client):
    create(client, slug="promo", name="Promo", target="https://shop.example.test/page?a=1")
    response = client.get("/redirect/promo")
    assert response.status_code == 302
    assert response.headers["Location"] == "https://shop.example.test/page?a=1"
    assert response.headers["Cache-Control"] == "no-store"


def test_redirect_by_code_and_301(client):
    link = create(client, slug="perm", name="Perm", target="https://example.test/", http_status=301)
    response = client.get(f"/links/{link['id']}")
    assert response.status_code == 301
    assert response.headers["Location"] == "https://example.test/"


def test_an_edit_without_a_code_keeps_the_stored_one(client):
    """The admin pages send no `http_status` (decision D20): an edit keeps a stored 301, and a new link is 302."""
    link = create(client, slug="perm", name="Perm", target="https://example.test/", http_status=301)
    body = {"name": "Perm 2", "slug": "perm", "target": "https://other.test/", "expires_on": None}
    changed = client.patch(f"/api/links/{link['id']}", json=body, headers=AUTH)
    assert changed.status_code == 200
    assert changed.get_json()["http_status"] == 301
    assert client.get("/redirect/perm").status_code == 301
    assert create(client, slug="fresh", name="Fresh", target="https://example.test/")["http_status"] == 302


def test_visit_query_string_is_never_forwarded(client):
    create(client, slug="promo", name="Promo", target="https://shop.example.test/page")
    response = client.get("/redirect/promo?utm_source=twitch&token=x")
    assert response.headers["Location"] == "https://shop.example.test/page"


def test_head_answers_like_get_with_no_body(client):
    create(client, slug="promo", name="Promo", target="https://shop.example.test/")
    response = client.head("/redirect/promo")
    assert response.status_code == 302
    assert response.headers["Location"] == "https://shop.example.test/"
    assert response.data == b""


def test_nested_slug_and_named_paths(client):
    create(client, slug="a/b.c/d-e", name="Deep", target="https://example.test/deep")
    nano = create(client, kind="nano", name="Été 2026!", target="https://example.test/nano")
    assert nano["slug"] == "NanoURL/Ete-2026"
    assert client.get("/redirect/a/b.c/d-e").headers["Location"] == "https://example.test/deep"
    assert client.get("/redirect/NanoURL/Ete-2026").headers["Location"] == "https://example.test/nano"
    assert nano["public_url"] == BASE + "/redirect/NanoURL/Ete-2026"
    assert nano["short_url"] == BASE + "/links/" + nano["id"]


@pytest.mark.parametrize(
    "path",
    [
        "/redirect/nothing",
        "/redirect/<script>alert(1)</script>",
        "/links/zzzzzzzz",
        "/links/no-code!",
        "/redirect/a//b",
    ],
)
def test_unknown_is_404_and_never_echoes_the_path(client, path):
    for accept in ("text/html", "*/*"):
        response = client.get(path, headers={"Accept": accept})
        assert response.status_code == 404
        assert response.headers["Cache-Control"] == "no-store"
        body = response.get_data(as_text=True)
        assert "script" not in body and "nothing" not in body and "zzzz" not in body


def test_a_path_with_a_final_newline_is_not_an_alias(client):
    create(client, slug="promo", name="Promo", target="https://example.test/")
    assert client.get("/redirect/promo%0A").status_code == 404
    assert client.get("/redirect/promo%20").status_code == 404


def test_unreadable_database_is_503_with_retry_after(client, store, monkeypatch):
    def broken(*_args):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(store, "hop", broken)
    response = client.get("/redirect/promo")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.headers["Cache-Control"] == "no-store"


def test_plain_404_body(client):
    assert client.get("/redirect/missing").get_data(as_text=True) == "404"


def test_expiry_is_inclusive_of_its_day_in_utc(client):
    create(client, slug="today", name="T", target="https://example.test/", expires_on=TODAY.isoformat())
    create(client, slug="gone", name="G", target="https://example.test/", expires_on=(TODAY - timedelta(1)).isoformat())
    assert client.get("/redirect/today").status_code == 302
    assert client.get("/redirect/gone").status_code == 404


def test_visit_never_writes(client, store, monkeypatch):
    create(client, slug="promo", name="Promo", target="https://example.test/")
    monkeypatch.setattr(
        store,
        "_connect",
        lambda readonly=False: (
            pytest.fail("a write connection") if not readonly else app.Store._connect(store, readonly=True)
        ),
    )
    assert client.get("/redirect/promo").status_code == 302


def test_visit_log_has_path_and_status_never_the_target(client, caplog):
    create(client, slug="promo", name="Promo", target="https://example.test/?secret=s3")
    with caplog.at_level("INFO", logger="moonie-redirect"):
        client.get("/redirect/promo")
    visits = [r.getMessage() for r in caplog.records if r.getMessage().startswith("visit")]
    assert visits == ["visit path='/redirect/promo' status=302"]
    assert "s3" not in caplog.text


def test_location_is_quoted_as_7_0_1_sent_it(client, store):
    # A row imported from 7.0.1 may hold a character its server quoted on the way out
    row = create(client, slug="q", name="Q", target="https://example.test/")
    store.update(row["id"], {"target": "https://example.test/a|b{c}%20d"})
    assert client.get("/redirect/q").headers["Location"] == "https://example.test/a%7Cb%7Bc%7D%20d"


def test_hand_edited_row_with_another_scheme_is_not_followed(client, store):
    row = create(client, slug="x", name="X", target="https://example.test/")
    store.update(row["id"], {"target": "javascript:alert(1)"})
    assert client.get("/redirect/x").status_code == 404


def test_a_hand_edited_target_with_cr_lf_comes_out_quoted(client, store):
    row = create(client, slug="crlf", name="C", target="https://example.test/")
    store.update(row["id"], {"target": "https://example.test/a\r\nSet-Cookie: x=1"})
    response = client.get("/redirect/crlf")
    assert response.status_code == 302
    assert response.headers["Location"] == "https://example.test/a%0D%0ASet-Cookie:%20x=1"
    assert "Set-Cookie" not in response.headers


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "version": app.VERSION}


# --- Validation ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://example.test/a b", None),
        ("javascript:alert(1)", None),
        ("JAVASCRIPT://example.test/%0aalert(1)", None),
        ("data:text/html,x", None),
        ("/relative", None),
        ("//example.test/", None),
        ("ftp://example.test/", None),
        ("https://", None),
        ("https://exa\\mple.test@evil.test/", None),
        ("https://example.test:99999/", None),
        ("https://example.test/\x00", None),
        ("https://exa mple.test/", None),
        ("https://" + "a" * 2050 + ".test/", None),
        ("  https://example.test/  ", "https://example.test/"),
        ("HTTPS://Example.test:8443/x?y=1#z", "https://Example.test:8443/x?y=1#z"),
        ("https://bücher.example/straße", "https://xn--bcher-kva.example/stra%C3%9Fe"),
        ("https://[2001:db8::1]:8080/", "https://[2001:db8::1]:8080/"),
        ("https://user:pw@example.test/", "https://user:pw@example.test/"),
        ("https://example.test/a|b", "https://example.test/a%7Cb"),
        ("https://example.test/%7C", "https://example.test/%7C"),
        ("http://192.168.1.10:8080/x", "http://192.168.1.10:8080/x"),
    ],
)
def test_target(value, expected):
    if expected is None:
        with pytest.raises(app.Invalid):
            app.check_target(value)
    else:
        assert app.check_target(value) == expected


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("promo", True),
        ("a/b/c", True),
        ("A.b_c-9", True),
        ("a" * 255, True),
        ("a" * 256, False),
        ("", False),
        ("a//b", False),
        ("a/", False),
        ("../x", False),
        ("a/./b", False),
        ("a b", False),
        ("é", False),
        ("api/x", False),
        ("NANOURL/x", False),
        ("qrcodes", False),
        ("apis/x", True),
    ],
)
def test_user_slug(value, ok):
    if ok:
        assert app.check_user_slug(value) == value
    else:
        with pytest.raises(app.Invalid):
            app.check_user_slug(value)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("a//b", "no empty segment: no '/' at either end, no '//'"),
        ("/a", "no empty segment: no '/' at either end, no '//'"),
        ("a/", "no empty segment: no '/' at either end, no '//'"),
        ("a/./b", "no '.' or '..' segment"),
        ("..", "no '.' or '..' segment"),
        ("a b", "letters, digits, '.', '_', '-' in '/'-separated segments"),
        ("a/..b/\u00e9", "letters, digits, '.', '_', '-' in '/'-separated segments"),
    ],
)
def test_a_bad_slug_says_which_rule_it_breaks(value, message):
    """The three shapes 7.0.1 told apart, so the page says the same sentence."""
    with pytest.raises(app.Invalid, match="^" + re.escape(message) + "$"):
        app.check_slug(value)


@pytest.mark.parametrize(
    "value", ["", "   ", "x" * 101, "a\u202eb", "a\x07b", "\u0301", "\u3000\u0301", "a\u17b4b", "\uffa0x"]
)
def test_name_refused(value):
    with pytest.raises(app.Invalid):
        app.check_name(value)


@pytest.mark.parametrize(
    "value", ["Caf\u00e9", "Cafe\u0301", "\U0001f389", "\u2764\ufe0f", "\u65e5\u672c", "1", "-", "a\u3000b"]
)
def test_name_accepted(value):
    """Letters with their accents, digits, punctuation, emoji with their variation selector, a wide space between."""
    assert app.check_name(value) == value


def test_name_and_path_of_named_links():
    assert app.check_name("  Hello  ") == "Hello"
    assert app.slug_from_name("NanoURL", "Straße") == "NanoURL/Stra-e"
    assert app.slug_from_name("QRcodes", "a日b") == "QRcodes/a-b"
    with pytest.raises(app.Invalid):
        app.slug_from_name("NanoURL", "日本")


SVG_LOGO = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1"/></svg>'


def svg_logo(text: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(text.encode()).decode()


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        (SVG_LOGO, True),
        ('<?xml version="1.0" encoding="UTF-8"?>\n' + SVG_LOGO, True),
        # Not an SVG document, though `<svg` shows early in the text
        ('<html xmlns="http://www.w3.org/1999/xhtml"><svg xmlns="http://www.w3.org/2000/svg"/></html>', False),
        ("<x><!-- <svg --></x>", False),
        ("<svg></svg>", False),
        ('<svg xmlns="http://www.w3.org/2000/svg">', False),
        ('<svg xmlns="http://www.w3.org/2000/svg"/><svg xmlns="http://www.w3.org/2000/svg"/>', False),
        ('<?xml version="1.0" encoding="nope"?><svg xmlns="http://www.w3.org/2000/svg"/>', False),
        # No DOCTYPE, so no entity to expand
        ('<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>', False),
        (
            '<!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
            '<svg xmlns="http://www.w3.org/2000/svg"><text>&b;</text></svg>',
            False,
        ),
        ('<svg xmlns="http://www.w3.org/2000/svg"><text>&ext;</text></svg>', False),
    ],
)
def test_svg_logo_is_one_svg_document_with_no_doctype(text, ok):
    if ok:
        assert app.check_design({"logo": svg_logo(text)}).logo == svg_logo(text)
    else:
        with pytest.raises(app.Invalid):
            app.check_design({"logo": svg_logo(text)})


@pytest.mark.parametrize(
    ("design", "ok"),
    [
        ({}, True),
        ({"color": "#000000", "background": "transparent", "module_style": "dots", "eye_style": "circle"}, True),
        ({"color": "#ffffff"}, False),
        ({"color": "red"}, False),
        ({"margin": 11}, False),
        ({"margin": True}, False),
        ({"logo_size": 0.5}, False),
        ({"module_style": "stars"}, False),
        ({"logo": "data:image/png;base64,aGVsbG8="}, False),
        ({"logo": svg_logo(SVG_LOGO)}, True),
        ({"logo": "https://example.test/logo.png"}, False),
        ([], False),
    ],
)
def test_design(design, ok):
    if ok:
        app.check_design(design)
    else:
        with pytest.raises(app.Invalid):
            app.check_design(design)


def test_expires_and_status():
    assert app.check_expires_on("") is None
    assert app.check_expires_on("2026-02-28") == "2026-02-28"
    assert app.check_http_status("301") == 301
    for bad in ("2026-02-30", "26-1-1", 20260101):
        with pytest.raises(app.Invalid):
            app.check_expires_on(bad)
    for bad in (303, True, "x"):
        with pytest.raises(app.Invalid):
            app.check_http_status(bad)


# --- QR codes --------------------------------------------------------------------------------------------------------


def test_qr_rendering_is_deterministic():
    styles = [
        app.Design(),
        app.Design(module_style="rounded", eye_style="rounded", background="transparent", margin=0),
        app.Design(module_style="dots", eye_style="circle", logo=svg_logo(SVG_LOGO)),
    ]
    for design in styles:
        first = app.render_svg("https://go.example.test/links/abcd2345", design)
        assert first == app.render_svg("https://go.example.test/links/abcd2345", design)
        assert first.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert app.render_svg("x", styles[0]) != app.render_svg("y", styles[0])


# Bumping segno may move a module: check the new drawing by eye, then pin its version and digest here together
GOLDEN_SEGNO = "1.6.6"
GOLDEN_QR_SHA256 = "a96cb35770c534c7c05343378200223ec42f99d3dc65ff4770100177ec48470a"


def test_qr_svg_golden_digest():
    import hashlib

    import segno

    assert segno.__version__ == GOLDEN_SEGNO
    design = app.Design(color="#000000", eye_color="#112233", module_style="rounded", eye_style="rounded", margin=2)
    svg = app.render_svg("https://go.example.test/links/abcd2345", design)
    assert hashlib.sha256(svg.encode()).hexdigest() == GOLDEN_QR_SHA256


def test_qr_svg_encodes_the_short_link(client):
    import segno

    qr = create(client, kind="qrcode", name="Flyer", target="https://example.test/", design={"margin": 2})
    assert qr["slug"] == "QRcodes/Flyer"
    response = client.get(f"/api/links/{qr['id']}/qr.svg", headers=AUTH)
    assert response.status_code == 200
    assert response.mimetype == "image/svg+xml"
    assert 'filename="Flyer.svg"' in response.headers["Content-Disposition"]
    expected = app.render_svg(BASE + "/links/" + qr["id"], app.Design(margin=2))
    assert response.get_data(as_text=True) == expected
    # The same matrix as segno gives for the short link at error level M
    size = len(segno.make(BASE + "/links/" + qr["id"], error="m", micro=False, boost_error=False).matrix)
    assert f'viewBox="0 0 {size + 4} {size + 4}"' in expected


# --- API -------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}, {"Authorization": "Basic " + TOKEN}],
)
def test_api_refuses_missing_or_bad_token(client, headers):
    response = client.get("/api/links", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_short_token_refuses_the_start(env, tmp_path):
    (tmp_path / "token").write_text("short")
    with pytest.raises(SystemExit):
        app.create_app(env)


def test_no_token_file_means_no_api(env):
    env.pop("MOONIE_REDIRECT_API_TOKEN_FILE")
    assert app.create_app(env).test_client().get("/api/links", headers=AUTH).status_code == 401


def test_api_crud(client):
    link = create(client, slug="promo", name="Promo", target="https://example.test/")
    assert link["kind"] == "link" and link["http_status"] == 302 and link["link_host"] is None
    assert client.get(f"/api/links/{link['id']}", headers=AUTH).get_json()["slug"] == "promo"
    changed = client.patch(f"/api/links/{link['id']}", json={"target": "https://other.test/"}, headers=AUTH)
    assert changed.status_code == 200 and changed.get_json()["target"] == "https://other.test/"
    assert client.get("/redirect/promo").headers["Location"] == "https://other.test/"
    nano = create(client, kind="nano", name="N", target="https://example.test/")
    assert [r["id"] for r in client.get("/api/links?kind=nano", headers=AUTH).get_json()["links"]] == [nano["id"]]
    assert len(client.get("/api/links", headers=AUTH).get_json()["links"]) == 2
    assert client.delete(f"/api/links/{link['id']}", headers=AUTH).status_code == 204
    assert client.delete(f"/api/links/{link['id']}", headers=AUTH).status_code == 404
    assert client.get("/redirect/promo").status_code == 404


def test_api_errors(client):
    create(client, slug="promo", name="Promo", target="https://example.test/")
    taken = client.post("/api/links", json={"slug": "promo", "name": "x", "target": "https://a.test/"}, headers=AUTH)
    assert taken.status_code == 409
    bad = client.post("/api/links", json={"slug": "api/x", "target": "javascript:x"}, headers=AUTH)
    assert bad.status_code == 400
    assert set(bad.get_json()["fields"]) == {"slug", "name", "target"}
    assert client.post("/api/links", json=[1], headers=AUTH).status_code == 400
    assert client.post("/api/links", json={"kind": "other"}, headers=AUTH).status_code == 400
    assert client.get("/api/links?kind=other", headers=AUTH).status_code == 400
    assert client.get("/api/links/nope", headers=AUTH).status_code == 404


def test_api_rename_of_a_named_link_moves_its_path(client):
    nano = create(client, kind="nano", name="Old", target="https://example.test/")
    renamed = client.patch(f"/api/links/{nano['id']}", json={"name": "New"}, headers=AUTH).get_json()
    assert renamed["slug"] == "NanoURL/New"
    assert client.get("/redirect/NanoURL/Old").status_code == 404
    assert client.get(f"/links/{nano['id']}").status_code == 302


# --- UI --------------------------------------------------------------------------------------------------------------


def test_admin_needs_a_login(client):
    response = client.get("/admin/links")
    assert response.status_code == 302 and response.headers["Location"] == "/login?next=/admin/links"


def test_a_password_file_saved_with_a_byte_order_mark_works(env):
    """OS neutral: a Windows editor may save the file as UTF-8 with a BOM, and a CRLF line end."""
    app.Path(env["MOONIE_REDIRECT_PASSWORD_FILE"]).write_bytes(b"\xef\xbb\xbf" + PASSWORD.encode() + b"\r\n")
    client = app.create_app(env).test_client()
    login(client)


def test_login_wrong_password(client):
    response = client.post("/login", data={"password": "nope", "csrf": csrf_of(client)})
    assert response.status_code == 401
    assert client.get("/admin/links").status_code == 302


def test_a_failed_login_never_sleeps_in_its_thread(client, monkeypatch):
    monkeypatch.setattr(app.time, "sleep", lambda _s: pytest.fail("a failed login slept"))
    assert client.post("/login", data={"password": "nope", "csrf": csrf_of(client)}).status_code == 401


def test_any_login_within_a_second_of_a_failure_is_429(client, clock):
    csrf = csrf_of(client)
    assert client.post("/login", data={"password": "nope", "csrf": csrf}).status_code == 401
    clock[0] += 0.9
    # Even the right password: the brake is on the attempt, not on the answer
    refused = client.post("/login", data={"password": PASSWORD, "csrf": csrf})
    assert refused.status_code == 429
    assert client.get("/admin/links").status_code == 302
    # A refused attempt does not move the brake on
    clock[0] += 0.2
    assert client.post("/login", data={"password": PASSWORD, "csrf": csrf}).status_code == 302
    assert client.get("/admin/links").status_code == 200


def test_the_login_brake_is_shared_by_every_app_and_client(env, clock):
    first, second = app.create_app(env).test_client(), app.create_app(env).test_client()
    first.post("/login", data={"password": "nope", "csrf": csrf_of(first)})
    assert second.post("/login", data={"password": PASSWORD, "csrf": csrf_of(second)}).status_code == 429


def test_concurrent_wrong_logins_get_one_try_per_window(env, monkeypatch):
    import threading

    real_compare = app.hmac.compare_digest

    def slow_compare(a, b):
        # Holds every attempt in its password check, so all of them are in flight at once
        threading.Event().wait(0.05)
        return real_compare(a, b)

    monkeypatch.setattr(app.hmac, "compare_digest", slow_compare)
    clients = [app.create_app(env).test_client() for _ in range(8)]
    tokens = [csrf_of(c) for c in clients]
    start = threading.Barrier(len(clients))
    codes = []

    def attempt(c, csrf):
        start.wait()
        codes.append(c.post("/login", data={"password": "nope", "csrf": csrf}).status_code)

    threads = [threading.Thread(target=attempt, args=pair) for pair in zip(clients, tokens, strict=True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(codes) == [401] + [429] * 7


def test_a_successful_login_clears_the_brake(client, clock):
    login(client)
    other = client.application.test_client()
    assert other.post("/login", data={"password": PASSWORD, "csrf": csrf_of(other)}).status_code == 302


def test_login_without_csrf_is_refused(client):
    client.get("/login")
    assert client.post("/login", data={"password": PASSWORD}).status_code == 400
    assert client.post("/login", data={"password": PASSWORD, "csrf": "forged"}).status_code == 400


def test_session_cookie_flags(env):
    for base, secure in ((BASE, True), ("http://go.example.test", False)):
        response = app.create_app(env | {"MOONIE_REDIRECT_PUBLIC_BASE_URL": base}).test_client().get("/login")
        flags = [part.strip().lower() for part in response.headers["Set-Cookie"].split(";")]
        assert flags[0].startswith("moonie_redirect=")
        assert "httponly" in flags and "samesite=lax" in flags
        assert ("secure" in flags) is secure


def test_logout(client):
    csrf = login(client)
    client.post("/logout", data={"csrf": csrf})
    assert client.get("/admin/links").status_code == 302


def test_a_create_refused_for_its_path_draws_no_id(client, monkeypatch):
    create(client, slug="promo", name="Promo", target="https://example.test/")
    drawn = []
    monkeypatch.setattr(app, "draw_code", lambda length: drawn.append(length) or "x" * length)
    answer = client.post("/api/links", json={"slug": "promo", "name": "P", "target": "https://e.test/"}, headers=AUTH)
    assert answer.status_code == 409 and drawn == []


def test_logout_ends_only_its_own_session(flask_app, client):
    """The row of the session logged out goes; another browser signed in with the same password stays."""
    other = flask_app.test_client()
    login(other)
    csrf = login(client)
    client.post("/logout", data={"csrf": csrf})
    assert client.get("/api/status").status_code == 401
    assert other.get("/api/status").status_code == 200


def test_a_new_login_ends_the_session_it_replaces(flask_app, client):
    login(client)
    before = client.get_cookie("moonie_redirect").value
    login(client)
    thief = flask_app.test_client()
    thief.set_cookie("moonie_redirect", before)
    assert thief.get("/api/status").status_code == 401
    assert client.get("/api/status").status_code == 200


def test_a_signed_cookie_without_a_session_row_is_refused(flask_app, client, store):
    """A cookie signed with the right key but whose row is gone (a restored database, a forged id) reads nothing."""
    login(client)
    with store.write() as conn:
        conn.execute("DELETE FROM admin_sessions")
    assert client.get("/api/links").status_code == 401
    assert client.get("/admin/links").status_code == 302


def test_a_login_drops_the_sessions_already_over(client, store, monkeypatch):
    login(client)
    later = app.time.time() + 13 * 3600
    monkeypatch.setattr(app.time, "time", lambda: later)
    other = client.application.test_client()
    login(other)
    with store.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM admin_sessions").fetchone()[0] == 1


# --- QR preview and suggested slug -----------------------------------------------------------------------------------


def rows(store):
    with sqlite3.connect(store.path) as conn:
        return conn.execute("SELECT * FROM redirect_links ORDER BY id").fetchall()


def test_suggested_slug_skips_taken_ones(client, store, monkeypatch):
    create(client, slug="aaaaaa", name="Taken", target="https://example.test/")
    drawn = iter("aaaaaabbbbbb")
    monkeypatch.setattr(app.secrets, "choice", lambda _alphabet: next(drawn))
    assert store.free_slug() == "bbbbbb"


def test_suggested_slug_gives_up_after_its_draws(client, store, monkeypatch):
    create(client, slug="aaaaaa", name="Taken", target="https://example.test/")
    monkeypatch.setattr(app.secrets, "choice", lambda _alphabet: "a")
    with pytest.raises(RuntimeError):
        store.free_slug()


def test_api_suggest(client, store):
    response = client.get("/api/links/suggest", headers=AUTH)
    assert response.status_code == 200
    slug = response.get_json()["slug"]
    assert len(slug) == app.SLUG_LENGTH and app.check_user_slug(slug) == slug
    assert create(client, slug=slug, name="S", target="https://example.test/")["slug"] == slug


def test_api_preview(client, store):
    def preview(**body):
        return client.post("/api/qrcodes/preview", json=body, headers=AUTH)

    assert preview().get_json() == {"svg": app.render_svg(BASE + "/links/" + app.PREVIEW_ID, app.Design())}
    drawn = preview(name="Flyer", design={"module_style": "rounded"})
    assert drawn.status_code == 200 and drawn.mimetype == "application/json"
    assert drawn.get_json()["svg"] == app.render_svg(
        BASE + "/links/" + app.PREVIEW_ID, app.Design(module_style="rounded")
    )
    qr = create(client, kind="qrcode", name="Flyer", target="https://example.test/", design={"margin": 2})
    stored = client.get(f"/api/links/{qr['id']}/qr.svg", headers=AUTH).get_data(as_text=True)
    before = rows(store)
    # Absent design stands for the stored one
    assert preview(id=qr["id"]).get_json()["svg"] == stored
    dots = preview(id=qr["id"], design={"module_style": "dots"}).get_json()["svg"]
    assert dots == app.render_svg(BASE + "/links/" + qr["id"], app.Design(module_style="dots"))
    # The previews wrote nothing
    assert rows(store) == before
    assert client.get(f"/api/links/{qr['id']}/qr.svg", headers=AUTH).get_data(as_text=True) == stored


def test_api_preview_refuses_what_a_save_refuses(client, store):
    def preview(body):
        return client.post("/api/qrcodes/preview", json=body, headers=AUTH)

    bad = preview({"name": "", "design": {"color": "#fefefe"}})
    assert bad.status_code == 400 and set(bad.get_json()["fields"]) == {"name", "design"}
    assert preview([1]).status_code == 400
    link = create(client, slug="promo", name="Promo", target="https://example.test/")
    for id_ in ("nothing", link["id"]):
        assert preview({"id": id_}).status_code == 404
    # An id that is not a string is a malformed body, not a missing row
    for id_ in (12, ["x"], {"a": 1}, True):
        bad_id = preview({"id": id_})
        assert bad_id.status_code == 400 and set(bad_id.get_json()["fields"]) == {"id"}
    qr = create(client, kind="qrcode", name="Flyer", target="https://example.test/")
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE redirect_links SET design = 'nope' WHERE id = ?", (qr["id"],))
    assert preview({"id": qr["id"]}).status_code == 422
    assert preview({"id": qr["id"], "design": {}}).status_code == 200


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_api_suggest_and_preview_need_the_token(client, headers):
    assert client.get("/api/links/suggest", headers=headers).status_code == 401
    assert client.post("/api/qrcodes/preview", json={}, headers=headers).status_code == 401


# --- Session key -----------------------------------------------------------------------------------------------------


def session_cookie(client) -> str:
    return client.get_cookie("moonie_redirect").value


def test_anonymous_cookie_does_not_verify_under_a_key_from_the_password_alone(flask_app, client):
    from flask import Flask
    from flask.sessions import SecureCookieSessionInterface
    from itsdangerous import BadSignature

    client.get("/login")
    cookie = session_cookie(client)
    signer = SecureCookieSessionInterface().get_signing_serializer
    assert signer(flask_app).loads(cookie)["csrf"]
    # Any key computed from the password alone, as an offline guesser would try
    for key in (
        app.hmac.new(PASSWORD.encode(), b"moonie-redirect session key", app.hashlib.sha256).hexdigest(),
        app.hmac.new(b"", app.hashlib.sha256(PASSWORD.encode()).digest(), app.hashlib.sha256).hexdigest(),
        PASSWORD,
    ):
        guess = Flask("guess")
        guess.secret_key = key
        with pytest.raises(BadSignature):
            signer(guess).loads(cookie)


def test_the_session_key_is_random_kept_in_the_data_dir_and_survives_a_restart(env):
    first = app.create_app(env).test_client()
    login(first)
    key_file = app.Path(env["MOONIE_REDIRECT_DB"]).parent / "session.key"
    assert len(key_file.read_bytes()) == 32
    second = app.create_app(env).test_client()
    second.set_cookie("moonie_redirect", session_cookie(first))
    assert second.get("/admin/links").status_code == 200


@pytest.mark.skipif(app.os.name == "nt", reason="POSIX file modes do not exist on Windows")
def test_the_session_key_file_is_private(env):
    app.create_app(env)
    key_file = app.Path(env["MOONIE_REDIRECT_DB"]).parent / "session.key"
    assert key_file.stat().st_mode & 0o777 == 0o600


def test_a_password_change_signs_everyone_out(env, tmp_path):
    first = app.create_app(env).test_client()
    login(first)
    (tmp_path / "password").write_text("another long password\n")
    second = app.create_app(env).test_client()
    second.set_cookie("moonie_redirect", session_cookie(first))
    assert second.get("/admin/links").status_code == 302


def test_a_session_key_file_is_used_as_it_is(env, tmp_path):
    (tmp_path / "key").write_text("k" * 40)
    env["MOONIE_REDIRECT_SECRET_KEY_FILE"] = str(tmp_path / "key")
    assert app.create_app(env).secret_key == "k" * 40
    assert not (app.Path(env["MOONIE_REDIRECT_DB"]).parent / "session.key").exists()


@pytest.mark.parametrize("content", [b"short", b""])
def test_a_damaged_session_key_file_refuses_the_start(env, content):
    key_file = app.Path(env["MOONIE_REDIRECT_DB"]).parent / "session.key"
    key_file.parent.mkdir(parents=True)
    key_file.write_bytes(content)
    with pytest.raises(SystemExit, match="session.key is damaged: delete it"):
        app.create_app(env)


def test_a_session_key_race_keeps_the_first_key_and_leaves_no_temp_file(tmp_path, monkeypatch):
    winner = b"w" * 32
    real_link = app.os.link

    def link_after_another_worker(src, dst):
        app.Path(dst).write_bytes(winner)
        real_link(src, dst)

    monkeypatch.setattr(app.os, "link", link_after_another_worker)
    assert app.session_key(tmp_path) == winner
    assert [p.name for p in tmp_path.iterdir()] == ["session.key"]


def test_a_crash_while_writing_the_session_key_leaves_nothing_behind(tmp_path, monkeypatch):
    real_fsync = app.os.fsync

    def crash(_fd):
        raise OSError("disk full")

    monkeypatch.setattr(app.os, "fsync", crash)
    with pytest.raises(OSError, match="disk full"):
        app.session_key(tmp_path)
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(app.os, "fsync", real_fsync)
    assert len(app.session_key(tmp_path)) == 32


# --- import-v7 -------------------------------------------------------------------------------------------------------

V7_SCHEMA = """CREATE TABLE redirect_links (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'link' CHECK (kind IN ('link', 'nano', 'qrcode')),
    link_host TEXT CHECK (link_host IN ('ip', 'hostname')),
    slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, target TEXT NOT NULL,
    http_status INTEGER NOT NULL DEFAULT 302 CHECK (http_status IN (301, 302)),
    expires_on TEXT, design TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""
V7_ROWS = [
    (
        "abcd2345",
        "link",
        None,
        "promo",
        "Promo",
        "https://shop.test/",
        301,
        None,
        None,
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    ),
    (
        "Qr7xYz89",
        "qrcode",
        "ip",
        "QRcodes/Flyer",
        "Flyer",
        "https://flyer.test/",
        302,
        None,
        json.dumps({"color": "#1b1f24", "margin": 4}),
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
    ),
    (
        "Nn3pQr45",
        "nano",
        "hostname",
        "NanoURL/Short",
        "Short",
        "https://nano.test/",
        302,
        None,
        None,
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
    ),
]


def test_import_v7(tmp_path, env, monkeypatch, capsys):
    old = tmp_path / "moonie.db"
    with sqlite3.connect(old) as conn:
        conn.execute(V7_SCHEMA)
        conn.executemany("INSERT INTO redirect_links VALUES (?,?,?,?,?,?,?,?,?,?,?)", V7_ROWS)
    conn.close()
    before = old.read_bytes()
    monkeypatch.setenv("MOONIE_REDIRECT_DB", env["MOONIE_REDIRECT_DB"])
    store = app.Store(app.Path(env["MOONIE_REDIRECT_DB"]))
    # A row already here under the same id is kept as it is
    store.create(
        "link",
        {
            "slug": "mine",
            "name": "Mine",
            "target": "https://mine.test/",
            "http_status": 302,
            "expires_on": None,
            "design": None,
            "link_host": None,
        },
    )
    with sqlite3.connect(env["MOONIE_REDIRECT_DB"]) as conn:
        conn.execute("UPDATE redirect_links SET id = 'Nn3pQr45'")
    conn.close()
    assert app.main(["app.py", "import-v7", str(old)]) == 0
    out = capsys.readouterr().out
    assert "imported 2, duplicates 1, refused 0" in out
    # The QR code written with 7.0.1's IP address is named, so its printed copies can be checked
    assert "1 imported rows have link_host 'ip'" in out and "old container IP and port" in out
    assert old.read_bytes() == before
    with sqlite3.connect(env["MOONIE_REDIRECT_DB"]) as conn:
        # The columns 7.0.1 had: 8.1 adds its Cloudflare columns with their defaults
        columns = ", ".join(app.COLUMNS)
        rows = conn.execute(f"SELECT {columns} FROM redirect_links WHERE id IN ('abcd2345', 'Qr7xYz89')").fetchall()
    conn.close()
    assert sorted(rows) == sorted(V7_ROWS[:2])
    client = app.create_app(env).test_client()
    assert client.get("/links/abcd2345").headers["Location"] == "https://shop.test/"
    assert client.get("/links/Qr7xYz89").headers["Location"] == "https://flyer.test/"
    assert client.get("/redirect/QRcodes/Flyer").status_code == 302
    assert client.get("/links/Nn3pQr45").headers["Location"] == "https://mine.test/"
    # Running it again changes nothing
    assert app.main(["app.py", "import-v7", str(old)]) == 0
    out = capsys.readouterr().out
    assert "imported 0, duplicates 3, refused 0" in out and "link_host" not in out


def test_import_v7_refuses_a_pending_write_ahead_log(tmp_path, env):
    old = tmp_path / "moonie.db"
    with sqlite3.connect(old) as conn:
        conn.execute(V7_SCHEMA)
    conn.close()
    (tmp_path / "moonie.db-wal").write_bytes(b"pending")
    with pytest.raises(SystemExit):
        app.Store(app.Path(env["MOONIE_REDIRECT_DB"])).import_v7(old)


def mine(store):
    values = {"name": "Mine", "target": "https://mine.test/", "http_status": 302, "expires_on": None, "design": None}
    return store.create("link", values | {"slug": "mine", "link_host": None})


def test_import_v7_checks_each_row(tmp_path, env, monkeypatch, capsys):
    # A hand-edited database, with none of the table's checks
    old = tmp_path / "moonie.db"
    with sqlite3.connect(old) as conn:
        conn.execute(f"CREATE TABLE redirect_links ({', '.join(app.COLUMNS)})")
        good = {"kind": "link", "link_host": None, "name": "Good", "target": "https://good.test/", "http_status": 302}
        good |= {"expires_on": None, "design": None, "created_at": "t", "updated_at": "t"}

        def row(n: int, **changes) -> tuple:
            values = good | {"id": f"Good23{n:02d}", "slug": f"good{n}"} | changes
            return tuple(values[c] for c in app.COLUMNS)

        rows = [
            row(0),
            row(1, id="no-code!"),
            row(2, slug="a//b"),
            row(3, target="javascript:alert(1)"),
            row(4, target="ftp://files.test/"),
            row(5, kind="other"),
            row(6, http_status=303),
            row(7, http_status="302"),
            row(8, name=None),
            # The path of a row already here, under another id
            row(9, slug="mine"),
            row(10, expires_on="2026-02-30"),
            row(11, expires_on="tomorrow"),
            row(12, expires_on=20260101),
            row(13, kind="qrcode", design="{not json"),
            row(14, kind="qrcode", design=json.dumps({"color": "#ffffff"})),
            # NULL stays allowed, and a valid day or design is copied
            row(15, expires_on="2099-12-31"),
            row(16, kind="qrcode", design=json.dumps({"color": "#1b1f24", "margin": 4})),
        ]
        conn.executemany("INSERT INTO redirect_links VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.close()
    monkeypatch.setenv("MOONIE_REDIRECT_DB", env["MOONIE_REDIRECT_DB"])
    store = app.Store(app.Path(env["MOONIE_REDIRECT_DB"]))
    mine(store)
    assert app.main(["app.py", "import-v7", str(old)]) == 0
    assert "imported 3, duplicates 1, refused 13" in capsys.readouterr().out
    assert sorted(r["slug"] for r in store.list()) == ["good0", "good15", "good16", "mine"]
    assert store.get("Good2309") is None


@pytest.mark.parametrize("content", [b"not a database at all, just bytes" * 200, None])
def test_import_v7_unreadable_database_is_one_line_and_exit_1(tmp_path, env, monkeypatch, capsys, content):
    old = tmp_path / "moonie.db"
    if content is None:
        # A real SQLite file without the table
        with sqlite3.connect(old) as conn:
            conn.execute("CREATE TABLE other (x)")
        conn.close()
    else:
        old.write_bytes(content)
    monkeypatch.setenv("MOONIE_REDIRECT_DB", env["MOONIE_REDIRECT_DB"])
    assert app.main(["app.py", "import-v7", str(old)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and len(captured.err.strip().splitlines()) == 1
    assert captured.err.startswith("cannot read the 7.0.1 database: ")


def test_import_v7_usage(capsys, tmp_path):
    assert app.main(["app.py", "import-v7", str(tmp_path / "missing.db")]) == 2
    assert app.main(["app.py", "other"]) == 2


@pytest.mark.parametrize("value", [None, "", "  ", "/"])
def test_no_public_base_refuses_the_start(env, value):
    if value is None:
        env.pop("MOONIE_REDIRECT_PUBLIC_BASE_URL")
    else:
        env["MOONIE_REDIRECT_PUBLIC_BASE_URL"] = value
    with pytest.raises(SystemExit, match="MOONIE_REDIRECT_PUBLIC_BASE_URL is required"):
        app.create_app(env)


def test_links_never_take_the_request_host(client):
    link = client.post(
        "/api/links", json={"slug": "x", "name": "X", "target": "https://e.test/"}, headers=AUTH | {"Host": "evil.test"}
    )
    assert link.get_json()["public_url"] == BASE + "/redirect/x"


def test_bad_public_base_refuses_the_start(env):
    env["MOONIE_REDIRECT_PUBLIC_BASE_URL"] = "ftp://x"
    with pytest.raises(SystemExit):
        app.create_app(env)


# --- Image -----------------------------------------------------------------------------------------------------------


def test_the_image_healthcheck_asks_the_configured_port(tmp_path):
    import http.server
    import subprocess
    import sys
    import threading

    dockerfile = (app.Path(__file__).parent.parent / "Dockerfile").read_text()
    command = json.loads(re.search(r"^HEALTHCHECK [^\n]*\\\n\s*CMD (\[.*\])$", dockerfile, re.M).group(1))
    assert command[0] == "python"

    class Health(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/health" else 404)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env = {**app.os.environ, "MOONIE_HTTP_PORT": str(server.server_port)}
        done = subprocess.run([sys.executable, *command[1:]], env=env, cwd=tmp_path, capture_output=True, timeout=10)
    finally:
        server.shutdown()
    assert done.returncode == 0, done.stderr


def test_the_env_example_leaves_the_public_base_url_empty_so_the_start_refuses_it(env):
    example = (app.Path(__file__).parent.parent / ".env.example").read_text(encoding="utf-8")
    values = dict(line.split("=", 1) for line in example.splitlines() if line and not line.startswith("#"))
    assert values["MOONIE_REDIRECT_PUBLIC_BASE_URL"] == ""
    with pytest.raises(SystemExit, match="MOONIE_REDIRECT_PUBLIC_BASE_URL is required"):
        app.create_app(env | {"MOONIE_REDIRECT_PUBLIC_BASE_URL": values["MOONIE_REDIRECT_PUBLIC_BASE_URL"]})
