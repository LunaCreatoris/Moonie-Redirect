"""LAN mode (D35): the app served over plain http on an IP address, with no reverse proxy in front.

The whole admin path runs as a browser on the LAN drives it: the login page, the login, a link and a QR code made
through the session, and the links followed. A browser sends no Sec-Fetch-Site from a plain http page on an IP
address (it is no secure context), and sends `same-origin` from http://127.0.0.1, so both are checked. The cookie
must not be Secure there, or the browser would drop it and no login would hold. An https deployment keeps its Secure
cookie and its headers unchanged.
"""

import re

import pytest

import app

PASSWORD = "correct horse battery staple"
LAN_BASE = "http://192.0.2.10:8080"
POLICY_HEADERS = ("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy")


@pytest.fixture
def env(tmp_path):
    (tmp_path / "password").write_text(PASSWORD + "\n")
    return {
        "MOONIE_REDIRECT_DB": str(tmp_path / "data" / "redirect.db"),
        "MOONIE_REDIRECT_PASSWORD_FILE": str(tmp_path / "password"),
        "MOONIE_REDIRECT_PUBLIC_BASE_URL": LAN_BASE,
    }


def lan_client(env, base=LAN_BASE):
    """A test client whose requests reach the app at `base`, as a browser on the LAN does."""
    return app.create_app(env | {"MOONIE_REDIRECT_PUBLIC_BASE_URL": base}).test_client(), base


def page_csrf(client, base, path):
    page = client.get(base + path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


def sign_in(client, base, fetch_site):
    """Log in through the form, then read the session's token from an admin page, as the admin's modules do."""
    headers = {} if fetch_site is None else {"Sec-Fetch-Site": fetch_site}
    login_page = client.get(base + "/login")
    assert login_page.status_code == 200
    cookie = login_page.headers["Set-Cookie"].lower()
    assert "; secure" not in cookie and "httponly" in cookie and "samesite=lax" in cookie
    answer = client.post(
        base + "/login", data={"password": PASSWORD, "csrf": page_csrf(client, base, "/login")}, headers=headers
    )
    assert answer.status_code == 302
    # A relative Location: the browser stays on the address it came from, whatever the public base URL says
    assert answer.headers["Location"].startswith("/admin/")
    admin = client.get(base + "/admin/links")
    assert admin.status_code == 200
    return re.search(r'name="csrf-token" content="([^"]+)"', admin.get_data(as_text=True)).group(1)


@pytest.mark.parametrize(
    ("base", "fetch_site"),
    [
        # A LAN address: no secure context, so no fetch metadata at all
        (LAN_BASE, None),
        # Loopback is a secure context even over http: the browser says same-origin
        ("http://127.0.0.1:8080", "same-origin"),
    ],
)
def test_a_full_login_and_create_over_http_on_an_ip(env, base, fetch_site):
    client, base = lan_client(env, base)
    csrf = sign_in(client, base, fetch_site)
    headers = {"X-CSRF-Token": csrf} | ({} if fetch_site is None else {"Sec-Fetch-Site": fetch_site})

    made = client.post(
        base + "/api/links",
        json={"slug": "menu", "name": "Menu", "target": "https://example.test/menu"},
        headers=headers,
    )
    assert made.status_code == 201, made.get_json()
    link = made.get_json()
    assert link["public_url"] == f"{base}/redirect/menu"
    assert link["short_url"] == f"{base}/links/{link['id']}"
    assert link["address_url"] == link["public_url"]

    qr = client.post(
        base + "/api/links",
        json={"kind": "qrcode", "name": "Flyer", "target": "https://example.test/", "design": {"margin": 2}},
        headers=headers,
    ).get_json()
    assert qr["address_url"] == f"{base}/links/{qr['id']}"
    svg = client.get(f"{base}/api/links/{qr['id']}/qr.svg").get_data(as_text=True)
    assert svg == app.render_svg(f"{base}/links/{qr['id']}", app.Design(margin=2))

    for path in ("/redirect/menu", f"/links/{link['id']}"):
        followed = client.get(base + path)
        assert followed.status_code == 302
        assert followed.headers["Location"] == "https://example.test/menu"

    logout_csrf = page_csrf(client, base, "/admin/links")
    assert client.post(base + "/logout", data={"csrf": logout_csrf}).status_code == 302
    assert client.get(base + "/api/status").status_code == 401


def test_a_cross_site_change_is_still_refused_over_http(env):
    client, base = lan_client(env)
    csrf = sign_in(client, base, None)
    body = {"slug": "x", "name": "X", "target": "https://example.test/"}
    for site in ("cross-site", "same-site"):
        answer = client.post(base + "/api/links", json=body, headers={"X-CSRF-Token": csrf, "Sec-Fetch-Site": site})
        assert answer.status_code == 403
    assert client.post(base + "/api/links", json=body).status_code == 403


@pytest.mark.parametrize("base", [LAN_BASE, "https://go.example.test"])
def test_the_same_headers_on_http_and_https_and_never_hsts(env, base):
    client, _ = lan_client(env, base)
    response = client.get(base + "/login")
    for name in POLICY_HEADERS:
        assert response.headers[name]
    assert response.headers["Content-Security-Policy"] == app.PAGE_POLICY
    # HSTS on a LAN address would lock browsers out of the plain http instance: the proxy sets it, if anyone does
    assert "Strict-Transport-Security" not in response.headers


def test_https_keeps_its_secure_cookie(env):
    client, base = lan_client(env, "https://go.example.test")
    cookie = client.get(base + "/login").headers["Set-Cookie"].lower()
    assert "; secure" in cookie
