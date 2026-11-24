"""The database of 8.2: migration from 8.x, and the rules a link save keeps for its Cloudflare address."""

import sqlite3

import pytest

import app

LINK = {"name": "Promo", "target": "https://shop.test/", "http_status": 302, "expires_on": None, "design": None}
LINK |= {"link_host": None}


@pytest.fixture
def store(tmp_path):
    store = app.Store(tmp_path / "redirect.db")
    host(store, "go.example.com")
    return store


def host(store, name, account="acc1", created=True, fallback=None):
    account_row = {"id": account, "name": "A", "list_id": "list1", "ruleset_id": "rs1", "rule_id": "r1"}
    host_row = {"host": name, "zone_id": "z1", "zone_name": "example.com", "record_id": "rec1"}
    store.save_setup(account_row, host_row | {"created_by_us": created}, fallback)


def removals(store):
    with store.read() as conn:
        return [dict(r) for r in conn.execute("SELECT source, marker, reason, after_link FROM cf_removals ORDER BY id")]


# --- Migration ---


def columns(path):
    with sqlite3.connect(path) as conn:
        found = {row[1] for row in conn.execute("PRAGMA table_info(redirect_links)")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}
    conn.close()
    return found, version, tables


def test_a_fresh_database_is_at_version_4(tmp_path):
    app.Store(tmp_path / "new.db")
    found, version, tables = columns(tmp_path / "new.db")
    assert version == app.SCHEMA_VERSION == 4
    assert set(app.CF_COLUMNS) <= found
    assert {"cf_meta", "cf_accounts", "cf_hosts", "cf_removals", "redirect_links_source", "admin_sessions"} <= tables


def make_8_1_db(path):
    """A database as 8.0.0 and 8.1.0 left it: the table, no version, one link."""
    with sqlite3.connect(path) as conn:
        conn.execute(app.SCHEMA)
        conn.execute(
            f"INSERT INTO redirect_links ({', '.join(app.COLUMNS)}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("abcd2345", "link", None, "promo", "Promo", "https://shop.test/", 302, None, None, "t", "t"),
        )
    conn.close()


def test_an_8_1_database_migrates_and_keeps_its_links(tmp_path):
    path = tmp_path / "old.db"
    make_8_1_db(path)
    store = app.Store(path)
    found, version, _ = columns(path)
    assert version == 4 and set(app.CF_COLUMNS) <= found
    row = store.get("abcd2345")
    assert (row["slug"], row["address"], row["rev"], row["cf_synced_rev"], row["cf_state"]) == (
        "promo",
        None,
        1,
        0,
        None,
    )
    assert store.hop("slug", "promo")["target"] == "https://shop.test/"
    # A second start finds nothing to do
    app.Store(path)
    assert columns(path)[1] == app.SCHEMA_VERSION


def test_a_migration_cut_halfway_runs_again(tmp_path):
    path = tmp_path / "half.db"
    make_8_1_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE redirect_links ADD COLUMN address TEXT")
        conn.execute("PRAGMA user_version = 1")
    conn.close()
    app.Store(path)
    found, version, _ = columns(path)
    assert version == 4 and set(app.CF_COLUMNS) <= found


def test_the_8_0_insert_still_works_on_a_migrated_database(tmp_path):
    # Rollback to 8.0.0: its INSERT names its own columns only, the new ones take their defaults
    path = tmp_path / "old.db"
    make_8_1_db(path)
    app.Store(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"INSERT INTO redirect_links ({', '.join(app.COLUMNS)}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("efgh2345", "link", None, "other", "Other", "https://o.test/", 301, None, None, "t", "t"),
        )
        conn.execute("UPDATE redirect_links SET target = 'https://new.test/' WHERE id = 'abcd2345'")
    conn.close()
    assert app.Store(path).get("efgh2345")["rev"] == 1


# --- A link's address ---


def test_a_lan_link_has_no_cloudflare_state(store):
    row = store.create("link", LINK | {"slug": "lan"})
    assert (row["address"], row["cf_state"], row["rev"]) == (None, None, 1)


def test_a_cloudflare_link_starts_pending_and_every_change_counts(store):
    row = store.create("link", LINK | {"slug": "promo", "address": "go.example.com"})
    assert (row["address"], row["cf_state"], row["rev"], row["cf_synced_rev"]) == ("go.example.com", "pending", 1, 0)
    with store.write() as conn:
        conn.execute("UPDATE redirect_links SET cf_state = 'error', cf_error = 'x'")
    row = store.update(row["id"], {"name": "Renamed"})
    assert (row["rev"], row["cf_state"], row["cf_error"]) == (2, "pending", None)
    assert removals(store) == []


def test_an_unknown_host_is_refused(store):
    with pytest.raises(app.Invalid) as refused:
        store.create("link", LINK | {"slug": "x", "address": "nope.example.com"})
    assert refused.value.field == "address"


def test_one_source_per_host_across_kinds(store):
    nano = store.create("nano", LINK | {"slug": "NanoURL/Promo", "address": "go.example.com"})
    with pytest.raises(app.SlugTaken) as taken:
        store.create("link", LINK | {"slug": nano["id"], "address": "go.example.com"})
    assert taken.value.field == "address"
    # The same path on the LAN, or on another host, is free
    host(store, "link.example.com")
    store.create("link", LINK | {"slug": nano["id"], "address": "link.example.com"})
    # Moving the NanoURL onto the host where that path is taken is refused too, and changes nothing
    with pytest.raises(app.SlugTaken) as taken:
        store.update(nano["id"], {"address": "link.example.com"})
    assert taken.value.field == "address" and store.get(nano["id"])["address"] == "go.example.com"


def test_a_change_of_source_queues_the_old_items_removal(store):
    row = store.create("link", LINK | {"slug": "a", "address": "go.example.com"})
    store.update(row["id"], {"slug": "b"})
    assert removals(store) == [
        {"source": "go.example.com/a", "marker": row["id"], "reason": "moved", "after_link": row["id"]}
    ]
    store.update(row["id"], {"address": None})
    assert removals(store)[-1] == {
        "source": "go.example.com/b",
        "marker": row["id"],
        "reason": "deleted",
        "after_link": None,
    }
    assert store.get(row["id"])["cf_state"] is None


def test_a_nano_keeps_its_source_when_renamed(store):
    row = store.create("nano", LINK | {"slug": "NanoURL/A", "address": "go.example.com"})
    store.update(row["id"], {"name": "B", "slug": "NanoURL/B"})
    assert removals(store) == []


def test_a_delete_queues_the_removal_in_the_same_transaction(store):
    row = store.create("link", LINK | {"slug": "a", "address": "go.example.com"})
    lan = store.create("link", LINK | {"slug": "lan"})
    assert store.delete(row["id"]) and store.delete(lan["id"])
    assert removals(store) == [
        {"source": "go.example.com/a", "marker": row["id"], "reason": "deleted", "after_link": None}
    ]
    assert not store.delete(row["id"])


def test_the_quota_refuses_a_link_the_list_has_no_place_for(tmp_path):
    store = app.Store(tmp_path / "q.db", item_limit=3)
    host(store, "go.example.com", fallback="https://www.google.com/")  # a page never sent: one place
    with store.write() as conn:
        conn.execute("UPDATE cf_accounts SET items_used = 1")
    first = store.create("link", LINK | {"slug": "a", "address": "go.example.com"})
    with pytest.raises(app.QuotaFull):
        store.create("link", LINK | {"slug": "b", "address": "go.example.com"})
    # A change that keeps the link in its account takes no new place; the LAN takes none at all
    store.update(first["id"], {"slug": "c"})
    lan = store.create("link", LINK | {"slug": "lan"})
    with pytest.raises(app.QuotaFull):
        store.update(lan["id"], {"address": "go.example.com"})
    assert store.get(lan["id"])["address"] is None


def test_install_id_is_drawn_once(store):
    first = store.install_id()
    assert len(first) == 32 and store.install_id() == first


def test_sync_now_puts_errors_and_pages_back_to_pending(store):
    host(store, "link.example.com", fallback="https://www.google.com/")
    row = store.create("link", LINK | {"slug": "a", "address": "go.example.com"})
    with store.write() as conn:
        conn.execute("UPDATE redirect_links SET cf_state = 'error', cf_error = 'x'")
        conn.execute("UPDATE cf_hosts SET fallback_state = 'error', fallback_error = 'x'")
    assert store.retry_all() == 2
    assert store.get(row["id"])["cf_state"] == "pending"
    assert store.cf_host("link.example.com")["fallback_state"] == "pending"
    assert store.cf_counts() == {"pending": 1, "active": 0, "error": 0, "expired": 0}
