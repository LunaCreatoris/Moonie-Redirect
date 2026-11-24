"""API keys (D25): made and revoked in Settings, shown once, kept as a digest; the scopes every endpoint asks for; the
token file as a fixed `*` key; the settings refused to every key (D28)."""

# The fixtures of test_app.py are imported, and every test names them as its arguments
# ruff: noqa: F811

import sqlite3

import pytest
from fake_cloudflare import FakeCloudflare
from test_app import AUTH, PASSWORD, TOKEN, client, clock, env, flask_app, login, store  # noqa: F401
from test_cloudflare_api import GO, LINK, SITE, World

import app

SPECIFIC = tuple(scope for scope in app.KNOWN_SCOPES if scope not in app.WILDCARD_SCOPES)


def admin(client):
    csrf = login(client)

    def send(method, path, **kwargs):
        headers = {"X-CSRF-Token": csrf, "Sec-Fetch-Site": "same-origin"}
        return client.open(path, method=method, headers=headers, **kwargs)

    return send


def key_header(store, *scopes):
    """A key put straight in the database: what the matrix needs, without a password check per key."""
    secret = app.new_api_key()
    store.add_api_key("test", list(scopes), app.key_digest(secret), secret[: app.KEY_SHOWN])
    return {"Authorization": f"Bearer {secret}"}


# --- Made, listed, used, revoked ---


def test_a_new_key_is_shown_once_and_kept_as_a_digest(client, store, env):
    send = admin(client)
    made = send(
        "POST", "/api/settings/keys", json={"name": "n8n", "scopes": ["redirect:links.read"], "password": PASSWORD}
    )
    assert made.status_code == 201
    body = made.get_json()
    secret = body.pop("secret")
    assert secret.startswith("mrk_") and len(secret) == 47 and body["prefix"] == secret[:8]
    assert body == {"id": body["id"], "name": "n8n", "prefix": secret[:8], "scopes": ["redirect:links.read"]}
    listed = send("GET", "/api/settings/keys").get_json()
    assert secret not in str(listed)
    row = next(key for key in listed["keys"] if key["id"] == body["id"])
    assert row == {
        "id": body["id"],
        "name": "n8n",
        "prefix": secret[:8],
        "scopes": ["redirect:links.read"],
        "created_at": row["created_at"],
        "last_used_at": None,
        "origin": "stored",
    }
    assert listed["known_scopes"] == list(app.KNOWN_SCOPES)
    with sqlite3.connect(env["MOONIE_REDIRECT_DB"]) as conn:
        dump = "\n".join(conn.iterdump())
    conn.close()
    assert secret not in dump and app.key_digest(secret) in dump
    auth = {"Authorization": f"Bearer {secret}"}
    assert client.get("/api/links?kind=link", headers=auth).status_code == 200
    assert send("DELETE", f"/api/settings/keys/{body['id']}").status_code == 204
    assert client.get("/api/links?kind=link", headers=auth).status_code == 401
    assert send("DELETE", f"/api/settings/keys/{body['id']}").status_code == 404


def test_scopes_are_kept_in_their_known_order_without_repeats(client):
    send = admin(client)
    scopes = ["cloudflare:read", "redirect:links.write", "cloudflare:read", "*"]
    made = send("POST", "/api/settings/keys", json={"name": "k", "scopes": scopes, "password": PASSWORD})
    assert made.get_json()["scopes"] == ["*", "redirect:links.write", "cloudflare:read"]


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"name": "", "scopes": ["*"]}, {"name"}),
        ({"name": "​", "scopes": ["*"]}, {"name"}),
        ({"name": "x" * 101, "scopes": ["*"]}, {"name"}),
        ({"scopes": ["*"]}, {"name"}),
        ({"name": "k", "scopes": []}, {"scopes"}),
        ({"name": "k", "scopes": "*"}, {"scopes"}),
        ({"name": "k", "scopes": ["redirect:links.delete"]}, {"scopes"}),
        ({"name": "k", "scopes": [None]}, {"scopes"}),
        ({"name": 5, "scopes": None}, {"name", "scopes"}),
    ],
)
def test_a_bad_name_or_scope_is_refused_before_the_password(client, store, body, fields):
    send = admin(client)
    answer = send("POST", "/api/settings/keys", json=body | {"password": "wrong"})
    assert answer.status_code == 400 and answer.get_json()["error"] == "invalid"
    assert set(answer.get_json()["fields"]) == fields
    assert store.api_keys() == []


def test_a_new_key_needs_the_password_under_the_brake(client, store, clock):
    send = admin(client)
    body = {"name": "k", "scopes": ["*"]}
    wrong = send("POST", "/api/settings/keys", json=body | {"password": "wrong"})
    assert wrong.status_code == 400 and wrong.get_json() == {
        "error": "login_failed",
        "fields": {"password": "wrong password"},
    }
    assert send("POST", "/api/settings/keys", json=body | {"password": PASSWORD}).status_code == 429
    assert send("POST", "/api/settings/keys", json=body).status_code == 429
    clock[0] += 2
    assert send("POST", "/api/settings/keys", json=body).status_code == 400  # no password at all
    clock[0] += 2
    assert send("POST", "/api/settings/keys", json=body | {"password": PASSWORD}).status_code == 201
    assert len(store.api_keys()) == 1


def test_the_last_use_is_written_at_most_once_a_minute(client, store, monkeypatch):
    stamp = ["2026-11-24T10:00:00Z"]
    monkeypatch.setattr(app, "now", lambda: stamp[0])
    auth = key_header(store, "*")
    client.get("/api/status", headers=auth)
    assert store.api_keys()[0]["last_used_at"] == "2026-11-24T10:00:00Z"
    stamp[0] = "2026-11-24T10:00:59Z"
    client.get("/api/status", headers=auth)
    assert store.api_keys()[0]["last_used_at"] == "2026-11-24T10:00:00Z"
    stamp[0] = "2026-11-24T10:01:00Z"
    client.get("/api/status", headers=auth)
    assert store.api_keys()[0]["last_used_at"] == "2026-11-24T10:01:00Z"


def test_the_token_file_is_a_fixed_row_with_every_scope(client, store, monkeypatch):
    send = admin(client)
    first = send("GET", "/api/settings/keys").get_json()["keys"]
    assert first == [
        {
            "id": "file",
            "name": "Token file",
            "prefix": None,
            "scopes": ["*"],
            "created_at": None,
            "last_used_at": None,
            "origin": "file",
        }
    ]
    assert TOKEN not in str(first)
    monkeypatch.setattr(app, "now", lambda: "2026-11-24T10:00:00Z")
    client.get("/api/status", headers=AUTH)
    assert send("GET", "/api/settings/keys").get_json()["keys"][0]["last_used_at"] == "2026-11-24T10:00:00Z"
    assert send("DELETE", "/api/settings/keys/file").status_code == 404  # removed by removing the file


def test_without_a_token_file_there_is_no_file_row(env):
    env.pop("MOONIE_REDIRECT_API_TOKEN_FILE")
    send = admin(app.create_app(env).test_client())
    assert send("GET", "/api/settings/keys").get_json()["keys"] == []


@pytest.mark.parametrize(
    "header",
    [
        "Bearer mrk_unknown",
        "Bearer " + "mrk_" + "x" * 300,
        "Bearer " + TOKEN[:-1],
        "Basic " + TOKEN,
        "Bearer",
        "",
    ],
)
def test_an_unknown_key_is_unauthorized(client, store, header):
    key_header(store, "*")
    answer = client.get("/api/status", headers={"Authorization": header})
    assert answer.status_code == 401 and answer.get_json() == {"error": "unauthorized"}


# --- The settings are the session's alone ---


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/session"),
        ("GET", "/api/settings/security"),
        ("POST", "/api/settings/password"),
        ("POST", "/api/settings/sessions/end"),
        ("GET", "/api/settings/keys"),
        ("POST", "/api/settings/keys"),
        ("DELETE", "/api/settings/keys/abc"),
        ("GET", "/api/settings/webhook"),
        ("PUT", "/api/settings/webhook"),
        ("DELETE", "/api/settings/webhook"),
        ("POST", "/api/settings/webhook/test"),
        ("GET", "/api/settings/cloudflare"),
        ("PUT", "/api/settings/cloudflare/token"),
        ("DELETE", "/api/settings/cloudflare/token"),
        ("PUT", "/api/settings/cloudflare/item-limit"),
        ("GET", "/api/settings/anything/else"),
    ],
)
def test_no_key_reaches_the_settings_not_even_a_wildcard(client, store, method, path):
    for auth in (AUTH, key_header(store, "*"), key_header(store, *app.KNOWN_SCOPES)):
        answer = client.open(path, method=method, headers=auth, json={})
        assert answer.status_code == 403 and answer.get_json() == {"error": "needs_admin"}, (path, auth)


# --- The scope of every endpoint ---


@pytest.fixture
def rows(client, store):
    """One row of each kind, made by the session."""
    send = admin(client)
    made = {}
    for kind, extra in (
        ("link", {"slug": "promo"}),
        ("nano", {}),
        ("qrcode", {"design": {}}),
    ):
        answer = send("POST", "/api/links", json={"kind": kind, "name": kind, "target": "https://t.test/"} | extra)
        assert answer.status_code == 201, answer.get_json()
        made[kind] = answer.get_json()["id"]
    return made


ROW = {"link": "redirect:links", "nano": "redirect:nanourls", "qrcode": "redirect:qrcodes"}
# (method, path, body, scope, status when the scope is missing). `{link}`, `{nano}`, `{qrcode}` are the rows' ids.
MATRIX = [
    ("GET", "/api/links?kind=link", None, "redirect:links.read", 403),
    ("GET", "/api/links?kind=nano", None, "redirect:nanourls.read", 403),
    ("GET", "/api/links?kind=qrcode", None, "redirect:qrcodes.read", 403),
    ("GET", "/api/links/suggest", None, "redirect:links.write", 403),
    ("GET", "/api/links/suggest?kind=nano", None, "redirect:nanourls.write", 403),
    ("GET", "/api/links/suggest?kind=qrcode", None, "redirect:qrcodes.write", 403),
    (
        "POST",
        "/api/links",
        {"kind": "link", "slug": "new", "name": "N", "target": "https://n.test/"},
        "redirect:links.write",
        403,
    ),
    ("POST", "/api/links", {"kind": "nano", "name": "N", "target": "https://n.test/"}, "redirect:nanourls.write", 403),
    (
        "POST",
        "/api/links",
        {"kind": "qrcode", "name": "N", "target": "https://n.test/", "design": {}},
        "redirect:qrcodes.write",
        403,
    ),
    ("POST", "/api/qrcodes/preview", {"design": {}}, "redirect:qrcodes.read", 403),
    ("GET", "/api/cloudflare", None, "cloudflare:read", 403),
    ("GET", "/api/cloudflare/compare", None, "cloudflare:read", 403),
    ("POST", "/api/cloudflare/sync", {}, "cloudflare:write", 403),
    ("GET", "/api/cloudflare/zones", None, "cloudflare:setup", 403),
    ("GET", "/api/cloudflare/proposals?zone=z", None, "cloudflare:setup", 403),
    ("POST", "/api/cloudflare/plan", {}, "cloudflare:setup", 403),
    ("POST", "/api/cloudflare/apply", {}, "cloudflare:setup", 403),
    ("POST", "/api/cloudflare/compare/apply", {}, "cloudflare:setup", 403),
    ("POST", f"/api/cloudflare/hosts/{GO}/fallback", {"fallback": None}, "cloudflare:setup", 403),
]
for kind, scope in ROW.items():
    row_path = "/api/links/{" + kind + "}"
    MATRIX += [
        ("GET", row_path, None, f"{scope}.read", 404),
        ("PATCH", row_path, {"name": "Renamed"}, f"{scope}.write", 403),
        ("DELETE", row_path, None, f"{scope}.write", 403),
    ]
MATRIX.append(("GET", "/api/links/{qrcode}/qr.svg", None, "redirect:qrcodes.read", 404))


def wildcards(scope):
    return ["*", scope.split(":")[0] + ":*"]


@pytest.mark.parametrize(("method", "path", "body", "scope", "denied"), MATRIX, ids=lambda v: str(v)[:40])
def test_every_endpoint_asks_its_scope(client, store, rows, method, path, body, scope, denied):
    path = path.format(**rows)
    kind = next((k for k, row_id in rows.items() if f"/{row_id}" in path), None)
    read = f"{ROW[kind]}.read" if kind else None
    # Every other specific scope: refused (a write keeps its row's read, so the write is what is missing)
    answer = client.open(
        path, method=method, headers=key_header(store, *[s for s in SPECIFIC if s != scope]), json=body
    )
    assert answer.status_code == denied, answer.get_json()
    assert answer.get_json() == {"error": "scope_denied" if denied == 403 else "not_found"}
    # The scope itself (with its row's read), or a wildcard over it, is let through
    for granted in [scope, *wildcards(scope)]:
        held = {granted} | ({read} if read and granted == scope else set())
        answer = client.open(path, method=method, headers=key_header(store, *held), json=body)
        assert answer.status_code not in (401, 403, 404), (granted, answer.status_code, answer.get_json())
        if method == "DELETE":
            break  # the row is gone


def test_a_status_call_takes_any_valid_key(client, store):
    assert client.get("/api/status", headers=key_header(store, "cloudflare:read")).status_code == 200


def test_a_list_with_no_kind_holds_only_the_kinds_the_key_reads(client, store, rows):
    answer = client.get("/api/links", headers=key_header(store, "redirect:links.read", "redirect:qrcodes.read"))
    assert {row["kind"] for row in answer.get_json()["links"]} == {"link", "qrcode"}
    refused = client.get("/api/links", headers=key_header(store, "cloudflare:read", "redirect:links.write"))
    assert refused.status_code == 403 and refused.get_json() == {"error": "scope_denied"}


def test_a_key_cannot_change_a_rows_kind(client, store, rows):
    auth = key_header(store, "redirect:links.read", "redirect:links.write")
    answer = client.patch(f"/api/links/{rows['link']}", json={"kind": "qrcode"}, headers=auth)
    assert store.get(rows["link"])["kind"] == "link"
    assert answer.status_code in (200, 400)


def test_an_address_on_cloudflare_also_needs_cloudflare_write(client, store):
    body = {"slug": "x", "name": "X", "target": "https://x.test/", "address": GO}
    answer = client.post("/api/links", json=body, headers=key_header(store, "redirect:links.write"))
    assert answer.status_code == 403 and answer.get_json() == {"error": "scope_denied"}
    answer = client.post("/api/links", json=body, headers=key_header(store, "redirect:links.write", "cloudflare:write"))
    assert answer.status_code == 409 and answer.get_json() == {"error": "cloudflare_off"}
    lan = client.post("/api/links", json=body | {"address": "lan"}, headers=key_header(store, "redirect:links.write"))
    assert lan.status_code == 201


@pytest.fixture
def world(env):
    return World(env)


def test_a_link_on_cloudflare_is_changed_or_removed_with_cloudflare_write_only(world):
    made = world.session("POST", "/api/links", json=LINK | {"address": GO}).get_json()
    links_only = world.key("redirect:links.read", "redirect:links.write")
    with_cf = world.key("redirect:links.read", "redirect:links.write", "cloudflare:write")
    path = f"/api/links/{made['id']}"
    answer = world.admin.patch(path, json={"name": "Other"}, headers=links_only)
    assert answer.status_code == 403 and answer.get_json() == {"error": "scope_denied"}
    assert world.admin.patch(path, json={"name": "Other"}, headers=with_cf).status_code == 200
    gone = world.admin.delete(path + "?confirm_break=true", headers=links_only)
    assert gone.status_code == 403
    assert world.admin.delete(path + "?confirm_break=true", headers=with_cf).status_code == 204


def test_the_setup_scope_opens_adopted_hosts_and_the_setup_to_a_key(world):
    setup = world.key("redirect:links.write", "cloudflare:write", "cloudflare:setup")
    made = world.admin.post("/api/links", json=LINK | {"address": SITE}, headers=setup)
    assert made.status_code == 201, made.get_json()
    assert world.admin.get("/api/cloudflare/zones", headers=setup).status_code == 200
    reader = world.key("cloudflare:read", "cloudflare:setup")
    assert "fingerprint" in world.admin.get("/api/cloudflare/compare", headers=reader).get_json()


def test_a_preview_at_a_cloudflare_address_needs_no_cloudflare_scope(world):
    auth = world.key("redirect:qrcodes.read")
    answer = world.admin.post("/api/qrcodes/preview", json={"design": {}, "address": SITE}, headers=auth)
    assert answer.status_code == 200, answer.get_json()


def test_a_fake_client_is_never_reached_by_a_refused_call(world):
    calls = len(world.fake.ledger)
    narrow = world.key("cloudflare:read")
    assert world.admin.get("/api/cloudflare/zones", headers=narrow).status_code == 403
    assert world.admin.post("/api/cloudflare/sync", headers=narrow, json={}).status_code == 403
    assert len(world.fake.ledger) == calls
    assert isinstance(world.fake, FakeCloudflare)
