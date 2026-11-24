"""Schema version 4: the settings, sealed secrets, API keys and the webhook's outbox, added without moving anything."""

import sqlite3

import pytest

import app

NEW_TABLES = {"settings", "secrets", "api_keys", "webhook_outbox", "webhook_outbox_due"}
PROMO = {"slug": "promo", "name": "Promo", "target": "https://shop.test/", "http_status": 302, "expires_on": None}
PROMO |= {"design": None, "link_host": None, "address": None}


def tables(path):
    with sqlite3.connect(path) as conn:
        found = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    return found, version


def make_v3_db(path):
    """A database as 9.1 left it: version 3, one link, no table of version 4."""
    store = app.Store(path)
    store.create("link", PROMO)
    with sqlite3.connect(path) as conn:
        for name in ("settings", "secrets", "api_keys", "webhook_outbox"):
            conn.execute(f"DROP TABLE {name}")
        conn.execute("PRAGMA user_version = 3")
    conn.close()


def test_a_9_1_database_gets_the_four_tables_and_keeps_its_links(tmp_path):
    path = tmp_path / "v3.db"
    make_v3_db(path)
    assert not NEW_TABLES & tables(path)[0]
    store = app.Store(path)
    found, version = tables(path)
    assert version == app.SCHEMA_VERSION == 4
    assert NEW_TABLES <= found
    assert [row["slug"] for row in store.list()] == ["promo"]


def test_the_migration_runs_again_harmlessly(tmp_path):
    path = tmp_path / "v3.db"
    make_v3_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
    conn.close()
    app.Store(path).set_setting("x", "1")
    store = app.Store(path)
    found, version = tables(path)
    assert version == 4 and NEW_TABLES <= found and store.setting("x") == "1"


def test_9_1_opens_a_version_4_database(tmp_path, monkeypatch):
    """9.1 runs only the steps under its version, checked with `<`: on a version 4 database none, and its links read."""
    path = tmp_path / "v4.db"
    app.Store(path).create("link", PROMO)
    monkeypatch.setattr(app, "SCHEMA_VERSION", 3)
    store = app.Store(path)
    assert store.hop("slug", "promo")["target"] == "https://shop.test/"
    assert tables(path)[1] == 4  # never written back down


def test_the_secrets_table_takes_only_its_two_names(tmp_path):
    path = tmp_path / "s.db"
    app.Store(path)
    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO secrets VALUES ('password', 'k', x'00', x'00', 't')")
    conn.close()


def test_the_outbox_takes_only_its_three_states(tmp_path):
    path = tmp_path / "o.db"
    app.Store(path)
    row = (
        "INSERT INTO webhook_outbox (id, event, body, created_at, status, next_attempt_at)"
        " VALUES (?, 'e', x'7b7d', 't', ?, 't')"
    )
    with sqlite3.connect(path) as conn:
        conn.execute(row, ("a", "pending"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(row, ("b", "sent"))
        assert conn.execute("SELECT attempts FROM webhook_outbox").fetchone() == (0,)
    conn.close()


def test_settings_are_set_replaced_and_dropped(tmp_path):
    store = app.Store(tmp_path / "x.db")
    assert store.setting("webhook_url") is None
    store.set_setting("webhook_url", "https://a.test/")
    store.set_setting("webhook_url", "https://b.test/")
    assert store.setting("webhook_url") == "https://b.test/"
    assert store.drop_setting("webhook_url") and not store.drop_setting("webhook_url")
    assert store.setting("webhook_url") is None
