"""The n8n webhook (D26): its settings endpoints, the guard on where it may send, the outbox and its delivery, against a
receiver on loopback. Loopback is closed to the webhook, so these tests open it through the Webhook constructor's
`allow`, and give names through its `resolver`: nothing here reaches beyond this machine."""

# The fixtures of test_app.py are imported, and every test names them as its arguments
# ruff: noqa: F811

import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_app import AUTH, PASSWORD, csrf_of, env  # noqa: F401

import app

SECRET = "0123456789abcdef"
LINK = {"slug": "promo", "name": "Promo", "target": "https://example.test/"}
ALL_EVENTS = ["redirect.link.created", "redirect.link.updated", "redirect.link.deleted"]
START = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)


# --- Fakes -----------------------------------------------------------------------------------------------------------


class FakeSecrets(app.WebhookSecrets):
    """The secret store as the webhook sees it. `unreadable` stands for a row the current key cannot open."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.unreadable = False

    def state(self, name):
        if name not in self.values:
            return "missing"
        return "unreadable" if self.unreadable else "stored"

    def read(self, name):
        return None if self.unreadable else self.values.get(name)

    def write(self, name, value):
        self.values[name] = value
        self.unreadable = False

    def delete(self, name):
        self.values.pop(name, None)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Receiver:
    """An HTTP server on 127.0.0.1 that records each request and answers from `script`: a list of (status, body,
    extra headers) used in turn, the last one repeated. `drip` sends a 200 one byte at a time, `silent` never
    answers."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.script: list[tuple[int, bytes, dict]] = [(200, b"", {})]
        self.drip = False
        self.silent = False
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                receiver.requests.append(
                    {"path": self.path, "headers": dict(self.headers), "body": self.rfile.read(length)}
                )
                if receiver.silent:
                    time.sleep(3)
                    return
                if receiver.drip:
                    self.send_response(200)
                    self.send_header("Content-Length", "1000")
                    self.end_headers()
                    for _ in range(1000):
                        try:
                            self.wfile.write(b"x")
                            self.wfile.flush()
                        except OSError:
                            return
                        time.sleep(0.1)
                    return
                index = min(len(receiver.requests) - 1, len(receiver.script) - 1)
                status, body, headers = receiver.script[index]
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST

        class Server(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass  # a TLS hello or a cut connection is what some tests send on purpose

        self.server = Server(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def receiver():
    found = Receiver()
    yield found
    found.close()


@pytest.fixture
def names(receiver):
    """What the fake resolver answers: `n8n.test` is the receiver; `inside.test` resolves to loopback too, but is
    judged by the real list in tests that do not open loopback."""
    return {"n8n.test": ["127.0.0.1"], "inside.test": ["127.0.0.1"], "lan.test": ["192.168.1.20"]}


@pytest.fixture
def resolver(names):
    def resolve(host, port, type=0, **_kwargs):
        if host in names:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in names[host]]
        try:
            ipaddress.ip_address(host)
        except ValueError:
            raise socket.gaierror(socket.EAI_NONAME, "unknown name") from None
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]

    return resolve


@pytest.fixture
def fake_clock():
    return Clock()


@pytest.fixture
def held():
    return FakeSecrets()


@pytest.fixture
def options(resolver, fake_clock):
    return {
        "resolver": resolver,
        "allow": ("127.0.0.0/8",),
        "clock": fake_clock,
        "rand": lambda: 0.5,
        "attempt_seconds": 2.0,
    }


@pytest.fixture
def flask_app(env, held, options):
    return app.create_app(env, secret_store=held, webhook=lambda store, given: app.Webhook(store, given, **options))


@pytest.fixture
def hook(flask_app):
    return flask_app.extensions["webhook"]


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def admin(client):
    """The client signed in, with its CSRF token: what every settings call needs."""
    response = client.post("/login", data={"password": PASSWORD, "csrf": csrf_of(client)})
    assert response.status_code == 302
    csrf = csrf_of(client, "/admin/links")

    def call(method, path, **kwargs):
        headers = {"X-CSRF-Token": csrf, "Sec-Fetch-Site": "same-origin"} | kwargs.pop("headers", {})
        return client.open(path, method=method, headers=headers, **kwargs)

    return call


def url_of(receiver, path="/webhook/abc?token=s3cr3t-in-query"):
    return f"http://n8n.test:{receiver.port}{path}"


def configure(admin, receiver, events=None, **extra):
    body = {"url": url_of(receiver), "events": ALL_EVENTS if events is None else events, "secret": SECRET} | extra
    response = admin("PUT", "/api/settings/webhook", json=body)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def outbox(hook):
    with hook.store.read() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM webhook_outbox ORDER BY rowid")]


def create_link(client, **body):
    response = client.post("/api/links", json=LINK | body, headers=AUTH)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


# --- Settings endpoints ----------------------------------------------------------------------------------------------


def test_nothing_configured_answers_the_empty_state(admin):
    answer = admin("GET", "/api/settings/webhook").get_json()
    assert answer == {
        "configured": False,
        "url": None,
        "events": [],
        "available": [
            {"name": "redirect.link.created", "label": "Link created"},
            {"name": "redirect.link.updated", "label": "Link updated"},
            {"name": "redirect.link.deleted", "label": "Link deleted"},
        ],
        "secret": "missing",
        "cleartext": False,
        "disabled_reason": None,
        "last_delivery": None,
        "waiting": 0,
        "timeout_seconds": 2,
    }


def test_the_default_time_limit_is_30_seconds(env, held):
    built = app.create_app(env, secret_store=held)
    assert built.extensions["webhook"].answer()["timeout_seconds"] == 30


def test_a_save_stores_the_url_and_events_and_never_answers_the_secret(admin, receiver, held):
    answer = configure(admin, receiver, events=["redirect.link.deleted", "redirect.link.created"])
    assert answer["configured"] is True
    assert answer["url"] == url_of(receiver)
    assert answer["events"] == ["redirect.link.created", "redirect.link.deleted"]  # in the list's order
    assert answer["secret"] == "stored" and answer["cleartext"] is True
    assert held.values == {"webhook_secret": SECRET}
    assert SECRET not in json.dumps(answer)
    assert SECRET not in admin("GET", "/api/settings/webhook").get_data(as_text=True)


def test_an_empty_secret_keeps_the_stored_one(admin, receiver, held):
    configure(admin, receiver)
    for kept in ({"secret": ""}, {"secret": None}, {}):
        body = {"url": url_of(receiver, "/other"), "events": []} | kept
        assert admin("PUT", "/api/settings/webhook", json=body).status_code == 200
        assert held.values["webhook_secret"] == SECRET
    configure(admin, receiver, secret="another-secret-of-16")
    assert held.values["webhook_secret"] == "another-secret-of-16"


def test_https_is_not_cleartext(admin):
    body = {"url": "https://n8n.example.com/webhook/x", "events": [], "secret": SECRET}
    assert admin("PUT", "/api/settings/webhook", json=body).get_json()["cleartext"] is False


@pytest.mark.parametrize(
    "url",
    [
        None,
        42,
        "",
        "n8n.test/webhook",
        "ftp://n8n.test/",
        "javascript:alert(1)",
        "http://",
        "http://user:pass@n8n.test/",
        "http://user@n8n.test/",
        "http://n8n.test:0/",
        "http://n8n.test:65536/",
        "http://n8n.test:port/",
        "http://n8n.test/a b",
        "http://n8n.test/\\",
        "http://bücher.test/",
        "http://n8n.test/" + "a" * 2048,
    ],
)
def test_a_url_that_is_no_http_url_is_refused(admin, url):
    response = admin("PUT", "/api/settings/webhook", json={"url": url, "events": [], "secret": SECRET})
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid", "fields": {"url": "url_invalid"}}


def test_the_longest_url_is_accepted(admin):
    url = "http://n8n.test/" + "a" * (2048 - len("http://n8n.test/"))
    assert admin("PUT", "/api/settings/webhook", json={"url": url, "events": [], "secret": SECRET}).status_code == 200


@pytest.mark.parametrize(
    "secret, code",
    [("short", "secret_invalid"), ("x" * 15, "secret_invalid"), ("x" * 257, "secret_invalid"), (42, "secret_invalid")],
)
def test_a_secret_out_of_bounds_is_refused(admin, secret, code):
    body = {"url": "http://n8n.test/", "events": [], "secret": secret}
    assert admin("PUT", "/api/settings/webhook", json=body).get_json()["fields"] == {"secret": code}


def test_secret_bounds_are_16_and_256(admin):
    for secret in ("x" * 16, "x" * 256):
        body = {"url": "http://n8n.test/", "events": [], "secret": secret}
        assert admin("PUT", "/api/settings/webhook", json=body).status_code == 200


def test_the_first_save_needs_a_secret(admin, held):
    response = admin("PUT", "/api/settings/webhook", json={"url": "http://n8n.test/", "events": []})
    assert response.status_code == 400
    assert response.get_json()["fields"] == {"secret": "secret_required"}
    assert held.values == {}


@pytest.mark.parametrize("events", [None, "redirect.link.created", ["redirect.link.moved"], [1], ["moonie.key.denied"]])
def test_events_must_come_from_the_list(admin, events):
    body = {"url": "http://n8n.test/", "events": events, "secret": SECRET}
    assert admin("PUT", "/api/settings/webhook", json=body).get_json()["fields"] == {"events": "events_invalid"}


def test_every_field_error_is_answered_at_once_and_nothing_is_stored(admin, held, hook):
    response = admin("PUT", "/api/settings/webhook", json={"url": "ftp://x/", "events": "x", "secret": "s"})
    assert response.get_json()["fields"] == {
        "url": "url_invalid",
        "events": "events_invalid",
        "secret": "secret_invalid",
    }
    assert held.values == {} and hook.answer()["configured"] is False


def test_a_body_that_is_no_object_is_refused(admin):
    assert admin("PUT", "/api/settings/webhook", json=[1]).status_code == 400


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/api/settings/webhook"),
        ("PUT", "/api/settings/webhook"),
        ("DELETE", "/api/settings/webhook"),
        ("POST", "/api/settings/webhook/test"),
    ],
)
def test_the_settings_are_the_sessions_alone(client, method, path):
    answer = client.open(path, method=method, headers=AUTH, json={})
    assert answer.status_code == 403 and answer.get_json() == {"error": "needs_admin"}
    assert client.open(path, method=method, json={}).status_code == 401


def test_a_change_needs_the_csrf_header(client, admin):
    body = {"url": "http://n8n.test/", "events": [], "secret": SECRET}
    response = client.put("/api/settings/webhook", json=body, headers={"Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 403 and response.get_json() == {"error": "csrf"}


def test_delete_drops_the_settings_the_secret_and_the_waiting_rows(admin, client, receiver, hook, held):
    configure(admin, receiver)
    create_link(client)
    hook.pump()  # delivered: a finished row stays until the purge
    create_link(client, slug="second")
    assert [row["status"] for row in outbox(hook)] == ["delivered", "pending"]
    assert admin("DELETE", "/api/settings/webhook").status_code == 204
    assert [row["status"] for row in outbox(hook)] == ["delivered"]
    assert held.values == {}
    assert hook.answer() | {"available": None} == {
        "configured": False,
        "url": None,
        "events": [],
        "available": None,
        "secret": "missing",
        "cleartext": False,
        "disabled_reason": None,
        "last_delivery": None,
        "waiting": 0,
        "timeout_seconds": 2,
    }
    assert admin("DELETE", "/api/settings/webhook").status_code == 204  # twice is no error


def test_the_url_path_and_query_never_reach_the_log(admin, client, receiver, hook, caplog):
    caplog.set_level(logging.INFO)
    configure(admin, receiver)
    create_link(client)
    hook.pump()
    admin("POST", "/api/settings/webhook/test", json={})
    assert "s3cr3t-in-query" not in caplog.text and "/webhook/abc" not in caplog.text
    assert f"http://n8n.test:{receiver.port}" in caplog.text
    assert SECRET not in caplog.text


# --- The guard -------------------------------------------------------------------------------------------------------

CLOSED = [
    "127.0.0.1",
    "127.8.9.10",
    "::1",
    "0.0.0.0",
    "::",
    "169.254.169.254",
    "169.254.1.1",
    "fe80::1",
    "224.0.0.1",
    "ff02::1",
    "240.0.0.1",
    "255.255.255.255",
    "192.0.2.1",  # documentation
    "198.18.0.1",  # benchmarking
    "168.63.129.16",  # a metadata service outside link-local
    "100.100.100.200",
    "fd00:ec2::254",
    "::ffff:127.0.0.1",  # mapped
    "::ffff:169.254.169.254",
    "2002:7f00:1::",  # 6to4 of 127.0.0.1
    "2002:a9fe:a9fe::",  # 6to4 of 169.254.169.254
    "2001:0:4136:e378:8000:63bf:80ff:fffe",  # Teredo, client 127.0.0.1
    "64:ff9b::7f00:1",  # NAT64 of 127.0.0.1
    "fec0::1",  # site-local
    "not an address",
]
OPEN = [
    "8.8.8.8",
    "1.1.1.1",
    "10.20.30.40",
    "172.16.0.1",
    "172.20.0.3",  # a Docker network: http://n8n:5678 resolves here
    "172.31.255.254",
    "192.168.1.10",
    "100.64.1.1",
    "fd00::5",
    "2606:4700:4700::1111",
    "::ffff:192.168.1.10",
]


@pytest.mark.parametrize("address", CLOSED)
def test_closed_addresses(address):
    assert app.address_refused(address) is True


@pytest.mark.parametrize("address", OPEN)
def test_open_addresses(address):
    assert app.address_refused(address) is False


def test_the_teredo_vector_is_what_it_says():
    teredo = ipaddress.ip_address("2001:0:4136:e378:8000:63bf:80ff:fffe").teredo
    assert teredo[1] == ipaddress.ip_address("127.0.0.1")


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.1",
        "2130706433",  # decimal
        "0x7f000001",  # hexadecimal
        "0177.0.0.1",  # octal
        "017700000001",
        "[::1]",
        "[::ffff:127.0.0.1]",
        "[::ffff:7f00:1]",
        "[2002:7f00:1::]",
        "[2001:0:4136:e378:8000:63bf:80ff:fffe]",
        "169.254.169.254",
        "[fe80::1]",
        "0.0.0.0",
        "0",
        "224.0.0.1",
        "localhost",
        "LOCALHOST.",
        "api.localhost",
    ],
)
def test_a_closed_host_is_refused_at_save(env, held, host):
    hook = app.create_app(env, secret_store=held).extensions["webhook"]
    with pytest.raises(app.InvalidFields) as refused:
        hook.save({"url": f"http://{host}:5678/hook", "events": [], "secret": SECRET})
    assert refused.value.errors == {"url": "url_closed"}


@pytest.mark.parametrize(
    "host",
    ["192.168.1.10", "10.20.30.40", "172.20.0.3", "100.64.1.1", "[fd00::5]", "8.8.8.8", "n8n", "n8n.example.com"],
)
def test_an_open_host_or_a_name_is_accepted_at_save(env, held, host):
    hook = app.create_app(env, secret_store=held).extensions["webhook"]
    assert hook.save({"url": f"http://{host}:5678/hook", "events": [], "secret": SECRET})["configured"] is True


def test_the_allow_list_opens_only_what_it_names(env, held):
    hook = app.Webhook(app.Store(app.Path(env["MOONIE_REDIRECT_DB"])), held, allow=("127.0.0.0/8",))
    assert hook.address_closed("127.0.0.1") is False
    assert hook.address_closed("::1") is True
    assert hook.address_closed("169.254.169.254") is True


def test_a_name_resolving_to_loopback_is_closed_at_each_attempt(env, held, resolver, fake_clock, receiver):
    """No allow-list: `inside.test` passes at save, being a name, and is refused when it resolves to loopback."""
    built = app.create_app(
        env,
        secret_store=held,
        webhook=lambda store, given: app.Webhook(store, given, resolver=resolver, clock=fake_clock),
    )
    hook = built.extensions["webhook"]
    hook.save({"url": f"http://inside.test:{receiver.port}/", "events": ALL_EVENTS, "secret": SECRET})
    hook.emit("redirect.link.created", {"id": "a", "kind": "link"})
    assert hook.pump() is True
    assert receiver.requests == []
    row = outbox(hook)[0]
    assert row["status"] == "pending" and row["attempts"] == 1 and row["last_error"] == "address_closed"


def test_one_closed_answer_among_open_ones_closes_the_name(hook, names, receiver, admin):
    names["n8n.test"] = ["192.168.1.20", "169.254.169.254", "127.0.0.1"]
    hook.allow = ()
    configure(admin, receiver)
    assert hook.test()["error"] == "address_closed"
    assert receiver.requests == []


def test_the_socket_goes_to_the_address_that_was_judged(hook, names, receiver, admin):
    """A resolver that answers loopback once, then something else: the attempt resolves once, and connects there."""
    answers = iter([["127.0.0.1"], ["192.0.2.1"]])
    asked = []

    def flipping(host, port, type=0, **_kwargs):
        asked.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in next(answers)]

    configure(admin, receiver)
    hook.resolver = flipping
    assert hook.test()["status"] == 200
    assert asked == ["n8n.test"] and len(receiver.requests) == 1


# --- Delivery --------------------------------------------------------------------------------------------------------


def test_a_delivery_carries_7_0_1_headers_and_a_signature_n8n_can_check(admin, client, receiver, hook, fake_clock):
    configure(admin, receiver)
    link = create_link(client)
    assert hook.pump() is True
    [sent] = receiver.requests
    headers = sent["headers"]
    assert sent["path"] == "/webhook/abc?token=s3cr3t-in-query"
    assert headers["Host"] == f"n8n.test:{receiver.port}"
    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"] == f"moonie-redirect/{app.VERSION}"
    assert headers["X-Moonie-Event"] == "redirect.link.created"
    assert headers["X-Moonie-Timestamp"] == str(int(START.timestamp()))
    event_id = headers["X-Moonie-Event-Id"]
    assert event_id.startswith("evt_") and len(event_id) == 36
    expected = hmac.new(
        SECRET.encode(), f"{event_id}.{headers['X-Moonie-Timestamp']}.".encode() + sent["body"], hashlib.sha256
    )
    assert headers["X-Moonie-Signature"] == "sha256=" + expected.hexdigest()
    body = json.loads(sent["body"])
    assert body == {
        "id": event_id,
        "event": "redirect.link.created",
        "source": "redirect",
        "at": "2026-11-24T12:00:00Z",
        "data": {
            "id": link["id"],
            "kind": "link",
            "slug": "promo",
            "name": "Promo",
            "target": "https://example.test/",
            "http_status": 302,
            "expires_on": None,
            "address": "lan",
            "updated_at": link["updated_at"],
        },
    }
    row = outbox(hook)[0]
    assert row["status"] == "delivered" and row["attempts"] == 1 and row["last_status"] == 200
    last = hook.answer()["last_delivery"]
    assert last == {
        "event_id": event_id,
        "event": "redirect.link.created",
        "status": 200,
        "at": "2026-11-24T12:00:00Z",
        "error": None,
    }


def test_signature_known_vector():
    body = b'{"ok":true}'
    assert app.sign(SECRET, "evt_00000000000000000000000000000001", 1700000000, body) == (
        "sha256=df81ab842a3ef4c657be5a04dae28169d95a7b96ce9613cc0f6f813a2f28e060"
    )


def test_a_qr_code_event_never_carries_its_design(admin, client, receiver, hook):
    configure(admin, receiver)
    create_link(client, kind="qrcode", slug="qr", name="Qr")
    hook.pump()
    data = json.loads(receiver.requests[0]["body"])["data"]
    assert data["kind"] == "qrcode" and "design" not in data and "logo" not in json.dumps(data)


def test_events_come_from_create_update_and_delete_by_key(admin, client, receiver, hook):
    configure(admin, receiver)
    link = create_link(client)
    assert client.patch(f"/api/links/{link['id']}", json={"target": "https://b.test/"}, headers=AUTH).status_code == 200
    assert client.delete(f"/api/links/{link['id']}", headers=AUTH).status_code == 204
    rows = outbox(hook)
    assert [row["event"] for row in rows] == ALL_EVENTS
    targets = [json.loads(row["body"])["data"]["target"] for row in rows]
    assert targets == ["https://example.test/", "https://b.test/", "https://b.test/"]
    while hook.pump():
        pass
    assert [r["headers"]["X-Moonie-Event"] for r in receiver.requests] == ALL_EVENTS


def test_events_come_from_create_update_and_delete_by_session(admin, receiver, hook):
    configure(admin, receiver)
    created = admin("POST", "/api/links", json=LINK)
    assert created.status_code == 201
    id_ = created.get_json()["id"]
    assert admin("PATCH", f"/api/links/{id_}", json={"name": "Renamed"}).status_code == 200
    assert admin("DELETE", f"/api/links/{id_}").status_code == 204
    assert [row["event"] for row in outbox(hook)] == ALL_EVENTS


def test_a_refused_or_empty_change_raises_no_event(admin, client, receiver, hook):
    configure(admin, receiver)
    link = create_link(client)
    assert client.post("/api/links", json=LINK, headers=AUTH).status_code == 409  # slug taken
    assert client.patch(f"/api/links/{link['id']}", json={"target": "ftp://x"}, headers=AUTH).status_code == 400
    assert client.patch(f"/api/links/{link['id']}", json={}, headers=AUTH).status_code == 200
    assert client.delete("/api/links/nothere1", headers=AUTH).status_code == 404
    assert [row["event"] for row in outbox(hook)] == ["redirect.link.created"]


def test_only_the_ticked_events_are_queued(admin, client, receiver, hook):
    configure(admin, receiver, events=["redirect.link.deleted"])
    link = create_link(client)
    client.patch(f"/api/links/{link['id']}", json={"name": "Other"}, headers=AUTH)
    client.delete(f"/api/links/{link['id']}", headers=AUTH)
    assert [row["event"] for row in outbox(hook)] == ["redirect.link.deleted"]


def test_with_no_webhook_nothing_is_queued(client, hook):
    create_link(client)
    assert outbox(hook) == []


def test_an_event_never_fails_the_request(admin, client, receiver, hook, monkeypatch):
    configure(admin, receiver)

    def broken(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(hook, "_emit", broken)
    create_link(client)


def test_an_unreadable_secret_queues_nothing_and_holds_the_rows(admin, client, receiver, hook, held, caplog):
    configure(admin, receiver)
    create_link(client)
    held.unreadable = True
    create_link(client, slug="second")
    assert len(outbox(hook)) == 1  # the second event was not queued
    assert hook.pump() is False
    assert receiver.requests == [] and outbox(hook)[0]["attempts"] == 0
    answer = admin("GET", "/api/settings/webhook").get_json()
    assert answer["secret"] == "unreadable" and answer["waiting"] == 1
    assert "signing secret cannot be read" in caplog.text
    # A save must bring a new secret, then the row goes
    response = admin("PUT", "/api/settings/webhook", json={"url": url_of(receiver), "events": ALL_EVENTS})
    assert response.get_json()["fields"] == {"secret": "secret_required"}
    configure(admin, receiver, secret="a-brand-new-secret")
    assert hook.pump() is True and outbox(hook)[0]["status"] == "delivered"


def test_the_outbox_holds_at_most_10000_waiting_rows(admin, client, receiver, hook, caplog):
    configure(admin, receiver)
    with hook.store.write() as conn:
        conn.executemany(
            "INSERT INTO webhook_outbox (id, event, body, created_at, status, next_attempt_at)"
            " VALUES (?, 'redirect.link.created', x'7b7d', '2026-11-24T12:00:00Z', 'pending', '2026-11-24T12:00:00Z')",
            [(f"evt_{n}",) for n in range(app.MAX_PENDING)],
        )
    create_link(client)
    assert len(outbox(hook)) == app.MAX_PENDING
    assert "outbox full" in caplog.text
    assert not any(json.loads(row["body"]).get("data") for row in outbox(hook))  # the new event was dropped


def test_an_event_larger_than_64_kib_is_dropped(admin, receiver, hook, caplog):
    configure(admin, receiver)
    hook.emit("redirect.link.created", {"id": "a", "name": "x" * (64 * 1024)})
    assert outbox(hook) == [] and "larger than" in caplog.text


# --- Retries, 410, redirects, limits ---------------------------------------------------------------------------------


def test_the_retry_schedule_is_10_s_60_s_5_min_30_min_then_failed(admin, client, receiver, hook, fake_clock):
    receiver.script = [(503, b"", {})]
    configure(admin, receiver)
    create_link(client)
    waits = []
    for attempt in range(1, 6):
        assert hook.pump() is True
        row = outbox(hook)[0]
        assert row["attempts"] == attempt and row["last_status"] == 503
        if attempt < 5:
            assert row["status"] == "pending"
            due = datetime.strptime(row["next_attempt_at"], app.STAMP).replace(tzinfo=UTC)
            waits.append((due - fake_clock.now).total_seconds())
            fake_clock.advance(waits[-1] - 1)
            assert hook.pump() is False  # not due yet
            fake_clock.advance(1)
    assert waits == [10, 60, 300, 1800]
    row = outbox(hook)[0]
    assert row["status"] == "failed" and row["finished_at"] is not None
    assert hook.pump() is False
    assert len(receiver.requests) == 5


@pytest.mark.parametrize("rand, wait", [(0.0, 8), (1.0, 12), (0.25, 9)])
def test_the_wait_has_20_percent_jitter(admin, client, receiver, hook, fake_clock, rand, wait):
    receiver.script = [(500, b"", {})]
    hook.rand = lambda: rand
    configure(admin, receiver)
    create_link(client)
    hook.pump()
    due = datetime.strptime(outbox(hook)[0]["next_attempt_at"], app.STAMP).replace(tzinfo=UTC)
    assert (due - fake_clock.now).total_seconds() == wait


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504, 599])
def test_these_statuses_are_retried(admin, client, receiver, hook, status):
    receiver.script = [(status, b"", {})]
    configure(admin, receiver)
    create_link(client)
    hook.pump()
    row = outbox(hook)[0]
    assert row["status"] == "pending" and row["attempts"] == 1 and row["last_status"] == status


def test_no_answer_is_retried(admin, client, receiver, hook):
    configure(admin, receiver)
    port = receiver.port
    receiver.close()
    create_link(client)
    hook.pump()
    row = outbox(hook)[0]
    assert row["status"] == "pending" and row["last_status"] is None
    assert row["last_error"].startswith("ConnectionRefusedError")
    assert str(port) not in row["last_error"]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 413, 301, 302, 303, 307, 308, 418])
def test_any_other_status_fails_the_row_at_once(admin, client, receiver, hook, status):
    receiver.script = [(status, b"", {"Location": f"http://127.0.0.1:{receiver.port}/elsewhere"})]
    configure(admin, receiver)
    create_link(client)
    hook.pump()
    row = outbox(hook)[0]
    assert row["status"] == "failed" and row["attempts"] == 1 and row["last_status"] == status


def test_a_redirect_is_never_followed(admin, client, receiver, hook):
    receiver.script = [(307, b"", {"Location": f"http://127.0.0.1:{receiver.port}/elsewhere"})]
    configure(admin, receiver)
    create_link(client)
    hook.pump()
    assert [r["path"] for r in receiver.requests] == ["/webhook/abc?token=s3cr3t-in-query"]
    assert admin("POST", "/api/settings/webhook/test", json={}).get_json()["status"] == 307
    assert len(receiver.requests) == 2


def test_410_disables_the_webhook_and_keeps_the_rows_until_a_save(admin, client, receiver, hook, caplog):
    receiver.script = [(410, b"", {}), (200, b"", {})]
    configure(admin, receiver)
    create_link(client)
    create_link(client, slug="second")
    assert hook.pump() is True
    assert "answered 410" in caplog.text
    answer = admin("GET", "/api/settings/webhook").get_json()
    assert answer["disabled_reason"] == "gone" and answer["waiting"] == 2
    assert [row["status"] for row in outbox(hook)] == ["pending", "pending"]
    assert hook.pump() is False  # nothing goes while disabled
    create_link(client, slug="third")  # nor is anything queued
    assert len(outbox(hook)) == 2
    # Save turns it back on, and the kept rows go
    assert configure(admin, receiver)["disabled_reason"] is None
    while hook.pump():
        pass
    assert [row["status"] for row in outbox(hook)] == ["delivered", "delivered"]
    assert len(receiver.requests) == 3


def test_a_slow_drip_reply_is_cut_at_the_deadline(admin, client, receiver, hook):
    receiver.drip = True
    hook.attempt_seconds = 0.5
    configure(admin, receiver)
    create_link(client)
    started = time.monotonic()
    hook.pump()
    assert time.monotonic() - started < 3
    row = outbox(hook)[0]
    assert row["status"] == "pending" and row["last_error"] == "deadline"


def test_a_silent_receiver_is_cut_at_the_deadline(admin, client, receiver, hook):
    receiver.silent = True
    hook.attempt_seconds = 0.5
    configure(admin, receiver)
    started = time.monotonic()
    result = admin("POST", "/api/settings/webhook/test", json={}).get_json()
    assert time.monotonic() - started < 3
    assert result["status"] is None and result["error"] == "deadline"


def test_a_reply_over_64_kib_still_delivers_and_is_dropped(admin, client, receiver, hook):
    receiver.script = [(200, b'"' + b"x" * (1024 * 1024) + b'"', {"Content-Type": "application/json"})]
    configure(admin, receiver)
    create_link(client)
    hook.pump()
    assert outbox(hook)[0]["status"] == "delivered"
    result = admin("POST", "/api/settings/webhook/test", json={}).get_json()
    assert result["status"] == 200 and result["reply_is_json"] is False


def test_https_to_a_plain_http_receiver_fails_the_handshake_without_naming_it(admin, receiver, hook):
    body = {"url": f"https://n8n.test:{receiver.port}/hook", "events": [], "secret": SECRET}
    assert admin("PUT", "/api/settings/webhook", json=body).status_code == 200
    result = hook.test()
    assert result["status"] is None and result["error"].startswith("SSL")
    assert "n8n.test" not in result["error"]


def test_a_delivery_after_the_url_moved_records_nothing(admin, client, receiver, hook, monkeypatch):
    """The answer of the old address says nothing of the new one: the row stays as it was, to go to the new one."""
    receiver.script = [(410, b"", {})]
    configure(admin, receiver)
    create_link(client)
    real = app._Attempt.run

    def moved(self):
        outcome = real(self)
        hook.save({"url": url_of(receiver, "/new"), "events": ALL_EVENTS})
        return outcome

    monkeypatch.setattr(app._Attempt, "run", moved)
    hook.pump()
    row = outbox(hook)[0]
    assert row["status"] == "pending" and row["attempts"] == 0
    assert hook.answer()["disabled_reason"] is None


def test_a_row_deleted_during_its_attempt_is_not_recorded(admin, client, receiver, hook, monkeypatch):
    configure(admin, receiver)
    create_link(client)
    real = app._Attempt.run

    def cleared(self):
        outcome = real(self)
        hook.clear()
        return outcome

    monkeypatch.setattr(app._Attempt, "run", cleared)
    hook.pump()
    assert outbox(hook) == [] and hook.answer()["last_delivery"] is None


def test_the_oldest_due_row_goes_first(admin, client, receiver, hook, fake_clock):
    configure(admin, receiver)
    for slug in ("one", "two", "three"):
        create_link(client, slug=slug)
        fake_clock.advance(1)
    while hook.pump():
        pass
    sent = [json.loads(r["body"])["data"]["slug"] for r in receiver.requests]
    assert sent == ["one", "two", "three"]


# --- Purge -----------------------------------------------------------------------------------------------------------


def test_finished_rows_are_purged_after_7_days_once_an_hour(admin, hook, fake_clock):
    def put(id_, status, finished):
        with hook.store.write() as conn:
            conn.execute(
                "INSERT INTO webhook_outbox (id, event, body, created_at, status, next_attempt_at, finished_at)"
                " VALUES (?, 'e', x'7b7d', '2026-01-01T00:00:00Z', ?, '2026-01-01T00:00:00Z', ?)",
                (id_, status, finished),
            )

    stamp = lambda days: app._stamp(START - timedelta(days=days))  # noqa: E731
    put("old-delivered", "delivered", stamp(8))
    put("old-failed", "failed", stamp(7.1))
    put("recent", "delivered", app._stamp(START - timedelta(days=7) + timedelta(minutes=10)))
    put("old-pending", "pending", None)
    assert hook.purge() == 2
    assert {row["id"] for row in outbox(hook)} == {"recent", "old-pending"}
    fake_clock.advance(30 * 60)  # `recent` is now past 7 days, but the purge runs once an hour
    assert hook.purge() == 0
    fake_clock.advance(31 * 60)
    assert hook.purge() == 1
    assert {row["id"] for row in outbox(hook)} == {"old-pending"}


# --- Test endpoint ---------------------------------------------------------------------------------------------------


def test_the_test_needs_a_webhook(admin):
    answer = admin("POST", "/api/settings/webhook/test", json={})
    assert answer.status_code == 409 and answer.get_json() == {"error": "not_configured"}


def test_the_test_needs_a_readable_secret(admin, receiver, held):
    configure(admin, receiver)
    held.unreadable = True
    assert admin("POST", "/api/settings/webhook/test", json={}).status_code == 409


def test_the_test_sends_one_signed_event_outside_the_outbox(admin, receiver, hook):
    receiver.script = [(200, b'{"ok": true}', {"Content-Type": "application/json"})]
    configure(admin, receiver, events=[])
    answer = admin("POST", "/api/settings/webhook/test", json={})
    assert answer.status_code == 200
    result = answer.get_json()
    assert result["status"] == 200 and result["error"] is None and result["reply_is_json"] is True
    assert isinstance(result["duration_ms"], int) and result["duration_ms"] >= 0
    [sent] = receiver.requests
    assert sent["headers"]["X-Moonie-Event"] == "moonie.webhook.test"
    assert json.loads(sent["body"])["data"] == {} and json.loads(sent["body"])["source"] == "redirect"
    assert outbox(hook) == [] and hook.answer()["last_delivery"] is None


def test_a_failed_test_is_never_retried(admin, receiver, hook):
    receiver.script = [(503, b"", {})]
    configure(admin, receiver)
    result = admin("POST", "/api/settings/webhook/test", json={}).get_json()
    assert result["status"] == 503 and result["reply_is_json"] is False
    assert len(receiver.requests) == 1 and outbox(hook) == []


def test_a_non_json_reply_is_said_so(admin, receiver):
    receiver.script = [(200, b"<html>", {})]
    configure(admin, receiver)
    assert admin("POST", "/api/settings/webhook/test", json={}).get_json()["reply_is_json"] is False


def test_one_test_at_a_time(admin, receiver, hook):
    configure(admin, receiver)
    hook._test_lock.acquire()
    try:
        answer = admin("POST", "/api/settings/webhook/test", json={})
        assert answer.status_code == 429 and answer.get_json() == {"error": "busy"}
    finally:
        hook._test_lock.release()
    assert admin("POST", "/api/settings/webhook/test", json={}).status_code == 200


# --- The thread ------------------------------------------------------------------------------------------------------


def test_the_thread_delivers_a_new_event_at_once(env, held, resolver, receiver):
    built = app.create_app(
        env,
        secret_store=held,
        webhook=lambda store, given: app.Webhook(store, given, resolver=resolver, allow=("127.0.0.0/8",)),
    )
    hook = built.extensions["webhook"]
    hook.save({"url": url_of(receiver), "events": ALL_EVENTS, "secret": SECRET})
    hook.start()
    try:
        built.test_client().post("/api/links", json=LINK, headers=AUTH)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not receiver.requests:
            time.sleep(0.05)
        assert len(receiver.requests) == 1
    finally:
        hook.stop()


def test_the_thread_sleeps_until_the_next_due_row(admin, client, receiver, hook, fake_clock):
    assert hook.idle_seconds() == 60
    receiver.script = [(503, b"", {})]
    configure(admin, receiver)
    create_link(client)
    assert hook.idle_seconds() == 0
    hook.pump()
    assert hook.idle_seconds() == 10
    fake_clock.advance(4)
    assert hook.idle_seconds() == 6


def test_a_held_thread_sleeps_and_a_save_wakes_it(admin, client, receiver, hook):
    """After a 410 the due row waits on the admin: the thread sleeps the full idle time, and the save that turns the
    webhook back on wakes it at once."""
    receiver.script = [(410, b"", {}), (200, b"", {})]
    configure(admin, receiver)
    create_link(client)
    assert hook.pump() is True
    hook.start()
    try:
        time.sleep(0.2)
        assert len(receiver.requests) == 1
        configure(admin, receiver)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and outbox(hook)[0]["status"] == "pending":
            time.sleep(0.05)
        assert outbox(hook)[0]["status"] == "delivered"
    finally:
        hook.stop()


def test_a_stop_that_times_out_never_leaves_two_threads(hook):
    """stop() gives up waiting while an attempt runs; the start() that follows waits for that thread to end rather
    than run a second one beside it."""
    entered, release = threading.Event(), threading.Event()

    def slow_pump():
        entered.set()
        release.wait(5)
        return False

    hook.pump = slow_pump
    hook.start()
    try:
        assert entered.wait(5)
        hook.stop(wait=0.05)
        threading.Timer(0.3, release.set).start()
        hook.start()
        alive = [thread for thread in threading.enumerate() if thread.name == "webhook" and thread.is_alive()]
        assert len(alive) == 1
    finally:
        release.set()
        hook.stop()
    assert not [thread for thread in threading.enumerate() if thread.name == "webhook" and thread.is_alive()]


def test_main_starts_the_webhook_thread():
    source = app.Path(app.__file__).read_text()
    main = source[source.index("def main(") :]
    assert 'app.extensions["webhook"].start()' in main


# --- With the app's own sealed store ---------------------------------------------------------------------------------


def sealed_app(env, resolver):
    """The app with no fake secret store: the webhook reads the secret from the sealed `secrets` table (D23)."""
    return app.create_app(
        env, webhook=lambda store, given: app.Webhook(store, given, resolver=resolver, allow=("127.0.0.0/8",))
    )


def signed_in(built):
    client = built.test_client()
    assert client.post("/login", data={"password": PASSWORD, "csrf": csrf_of(client)}).status_code == 302
    csrf = csrf_of(client, "/admin/links")
    return client, {"X-CSRF-Token": csrf, "Sec-Fetch-Site": "same-origin"}


def test_the_app_seals_the_webhook_secret_and_signs_with_it(env, resolver, receiver):
    built = sealed_app(env, resolver)
    assert isinstance(built.extensions["webhook"].secrets, app.SealedSecrets)
    client, headers = signed_in(built)
    body = {"url": url_of(receiver), "events": ALL_EVENTS, "secret": SECRET}
    assert client.put("/api/settings/webhook", json=body, headers=headers).status_code == 200
    store = built.extensions["store"]
    with store.read() as conn:
        [row] = conn.execute("SELECT name, value FROM secrets").fetchall()
    assert row["name"] == "webhook_secret" and SECRET.encode() not in bytes(row["value"])
    assert SECRET.encode() not in store.path.read_bytes()
    client.post("/api/links", json=LINK, headers=AUTH)
    hook = built.extensions["webhook"]
    assert hook.pump() is True
    [sent] = receiver.requests
    signed = f"{sent['headers']['X-Moonie-Event-Id']}.{sent['headers']['X-Moonie-Timestamp']}.".encode() + sent["body"]
    expected = "sha256=" + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
    assert sent["headers"]["X-Moonie-Signature"] == expected


def test_a_new_store_key_leaves_the_webhook_secret_unreadable_and_holds_the_rows(env, resolver, receiver, tmp_path):
    first = tmp_path / "first_key"
    first.write_text("11" * 32 + "\n")
    built = sealed_app(env | {"MOONIE_REDIRECT_STORE_KEY_FILE": str(first)}, resolver)
    built.extensions["webhook"].save({"url": url_of(receiver), "events": ALL_EVENTS, "secret": SECRET})
    second = tmp_path / "second_key"
    second.write_text("22" * 32 + "\n")
    again = sealed_app(env | {"MOONIE_REDIRECT_STORE_KEY_FILE": str(second)}, resolver)
    hook = again.extensions["webhook"]
    assert hook.answer()["secret"] == "unreadable"
    again.test_client().post("/api/links", json=LINK, headers=AUTH)
    hook.pump()
    assert receiver.requests == []
