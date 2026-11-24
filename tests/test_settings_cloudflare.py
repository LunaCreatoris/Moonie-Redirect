"""Settings > Cloudflare (D27): the token set, replaced and cleared while the app runs, the file as its fallback, and
the item limit read live. Against the in-memory fake only."""

# The fixtures of test_app.py are imported, and every test names them as its arguments
# ruff: noqa: F811

import sqlite3

import pytest
from fake_cloudflare import LISTS, FakeCloudflare
from test_app import client, clock, env, flask_app, login  # noqa: F401
from test_cloudflare_api import GO, LINK, World

import app

NEW_TOKEN = "new-cf-token-abcdefghijklmnopqrstuvwxyz0123"
OTHER_KEY = bytes(range(32))


class Factory:
    """What makes a client of a token set in the settings: a fake set up with one account, which knows the token
    unless `refuse` is set. `made` keeps every client made."""

    def __init__(self) -> None:
        self.made: list[FakeCloudflare] = []
        self.refuse = False
        self.denied: set[str] = set()
        self.unreachable = False

    def __call__(self, token: str) -> FakeCloudflare:
        fake = FakeCloudflare(token)
        fake.setup()
        fake.denied = set(self.denied)
        if self.refuse:
            fake.token = "another-token-entirely"
        if self.unreachable:
            fake.fault("timeout", times=99)
        self.made.append(fake)
        return fake


class Admin:
    def __init__(self, env, *, cloudflare=None, factory=None) -> None:
        self.factory = factory or Factory()
        self.app = app.create_app(env, cloudflare=cloudflare, cloudflare_factory=self.factory)
        self.store = self.app.extensions["store"]
        self.sync = self.app.extensions["sync"]
        self.client = self.app.test_client()
        self.csrf = login(self.client)

    def send(self, method, path, **kwargs):
        headers = {"X-CSRF-Token": self.csrf, "Sec-Fetch-Site": "same-origin"}
        return self.client.open(path, method=method, headers=headers, **kwargs)

    def get(self):
        return self.send("GET", "/api/settings/cloudflare").get_json()

    def set_token(self, token=NEW_TOKEN):
        return self.send("PUT", "/api/settings/cloudflare/token", json={"token": token})


@pytest.fixture
def admin(env):
    return Admin(env)


def test_with_no_token_cloudflare_is_off(admin):
    assert admin.get() == {
        "token": {"origin": "missing", "state": "off", "missing": [], "unverified": [], "checked_at": None},
        "item_limit": {"value": 10000, "origin": "default"},
    }
    assert admin.sync.client is None


def test_a_token_set_here_is_checked_stored_sealed_and_used_at_once(admin, env):
    answer = admin.set_token()
    assert answer.status_code == 200, answer.get_json()
    token = answer.get_json()["token"]
    assert token["origin"] == "stored" and token["state"] == "ok" and token["missing"] == []
    assert token["checked_at"] is not None
    assert admin.sync.client is admin.factory.made[-1]
    assert NEW_TOKEN not in str(answer.get_json())
    with sqlite3.connect(env["MOONIE_REDIRECT_DB"]) as conn:
        dump = "\n".join(conn.iterdump())
    conn.close()
    assert NEW_TOKEN not in dump
    # The check just made is what the page reads, not a second one
    calls = len(admin.factory.made[-1].ledger)
    assert admin.get()["token"]["state"] == "ok" and len(admin.factory.made[-1].ledger) == calls
    # The Cloudflare endpoints are on with it
    assert admin.send("GET", "/api/cloudflare/zones").status_code == 200


def test_a_stored_token_is_used_again_at_the_next_start(admin, env):
    admin.set_token()
    again = Admin(env, factory=admin.factory)
    assert again.get()["token"]["origin"] == "stored"
    assert again.sync.client is admin.factory.made[-1] and len(admin.factory.made) == 2


def test_a_token_cloudflare_refuses_is_not_stored(admin):
    admin.factory.refuse = True
    answer = admin.set_token()
    assert answer.status_code == 400 and answer.get_json() == {"error": "token_invalid"}
    assert admin.store.read_sealed(admin.app.extensions["box"], "cloudflare_token") == ("missing", None)
    assert admin.sync.client is None


@pytest.mark.parametrize("token", ["", "   ", "two words", None, 42, "é" * 10, "x" * 16385])
def test_a_token_that_is_no_token_is_refused(admin, token):
    answer = admin.set_token(token)
    assert answer.status_code == 400 and answer.get_json()["error"] == "invalid"
    assert set(answer.get_json()["fields"]) == {"token"}
    assert admin.factory.made == []


def test_missing_permissions_are_stored_and_said(admin):
    admin.factory.denied = {LISTS}
    answer = admin.set_token().get_json()["token"]
    assert answer["origin"] == "stored" and answer["state"] == "ok"
    assert answer["missing"] == [app.PERM_LISTS_EDIT]


def test_a_token_cloudflare_could_not_check_is_stored_unchecked(admin):
    admin.factory.unreachable = True
    answer = admin.set_token()
    assert answer.status_code == 200
    assert answer.get_json()["token"]["origin"] == "stored"
    assert answer.get_json()["token"]["state"] == "unchecked"
    assert admin.sync.client is admin.factory.made[-1]


def test_clearing_falls_back_to_the_file_then_off(env, tmp_path):
    file_fake = FakeCloudflare()
    admin = Admin(env, cloudflare=file_fake)
    assert admin.get()["token"]["origin"] == "file"
    admin.set_token()
    assert admin.sync.client is not file_fake
    cleared = admin.send("DELETE", "/api/settings/cloudflare/token")
    assert cleared.status_code == 200 and cleared.get_json()["token"]["origin"] == "file"
    assert admin.sync.client is file_fake
    alone = Admin(env)
    alone.set_token()
    off = alone.send("DELETE", "/api/settings/cloudflare/token").get_json()
    assert off["token"]["origin"] == "missing" and off["token"]["state"] == "off"
    assert alone.sync.client is None
    assert alone.send("GET", "/api/cloudflare/zones").get_json() == {"error": "cloudflare_off"}


def test_a_token_sealed_with_another_key_is_unreadable_and_the_file_serves(env):
    file_fake = FakeCloudflare()
    first = Admin(env)
    first.store.write_sealed(app.SecretBox(OTHER_KEY), "cloudflare_token", NEW_TOKEN)
    with_file = Admin(env, cloudflare=file_fake)
    assert with_file.get()["token"]["origin"] == "unreadable"
    assert with_file.sync.client is file_fake
    alone = Admin(env)
    assert alone.get()["token"]["origin"] == "unreadable" and alone.sync.client is None
    # Replace works over an unreadable row
    assert alone.set_token().get_json()["token"]["origin"] == "stored"


def test_a_token_set_here_starts_the_sync_thread_of_a_running_app(admin):
    admin.sync.start()  # what main() does; with no token, no thread runs
    assert admin.sync._thread is None
    try:
        admin.set_token()
        assert admin.sync._thread is not None and admin.sync._thread.is_alive()
    finally:
        admin.sync.stop()
        admin.sync._thread.join(5)


def test_a_test_app_never_starts_the_thread(admin):
    admin.set_token()
    assert admin.sync._thread is None


# --- Sync.use ---


def test_use_drops_the_cached_check(tmp_path):
    store = app.Store(tmp_path / "r.db")
    first, second = FakeCloudflare(), FakeCloudflare()
    sync = app.Sync(store, first)
    assert sync.token_state()["state"] == "ok"
    second.token = "something else"  # this client's token is refused
    sync.use(second)
    assert sync.token_state()["state"] == "invalid"
    sync.use(None)
    assert sync.token_state()["state"] == "off"


def test_a_pass_in_flight_ends_with_the_client_it_started_with(env):
    world = World(env)
    world.create(**LINK, address=GO)
    other = FakeCloudflare()
    original = world.fake.lists

    def swap_then_list(account_id):
        world.sync.use(other)  # a token set in the settings while the pass runs
        return original(account_id)

    world.fake.lists = swap_then_list
    world.sync.run_pass()
    assert f"{GO}/promo" in world.items()
    assert other.ledger == []
    assert world.sync.client is other


def test_a_check_of_a_token_swapped_out_meanwhile_is_not_kept(tmp_path):
    store = app.Store(tmp_path / "r.db")
    slow, fresh = FakeCloudflare(), FakeCloudflare()
    sync = app.Sync(store, slow)
    verify = slow.verify_token

    def swapped_during_check():
        sync.use(fresh, {"state": "ok", "missing": ["fresh"], "unverified": [], "checked_at": "t"})
        return verify()

    slow.verify_token = swapped_during_check
    sync.token_state()
    assert sync.token_state()["missing"] == ["fresh"]


# --- The item limit ---


def test_the_item_limit_is_set_cleared_and_read_live(env):
    world = World(env)
    admin = world.session
    answer = admin("PUT", "/api/settings/cloudflare/item-limit", json={"value": 1})
    assert answer.status_code == 200 and answer.get_json()["item_limit"] == {"value": 1, "origin": "stored"}
    # The page for unknown paths of go already takes the one item
    full = world.session("POST", "/api/links", json=LINK | {"address": GO})
    assert full.status_code == 409 and full.get_json() == {"error": "quota_full"}
    cleared = admin("PUT", "/api/settings/cloudflare/item-limit", json={"value": None})
    assert cleared.get_json()["item_limit"] == {"value": 10000, "origin": "default"}
    assert world.session("POST", "/api/links", json=LINK | {"address": GO}).status_code == 201


def test_the_item_limit_set_here_wins_over_the_variable(env):
    admin = Admin(env | {"MOONIE_REDIRECT_CLOUDFLARE_ITEM_LIMIT": "50"})
    assert admin.get()["item_limit"] == {"value": 50, "origin": "env"}
    put = admin.send("PUT", "/api/settings/cloudflare/item-limit", json={"value": 7})
    assert put.get_json()["item_limit"] == {"value": 7, "origin": "stored"} and admin.store.item_limit == 7
    back = admin.send("PUT", "/api/settings/cloudflare/item-limit", json={"value": None})
    assert back.get_json()["item_limit"] == {"value": 50, "origin": "env"}


@pytest.mark.parametrize("body", [{}, {"value": 0}, {"value": -1}, {"value": "5"}, {"value": 1.5}, {"value": True}])
def test_an_item_limit_out_of_bounds_is_refused(admin, body):
    answer = admin.send("PUT", "/api/settings/cloudflare/item-limit", json=body)
    assert answer.status_code == 400 and answer.get_json()["error"] == "invalid"
    assert set(answer.get_json()["fields"]) == {"value"}
    assert admin.store.setting(app.ITEM_LIMIT_SETTING) is None


def test_the_largest_item_limit_is_taken(admin):
    top = app.ITEM_LIMIT_MAX
    assert admin.send("PUT", "/api/settings/cloudflare/item-limit", json={"value": top}).status_code == 200
    assert admin.send("PUT", "/api/settings/cloudflare/item-limit", json={"value": top + 1}).status_code == 400


def test_the_cloudflare_settings_need_the_csrf_token(admin):
    answer = admin.client.put("/api/settings/cloudflare/token", json={"token": NEW_TOKEN})
    assert answer.status_code == 403 and answer.get_json() == {"error": "csrf"}
    assert admin.factory.made == []
