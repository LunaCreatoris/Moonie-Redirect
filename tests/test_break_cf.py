"""Breaker round on 9.1.0's Cloudflare side: each `test_break_cf_*` reproduces a hole that round found, fixed since, or
pins an attack the app held against. A docstring's "Was:" part tells the hole as it was; the asserts hold the rule that
now applies. Against the in-memory fake only, never the real API."""

# The fixtures of test_app.py are imported, and every test names them as its arguments
# ruff: noqa: F811

import json
import logging
import re
import sqlite3
import threading

import pytest
from fake_cloudflare import INSTALL, FakeCloudflare
from fake_cloudflare import TOKEN as CF_TOKEN
from test_app import AUTH, BASE, client, clock, create, env, flask_app, login  # noqa: F401
from test_cloudflare_api import GO, LINK, SITE, WIKI, World
from test_cloudflare_import import V7_LINKS, entry, old_db
from test_cloudflare_sync import World as SyncWorld

import app


@pytest.fixture
def world(env):
    return World(env)


def import_env(tmp_path, monkeypatch, base="https://redirect.lan"):
    db = tmp_path / "data" / "redirect.db"
    monkeypatch.setenv("MOONIE_REDIRECT_DB", str(db))
    monkeypatch.setenv("MOONIE_REDIRECT_PUBLIC_BASE_URL", base)
    return app.Store(db)


def landed_then_timeout(fake: FakeCloudflare, method: str, path: str) -> None:
    """The next `method` call whose path matches reaches the fake and is done there, then its answer is lost: a read
    timeout, which says nothing of whether it landed."""
    send = fake._send
    armed = [True]

    def lossy(verb, url, body):
        answer = send(verb, url, body)
        if armed[0] and verb == method and re.search(path, url):
            armed[0] = False
            raise app.CfUnreachable("timeout")
        return answer

    fake._send = lossy


HOSTILE_SCHEMA = (
    V7_LINKS,
    "CREATE TABLE cloudflare_install (only_row, install_id)",
    "CREATE TABLE cloudflare_accounts (id, name, list_id, ruleset_id, rule_id, op_kind)",
    "CREATE TABLE cloudflare_hosts (host, zone_id, zone_name, account_id, record_id, created_by_us, created_at)",
    "CREATE TABLE cloudflare_entries"
    " (id, kind, host, path, name, target, http_status, expires_on, created_at, updated_at)",
    "CREATE TABLE cloudflare_removals (id, source_url, account_id, entry_id, remote_id, reason)",
    f"INSERT INTO cloudflare_install VALUES (1, '{INSTALL}')",
)
GOOD_ACCOUNT = "INSERT INTO cloudflare_accounts VALUES ('acc1', 'Main', 'list1', 'rs1', 'rule1', NULL)"
GOOD_HOST = "INSERT INTO cloudflare_hosts VALUES ('go.example.com', 'zone1', 'example.com', 'acc1', 'rec1', 1, 't')"


# --- Holes -----------------------------------------------------------------------------------------------------------


def test_break_cf_a_slug_change_on_a_cloudflare_link_needs_confirm_break(world):
    """D13: a link's `https://<host>/<slug>` shared elsewhere stops when its address is given up. A new slug on the same
    host stops it just the same (the old item is queued for removal). Was: it went through with no confirmation."""
    link = world.create(**LINK, address=GO)
    world.run()
    assert f"{GO}/promo" in world.items()
    answer = world.bearer("PATCH", f"/api/links/{link['id']}", json={"slug": "renamed"})
    assert answer.status_code == 400 and answer.get_json() == {"error": "confirm_break"}
    world.run()
    assert f"{GO}/promo" in world.items()


def test_break_cf_a_key_without_setup_cannot_move_a_link_to_another_path_of_an_adopted_host(world):
    """An adopted host may serve a real site, so only a caller with `cloudflare:setup` may put a path of it in the
    list. Was: with one link there made by the admin, a narrower key renamed it to any path of the live site (here
    `/login`), which Cloudflare then answered before the site's origin."""
    made = world.session("POST", "/api/links", json=LINK | {"address": SITE})
    assert made.status_code == 201
    answer = world.narrow("PATCH", f"/api/links/{made.get_json()['id']}", json={"slug": "login", "confirm_break": True})
    assert answer.status_code == 403 and answer.get_json() == {"error": "scope_denied"}
    world.run()
    assert f"{SITE}/login" not in world.items()


@pytest.mark.parametrize("install_id", ["not:a-marker", "", "x" * 65, "caf\u00e9"])
def test_break_cf_import_never_takes_an_install_id_no_marker_can_hold(tmp_path, monkeypatch, install_id):
    """The install id goes into every item's marker, `moonie:<install>:<link>`, of 1 to 64 of [0-9A-Za-z_-]. Was: a
    damaged 7.0.1 row was taken as it is, and kept for good (`install_id()` never draws again): every later upsert
    raised in `marker()`, so nothing was ever sent again."""
    store = import_env(tmp_path, monkeypatch)
    old = old_db(tmp_path / "moonie.db", extra=[f"UPDATE cloudflare_install SET install_id = '{install_id}'"])
    assert app.main(["app.py", "import-v7", str(old)]) == 0
    assert app._MARKER_PART.fullmatch(store.install_id())


@pytest.mark.parametrize(
    "rows",
    [
        # A host that is no text
        [GOOD_ACCOUNT, "INSERT INTO cloudflare_hosts VALUES (NULL, 'zone1', 'example.com', 'acc1', 'rec1', 1, 't')"],
        # A NanoURL whose name is a number
        [
            GOOD_ACCOUNT,
            GOOD_HOST,
            "INSERT INTO cloudflare_entries VALUES"
            " ('e1', 'nano', 'go.example.com', 'k3mz8npq', 7, 'https://t.test/', 302, NULL, 't', 't')",
        ],
        # An entry whose host is no text
        [
            GOOD_ACCOUNT,
            GOOD_HOST,
            "INSERT INTO cloudflare_entries VALUES"
            " ('e1', 'link', NULL, 'promo', 'Promo', 'https://t.test/', 302, NULL, 't', 't')",
        ],
        # An account with no name
        ["INSERT INTO cloudflare_accounts VALUES ('acc1', NULL, 'list1', 'rs1', 'rule1', NULL)"],
        # A removal with no source
        [GOOD_ACCOUNT, "INSERT INTO cloudflare_removals VALUES (1, NULL, 'acc1', 'abc', NULL, 'deleted')"],
    ],
    ids=["host-null", "nano-name-int", "entry-host-null", "account-name-null", "removal-source-null"],
)
def test_break_cf_import_of_a_damaged_plugin_database_refuses_rows_rather_than_crashing(tmp_path, monkeypatch, rows):
    """A 7.0.1 database edited by hand, or from a plugin build whose schema had no constraints. Was: one row of a wrong
    type raised out of `import-v7` with a traceback (TypeError, AttributeError or IntegrityError) and the whole
    Cloudflare step was lost, where the links step counts such a row as refused."""
    import_env(tmp_path, monkeypatch)
    old = tmp_path / "moonie.db"
    with sqlite3.connect(old) as conn:
        for statement in (*HOSTILE_SCHEMA, *rows):
            conn.execute(statement)
    conn.close()
    assert app.main(["app.py", "import-v7", str(old)]) == 0


@pytest.mark.parametrize(
    "target",
    ["javascript:alert(1)", "not a url", "https://redirect.lan/admin/links", "https://go.example.com/loop"],
    ids=["javascript", "not-a-url", "admin-host", "loop"],
)
def test_break_cf_import_checks_a_pages_target_as_the_admin_page_does(tmp_path, monkeypatch, target):
    """A host's page for unknown paths set through the admin goes through `check_fallback`: an http(s) URL, not on a
    host set up here (a loop), not on the admin's host. Was: an imported root's target was copied unchecked
    into `cf_hosts.fallback`, and the sync later sent it to Cloudflare as the target of `<host>/*`."""
    store = import_env(tmp_path, monkeypatch)
    old = old_db(tmp_path / "moonie.db", extra=[entry("r1", "link", "go.example.com", "", target)])
    assert app.main(["app.py", "import-v7", str(old)]) == 0
    assert store.cf_host("go.example.com")["fallback"] is None


def test_break_cf_import_never_puts_a_link_under_well_known(tmp_path, monkeypatch):
    """`.well-known` at a Cloudflare host's root is where certificates and security contacts are read: the API refuses a
    link there. Was: an imported plugin entry landed there all the same."""
    store = import_env(tmp_path, monkeypatch)
    old = old_db(
        tmp_path / "moonie.db",
        extra=[
            entry("e1", "link", "go.example.com", ".well-known/acme-challenge/x"),
            entry("e2", "link", "go.example.com", ".Well-Known/security.txt"),
        ],
    )
    assert app.main(["app.py", "import-v7", str(old)]) == 0
    assert [row["slug"] for row in store.list() if row["address"]] == []


def test_break_cf_import_never_takes_the_admins_host(tmp_path, monkeypatch):
    """D18: an item on the host the admin is reached on answers before the admin. A plan refuses that host
    (`admin_host`). Was: the import took it, and its links, when 9.x served the admin on a name 7.0.1 used for
    Cloudflare."""
    store = import_env(tmp_path, monkeypatch, base="https://go.example.com")
    old = old_db(tmp_path / "moonie.db", extra=[entry("e1", "link", "go.example.com", "promo")])
    assert app.main(["app.py", "import-v7", str(old)]) == 0
    assert store.cf_hosts() == [] and [row for row in store.list() if row["address"]] == []


def test_break_cf_a_record_created_by_an_apply_whose_answer_was_lost_stays_ours(env):
    """The placeholder record is created, then the answer is lost (read timeout): apply answers 502 and saves nothing.
    Was: applied again, the plan found our own placeholder (192.0.2.1, comment `moonie-redirect`) and adopted it as
    if it could serve a site: the host was saved as not created here, so it could never have its page for unknown
    paths, and only the admin could give it to a link."""
    world = World(env, hosts=False)
    landed_then_timeout(world.fake, "POST", r"/dns_records$")
    plan = world.plan("go", WIKI).get_json()
    body = {"zone_id": world.zone, "label": "go", "fallback": WIKI, "fingerprint": plan["fingerprint"]}
    assert world.session("POST", "/api/cloudflare/apply", json=body).status_code == 502
    assert world.store.cf_hosts() == []
    plan = world.plan("go", WIKI).get_json()
    body["fingerprint"] = plan["fingerprint"]
    assert world.session("POST", "/api/cloudflare/apply", json=body).status_code == 201
    host = world.store.cf_host(GO)
    assert (host["created_by_us"], host["fallback"]) == (1, WIKI)


@pytest.mark.parametrize("zone_name", ["exa mple.com", "example.com/x", "exa\u202emple.com", "-bad-.com"])
def test_break_cf_a_zone_name_that_is_no_host_name_is_never_set_up(tmp_path, zone_name):
    """Was: Cloudflare's zone name was only checked to be a non-empty text: a malformed answer became a host of
    `cf_hosts`, then the address of links and the start of every source sent."""
    fake = FakeCloudflare()
    account = fake.add_account()
    zone = fake.add_zone(zone_name, account)
    store = app.Store(tmp_path / "redirect.db")
    try:
        plan, _ = app.plan_for(fake, store, zone, "go", None, set())
        app.apply_plan(
            fake,
            store,
            zone_id=zone,
            label="go",
            fallback=None,
            fingerprint_sent=plan["fingerprint"],
            confirm_live=False,
            serving=set(),
        )
    except (app.PlanRefused, app.Invalid, app.CfError, app.CfUnreachable):
        pass
    assert all(app.HOST_NAME.fullmatch(row["host"]) for row in store.cf_hosts())


def test_break_cf_a_token_file_saved_with_a_byte_order_mark_works(tmp_path):
    """OS neutral: Windows editors may save the token file as UTF-8 with a BOM. Was: `read_secret` stripped spaces
    and line ends but kept U+FEFF, and the app refused to start ("must hold one printable ASCII token")."""
    path = tmp_path / "cloudflare_token"
    path.write_bytes(b"\xef\xbb\xbf" + CF_TOKEN.encode() + b"\r\n")
    client = app.cloudflare_client({"MOONIE_REDIRECT_CLOUDFLARE_TOKEN_FILE": str(path)})
    assert client is not None


# --- Probes that hold ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["inf", "-inf", "nan", "-5", "1e400", "", "   ", "0x10", "\u0661\u0662", "Wed, 21 Oct 2015 07:28:00 GMT",
     "Fri, 31 Dec 9999 23:59:59 GMT", "Mon, 99 Foo 2026 99:99:99 GMT", "9" * 400],
)  # fmt: skip
def test_break_cf_probe_any_retry_after_is_bounded(value):
    fake = FakeCloudflare()
    fake.add_account()
    fake.fault("429", retry_after=value, times=10)
    try:
        fake.zones()
    except app.RateLimited as limited:
        assert 0.0 <= limited.retry_after <= app.RETRY_AFTER_CAP
    assert all(0.0 <= slept <= app.MAX_WAIT for slept in fake.clock.slept)


@pytest.mark.parametrize(
    "damage",
    [
        {"redirect": {"source_url": "go.example.com/x", "target_url": "https://t.test/", "status_code": "301"}},
        {"redirect": {"source_url": 7, "target_url": "https://t.test/", "status_code": 301}},
        {"redirect": None},
        {"id": "../../user/tokens"},
        {"id": None},
    ],
)
def test_break_cf_probe_a_malformed_item_stops_the_account_and_writes_nothing(tmp_path, damage):
    world = SyncWorld(tmp_path)
    item = world.fake.add_item(world.account, world.list_id, "go.example.com/other", "https://t.test/")
    world.fake.state.lists[world.account][world.list_id]["items"][item] |= damage
    link = world.link("promo")
    world.run()
    assert world.fake.writes() == []
    assert world.row(link["id"])["cf_state"] == "pending"
    assert json.loads(world.account_row()["last_error"])["code"] == "unreachable"


def test_break_cf_probe_the_token_echoed_by_cloudflare_reaches_no_log_row_or_answer(world, caplog):
    caplog.set_level(logging.DEBUG)
    echo = f"bad token {CF_TOKEN} here"
    world.create(**LINK, address=GO)
    world.fake.fault("status", status=400, method="POST", path=r"/items$", message=echo)
    world.run()
    world.bearer("POST", "/api/cloudflare/sync")
    world.fake.next_op = {"fail": echo}
    world.run()
    world.fake.fault("429", retry_after="999", message=echo)
    world.sync.not_before = float("-inf")
    world.run()
    texts = [caplog.text]
    for path in ("/api/cloudflare", "/api/links", "/api/cloudflare/compare"):
        world.sync.not_before = float("-inf")
        texts.append(world.session("GET", path).get_data(as_text=True))
    with sqlite3.connect(world.store.path) as conn:
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            texts.append(repr(conn.execute(f"SELECT * FROM {table}").fetchall()))
    conn.close()
    assert not any(CF_TOKEN in text for text in texts)


@pytest.mark.parametrize("reached", ["GO.EXAMPLE.COM", "go.example.com.", "go.example.com:8443", "Go.Example.Com.:443"])
def test_break_cf_probe_the_admins_host_is_refused_in_any_spelling(tmp_path, reached):
    fake = FakeCloudflare()
    _, zone, _ = fake.setup()
    store = app.Store(tmp_path / "redirect.db")
    plan, _ = app.plan_for(fake, store, zone, "go", None, app.serving_hosts(BASE, reached))
    assert plan["blocked"] == "admin_host"
    base = f"https://{reached}"
    plan, _ = app.plan_for(fake, store, zone, "go", None, app.serving_hosts(base))
    assert plan["blocked"] == "admin_host"


@pytest.mark.parametrize(
    "page",
    ["https://GO.EXAMPLE.COM/x", "https://go.example.com./x", "https://go.example.com:8443/", "https://u@go.example.com/",
     "https://go.example.test/admin", "https://GO.example.TEST.:443/"],
)  # fmt: skip
def test_break_cf_probe_a_page_can_never_point_at_our_hosts_or_the_admin(world, page):
    answer = world.session("POST", f"/api/cloudflare/hosts/{GO}/fallback", json={"fallback": page})
    assert answer.status_code == 400
    assert world.store.cf_host(GO)["fallback"] == WIKI


@pytest.mark.parametrize(
    "path", ["/api/cloudflare/plan", "/api/cloudflare/apply", f"/api/cloudflare/hosts/{GO}/fallback",
             "/api/cloudflare/compare/apply", "/api/cloudflare/sync", "/api/links"],
)  # fmt: skip
@pytest.mark.parametrize("site", ["cross-site", "same-site", "none", "SAME-ORIGIN"])
def test_break_cf_probe_a_change_from_another_site_is_refused_with_a_valid_csrf_token(world, path, site):
    answer = world.session("POST", path, json={"fallback": None}, headers={"Sec-Fetch-Site": site})
    assert answer.status_code == 403 and answer.get_json() == {"error": "csrf"}


def test_break_cf_probe_compare_apply_takes_only_what_the_report_holds(world):
    link = world.create(**LINK, address=GO)
    world.run()
    foreign = world.fake.add_item(world.account, world.list_id, f"{GO}/theirs", "https://t.test/")
    report = world.session("GET", "/api/cloudflare/compare").get_json()
    fingerprint = report["fingerprint"]
    for body in (
        {"push": [link["id"]]},  # in sync: no gap to push
        {"push": ["fallback:" + SITE]},  # an adopted host has no page
        {"push": ["fallback:" + GO + "x"]},
        {"remove": ["fake-9999"], "confirm_remove": 1},
        {"remove": [foreign], "confirm_remove": 2},
        {"remove": [foreign, foreign], "confirm_remove": 2},
        {"push": "abc"},
        {"push": [None]},
    ):
        answer = world.session("POST", "/api/cloudflare/compare/apply", json=body | {"fingerprint": fingerprint})
        assert answer.status_code == 400, body
    # A replayed report once Cloudflare moved on
    world.fake.add_item(world.account, world.list_id, f"{GO}/more", "https://t.test/")
    stale = {"fingerprint": fingerprint, "remove": [foreign], "confirm_remove": 1}
    answer = world.session("POST", "/api/cloudflare/compare/apply", json=stale)
    assert answer.status_code == 409 and answer.get_json() == {"error": "remote_changed"}
    # A key without `cloudflare:setup` sees the report but holds no fingerprint, and may not apply one it computes
    seen = world.narrow("GET", "/api/cloudflare/compare").get_json()
    assert "fingerprint" not in seen
    forged = {"fingerprint": app.fingerprint(seen), "remove": [foreign], "confirm_remove": 1}
    assert world.narrow("POST", "/api/cloudflare/compare/apply", json=forged).status_code == 403
    assert world.store.cf_counts()["active"] == 1
    with world.store.read() as conn:
        assert conn.execute("SELECT count(*) FROM cf_removals").fetchone()[0] == 0


def test_break_cf_probe_a_link_answers_through_its_last_day_in_utc_and_goes_at_midnight(tmp_path):
    world = SyncWorld(tmp_path)
    link = world.link("promo", expires_on="2026-03-10")
    world.run(2)
    assert "go.example.com/promo" in world.items()
    world.now = world.now.replace(hour=23, minute=59, second=59)
    world.run(2)
    assert world.row(link["id"])["cf_state"] == "active" and "go.example.com/promo" in world.items()
    world.later(seconds=1)
    world.run(2)
    assert world.row(link["id"])["cf_state"] == "expired" and "go.example.com/promo" not in world.items()
    # A day pushed back into the past sends nothing again
    world.store.update(link["id"], {"expires_on": "2026-03-09"})
    world.run(2)
    assert world.row(link["id"])["cf_state"] == "expired" and "go.example.com/promo" not in world.items()
    world.later(days=-2)  # a clock set back: the item comes back only once the row says so
    world.store.update(link["id"], {"expires_on": "2026-03-10"})
    world.run(2)
    assert "go.example.com/promo" in world.items()


def test_break_cf_probe_concurrent_saves_on_one_source_keep_one(tmp_path):
    world = SyncWorld(tmp_path)
    nano = world.link("NanoURL/menu", kind="nano")
    barrier = threading.Barrier(8)
    outcomes: list[str] = []

    def save(index: int) -> None:
        barrier.wait()
        try:
            if index % 2:
                world.store.create("link", app.check_fields("link", {"slug": nano["id"], "name": "N", "target":
                                   "https://a.test/"}, creating=True) | {"address": GO})  # fmt: skip
            else:
                lan = world.store.create("link", app.check_fields("link", {"slug": f"s{index}", "name": "N", "target":
                                         "https://a.test/"}, creating=True))  # fmt: skip
                world.store.update(lan["id"], {"slug": nano["id"], "address": GO})
            outcomes.append("saved")
        except app.SlugTaken:
            outcomes.append("taken")

    threads = [threading.Thread(target=save, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("saved") <= 1
    sources = [app.link_source(r["address"], r["kind"], r["slug"], r["id"]) for r in world.store.list() if r["address"]]
    assert len(sources) == len(set(sources))


def test_break_cf_probe_ids_from_a_hostile_import_never_climb_out_of_their_path(tmp_path, monkeypatch):
    store = import_env(tmp_path, monkeypatch)
    old = tmp_path / "moonie.db"
    with sqlite3.connect(old) as conn:
        for statement in HOSTILE_SCHEMA:
            conn.execute(statement)
        conn.execute("INSERT INTO cloudflare_accounts VALUES ('../../user/tokens', 'A', 'x/../y', NULL, NULL, NULL)")
        conn.execute("INSERT INTO cloudflare_accounts VALUES ('acc2', 'B', '../../zones', NULL, NULL, NULL)")
    conn.close()
    assert app.main(["app.py", "import-v7", str(old)]) == 0
    fake = FakeCloudflare()
    app.Sync(store, fake).run_pass()
    assert not any(".." in call.path for call in fake.ledger)
    assert all(row["last_error"] is not None for row in store.cf_accounts())


@pytest.mark.parametrize("text", [f"{CF_TOKEN}\r\n", f"  {CF_TOKEN}  \n", f"\n\n{CF_TOKEN}"])
def test_break_cf_probe_token_files_with_line_ends_or_blanks_work(tmp_path, text):
    path = tmp_path / "token"
    path.write_bytes(text.encode())
    client = app.cloudflare_client({"MOONIE_REDIRECT_CLOUDFLARE_TOKEN_FILE": str(path)})
    assert client is not None and CF_TOKEN not in repr(client)


@pytest.mark.parametrize("text", ["", " \r\n\t", f"{CF_TOKEN[:20]} {CF_TOKEN[20:]}", f"{CF_TOKEN}\n{CF_TOKEN}"])
def test_break_cf_probe_an_empty_token_file_is_off_and_a_broken_one_stops_without_echoing_it(tmp_path, text, capsys):
    path = tmp_path / "token"
    path.write_text(text, encoding="utf-8")
    try:
        client = app.cloudflare_client({"MOONIE_REDIRECT_CLOUDFLARE_TOKEN_FILE": str(path)})
    except SystemExit as stop:
        assert CF_TOKEN[:20] not in str(stop)
    else:
        assert client is None
    out = capsys.readouterr()
    assert CF_TOKEN[:20] not in out.out + out.err


def test_break_cf_probe_no_cloudflare_call_ever_leaves_the_api_root(world):
    world.create(**LINK, address=GO)
    world.create(kind="nano", name="Menu", target="http://127.0.0.1:22/", address=GO)
    world.session("POST", f"/api/cloudflare/hosts/{GO}/fallback", json={"fallback": "http://169.254.169.254/latest"})
    world.session("GET", "/api/cloudflare/proposals?zone=" + "http://169.254.169.254")
    world.session("POST", "/api/cloudflare/plan", json={"zone_id": "../../x", "label": "go", "fallback": None})
    world.run()
    world.session("GET", "/api/cloudflare/compare")
    known = re.compile(r"/(user|accounts|zones)(/|$)")
    assert world.fake.ledger and all(known.match(call.path) and ".." not in call.path for call in world.fake.ledger)


def test_break_cf_probe_the_quota_counts_a_move_within_an_account_once(env):
    world = World(env, item_limit=3)  # go's page takes one item
    one = world.create(**LINK, address=GO)
    world.create(**LINK | {"slug": "two"}, address=GO)
    assert world.bearer("POST", "/api/links", json=LINK | {"slug": "three", "address": GO}).status_code == 409
    moved = world.session("PATCH", f"/api/links/{one['id']}", json={"address": SITE, "confirm_break": True})
    assert moved.status_code == 200
    back = world.session("PATCH", f"/api/links/{one['id']}", json={"address": GO, "confirm_break": True})
    assert back.status_code == 200
    world.run()
    assert world.bearer("POST", "/api/links", json=LINK | {"slug": "three", "address": GO}).status_code == 409


def test_break_cf_probe_a_stale_or_replayed_plan_is_refused(env):
    world = World(env, hosts=False)
    plan = world.plan("go", WIKI).get_json()
    body = {"zone_id": world.zone, "label": "go", "fallback": WIKI, "fingerprint": plan["fingerprint"]}
    world.fake.add_record(world.zone, "A", GO, "203.0.113.9")  # the name changed hands meanwhile
    answer = world.session("POST", "/api/cloudflare/apply", json=body)
    assert answer.status_code == 409 and answer.get_json() == {"error": "plan_stale"}
    world = World(env, hosts=False)
    plan = world.plan("go", None).get_json()
    body = {"zone_id": world.zone, "label": "go", "fallback": None, "fingerprint": plan["fingerprint"]}
    assert world.session("POST", "/api/cloudflare/apply", json=body | {"fallback": WIKI}).status_code == 409
    assert world.session("POST", "/api/cloudflare/apply", json=body).status_code == 201
    assert world.session("POST", "/api/cloudflare/apply", json=body).status_code == 409
    assert len(world.fake.calls("POST", r"/dns_records$")) == 1


def test_break_cf_probe_an_operation_lost_between_its_record_and_its_id_is_sent_once_more(tmp_path, monkeypatch):
    world = SyncWorld(tmp_path)
    link = world.link("promo")
    monkeypatch.setattr(world.sync, "_set_op_id", lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        world.run()
    monkeypatch.undo()
    assert world.account_row()["op_kind"] == "upsert" and world.account_row()["op_id"] is None
    world.run(2)
    assert world.row(link["id"])["cf_state"] == "active"
    assert len(world.fake.items(world.account, world.list_id)) == 1
    world.later(minutes=1)
    world.store.delete(link["id"])
    world.run(3)
    world.later(minutes=20)  # past the hold of the lost upsert
    world.run(2)
    assert world.items() == {}
