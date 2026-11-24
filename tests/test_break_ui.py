"""Breaker round on the 9.0.0 admin: the session on the API, its CSRF guard, the login's `next`, the headers of every
page, the names the API accepts, and what the frame's status costs. A test named `test_break_*` reproduces a hole found
in this round, fixed since: its docstring's "Was:" part tells the hole as it was. The others pin a corner that held."""

# The fixtures of test_app.py are imported, and every test names them as its arguments
# ruff: noqa: F811

import base64
import json
import posixpath
import re
import time
import tracemalloc
from urllib.parse import unquote, urlsplit

import pytest
from test_app import AUTH, PASSWORD, client, clock, create, csrf_of, env, flask_app, login, store  # noqa: F401

import app

# The real clock, read once: a moved clock patches the same module function
NOW = time.time()
LINK = {"slug": "promo", "name": "Promo", "target": "https://example.test/"}
SAME = {"Sec-Fetch-Site": "same-origin"}


def session_token(flask_app, cookie: str) -> str:
    """The CSRF token a copied session cookie carries: Flask's session is signed, not encrypted. It is read through
    Flask's own serializer, as a payload Flask chose to compress starts with "." and is zlib data, not plain JSON."""
    return flask_app.session_interface.get_signing_serializer(flask_app).loads(cookie)["csrf"]


def move_clock(monkeypatch, hours: float) -> None:
    """The time the session's signature is made and checked with, `hours` after the start of the tests."""
    later = NOW + hours * 3600
    monkeypatch.setattr("itsdangerous.timed.time.time", lambda: later)


def test_session_token_reads_a_compressed_cookie(flask_app):
    """A compressible session makes Flask zlib-compress the cookie, which then starts with ".": the helper reads it
    all the same (a split on "." read an empty payload there, and the logout test failed now and then)."""
    serializer = flask_app.session_interface.get_signing_serializer(flask_app)
    compressed = serializer.dumps({"csrf": "token", "pad": "a" * 400})
    plain = serializer.dumps({"csrf": "token"})
    assert compressed.startswith(".") and not plain.startswith(".")
    assert session_token(flask_app, compressed) == session_token(flask_app, plain) == "token"


# --- Corners that held ------------------------------------------------------------------------------------------------


def test_an_expired_session_mid_save_is_401_so_the_page_goes_to_the_login(client, store, monkeypatch):
    """The page's token is still in its meta when the session ends: the save must say 401 (the page then goes to the
    login), never 403 csrf (which would read as another origin), and change nothing."""
    csrf = login(client)
    row = create(client, **LINK)
    move_clock(monkeypatch, 13)
    headers = {"X-CSRF-Token": csrf} | SAME
    for method, path, body in (
        ("POST", "/api/links", LINK | {"slug": "other"}),
        ("PATCH", f"/api/links/{row['id']}", {"target": "https://other.test/"}),
        ("DELETE", f"/api/links/{row['id']}", None),
        ("POST", "/api/qrcodes/preview", {}),
    ):
        answer = client.open(path, method=method, json=body, headers=headers)
        assert answer.status_code == 401 and answer.get_json() == {"error": "unauthorized"}, (method, path)
    assert [r["target"] for r in store.list()] == [LINK["target"]]


@pytest.mark.parametrize(
    ("headers", "kind"),
    [
        ({"X-HTTP-Method-Override": "DELETE"}, "json"),
        ({"X-CSRF-Token": "{csrf}", "Sec-Fetch-Site": "Same-Origin"}, "json"),
        ({"X-CSRF-Token": " {csrf} ", "Sec-Fetch-Site": "same-origin"}, "json"),
        ({"X-CSRF-Token": "{csrf}", "Sec-Fetch-Site": "cross-site, same-origin"}, "json"),
        ({"X-CSRF-Token": "{csrf}", "Sec-Fetch-Site": "same-origin"}, "text"),
        ({"X-CSRF-Token": "{csrf}", "Sec-Fetch-Site": "same-origin"}, "form"),
    ],
    ids=["method-override", "site-case", "token-spaces", "site-list", "text-plain", "form"],
)
def test_no_cross_site_shape_changes_a_link_through_the_cookie(client, store, headers, kind):
    csrf = login(client)
    sent = {name: value.replace("{csrf}", csrf) for name, value in headers.items()}
    body = LINK
    if kind == "json":
        answer = client.post("/api/links", json=body, headers=sent)
    elif kind == "text":
        answer = client.post("/api/links", data=json.dumps(body), content_type="text/plain", headers=sent)
    else:
        answer = client.post("/api/links", data=body, headers=sent)
    assert answer.status_code in (400, 403)
    assert store.list() == []


def test_a_preflight_without_the_cookie_is_refused_and_no_answer_allows_another_origin(client):
    preflight = client.options(
        "/api/links",
        headers={
            "Origin": "https://evil.test",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-csrf-token, content-type",
        },
    )
    assert preflight.status_code == 401
    login(client)
    for answer in (client.options("/api/links", headers={"Origin": "https://evil.test"}), client.get("/api/links")):
        assert not any(name.lower().startswith("access-control-") for name in answer.headers.keys())


def resolved(location: str) -> str:
    """The path a browser opens for a Location on this origin."""
    parts = urlsplit(location)
    assert not parts.scheme and not parts.netloc, location
    return posixpath.normpath(unquote(parts.path).replace("\\", "/"))


@pytest.mark.parametrize(
    "next_",
    [
        "/admin/%252e%252e/login",
        "/admin/%2e%2e%2f%2e%2e%2fevil",
        "/admin/.%2e/login",
        "/admin/..;/login",
        "/admin//evil.test",
        "/admin/%2f%2fevil.test",
        "/admin/\u2025/login",
        "/admin/\uff0e\uff0e/login",
        "/admin/\u3000",
        "/admin/%00",
        "/admin/%0d%0aSet-Cookie:%20x=1",
        "/admin/\u2028",
        "/admin/x#\\@evil.test",
        "/admin/?x=\\",
        "/admin/\t/evil",
        "/admin/\u0130",
        "\\/admin/",
        "/\\evil.test/admin/",
        "/admin/@evil.test",
        "/admin/:evil",
        "/admin/" + "a" * 4000,
    ],
)
def test_the_login_lands_on_this_origin_under_admin_whatever_next_says(client, next_):
    csrf = csrf_of(client)
    answer = client.post("/login", data={"password": PASSWORD, "csrf": csrf, "next": next_})
    assert answer.status_code == 302
    location = answer.headers["Location"]
    assert not location.startswith("//") and "\r" not in location and "\n" not in location
    assert (resolved(location) + "/").startswith("/admin/"), location
    assert "Set-Cookie: x" not in str(answer.headers)
    page = client.get("/login", query_string={"next": next_}).get_data(as_text=True)
    for value in re.findall(r'name="next" value="([^"]*)"', page):
        assert "<" not in value and '"' not in value


@pytest.mark.parametrize(
    ("method", "path", "data", "status"),
    [
        ("GET", "/login", None, 200),
        ("GET", "/login?expired=1&next=/admin/links", None, 200),
        ("POST", "/login", {"password": "wrong"}, 401),
        ("POST", "/login", {"password": "wrong"}, 429),
        ("POST", "/login", {}, 400),
        ("GET", "/admin/links", None, 302),
        ("GET", "/nothing", None, 404),
        ("GET", "/redirect/nothing", None, 404),
    ],
)
def test_every_html_answer_carries_the_page_policy_and_no_store(client, method, path, data, status):
    if data is not None and "password" in data:
        data = data | {"csrf": csrf_of(client)}
        if status == 429:
            client.post("/login", data=data)
    answer = client.open(path, method=method, data=data, headers={"Accept": "text/html"})
    assert answer.status_code == status
    assert answer.headers["Content-Security-Policy"] == app.PAGE_POLICY
    assert answer.headers["Cache-Control"] == "no-store"
    assert answer.headers["X-Content-Type-Options"] == "nosniff"


def test_the_logged_in_frames_and_api_answers_are_never_framed_nor_kept(client):
    login(client)
    row = create(client, kind="qrcode", name="Q", target="https://example.test/")
    for path in ("/admin/links", "/admin/nowhere", "/api/status", "/api/links", f"/api/links/{row['id']}/qr.svg"):
        answer = client.get(path)
        assert "frame-ancestors 'none'" in answer.headers["Content-Security-Policy"], path
        assert answer.headers["Cache-Control"] == "no-store", path


@pytest.mark.parametrize(
    "path", ["/admin/links/new", "/admin/nanourls/new", "/admin/qrcodes/new", "/admin/links/abcdefgh/delete"]
)
def test_the_8x_form_posts_are_gone_even_with_a_valid_form(client, store, path):
    csrf = login(client)
    answer = client.post(path, data={"csrf": csrf} | LINK)
    assert answer.status_code == 405
    assert store.list() == []


# --- Holes ------------------------------------------------------------------------------------------------------------


def test_break_logout_ends_a_copied_session(flask_app, client, store):
    """A session cookie copied before the logout (a shared machine, a proxy log, a backup of the browser profile) must
    die with the logout. Was: the session was a signed cookie with nothing on the server, so the logout only dropped
    the browser's copy: the copy still read and changed every link, CSRF token included, as it carried that too."""
    csrf = login(client)
    copied = client.get_cookie("moonie_redirect").value
    assert session_token(flask_app, copied) == csrf
    assert client.post("/logout", data={"csrf": csrf}).status_code == 302

    thief = flask_app.test_client()
    thief.set_cookie("moonie_redirect", copied)
    assert thief.get("/api/links").status_code == 401
    answer = thief.post("/api/links", json=LINK, headers={"X-CSRF-Token": session_token(flask_app, copied)} | SAME)
    assert answer.status_code == 401
    assert store.list() == []


def test_break_a_session_ends_12_hours_after_its_login_even_when_used(client, monkeypatch):
    """The README says the session lasts 12 hours. Was: every answer signed the cookie again with a new time, so a
    session used once in each 12 hours never ended: a copied cookie kept alive by a script lasted forever."""
    login(client)
    move_clock(monkeypatch, 11)
    assert client.get("/api/status").status_code == 200
    move_clock(monkeypatch, 22)
    assert client.get("/api/status").status_code == 401
    assert client.get("/admin/links").status_code == 302


def test_break_the_status_counts_without_reading_every_design(client, store):
    """The frame asks /api/status on every navigation, for a count. Was: it read every row whole, each QR code's
    logo included (up to 256 KiB each): 200 QR codes with big logos cost 60 MB of memory per navigation, and 10,000 a
    few GB. A count needs none of it."""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg">' + '<rect width="1" height="1"/>' * 8000 + "</svg>").encode()
    logo = "data:image/svg+xml;base64," + base64.b64encode(svg).decode()
    first = create(client, kind="qrcode", name="Q0", target="https://example.test/", design={"logo": logo})
    row = store.get(first["id"])
    with store.write() as conn:
        for index in range(1, 40):
            copy = row | {"id": f"q{index:07d}", "slug": f"QRcodes/q{index}"}
            columns, marks = ", ".join(copy), ", ".join("?" * len(copy))
            conn.execute(f"INSERT INTO {app.TABLE} ({columns}) VALUES ({marks})", list(copy.values()))
    tracemalloc.start()
    try:
        answer = client.get("/api/status", headers=AUTH)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert answer.get_json()["links"] == 40
    assert peak < 2_000_000, f"/api/status peaked at {peak / 1e6:.1f} MB for a count of 40"


@pytest.mark.parametrize(
    "name",
    ["\u3164", "\u115f", "\u1160", "\uffa0", "\u2800", "Promo\u3164", "\u034f"],
    ids=["hangul", "choseong", "jungseong", "halfwidth", "braille-blank", "trailing", "cgj"],
)
def test_break_a_name_of_invisible_letters_is_refused(client, name):
    """The rule refuses "control or invisible characters". Was: it went by Unicode category C alone, yet the Hangul
    fillers are letters (Lo), the braille blank a symbol (So) and the combining grapheme joiner a mark (Mn): all draw
    nothing, so a link named with them showed an empty name in the list, or two links looked alike."""
    answer = client.post("/api/links", json=LINK | {"name": name}, headers=AUTH)
    assert answer.status_code == 400
    assert answer.get_json()["fields"]["name"] == "holds control or invisible characters"
