"""Breaker round on the Settings page of 9.2.0: the webhook's guard and delivery, the secrets, the keys and the session
endpoints, probed from outside. Every test drives the app as a receiver, an admin or a key would; loopback is opened
through the Webhook constructor only, as in test_webhook.py."""

# The fixtures of test_app.py and test_webhook.py are imported, and every test names them as its arguments
# ruff: noqa: F811

import datetime as dt
import hashlib
import hmac
import logging
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from test_app import AUTH, PASSWORD, csrf_of, env  # noqa: F401
from test_settings_cloudflare import Factory
from test_webhook import (  # noqa: F401
    ALL_EVENTS,
    LINK,
    SECRET,
    admin,
    client,
    configure,
    create_link,
    fake_clock,
    flask_app,
    held,
    hook,
    names,
    options,
    outbox,
    receiver,
    resolver,
)

import app

# --- A webhook that cannot send ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("why", ["gone", "unreadable"])
def test_break_settings_a_webhook_that_cannot_send_sleeps(admin, client, receiver, hook, held, why):
    """A receiver that answered 410, or a secret the store key no longer opens, holds the waiting rows (D26). Nothing
    can go out until the admin saves again, so the thread must sleep, not poll the database in a tight loop."""
    configure(admin, receiver)
    create_link(client)
    if why == "gone":
        receiver.script = [(410, b"", {})]
        assert hook.pump() is True
        assert hook.answer()["disabled_reason"] == "gone"
    else:
        held.unreadable = True
    assert outbox(hook)[0]["status"] == "pending"
    rounds = []
    real = hook.pump

    def counted():
        rounds.append(1)
        return real()

    hook.pump = counted
    hook.start()
    try:
        time.sleep(0.5)
    finally:
        hook.stop()
    assert len(rounds) <= 3, f"{len(rounds)} rounds in 0.5 s while nothing can be sent"


# --- Probes that held: the guard -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "2852039166",  # 169.254.169.254, decimal
        "0251.0376.0251.0376",  # 169.254.169.254, octal
        "0xa9.0xfe.0xa9.0xfe",  # 169.254.169.254, hexadecimal parts
        "0x7f.1",
        "127.0.0.1.",
        "[::ffff:a9fe:a9fe]",
        "[0:0:0:0:0:ffff:127.0.0.1]",
        "[::127.0.0.1]",  # IPv4-compatible, deprecated
        "[::ffff:0:7f00:1]",  # IPv4-translated
        "[64:ff9b::a9fe:a9fe]",  # NAT64 of the metadata address
        "[64:ff9b:1::7f00:1]",  # local-use NAT64
        "[fe80::1%25eth0]",
        "[fd00:ec2::254]",
        "0.0.0.0",
        "[::]",
        "foo.localhost.",
    ],
)
def test_break_settings_probe_more_closed_spellings_are_refused_at_save(env, held, host):
    hook = app.create_app(env, secret_store=held).extensions["webhook"]
    with pytest.raises(app.InvalidFields) as refused:
        hook.save({"url": f"http://{host}:5678/hook", "events": [], "secret": SECRET})
    assert refused.value.errors == {"url": "url_closed"}


@pytest.mark.parametrize(
    "url",
    [
        "http://:@n8n.test/",
        "http://user%40x@n8n.test/",
        "http://n8n.test:-1/",
        "http://n8n.test:99999999999/",
        "http://n8n.test:١/",
        "http://n8n.test\t/",
        "http://n8n.test/\r\nX-Injected: 1",
        "HTTP://n8n.test@evil.test/",
        "http://[::1/",
    ],
)
def test_break_settings_probe_malformed_urls_are_refused(admin, url):
    response = admin("PUT", "/api/settings/webhook", json={"url": url, "events": [], "secret": SECRET})
    assert response.status_code == 400
    assert response.get_json()["fields"]["url"] in ("url_invalid", "url_closed")


def _six(address, port):
    return (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, port, 0, 0))


@pytest.mark.parametrize(
    "answer",
    [
        ["::ffff:169.254.169.254"],
        ["fe80::1%lo0"],
        ["64:ff9b::a9fe:a9fe"],
        ["2002:a9fe:a9fe::"],
        ["fd00:ec2::254"],
        ["::"],
        ["::1"],
        ["0.0.0.0"],
        ["10.20.30.40", "169.254.169.254"],  # one closed answer among open ones closes the name
    ],
)
def test_break_settings_probe_closed_answers_are_refused_before_any_connect(
    admin, receiver, hook, names, monkeypatch, answer
):
    """A name is judged on every address it resolves to, IPv6 answers included, and nothing is connected to."""
    dialed = []
    monkeypatch.setattr(
        app.socket, "create_connection", lambda *a, **k: dialed.append(a) or (_ for _ in ()).throw(OSError())
    )

    def resolve(host, port, type=0, **_kwargs):
        return [
            _six(ip, port) if ":" in ip else (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in answer
        ]

    configure(admin, receiver)
    hook.allow = ()
    hook.resolver = resolve
    assert hook.test()["error"] == "address_closed"
    assert dialed == [] and receiver.requests == []


def test_break_settings_probe_a_docker_service_name_passes_the_guard_at_each_attempt(admin, hook, monkeypatch):
    """`http://n8n:5678` resolves to the Docker network (172.16/12): saved, and dialed at the very address judged, with
    no allow-list."""
    dialed = []

    def refuse(address, timeout=None, *args, **kwargs):
        dialed.append(address)
        raise ConnectionRefusedError(111, "refused")

    monkeypatch.setattr(app.socket, "create_connection", refuse)
    hook.allow = ()
    hook.resolver = lambda host, port, type=0, **_: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.20.0.3", port))]
    body = {"url": "http://n8n:5678/webhook/x", "events": ALL_EVENTS, "secret": SECRET}
    assert admin("PUT", "/api/settings/webhook", json=body).status_code == 200
    result = hook.test()
    assert dialed == [("172.20.0.3", 5678)]
    assert result["status"] is None and result["error"] != "address_closed"


# --- Probes that held: TLS names the host, never the address ---------------------------------------------------------


def _pem_pair(tmp_path, name):
    """A CA and a server certificate for `name`, signed by it: what a receiver behind a private CA shows."""
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    later = now + dt.timedelta(days=3650)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "break test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(later)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(2)
        .not_valid_before(now)
        .not_valid_after(later)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    ca_file, cert_file, key_file = tmp_path / "ca.pem", tmp_path / "cert.pem", tmp_path / "key.pem"
    ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_file.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return ca_file, cert_file, key_file


class TlsReceiver:
    def __init__(self, cert_file, key_file) -> None:
        self.seen: dict = {"sni": [], "host": []}
        seen = self.seen
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_file, key_file)
        context.sni_callback = lambda _sock, server_name, _ctx: seen["sni"].append(server_name)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                seen["host"].append(self.headers.get("Host"))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        class Server(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass

        self.server = Server(("127.0.0.1", 0), Handler)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.mark.parametrize(("certified", "delivered"), [("n8n.test", True), ("other.test", False)])
def test_break_settings_probe_tls_sends_the_name_and_checks_the_certificate_against_it(
    admin, hook, tmp_path, monkeypatch, certified, delivered
):
    ca_file, cert_file, key_file = _pem_pair(tmp_path, certified)
    real = ssl.create_default_context
    monkeypatch.setattr(app.ssl, "create_default_context", lambda *a, **k: real(cafile=str(ca_file)))
    tls = TlsReceiver(cert_file, key_file)
    try:
        body = {"url": f"https://n8n.test:{tls.port}/hook", "events": ALL_EVENTS, "secret": SECRET}
        assert admin("PUT", "/api/settings/webhook", json=body).status_code == 200
        result = hook.test()
    finally:
        tls.close()
    assert tls.seen["sni"] == ["n8n.test"]  # the name, never 127.0.0.1
    if delivered:
        assert result["status"] == 200 and tls.seen["host"] == [f"n8n.test:{tls.port}"]
    else:
        assert result["status"] is None and result["error"].startswith("SSLCertVerificationError")
        assert "other.test" not in result["error"] and "n8n.test" not in result["error"]
        assert tls.seen["host"] == []


# --- Probes that held: the outbox ------------------------------------------------------------------------------------


def test_break_settings_probe_the_cap_holds_under_concurrent_events(admin, client, receiver, hook):
    configure(admin, receiver)
    stamp = "2026-11-24T12:00:00Z"
    with hook.store.write() as conn:
        conn.executemany(
            "INSERT INTO webhook_outbox (id, event, body, created_at, status, attempts, next_attempt_at)"
            " VALUES (?, 'redirect.link.created', x'7b7d', ?, 'pending', 0, ?)",
            [(f"evt_fill{i}", stamp, stamp) for i in range(app.MAX_PENDING - 5)],
        )
    row = {"id": "abc", "kind": "link", "slug": "s", "name": "n", "target": "https://example.test/"}
    start = threading.Barrier(30)

    def fire():
        start.wait()
        hook.emit("redirect.link.created", row)

    threads = [threading.Thread(target=fire) for _ in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    with hook.store.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM webhook_outbox WHERE status = 'pending'").fetchone()[0] == (
            app.MAX_PENDING
        )


def test_break_settings_probe_a_crash_after_sending_means_one_more_delivery_never_none(
    admin, client, receiver, hook, monkeypatch
):
    configure(admin, receiver)
    create_link(client)

    def crash(*_args):
        raise RuntimeError("the process died before recording the attempt")

    monkeypatch.setattr(hook, "_record", crash)
    with pytest.raises(RuntimeError):
        hook.pump()
    assert len(receiver.requests) == 1
    [row] = outbox(hook)
    assert row["status"] == "pending" and row["attempts"] == 0
    monkeypatch.undo()
    assert hook.pump() is True
    first, second = receiver.requests
    assert first["headers"]["X-Moonie-Event-Id"] == second["headers"]["X-Moonie-Event-Id"]
    assert first["body"] == second["body"]
    for sent in (first, second):
        h = sent["headers"]
        signed = f"{h['X-Moonie-Event-Id']}.{h['X-Moonie-Timestamp']}.".encode() + sent["body"]
        assert h["X-Moonie-Signature"] == "sha256=" + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
    assert outbox(hook)[0]["status"] == "delivered"


# --- Probes that held: CSRF on every settings change -----------------------------------------------------------------

CHANGES = [
    ("POST", "/api/settings/password", {"password": PASSWORD, "new_password": "a much longer new password"}),
    ("POST", "/api/settings/sessions/end", {}),
    ("POST", "/api/settings/keys", {"name": "n8n", "scopes": ["*"], "password": PASSWORD}),
    ("DELETE", "/api/settings/keys/abcdefgh", None),
    ("PUT", "/api/settings/cloudflare/token", {"token": "new-cf-token-abcdefghijklmnopqrstuvwxyz0123"}),
    ("DELETE", "/api/settings/cloudflare/token", None),
    ("PUT", "/api/settings/cloudflare/item-limit", {"value": 5}),
    ("PUT", "/api/settings/webhook", {"url": "http://n8n.test/", "events": [], "secret": SECRET}),
    ("DELETE", "/api/settings/webhook", None),
    ("POST", "/api/settings/webhook/test", {}),
]


@pytest.mark.parametrize(("method", "path", "body"), CHANGES, ids=lambda v: str(v)[:40])
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Sec-Fetch-Site": "same-origin"},
        {"X-CSRF-Token": "TOKEN", "Sec-Fetch-Site": "cross-site"},
        {"X-CSRF-Token": "TOKEN", "Sec-Fetch-Site": "same-site"},
        {"X-CSRF-Token": "TOKEN", "Sec-Fetch-Site": "none"},
        {"X-CSRF-Token": "wrong", "Sec-Fetch-Site": "same-origin"},
        {"X-CSRF-Token": "", "Sec-Fetch-Site": "same-origin"},
    ],
    ids=["bare", "no-token", "cross-site", "same-site", "none", "wrong-token", "empty-token"],
)
def test_break_settings_probe_every_settings_change_needs_the_csrf_token_from_this_origin(
    env, method, path, body, headers
):
    built = app.create_app(env, cloudflare_factory=Factory())
    store = built.extensions["store"]
    signed = built.test_client()
    assert signed.post("/login", data={"password": PASSWORD, "csrf": csrf_of(signed)}).status_code == 302
    token = csrf_of(signed, "/admin/links")
    sent = {key: (token if value == "TOKEN" else value) for key, value in headers.items()}
    before = (store.setting(app.ADMIN_PASSWORD_SETTING), store.api_keys(), store.sessions_active(time.time()))
    answer = signed.open(path, method=method, headers=sent, json=body)
    assert answer.status_code == 403 and answer.get_json() == {"error": "csrf"}
    assert (store.setting(app.ADMIN_PASSWORD_SETTING), store.api_keys(), store.sessions_active(time.time())) == before


# --- Probes that held: nothing secret leaves -------------------------------------------------------------------------


def test_break_settings_probe_no_secret_reaches_a_log_an_answer_or_the_database_files(env, options, receiver, caplog):
    """Every secret the Settings page takes, through a whole session of use: the webhook secret, the Cloudflare token,
    a new API key, the new password. None may appear in a log line at any level, in any answer but the one that shows
    a key once, or in the bytes of the database, its WAL or its shared memory."""
    caplog.set_level(logging.DEBUG)
    webhook_secret = "whsec-" + "q" * 30
    cf_token = "cf-token-" + "z" * 31
    new_password = "pass-" + "w" * 30
    built = app.create_app(
        env,
        cloudflare_factory=Factory(),
        webhook=lambda store, given: app.Webhook(store, given, **options),
    )
    store, hook = built.extensions["store"], built.extensions["webhook"]
    browser = built.test_client()
    assert browser.post("/login", data={"password": PASSWORD, "csrf": csrf_of(browser)}).status_code == 302
    headers = {"X-CSRF-Token": csrf_of(browser, "/admin/links"), "Sec-Fetch-Site": "same-origin"}
    answers = []

    def call(method, path, **kwargs):
        response = browser.open(path, method=method, headers=headers, **kwargs)
        answers.append(response.get_data())
        return response

    url = f"http://n8n.test:{receiver.port}/hook"
    assert (
        call("PUT", "/api/settings/webhook", json={"url": url, "events": ALL_EVENTS, "secret": "short"}).status_code
        == 400
    )
    assert (
        call(
            "PUT", "/api/settings/webhook", json={"url": url, "events": ALL_EVENTS, "secret": webhook_secret}
        ).status_code
        < 300
    )
    assert call("PUT", "/api/settings/cloudflare/token", json={"token": cf_token}).status_code < 300
    made = call("POST", "/api/settings/keys", json={"name": "n8n", "scopes": ["*"], "password": PASSWORD})
    key = made.get_json()["secret"]
    answers.pop()  # the one answer that shows the key, once
    keyed = {"Authorization": f"Bearer {key}"}
    assert browser.post("/api/links", json=LINK, headers=keyed).status_code == 201
    hook.pump()
    receiver.script = [(500, b"", {})]
    call("POST", "/api/settings/webhook/test", json={})
    for path in ("/api/settings/security", "/api/settings/keys", "/api/settings/webhook", "/api/settings/cloudflare"):
        call("GET", path)
    answers.append(browser.get("/api/cloudflare", headers=keyed).get_data())
    answers.append(browser.get("/api/links", headers=keyed).get_data())
    assert (
        call("POST", "/api/settings/password", json={"password": PASSWORD, "new_password": new_password}).status_code
        < 300
    )
    call("DELETE", "/api/settings/cloudflare/token")
    files = b"".join(path.read_bytes() for path in store.path.parent.iterdir() if path.name.startswith(store.path.name))
    for secret in (webhook_secret, cf_token, key, new_password):
        assert secret not in caplog.text, secret
        assert all(secret.encode() not in answer for answer in answers), secret
        assert secret.encode() not in files, secret
