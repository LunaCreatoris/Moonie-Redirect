"""The admin pages' calls against the real app: every action of the shell's table (static/ui/shell.js ACTIONS) reaches a
route the server has, with the method it sends, and the Settings page's calls, made in the order the page makes them,
get the answers the page reads. The node tests drive the same calls against a fake; this file holds the fake to the
server."""

# The fixtures of test_app.py are imported, and every test names them as its arguments
# ruff: noqa: F811

import re
from pathlib import Path

import pytest
from test_app import AUTH, PASSWORD, client, clock, env, flask_app, login  # noqa: F401
from test_settings_cloudflare import NEW_TOKEN, Factory
from werkzeug.exceptions import MethodNotAllowed, NotFound

import app

SHELL = Path(__file__).resolve().parents[1] / "static" / "ui" / "shell.js"
NEW_PASSWORD = "a brand new admin password"
SECRET = "0123456789abcdef"


def actions() -> dict[str, dict]:
    """The shell's table, read from its source: each action's path (an id stands for its argument), method and query."""
    source = SHELL.read_text(encoding="utf-8")
    table = source[source.index("const ACTIONS = {") : source.index("\n}\n", source.index("const ACTIONS = {"))]
    found = {}
    for line in table.splitlines():
        entry = re.match(r"\s*'([a-z_.]+)': \{ path: \([a-z]*\) => (`[^`]*`|'[^']*')(.*)\},?$", line)
        if entry is None:
            continue
        name, path, rest = entry.groups()
        path = re.sub(r"\$\{encodeURIComponent\([a-z]+\)\}", "some-id", path[1:-1])
        method = re.search(r"method: '([A-Z]+)'", rest)
        query = re.search(r"query: \{ kind: '([a-z]+)' \}", rest)
        found[name] = {"path": path, "method": method and method.group(1), "kind": query and query.group(1)}
    return found


ACTIONS = actions()


def test_the_table_is_read_whole():
    assert len(ACTIONS) == SHELL.read_text(encoding="utf-8").count(": { path: (")
    assert {"links.suggest", "admin.security", "admin.webhook_test", "admin.cf_item_limit"} <= set(ACTIONS)


@pytest.mark.parametrize("name", sorted(ACTIONS))
def test_every_action_reaches_a_route_of_the_server(flask_app, name):
    action = ACTIONS[name]
    urls = flask_app.url_map.bind("redirect.test")
    if action["method"] is None:
        # The page gives the method (PATCH, DELETE) or the body does (GET, POST): the path alone must be a route
        try:
            urls.match(action["path"], method="GET")
        except MethodNotAllowed:
            pass
        except NotFound:
            pytest.fail(f"{name}: no route {action['path']}")
    else:
        urls.match(action["path"], method=action["method"])
    if action["kind"] is not None:
        assert action["kind"] in app.KINDS


def test_the_suggestion_asks_for_the_kind_the_server_checks(client):
    assert ACTIONS["links.suggest"]["kind"] == "link"
    answer = client.get("/api/links/suggest?kind=link", headers=AUTH)
    assert answer.status_code == 200 and isinstance(answer.get_json()["slug"], str)


class Page:
    """The Settings page's calls, with the session and its CSRF token, as the shell's request sends them."""

    def __init__(self, env) -> None:
        self.factory = Factory()
        self.app = app.create_app(env, cloudflare_factory=self.factory)
        self.client = self.app.test_client()
        self.csrf = login(self.client)

    def api(self, name, *, id_="", json=None):
        action = ACTIONS[name]
        method = action["method"] or ("GET" if json is None else "POST")
        path = action["path"].replace("some-id", id_)
        headers = {"Sec-Fetch-Site": "same-origin"}
        if method != "GET":
            headers["X-CSRF-Token"] = self.csrf
        return self.client.open(path, method=method, headers=headers, json=json)


@pytest.fixture
def page(env):
    return Page(env)


def test_the_security_tab_against_the_server(page):
    security = page.api("admin.security")
    assert security.status_code == 200
    body = security.get_json()
    assert body["password"]["origin"] == "file" and body["sessions"]["hours"] == 12
    assert body["login_brake_seconds"] == 1
    changed = page.api("admin.password", json={"password": PASSWORD, "new_password": "short"})
    assert changed.status_code == 400 and set(changed.get_json()["fields"]) == {"new_password"}
    wrong = page.api("admin.password", json={"password": "not it at all", "new_password": NEW_PASSWORD})
    assert wrong.status_code == 400 and wrong.get_json() == {
        "error": "login_failed",
        "fields": {"password": "wrong password"},
    }
    # The brake holds the next check for a second, as the page says under the password
    braked = page.api("admin.password", json={"password": "not it at all", "new_password": NEW_PASSWORD})
    assert braked.status_code == 429 and braked.get_json() == {"error": "too_many_attempts"}
    assert page.api("admin.sessions_end", json={}).status_code == 204


def test_the_webhook_tab_against_the_server(page):
    keys = page.api("admin.keys").get_json()
    assert keys["keys"][0] == {
        "id": "file",
        "name": "Token file",
        "prefix": None,
        "scopes": ["*"],
        "created_at": None,
        "last_used_at": None,
        "origin": "file",
    }
    assert keys["known_scopes"][:2] == ["*", "redirect:*"] and "cloudflare:setup" in keys["known_scopes"]
    webhook = page.api("admin.webhook").get_json()
    assert {"configured", "url", "events", "available", "secret", "cleartext", "disabled_reason"} <= set(webhook)
    assert {"last_delivery", "waiting", "timeout_seconds"} <= set(webhook)
    not_yet = page.api("admin.webhook_test", json={})
    assert not_yet.status_code == 409 and not_yet.get_json() == {"error": "not_configured"}
    closed = page.api("admin.webhook_save", json={"url": "http://127.0.0.1:5678/h", "events": [], "secret": SECRET})
    assert closed.status_code == 400 and closed.get_json()["fields"] == {"url": "url_closed"}
    first = page.api("admin.webhook_save", json={"url": "http://n8n.test:5678/h", "events": []})
    assert first.status_code == 400 and first.get_json()["fields"] == {"secret": "secret_required"}
    saved = page.api("admin.webhook_save", json={"url": "http://n8n.test:5678/h", "events": [], "secret": SECRET})
    assert saved.status_code == 200 and saved.get_json()["secret"] == "stored"
    assert page.api("admin.webhook_delete").status_code == 204


def test_the_keys_card_against_the_server(page):
    made = page.api(
        "admin.key_create",
        json={"name": "n8n", "scopes": ["redirect:*"], "password": PASSWORD},
    )
    assert made.status_code == 201, made.get_json()
    key = made.get_json()
    assert set(key) == {"id", "name", "prefix", "scopes", "secret"} and key["secret"].startswith(key["prefix"])
    assert page.api("admin.key_revoke", id_=key["id"]).status_code == 204
    assert page.api("admin.key_revoke", id_=key["id"]).status_code == 404


def test_the_cloudflare_tab_against_the_server(page):
    before = page.api("admin.cloudflare").get_json()
    assert before["token"]["origin"] == "missing" and before["item_limit"] == {"value": 10000, "origin": "default"}
    unprintable = page.api("admin.cf_token_set", json={"token": "bad tokené"})
    assert unprintable.status_code == 400 and set(unprintable.get_json()["fields"]) == {"token"}
    page.factory.refuse = True
    refused = page.api("admin.cf_token_set", json={"token": NEW_TOKEN})
    assert refused.status_code == 400 and refused.get_json() == {"error": "token_invalid"}
    page.factory.refuse = False
    stored = page.api("admin.cf_token_set", json={"token": NEW_TOKEN}).get_json()
    assert stored["token"]["origin"] == "stored" and stored["token"]["state"] == "ok"
    bad = page.api("admin.cf_item_limit", json={"value": 0})
    assert bad.status_code == 400 and set(bad.get_json()["fields"]) == {"value"}
    limit = page.api("admin.cf_item_limit", json={"value": 25000}).get_json()
    assert limit["item_limit"] == {"value": 25000, "origin": "stored"}
    assert page.api("admin.cf_token_clear").get_json()["token"]["origin"] == "missing"
