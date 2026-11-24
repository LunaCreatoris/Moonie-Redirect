"""The sync engine, pass by pass, against the in-memory fake and an injected clock."""

from datetime import UTC, datetime, timedelta

import pytest
from fake_cloudflare import INSTALL, OTHER_INSTALL, FakeCloudflare

import app

LINK = {"name": "Promo", "target": "https://shop.test/", "http_status": 302, "expires_on": None, "design": None}
LINK |= {"link_host": None}
GO = "go.example.com"
WIKI = app.FALLBACK_CHOICES[0]


class World:
    """One account, one zone, the host `go.example.com` set up here, a store and its sync."""

    def __init__(self, tmp_path, *, fallback=None, item_limit=10000):
        self.fake = FakeCloudflare()
        self.account, self.zone, self.list_id = self.fake.setup()
        self.store = app.Store(tmp_path / "redirect.db", item_limit=item_limit)
        with self.store.write() as conn:
            conn.execute("INSERT INTO cf_meta (key, value) VALUES ('install_id', ?)", (INSTALL,))
        self.now = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
        self.sync = app.Sync(self.store, self.fake, clock=lambda: self.now, monotonic=self.fake.clock)
        self.serving = {"admin.example.com"}
        self.setup("go", fallback)
        self.fake.ledger.clear()

    def setup(self, label, fallback=None):
        plan, _ = app.plan_for(self.fake, self.store, self.zone, label, fallback, self.serving)
        app.apply_plan(
            self.fake,
            self.store,
            zone_id=self.zone,
            label=label,
            fallback=fallback,
            fingerprint_sent=plan["fingerprint"],
            confirm_live=False,
            serving=self.serving,
        )

    def link(self, slug, kind="link", address=GO, **values):
        return self.store.create(kind, LINK | {"slug": slug, "address": address} | values)

    def items(self):
        return self.fake.sources(self.account, self.list_id)

    def row(self, id_):
        return self.store.get(id_)

    def account_row(self):
        return self.store.cf_account(self.account)

    def run(self, passes=1):
        for _ in range(passes):
            self.sync.run_pass()

    def later(self, **delta):
        self.now += timedelta(**delta)


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def error_code(text):
    return None if text is None else app.json.loads(text)["code"]


def test_a_pending_link_becomes_active(world):
    row = world.link("promo")
    world.run()
    item = world.items()[f"{GO}/promo"]
    assert item["redirect"]["target_url"] == "https://shop.test/" and item["comment"] == f"moonie:{INSTALL}:{row['id']}"
    row = world.row(row["id"])
    assert (row["cf_state"], row["cf_synced_rev"]) == ("active", row["rev"])
    assert world.account_row()["op_kind"] is None and world.account_row()["last_sync_at"]


def test_a_nano_and_a_qr_code_go_at_their_id(world):
    nano = world.link("NanoURL/Promo", kind="nano")
    world.run()
    assert f"{GO}/{nano['id']}" in world.items()


def test_a_post_at_an_existing_source_replaces_the_item(world):
    # Assumed from what the Cloudflare plugin saw, not measured here: pinned on the fake only
    row = world.link("promo")
    world.run()
    first = world.items()[f"{GO}/promo"]["id"]
    world.store.update(row["id"], {"target": "https://other.test/"})
    world.run()
    items = world.items()
    assert len(items) == 1 and items[f"{GO}/promo"]["id"] == first
    assert items[f"{GO}/promo"]["redirect"]["target_url"] == "https://other.test/"


def test_an_edit_during_the_operation_stays_pending_and_goes_next(world):
    world.fake.op_polls = 1
    row = world.link("promo")
    world.run()  # sent, still running
    assert world.account_row()["op_id"] is not None
    world.store.update(row["id"], {"target": "https://edited.test/"})
    world.run()  # completes the first send: its revision is no longer the row's
    assert world.row(row["id"])["cf_state"] == "pending"
    world.fake.op_polls = 0
    world.run(2)
    assert world.row(row["id"])["cf_state"] == "active"
    assert world.items()[f"{GO}/promo"]["redirect"]["target_url"] == "https://edited.test/"


def test_a_failed_batch_goes_one_at_a_time_until_the_bad_link_is_alone(world):
    bad = world.link("bad")
    world.later(seconds=1)
    goods = [world.link(f"good{n}") for n in range(2)]
    world.fake.failing_sources.add(f"{GO}/bad")
    world.run()
    assert world.account in world.sync._single
    assert error_code(world.account_row()["last_error"]) == "operation_failed"
    world.run(4)
    assert world.row(bad["id"])["cf_state"] == "error"
    assert error_code(world.row(bad["id"])["cf_error"]) == "operation_failed"
    assert all(world.row(g["id"])["cf_state"] == "active" for g in goods)
    assert world.account not in world.sync._single


def test_a_refusal_naming_a_source_marks_that_link_only(world):
    bad = world.link("bad")
    good = world.link("good")
    world.fake.bad_sources.add(f"{GO}/bad")
    world.run(2)
    assert world.row(bad["id"])["cf_state"] == "error"
    assert error_code(world.row(bad["id"])["cf_error"]) == "refused"
    assert world.row(good["id"])["cf_state"] == "active"


def test_a_refusal_naming_nobody_switches_to_one_at_a_time(world):
    world.link("a")
    world.link("b")
    world.fake.fault("status", status=400, method="POST", path="items$", message="something is wrong")
    world.run()
    assert world.account in world.sync._single and world.sync._failures == 1
    world.run(2)
    assert len(world.items()) == 2


@pytest.mark.parametrize("comment", [None, "made by hand", f"moonie:{OTHER_INSTALL}:abcd2345"])
def test_an_item_this_install_did_not_write_is_never_written_over(world, comment):
    world.fake.add_item(world.account, world.list_id, f"{GO}/promo", "https://theirs.test/", comment=comment)
    row = world.link("promo")
    world.run(2)
    assert error_code(world.row(row["id"])["cf_error"]) == "foreign_item"
    assert world.items()[f"{GO}/promo"]["redirect"]["target_url"] == "https://theirs.test/"
    assert not world.fake.calls("POST", "items$")


def test_a_deleted_links_item_is_removed_by_its_marker_only(world):
    row = world.link("promo")
    world.run()
    theirs = world.fake.add_item(world.account, world.list_id, f"{GO}/promo", "https://t.test/", comment="by hand")
    world.store.delete(row["id"])
    world.run()
    left = world.fake.items(world.account, world.list_id)
    assert [item["id"] for item in left] == [theirs]
    with world.store.read() as conn:
        assert conn.execute("SELECT count(*) FROM cf_removals").fetchone()[0] == 0


def test_a_moved_links_old_item_waits_for_the_new_one(world):
    row = world.link("a")
    world.run()
    world.fake.op_polls = 1
    world.store.update(row["id"], {"slug": "b"})
    world.run()  # the new item is sent and still running: the old one stays
    assert set(world.items()) == {f"{GO}/a"}
    world.fake.op_polls = 0
    world.run(2)
    assert set(world.items()) == {f"{GO}/b"}


def test_a_link_moved_back_cancels_its_removal(world):
    row = world.link("a")
    world.run()
    world.store.update(row["id"], {"slug": "b"})
    world.store.update(row["id"], {"slug": "a"})
    world.run(2)
    assert set(world.items()) == {f"{GO}/a"}
    assert world.row(row["id"])["cf_state"] == "active"


def test_moving_to_the_lan_removes_the_item(world):
    row = world.link("a")
    world.run()
    world.store.update(row["id"], {"address": None})
    world.run()
    assert world.items() == {}


def test_expiry_removes_the_item_and_keeps_the_row_and_a_new_day_sends_it_again(world):
    row = world.link("a", expires_on="2026-03-10")
    world.run()
    assert f"{GO}/a" in world.items()
    world.later(days=1)  # the last day is over, in UTC
    world.run()
    assert world.items() == {} and world.row(row["id"])["cf_state"] == "expired"
    world.run()
    assert world.row(row["id"])["cf_state"] == "expired"
    world.store.update(row["id"], {"expires_on": "2026-03-20"})
    world.run()
    assert f"{GO}/a" in world.items() and world.row(row["id"])["cf_state"] == "active"


def test_a_crash_between_the_operation_record_and_its_id_resends_and_holds_removals(world, monkeypatch):
    gone = world.link("gone")
    world.run()
    world.store.delete(gone["id"])
    row = world.link("promo")

    def crash(*_args):
        raise KeyboardInterrupt  # the process stops after the POST, before the id is written

    monkeypatch.setattr(world.sync, "_set_op_id", crash)
    with pytest.raises(KeyboardInterrupt):
        world.run()
    account = world.account_row()
    assert account["op_kind"] == "upsert" and account["op_id"] is None
    # A new process: the upsert recorded without an id is dropped and sent again, removals wait a pass
    world.sync = app.Sync(world.store, world.fake, clock=lambda: world.now, monotonic=world.fake.clock)
    world.run()
    account = world.account_row()
    assert account["op_kind"] is None and account["hold_until"] == "2026-03-10T12:15:00Z"
    assert world.row(row["id"])["cf_state"] == "active"
    assert len(world.fake.calls("POST", "items$")) == 3


def test_during_a_hold_a_removal_that_finds_nothing_stays_queued(world):
    row = world.link("promo")
    with world.store.write() as conn:
        conn.execute("UPDATE cf_accounts SET hold_until = '2026-03-10T12:15:00Z'")
    world.store.delete(row["id"])  # never sent: Cloudflare holds no item of it, yet
    world.run()
    with world.store.read() as conn:
        assert conn.execute("SELECT count(*) FROM cf_removals").fetchone()[0] == 1
    # The lost write lands late: the held removal still deletes it
    world.fake.add_item(
        world.account, world.list_id, f"{GO}/promo", "https://shop.test/", comment=f"moonie:{INSTALL}:{row['id']}"
    )
    world.run()
    assert world.items() == {}
    world.later(minutes=16)
    world.run()
    with world.store.read() as conn:
        assert conn.execute("SELECT count(*) FROM cf_removals").fetchone()[0] == 0


def test_an_operation_unknown_to_cloudflare_is_dropped_and_resent(world):
    row = world.link("promo")
    world.fake.next_op = {"unknown": True}
    world.run()
    assert world.row(row["id"])["cf_state"] == "pending" and world.account_row()["hold_until"]
    world.run()
    assert world.row(row["id"])["cf_state"] == "active"


def test_an_operation_running_past_its_deadline_is_dropped(world):
    world.link("promo")
    world.fake.next_op = {"stuck": True}
    world.run()
    assert world.sync._settle(world.account) == "running"
    world.later(minutes=16)
    assert world.sync._settle(world.account) == "expired"
    account = world.account_row()
    assert account["op_kind"] is None and error_code(account["last_error"]) == "operation_expired"
    assert account["hold_until"] == "2026-03-10T12:31:00Z"


def test_a_long_retry_after_holds_every_call(world):
    world.link("promo")
    world.fake.fault("429", method="POST", retry_after="120")
    world.run()
    assert world.sync.rate_held()
    assert error_code(world.account_row()["last_error"]) == "rate_limited"
    calls = len(world.fake.ledger)
    world.run()
    assert len(world.fake.ledger) == calls
    world.fake.clock.now += 121
    world.run()
    assert f"{GO}/promo" in world.items()


def test_failed_passes_back_off(world):
    world.fake.fault("status", status=500, method="GET", path="lists$", times=100)
    world.run()
    assert world.sync._failures == 1 and world.sync.backoff_until == world.fake.clock() + 1
    world.run()
    assert world.sync._failures == 2 and world.sync.backoff_until == world.fake.clock() + 2
    assert error_code(world.account_row()["last_error"]) == "refused"
    world.fake._faults.clear()
    world.run()
    assert world.sync._failures == 0 and world.account_row()["last_error"] is None


def test_a_missing_list_sends_nothing(world):
    world.link("promo")
    del world.fake.state.lists[world.account][world.list_id]
    world.run()
    assert error_code(world.account_row()["last_error"]) == "list_missing"
    assert not world.fake.calls("POST")


def test_an_invalid_token_idles(world):
    world.link("promo")
    world.fake.token_status = "disabled"
    world.run()
    assert world.sync.token_state()["state"] == "invalid"
    assert {call.path for call in world.fake.ledger if call.method != "GET"} == set()


def test_the_quota_is_read_and_a_full_list_refuses(tmp_path):
    world = World(tmp_path, item_limit=2)
    world.fake.add_item(world.account, world.list_id, "other.example.com/x", "https://t.test/")
    world.run()
    assert world.account_row()["items_used"] == 1 and world.account_row()["lists_used"] == 1
    world.link("a")
    with pytest.raises(app.QuotaFull):
        world.link("b")


def test_a_page_for_unknown_paths_goes_after_the_links(tmp_path):
    world = World(tmp_path, fallback=WIKI)
    world.link("promo")
    world.run()
    posts = [call.body for call in world.fake.calls("POST", "items$")]
    assert [[item["redirect"]["source_url"] for item in body] for body in posts] == [[f"{GO}/promo"], [f"{GO}/"]]
    root = world.items()[f"{GO}/"]
    assert root["redirect"]["subpath_matching"] is True and root["comment"] == f"moonie:{INSTALL}:fallback"
    host = world.store.cf_host(GO)
    assert (host["fallback_state"], host["fallback_synced_rev"]) == ("active", 1)


def test_a_page_is_not_sent_once_the_host_points_at_a_real_origin(tmp_path):
    world = World(tmp_path, fallback=WIKI)
    record = next(r for r in world.fake.state.records[world.zone] if r["name"] == GO)
    record["content"] = "203.0.113.5"
    world.run()
    assert error_code(world.store.cf_host(GO)["fallback_error"]) == "origin_live"
    assert world.items() == {}


def test_a_page_never_takes_a_root_someone_else_holds(tmp_path):
    world = World(tmp_path, fallback=WIKI)
    world.fake.add_item(world.account, world.list_id, f"{GO}/", "https://theirs.test/", subpath=True)
    world.run()
    assert error_code(world.store.cf_host(GO)["fallback_error"]) == "foreign_item"
    assert world.items()[f"{GO}/"]["redirect"]["target_url"] == "https://theirs.test/"


def test_no_page_removes_the_root_item(tmp_path):
    world = World(tmp_path, fallback=WIKI)
    world.run()
    app.change_fallback(world.store, GO, None, world.serving)
    world.run()
    assert world.items() == {}


def test_sync_now_sends_errors_again(world):
    row = world.link("promo")
    world.fake.bad_sources.add(f"{GO}/promo")
    world.run()
    assert world.row(row["id"])["cf_state"] == "error"
    world.fake.bad_sources.clear()
    world.sync.sync_now()
    world.run()
    assert world.row(row["id"])["cf_state"] == "active"


def test_without_a_token_the_engine_stays_dormant(tmp_path):
    store = app.Store(tmp_path / "redirect.db")
    sync = app.Sync(store, None)
    sync.run_pass()
    sync.start()
    assert sync._thread is None and sync.token_state()["state"] == "off"


def test_the_app_reads_the_token_file_and_starts_no_thread(tmp_path, monkeypatch):
    env = {
        "MOONIE_REDIRECT_DB": str(tmp_path / "redirect.db"),
        "MOONIE_REDIRECT_PUBLIC_BASE_URL": "https://redirect.lan",
    }
    assert app.create_app(env).extensions["sync"].client is None
    (tmp_path / "cf").write_text("cf-token-value\n")
    on = app.create_app(env | {"MOONIE_REDIRECT_CLOUDFLARE_TOKEN_FILE": str(tmp_path / "cf")})
    assert isinstance(on.extensions["sync"].client, app.Cloudflare) and on.extensions["sync"]._thread is None
    (tmp_path / "bad").write_text("two words\n")
    with pytest.raises(SystemExit):
        app.create_app(env | {"MOONIE_REDIRECT_CLOUDFLARE_TOKEN_FILE": str(tmp_path / "bad")})
    with pytest.raises(SystemExit):
        app.create_app(env | {"MOONIE_REDIRECT_CLOUDFLARE_ITEM_LIMIT": "lots"})
    limited = app.create_app(env | {"MOONIE_REDIRECT_CLOUDFLARE_ITEM_LIMIT": "50"})
    assert limited.extensions["store"].item_limit == 50
    fake = FakeCloudflare()
    assert app.create_app(env, cloudflare=fake).extensions["sync"].client is fake


def test_logs_never_hold_the_token_or_a_target(world, caplog):
    caplog.set_level("DEBUG")
    world.link("promo", target="https://secret-target.test/")
    world.fake.bad_sources.add(f"{GO}/promo")
    world.run()
    assert "secret-target" not in caplog.text and world.fake.token not in caplog.text


def test_a_moved_links_old_item_stays_while_the_new_one_is_refused(world):
    row = world.link("a")
    world.run()
    world.fake.bad_sources.add(f"{GO}/b")
    world.store.update(row["id"], {"slug": "b"})
    world.run(3)
    assert world.row(row["id"])["cf_state"] == "error"
    assert set(world.items()) == {f"{GO}/a"}  # printed codes keep working until the new source is active
    world.fake.bad_sources.clear()
    world.sync.sync_now()
    world.run(2)
    assert set(world.items()) == {f"{GO}/b"}


def test_a_new_link_at_a_deleted_links_source_keeps_its_item(world):
    # The upsert writes over the old item in place: a removal must read the list again, never act on what it was
    old = world.link("promo")
    world.run()
    world.store.delete(old["id"])
    new = world.link("promo", target="https://new.test/")
    world.run(2)
    item = world.items()[f"{GO}/promo"]
    assert item["comment"] == f"moonie:{INSTALL}:{new['id']}" and world.row(new["id"])["cf_state"] == "active"


def test_a_refusal_echoing_a_target_never_reaches_the_logs(world, caplog):
    caplog.set_level("DEBUG")
    world.link("promo", target="https://secret-target.test/")
    world.fake.fault("status", status=400, method="POST", path="items$", message="bad https://secret-target.test/")
    world.fake.fault("status", status=500, method="POST", path="items$", message="bad https://secret-target.test/")
    world.run(2)
    assert "secret-target" not in caplog.text


def test_the_admins_own_host_never_gets_an_item(tmp_path):
    # MOONIE_REDIRECT_PUBLIC_BASE_URL moved onto a host set up earlier, with its links and its page for unknown paths
    world = World(tmp_path, fallback=WIKI)
    row = world.link("promo")
    world.sync = app.Sync(world.store, world.fake, clock=lambda: world.now, monotonic=world.fake.clock, admin={GO})
    world.run(2)
    assert not world.fake.calls("POST") and world.items() == {}
    assert error_code(world.row(row["id"])["cf_error"]) == "admin_host"
    assert world.row(row["id"])["cf_state"] == "error"
    host = world.store.cf_host(GO)
    assert (host["fallback_state"], error_code(host["fallback_error"])) == ("error", "admin_host")
    assert error_code(world.account_row()["last_error"]) == "admin_host"
    # Sync now sends them back to pending: they are refused again, never sent
    world.sync.sync_now()
    world.run()
    assert not world.fake.calls("POST") and world.row(row["id"])["cf_state"] == "error"


def test_another_host_of_the_account_still_syncs_beside_the_admins(tmp_path):
    world = World(tmp_path)
    world.setup("other")
    world.fake.ledger.clear()
    world.link("promo")
    other = world.link("deal", address="other.example.com")
    world.sync = app.Sync(world.store, world.fake, clock=lambda: world.now, monotonic=world.fake.clock, admin={GO})
    world.run(2)
    assert set(world.items()) == {"other.example.com/deal"}
    assert world.row(other["id"])["cf_state"] == "active"
    assert error_code(world.account_row()["last_error"]) == "admin_host"
