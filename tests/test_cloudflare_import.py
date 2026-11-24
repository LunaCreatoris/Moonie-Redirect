"""`import-v7`'s Cloudflare step, from a database built with the 7.0.1 plugin's own migrations."""

import sqlite3

import pytest
from fake_cloudflare import INSTALL, FakeCloudflare

import app

V7_LINKS = """CREATE TABLE redirect_links (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'link' CHECK (kind IN ('link', 'nano', 'qrcode')),
    link_host TEXT CHECK (link_host IN ('ip', 'hostname')),
    slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, target TEXT NOT NULL,
    http_status INTEGER NOT NULL DEFAULT 302 CHECK (http_status IN (301, 302)),
    expires_on TEXT, design TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""

# The statements of the Cloudflare plugin's migrations/0001_init.sql, as it shipped (comments left out)
PLUGIN_0001 = """
CREATE TABLE cloudflare_accounts (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  list_id TEXT,
  ruleset_id TEXT,
  rule_id TEXT,
  op_kind TEXT CHECK (op_kind IN ('upsert', 'delete')),
  op_items TEXT,
  op_id TEXT,
  op_started_at TEXT,
  hold_until TEXT,
  quota_used INTEGER,
  lists_used INTEGER,
  quota_checked_at TEXT,
  last_sync_at TEXT,
  last_error TEXT,
  seen_at TEXT NOT NULL
);
CREATE TABLE cloudflare_install (
  only_row INTEGER PRIMARY KEY CHECK (only_row = 1),
  install_id TEXT NOT NULL
);
CREATE TABLE cloudflare_hosts (
  host TEXT PRIMARY KEY,
  zone_id TEXT NOT NULL,
  zone_name TEXT NOT NULL,
  account_id TEXT NOT NULL REFERENCES cloudflare_accounts(id),
  record_id TEXT,
  created_by_us INTEGER NOT NULL CHECK (created_by_us IN (0, 1)),
  created_at TEXT NOT NULL
);
CREATE TABLE cloudflare_entries (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('link', 'nano', 'qrcode')),
  host TEXT NOT NULL REFERENCES cloudflare_hosts(host),
  path TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  target TEXT NOT NULL,
  http_status INTEGER NOT NULL CHECK (http_status IN (301, 302)),
  expires_on TEXT,
  rev INTEGER NOT NULL DEFAULT 1,
  synced_rev INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'active', 'error')),
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (host, path)
);
CREATE TABLE cloudflare_removals (
  id INTEGER PRIMARY KEY,
  source_url TEXT NOT NULL,
  account_id TEXT NOT NULL,
  entry_id TEXT,
  remote_id TEXT,
  reason TEXT NOT NULL CHECK (reason IN ('deleted', 'moved', 'expired', 'resync')),
  after_entry TEXT,
  queued_at TEXT NOT NULL
);
CREATE INDEX cloudflare_entries_state ON cloudflare_entries (state);
CREATE INDEX cloudflare_removals_account ON cloudflare_removals (account_id, source_url);
"""

# The statements of the Cloudflare plugin's migrations/0002_fold_hosts.sql (comments left out, long lines wrapped)
PLUGIN_0002 = """
CREATE TABLE cloudflare_parked_hosts (
  host TEXT PRIMARY KEY,
  zone_id TEXT NOT NULL,
  zone_name TEXT NOT NULL,
  account_id TEXT NOT NULL,
  record_id TEXT,
  created_by_us INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE cloudflare_parked_entries (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  host TEXT NOT NULL,
  path TEXT NOT NULL,
  name TEXT NOT NULL,
  target TEXT NOT NULL,
  http_status INTEGER NOT NULL,
  expires_on TEXT,
  rev INTEGER NOT NULL,
  synced_rev INTEGER NOT NULL,
  state TEXT NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE cloudflare_held_hosts (
  host TEXT PRIMARY KEY REFERENCES cloudflare_hosts(host) ON DELETE CASCADE,
  reason TEXT NOT NULL CHECK (reason IN ('fold_conflict'))
);
CREATE TABLE cloudflare_exact_removals (
  removal_id INTEGER PRIMARY KEY REFERENCES cloudflare_removals(id) ON DELETE CASCADE
);
INSERT INTO cloudflare_parked_entries (id, kind, host, path, name, target, http_status, expires_on, rev, synced_rev,
  state, error, created_at, updated_at)
  SELECT id, kind, host, path, name, target, http_status, expires_on, rev, synced_rev, state, error, created_at,
  updated_at
  FROM cloudflare_entries
  WHERE host <> rtrim(lower(host), '.') OR host GLOB '*[^' || char(1) || '-' || char(127) || ']*';
DELETE FROM cloudflare_entries
  WHERE host <> rtrim(lower(host), '.') OR host GLOB '*[^' || char(1) || '-' || char(127) || ']*';
INSERT INTO cloudflare_parked_hosts (host, zone_id, zone_name, account_id, record_id, created_by_us, created_at)
  SELECT host, zone_id, zone_name, account_id, record_id, created_by_us, created_at
  FROM cloudflare_hosts
  WHERE host <> rtrim(lower(host), '.') OR host GLOB '*[^' || char(1) || '-' || char(127) || ']*';
DELETE FROM cloudflare_hosts
  WHERE host <> rtrim(lower(host), '.') OR host GLOB '*[^' || char(1) || '-' || char(127) || ']*';
"""

T = "2026-01-01T00:00:00Z"


def old_db(path, *, op_kind=None, extra=()):
    """The real state: one account with its list, ruleset and rule, `go.example.com` created by the plugin with its
    record, no entry. `extra` are more statements run once the migrations are in."""
    with sqlite3.connect(path) as conn:
        conn.execute(V7_LINKS)
        conn.executescript(PLUGIN_0001 + PLUGIN_0002)
        conn.execute("INSERT INTO cloudflare_install VALUES (1, ?)", (INSTALL,))
        conn.execute(
            "INSERT INTO cloudflare_accounts (id, name, list_id, ruleset_id, rule_id, op_kind, seen_at)"
            " VALUES ('acc1', 'Main', 'list1', 'rs1', 'rule1', ?, ?)",
            (op_kind, T),
        )
        conn.execute(
            "INSERT INTO cloudflare_hosts VALUES ('go.example.com', 'zone1', 'example.com', 'acc1', 'rec1', 1, ?)", (T,)
        )
        for statement in extra:
            conn.execute(statement)
    conn.close()
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "data" / "redirect.db"
    monkeypatch.setenv("MOONIE_REDIRECT_DB", str(db))
    return {"MOONIE_REDIRECT_DB": str(db), "MOONIE_REDIRECT_PUBLIC_BASE_URL": "https://redirect.lan"}


def store_of(env):
    return app.Store(app.Path(env["MOONIE_REDIRECT_DB"]))


def entry(id_, kind, host, path, target="https://t.test/", name="", table="cloudflare_entries"):
    return (
        f"INSERT INTO {table} (id, kind, host, path, name, target, http_status, rev, synced_rev, state, created_at,"
        f" updated_at) VALUES ('{id_}', '{kind}', '{host}', '{path}', '{name}', '{target}', 302, 1, 1, 'active',"
        f" '{T}', '{T}')"
    )


def test_the_real_state_imports_and_keeps_the_install_id(tmp_path, env, capsys):
    old = old_db(tmp_path / "moonie.db")
    before = old.read_bytes()
    assert app.main(["app.py", "import-v7", str(old)]) == 0
    out = capsys.readouterr().out
    assert "cloudflare: accounts 1, hosts 1, pages 0, entries 0, entries refused 0, removals 0" in out
    assert old.read_bytes() == before
    store = store_of(env)
    assert store.install_id() == INSTALL
    [account] = store.cf_accounts()
    assert (account["list_id"], account["ruleset_id"], account["rule_id"]) == ("list1", "rs1", "rule1")
    assert account["items_used"] is None and account["hold_until"] is None
    [host] = store.cf_hosts()
    assert (host["host"], host["record_id"], host["created_by_us"], host["fallback"]) == (
        "go.example.com",
        "rec1",
        1,
        None,
    )


def test_the_first_pass_after_import_finds_its_list_and_sends_nothing(tmp_path, env):
    old_db(tmp_path / "moonie.db")
    app.main(["app.py", "import-v7", str(tmp_path / "moonie.db")])
    fake = FakeCloudflare()
    account = fake.add_account()
    list_id = fake.add_list(account)
    fake.add_item(account, list_id, "go.example.com/old", "https://t.test/", comment=f"moonie:{INSTALL}:abc123")
    store = store_of(env)
    with store.write() as conn:  # the fake's ids stand for the real ones
        conn.execute("UPDATE cf_accounts SET id = ?, list_id = ?", (account, list_id))
        conn.execute("UPDATE cf_hosts SET account_id = ?", (account,))
    app.Sync(store, fake).run_pass()
    assert [call.method for call in fake.ledger if call.method != "GET"] == []
    assert store.cf_account(account)["items_used"] == 1 and store.cf_account(account)["last_error"] is None


def test_running_it_again_changes_nothing(tmp_path, env, capsys):
    old = old_db(
        tmp_path / "moonie.db",
        extra=[
            entry("fallback:go.example.com", "link", "go.example.com", "", "https://www.google.com/"),
            entry("aa11", "nano", "go.example.com", "k3mz8npq", name="Promo"),
        ],
    )
    app.main(["app.py", "import-v7", str(old)])
    first = capsys.readouterr().out
    assert "pages 1, entries 1," in first
    with sqlite3.connect(app.Path(env["MOONIE_REDIRECT_DB"])) as conn:
        snapshot = [conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in ("redirect_links", "cf_hosts")]
    conn.close()
    app.main(["app.py", "import-v7", str(old)])
    assert (
        "cloudflare: accounts 0, hosts 0, pages 0, entries 0, entries refused 0, removals 0" in capsys.readouterr().out
    )
    with sqlite3.connect(app.Path(env["MOONIE_REDIRECT_DB"])) as conn:
        again = [conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in ("redirect_links", "cf_hosts")]
    conn.close()
    assert again == snapshot


def test_another_install_id_with_hosts_here_refuses_the_step(tmp_path, env, capsys):
    store = store_of(env)
    with store.write() as conn:
        conn.execute("INSERT INTO cf_meta VALUES ('install_id', 'feedfeedfeedfeedfeedfeedfeedfeed')")
    store.save_setup(
        {"id": "acc9", "name": "B", "list_id": "l9", "ruleset_id": None, "rule_id": None},
        {"host": "link.other.com", "zone_id": "z9", "zone_name": "other.com", "record_id": None, "created_by_us": 1},
        None,
    )
    old = old_db(tmp_path / "moonie.db")
    assert app.main(["app.py", "import-v7", str(old)]) == 0
    out = capsys.readouterr().out
    assert "cloudflare: not imported" in out and "links were imported" in out
    assert store.install_id() != INSTALL and [h["host"] for h in store.cf_hosts()] == ["link.other.com"]


def test_another_install_id_with_nothing_behind_it_is_replaced(tmp_path, env):
    store = store_of(env)
    store.install_id()
    app.main(["app.py", "import-v7", str(old_db(tmp_path / "moonie.db"))])
    assert store.install_id() == INSTALL


def test_parked_and_colliding_hosts(tmp_path, env, capsys):
    host = "INSERT INTO cloudflare_parked_hosts VALUES ('{}', 'zone1', 'Example.com', 'acc1', 'rec', 1, '{}')"
    old = old_db(
        tmp_path / "moonie.db",
        extra=[
            host.format("Link.Example.com.", T),  # parked by 0002, folds alone: taken back
            host.format("Redirect.example.com", T),  # these two fold to one host: both refused
            host.format("REDIRECT.example.com", T),
        ],
    )
    app.main(["app.py", "import-v7", str(old)])
    out = capsys.readouterr().out
    assert "hosts 2," in out
    assert (
        "hosts refused (one host in several spellings, no account, the admin's host, or no host name):"
        " REDIRECT.example.com, Redirect.example.com" in out
    )
    assert [h["host"] for h in store_of(env).cf_hosts()] == ["go.example.com", "link.example.com"]


def test_a_root_becomes_the_hosts_page(tmp_path, env):
    old = old_db(
        tmp_path / "moonie.db",
        extra=[
            entry("fallback:go.example.com", "link", "go.example.com", "", "https://en.wikipedia.org/wiki/HTTP_404")
        ],
    )
    app.main(["app.py", "import-v7", str(old)])
    host = store_of(env).cf_host("go.example.com")
    assert (host["fallback"], host["fallback_state"], host["fallback_rev"], host["fallback_synced_rev"]) == (
        "https://en.wikipedia.org/wiki/HTTP_404",
        "pending",
        1,
        0,
    )


def test_entries_become_links_on_their_host(tmp_path, env, capsys):
    old = old_db(
        tmp_path / "moonie.db",
        extra=[
            entry("e1", "link", "go.example.com", "spring/sale", name="Sale"),
            entry("e2", "nano", "go.example.com", "k3mz8npq", name="Short one"),
            entry("e3", "qrcode", "go.example.com", "q7mz8npq"),
            entry("e4", "link", "go.example.com", "bad//path"),  # breaks a rule of this app
            entry("e5", "link", "nowhere.example.com", "x"),  # no host
            "INSERT INTO redirect_links VALUES ('k3mz8npq', 'link', NULL, 'mine', 'Mine', 'https://m.test/', 302,"
            " NULL, NULL, 't', 't')",  # a LAN link already holds the code of e2
        ],
    )
    app.main(["app.py", "import-v7", str(old)])
    assert "entries 2, entries refused 3" in capsys.readouterr().out
    store = store_of(env)
    rows = {(r["kind"], r["slug"]): r for r in store.list() if r["address"]}
    assert set(rows) == {("link", "spring/sale"), ("qrcode", "QRcodes/q7mz8npq")}
    qr = rows[("qrcode", "QRcodes/q7mz8npq")]
    assert qr["id"] == "q7mz8npq" and qr["cf_state"] == "pending" and app.read_design(qr["design"]) == app.Design()
    # A link with no name takes its path as one
    assert rows[("link", "spring/sale")]["name"] == "Sale"


def test_the_first_upsert_rewrites_an_imported_entrys_item_with_its_new_marker(tmp_path, env):
    old_db(tmp_path / "moonie.db", extra=[entry("e2", "nano", "go.example.com", "k3mz8npq", name="Short")])
    app.main(["app.py", "import-v7", str(tmp_path / "moonie.db")])
    fake = FakeCloudflare()
    account = fake.add_account()
    list_id = fake.add_list(account)
    old_item = fake.add_item(
        account, list_id, "go.example.com/k3mz8npq", "https://t.test/", comment=f"moonie:{INSTALL}:e2"
    )
    store = store_of(env)
    with store.write() as conn:
        conn.execute("UPDATE cf_accounts SET id = ?, list_id = ?", (account, list_id))
        conn.execute("UPDATE cf_hosts SET account_id = ?", (account,))
    app.Sync(store, fake).run_pass()
    [item] = fake.items(account, list_id)
    assert item["id"] == old_item and item["comment"] == f"moonie:{INSTALL}:k3mz8npq"
    assert store.get("k3mz8npq")["cf_state"] == "active"


def test_an_operation_in_flight_holds_removals_and_pending_removals_come_along(tmp_path, env, capsys):
    old = old_db(
        tmp_path / "moonie.db",
        op_kind="upsert",
        extra=[
            "INSERT INTO cloudflare_removals (source_url, account_id, entry_id, reason, queued_at)"
            f" VALUES ('go.example.com/gone', 'acc1', 'e9', 'deleted', '{T}')",
            "INSERT INTO cloudflare_removals (source_url, account_id, entry_id, reason, queued_at)"
            f" VALUES ('go.example.com/x', 'unknown', 'e8', 'deleted', '{T}')",
        ],
    )
    app.main(["app.py", "import-v7", str(old)])
    out = capsys.readouterr().out
    assert "removals 1" in out and "warning: account acc1 had an operation in flight" in out
    store = store_of(env)
    assert store.cf_account("acc1")["hold_until"] is not None
    with store.read() as conn:
        [removal] = conn.execute("SELECT source, marker, reason FROM cf_removals").fetchall()
    assert tuple(removal) == ("go.example.com/gone", "e9", "deleted")


def test_a_7_0_1_database_without_the_plugin_prints_nothing_of_it(tmp_path, env, capsys):
    old = tmp_path / "moonie.db"
    with sqlite3.connect(old) as conn:
        conn.execute(V7_LINKS)
    conn.close()
    assert app.main(["app.py", "import-v7", str(old)]) == 0
    assert "cloudflare" not in capsys.readouterr().out


def test_an_install_id_no_marker_can_hold_is_left_and_said(tmp_path, env, capsys):
    """D15: this app draws its own; hosts and links still come over, and the output says 7.0.1's items are foreign."""
    old = old_db(
        tmp_path / "moonie.db",
        extra=["UPDATE cloudflare_install SET install_id = 'not:a-marker'", entry("e1", "link", "go.example.com", "a")],
    )
    assert app.main(["app.py", "import-v7", str(old)]) == 0
    out = capsys.readouterr().out
    assert "install id cannot mark an item" in out and "every item 7.0.1 wrote is foreign" in out
    store = store_of(env)
    assert app._MARKER_PART.fullmatch(store.install_id()) and store.install_id() != "not:a-marker"
    assert [h["host"] for h in store.cf_hosts()] == ["go.example.com"] and "entries 1," in out


def test_damaged_rows_and_refused_pages_are_counted(tmp_path, env, capsys):
    old = old_db(
        tmp_path / "moonie.db",
        extra=[
            entry("r1", "link", "go.example.com", "", "javascript:alert(1)"),
            "INSERT INTO cloudflare_removals (source_url, account_id, reason, queued_at)"
            " VALUES (X'41', 'acc1', 'deleted', 't')",
        ],
    )
    assert app.main(["app.py", "import-v7", str(old)]) == 0
    out = capsys.readouterr().out
    assert "cloudflare: pages for unknown paths refused 1" in out
    assert "cloudflare: damaged rows left out 1" in out
    assert store_of(env).cf_host("go.example.com")["fallback"] is None


def test_the_admins_host_and_its_links_are_refused(tmp_path, monkeypatch, env, capsys):
    monkeypatch.setenv("MOONIE_REDIRECT_PUBLIC_BASE_URL", "https://GO.example.com:8443/")
    old = old_db(tmp_path / "moonie.db", extra=[entry("e1", "link", "go.example.com", "promo")])
    assert app.main(["app.py", "import-v7", str(old)]) == 0
    out = capsys.readouterr().out
    assert "the admin's host, or no host name): go.example.com" in out and "entries refused 1" in out
    assert store_of(env).cf_hosts() == []
