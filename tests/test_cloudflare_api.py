"""The JSON API of 9.1.0's Cloudflare side: a link's address, its answer and its QR code; the confirmations a change
that stops a Cloudflare address needs; the Cloudflare endpoints, which of them the bearer token reaches, and Compare.
Against the in-memory fake only."""

# The fixtures of test_app.py are imported, and every test names them as its arguments
# ruff: noqa: F811

import pytest
from fake_cloudflare import TOKEN as CF_TOKEN
from fake_cloudflare import FakeCloudflare
from test_app import AUTH, BASE, PASSWORD, client, clock, create, env, flask_app, login  # noqa: F401

import app

GO = "go.example.com"
SITE = "www.example.com"
LINK = {"slug": "promo", "name": "Promo", "target": "https://shop.test/"}
WIKI = app.FALLBACK_CHOICES[0]


class World:
    """The app on the fake, with `go.example.com` created here (with a page for unknown paths) and `www.example.com`
    adopted (a proxied record of a real site was there)."""

    def __init__(self, env, *, item_limit: int | None = None, hosts: bool = True):
        self.fake = FakeCloudflare()
        self.account, self.zone, self.list_id = self.fake.setup()
        self.fake.add_record(self.zone, "A", SITE, "203.0.113.7")
        if item_limit is not None:
            env = env | {"MOONIE_REDIRECT_CLOUDFLARE_ITEM_LIMIT": str(item_limit)}
        self.app = app.create_app(env, cloudflare=self.fake)
        self.store = self.app.extensions["store"]
        self.sync = self.app.extensions["sync"]
        self.admin = self.app.test_client()
        self.csrf = login(self.admin)
        if hosts:
            self.set_up("go", WIKI)
            self.set_up("www", None, confirm_live=True)

    def session(self, method: str, path: str, **kwargs):
        headers = {"X-CSRF-Token": self.csrf, "Sec-Fetch-Site": "same-origin"} | kwargs.pop("headers", {})
        return self.admin.open(path, method=method, headers=headers, **kwargs)

    def bearer(self, method: str, path: str, **kwargs):
        return self.admin.open(path, method=method, headers=AUTH | kwargs.pop("headers", {}), **kwargs)

    def key(self, *scopes: str) -> dict:
        """The header of a new API key holding `scopes` only (made through the session, as the Settings page does)."""
        body = {"name": "Narrow", "scopes": list(scopes), "password": PASSWORD}
        made = self.session("POST", "/api/settings/keys", json=body)
        assert made.status_code == 201, made.get_json()
        return {"Authorization": f"Bearer {made.get_json()['secret']}"}

    def narrow(self, method: str, path: str, **kwargs):
        """A call with a key that reads and writes everything but cannot set Cloudflare up (no `cloudflare:setup`)."""
        if not hasattr(self, "_narrow"):
            self._narrow = self.key("redirect:*", "cloudflare:read", "cloudflare:write")
        return self.admin.open(path, method=method, headers=self._narrow | kwargs.pop("headers", {}), **kwargs)

    def plan(self, label: str, fallback: str | None = None, **kwargs):
        body = {"zone_id": self.zone, "label": label, "fallback": fallback}
        return self.session("POST", "/api/cloudflare/plan", json=body, **kwargs)

    def set_up(self, label: str, fallback: str | None, *, confirm_live: bool = False):
        plan = self.plan(label, fallback).get_json()
        body = {"zone_id": self.zone, "label": label, "fallback": fallback, "fingerprint": plan["fingerprint"]}
        answer = self.session("POST", "/api/cloudflare/apply", json=body | {"confirm_live": confirm_live})
        assert answer.status_code == 201, answer.get_json()
        return answer.get_json()

    def create(self, **body):
        answer = self.bearer("POST", "/api/links", json=body)
        assert answer.status_code == 201, answer.get_json()
        return answer.get_json()

    def items(self) -> dict[str, dict]:
        return self.fake.sources(self.account, self.list_id)

    def run(self, passes: int = 2) -> None:
        for _ in range(passes):
            self.sync.run_pass()


@pytest.fixture
def world(env):
    return World(env)


# --- A link's answer -------------------------------------------------------------------------------------------------


def test_a_lan_link_says_its_address_and_hides_the_sync_columns(client):
    link = create(client, **LINK)
    qr = create(client, kind="qrcode", name="Flyer", target="https://example.test/")
    nano = create(client, kind="nano", name="Menu", target="https://example.test/")
    for row in (link, qr, nano):
        assert row["address"] == "lan" and row["cloudflare"] is None
        assert not {"rev", "cf_synced_rev", "cf_state", "cf_error"} & set(row)
    assert link["address_url"] == link["public_url"] == BASE + "/redirect/promo"
    assert nano["address_url"] == nano["public_url"]
    assert qr["address_url"] == qr["short_url"] == f"{BASE}/links/{qr['id']}"


def test_the_list_says_which_addresses_a_link_may_have(client, world):
    assert client.get("/api/links", headers=AUTH).get_json()["addresses"] == [
        {"address": "lan", "url": BASE, "adopted": False}
    ]
    assert world.bearer("GET", "/api/links").get_json()["addresses"] == [
        {"address": "lan", "url": BASE, "adopted": False},
        {"address": GO, "url": f"https://{GO}", "adopted": False},
        {"address": SITE, "url": f"https://{SITE}", "adopted": True},
    ]


def test_a_link_on_a_cloudflare_host(world):
    link = world.create(**LINK, address=GO)
    nano = world.create(kind="nano", name="Menu", target="https://example.test/", address=GO)
    assert link["address"] == GO and link["address_url"] == f"https://{GO}/promo"
    assert link["public_url"] == BASE + "/redirect/promo"  # the LAN keeps its meaning
    assert nano["address_url"] == f"https://{GO}/{nano['id']}"
    assert link["cloudflare"] == {"state": "pending", "error": None}
    world.run()
    assert f"{GO}/promo" in world.items() and f"{GO}/{nano['id']}" in world.items()
    assert world.bearer("GET", f"/api/links/{link['id']}").get_json()["cloudflare"] == {
        "state": "active",
        "error": None,
    }


def test_a_link_error_is_read_from_its_json(world):
    link = world.create(**LINK, address=GO)
    world.fake.add_item(world.account, world.list_id, f"{GO}/promo", "https://elsewhere.test/")
    world.run()
    answer = world.bearer("GET", f"/api/links/{link['id']}").get_json()
    assert answer["cloudflare"] == {"state": "error", "error": {"code": "foreign_item", "detail": None}}
    with world.store.write() as conn:
        conn.execute("UPDATE redirect_links SET cf_error = 'not json' WHERE id = ?", (link["id"],))
    answer = world.bearer("GET", f"/api/links/{link['id']}").get_json()
    assert answer["cloudflare"]["error"] == {"code": "unknown", "detail": None}


@pytest.mark.parametrize(
    ("address", "status", "error"),
    [
        ("nowhere.example.com", 400, "invalid"),
        (7, 400, "invalid"),
        ("", 400, "invalid"),
        (None, 400, "invalid"),
    ],
)
def test_an_address_that_is_no_host_here_is_refused(world, address, status, error):
    answer = world.bearer("POST", "/api/links", json=LINK | {"address": address})
    assert answer.status_code == status and answer.get_json()["error"] == error
    assert set(answer.get_json()["fields"]) == {"address"}
    assert world.store.list() == []


def test_a_host_while_cloudflare_is_off_is_refused(client):
    answer = client.post("/api/links", json=LINK | {"address": GO}, headers=AUTH)
    assert answer.status_code == 409 and answer.get_json() == {"error": "cloudflare_off"}
    assert client.post("/api/links", json=LINK | {"address": "lan"}, headers=AUTH).status_code == 201


def test_an_adopted_host_needs_the_setup_scope(world):
    answer = world.narrow("POST", "/api/links", json=LINK | {"address": SITE})
    assert answer.status_code == 403 and answer.get_json() == {"error": "scope_denied"}
    made = world.session("POST", "/api/links", json=LINK | {"address": SITE})
    assert made.status_code == 201
    # A key without the setup scope may still change the rest of a link that has it
    changed = world.narrow(
        "PATCH", f"/api/links/{made.get_json()['id']}", json={"target": "https://b.test/", "address": SITE}
    )
    assert changed.status_code == 200


@pytest.mark.parametrize("slug", [".well-known/acme-challenge/x", ".WELL-KNOWN/security.txt", ".Well-Known"])
def test_well_known_is_refused_on_a_cloudflare_host_only(world, slug):
    answer = world.bearer("POST", "/api/links", json=LINK | {"slug": slug, "address": GO})
    assert answer.status_code == 400 and set(answer.get_json()["fields"]) == {"address"}
    link = world.create(**LINK | {"slug": slug})
    moved = world.bearer("PATCH", f"/api/links/{link['id']}", json={"address": GO})
    assert moved.status_code == 400 and set(moved.get_json()["fields"]) == {"address"}


def test_one_source_per_host_across_kinds(world):
    nano = world.create(kind="nano", name="Menu", target="https://example.test/", address=GO)
    answer = world.bearer("POST", "/api/links", json=LINK | {"slug": nano["id"], "address": GO})
    assert answer.status_code == 409
    assert answer.get_json() == {"error": "slug_taken", "fields": {"address": "this path is taken on this host"}}
    # The same path on the LAN is free: the LAN path of a NanoURL is its name
    assert world.bearer("POST", "/api/links", json=LINK | {"slug": nano["id"]}).status_code == 201


def test_a_full_list_refuses_one_more_link(env):
    world = World(env, item_limit=2)  # the page for unknown paths of go takes one item
    world.create(**LINK, address=GO)
    answer = world.bearer("POST", "/api/links", json=LINK | {"slug": "other", "address": GO})
    assert answer.status_code == 409 and answer.get_json() == {"error": "quota_full"}
    assert world.bearer("POST", "/api/links", json=LINK | {"slug": "other"}).status_code == 201


# --- What stops a Cloudflare address ----------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["link", "nano", "qrcode"])
def test_giving_up_a_cloudflare_address_needs_confirm_break(world, kind):
    body = LINK if kind == "link" else {"kind": kind, "name": "Menu", "target": "https://example.test/"}
    row = world.create(**body, address=GO)
    path = f"/api/links/{row['id']}"
    for to in ("lan", SITE):
        refused = world.session("PATCH", path, json={"address": to})
        assert refused.status_code == 400 and refused.get_json() == {"error": "confirm_break"}
    assert world.bearer("GET", path).get_json()["address"] == GO
    # Any other change keeps the address, and needs nothing
    assert world.bearer("PATCH", path, json={"target": "https://b.test/"}).status_code == 200
    assert world.bearer("PATCH", path, json={"address": GO}).status_code == 200
    moved = world.bearer("PATCH", path, json={"address": "lan", "confirm_break": True})
    assert moved.status_code == 200 and moved.get_json()["address"] == "lan"
    # Back from the LAN to a host breaks nothing printed
    assert world.bearer("PATCH", path, json={"address": GO}).status_code == 200


def test_a_new_slug_on_a_cloudflare_host_needs_confirm_break_and_on_the_lan_nothing(world):
    """D13: `https://<host>/<old slug>` stops just as when the address goes; a LAN link's slug moves freely."""
    row = world.create(**LINK, address=GO)
    path = f"/api/links/{row['id']}"
    assert world.bearer("PATCH", path, json={"slug": "promo"}).status_code == 200  # the same source
    renamed = world.bearer("PATCH", path, json={"slug": "renamed", "confirm_break": True})
    assert renamed.status_code == 200 and renamed.get_json()["slug"] == "renamed"
    # A NanoURL's source is its id: its name, and so its LAN path, changes nothing on the host
    nano = world.create(kind="nano", name="Menu", target="https://example.test/", address=GO)
    assert world.bearer("PATCH", f"/api/links/{nano['id']}", json={"name": "Card"}).status_code == 200
    lan = world.create(**LINK | {"slug": "lan"})
    assert world.bearer("PATCH", f"/api/links/{lan['id']}", json={"slug": "lan2"}).status_code == 200


def test_the_admin_may_move_a_link_within_an_adopted_host(world):
    made = world.session("POST", "/api/links", json=LINK | {"address": SITE}).get_json()
    answer = world.session("PATCH", f"/api/links/{made['id']}", json={"slug": "other", "confirm_break": True})
    assert answer.status_code == 200 and answer.get_json()["slug"] == "other"


def test_confirm_break_must_be_true_itself(world):
    row = world.create(**LINK, address=GO)
    for given in ("true", 1, "yes", None):
        answer = world.bearer("PATCH", f"/api/links/{row['id']}", json={"address": "lan", "confirm_break": given})
        assert answer.status_code == 400


def test_deleting_a_cloudflare_link_needs_confirm_break(world):
    one = world.create(**LINK, address=GO)
    two = world.create(**LINK | {"slug": "two"}, address=GO)
    assert world.bearer("DELETE", f"/api/links/{one['id']}").get_json() == {"error": "confirm_break"}
    assert world.bearer("DELETE", f"/api/links/{one['id']}", json={"confirm_break": False}).status_code == 400
    assert world.bearer("DELETE", f"/api/links/{one['id']}", json={"confirm_break": True}).status_code == 204
    assert world.bearer("DELETE", f"/api/links/{two['id']}?confirm_break=true").status_code == 204
    lan = world.create(**LINK | {"slug": "lan"})
    assert world.bearer("DELETE", f"/api/links/{lan['id']}").status_code == 204


# --- QR codes ---------------------------------------------------------------------------------------------------------


def test_a_qr_code_holds_its_address(world):
    qr = world.create(kind="qrcode", name="Flyer", target="https://example.test/", address=GO)
    svg = world.bearer("GET", f"/api/links/{qr['id']}/qr.svg").get_data(as_text=True)
    assert svg == app.render_svg(f"https://{GO}/{qr['id']}", app.Design())
    world.bearer("PATCH", f"/api/links/{qr['id']}", json={"address": "lan", "confirm_break": True})
    svg = world.bearer("GET", f"/api/links/{qr['id']}/qr.svg").get_data(as_text=True)
    assert svg == app.render_svg(f"{BASE}/links/{qr['id']}", app.Design())


def test_a_preview_draws_the_address_asked(world):
    qr = world.create(kind="qrcode", name="Flyer", target="https://example.test/", address=GO)
    preview = world.session("POST", "/api/qrcodes/preview", json={"id": qr["id"]}).get_json()["svg"]
    assert preview == app.render_svg(f"https://{GO}/{qr['id']}", app.Design())
    preview = world.session("POST", "/api/qrcodes/preview", json={"id": qr["id"], "address": "lan"}).get_json()["svg"]
    assert preview == app.render_svg(f"{BASE}/links/{qr['id']}", app.Design())
    preview = world.session("POST", "/api/qrcodes/preview", json={"address": GO}).get_json()["svg"]
    assert preview == app.render_svg(f"https://{GO}/{app.PREVIEW_ID}", app.Design())
    refused = world.session("POST", "/api/qrcodes/preview", json={"address": "nowhere.example.com"})
    assert refused.status_code == 400


# --- The Cloudflare endpoints ----------------------------------------------------------------------------------------


def test_the_state_while_cloudflare_is_off(client):
    login(client)
    state = client.get("/api/cloudflare").get_json()
    assert state["enabled"] is False and state["token"]["state"] == "off"
    assert state["accounts"] == [] and state["hosts"] == []
    for method, path in (
        ("POST", "/api/cloudflare/sync"),
        ("GET", "/api/cloudflare/compare"),
    ):
        answer = client.open(path, method=method, headers=AUTH)
        assert answer.status_code == 409 and answer.get_json() == {"error": "cloudflare_off"}


def test_the_state(world):
    world.create(**LINK, address=GO)
    state = world.bearer("GET", "/api/cloudflare").get_json()
    assert state["enabled"] is True
    assert state["token"] == {"state": "ok", "missing": [], "unverified": []}
    assert [account["name"] for account in state["accounts"]] == ["Main account"]
    account = state["accounts"][0]
    assert account["list"] == {"id": world.list_id} and account["quota"]["limit"] == 10000
    assert account["quota"]["used"] == 2  # the link and go's page, promised and not yet sent
    hosts = {host["host"]: host for host in state["hosts"]}
    assert hosts[GO]["created_by_us"] is True and hosts[GO]["fallback"] == WIKI
    assert hosts[GO]["fallback_state"] == "pending" and hosts[GO]["fallback_blocked"] is None
    assert hosts[SITE]["created_by_us"] is False and hosts[SITE]["fallback"] is None
    assert state["counts"] == {"pending": 1, "active": 0, "error": 0, "expired": 0, "removals": 0}
    assert CF_TOKEN not in world.bearer("GET", "/api/cloudflare").get_data(as_text=True)


def test_a_page_held_back_says_why(world):
    with world.store.write() as conn:
        conn.execute(
            "UPDATE cf_hosts SET fallback_state = 'error', fallback_error = ? WHERE host = ?",
            (app.error_text("origin_live"), GO),
        )
    hosts = {host["host"]: host for host in world.bearer("GET", "/api/cloudflare").get_json()["hosts"]}
    assert hosts[GO]["fallback_blocked"] == "live"
    assert hosts[GO]["fallback_error"] == {"code": "origin_live", "detail": None}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/cloudflare/zones", None),
        ("GET", "/api/cloudflare/proposals?zone=x", None),
        ("POST", "/api/cloudflare/plan", {}),
        ("POST", "/api/cloudflare/apply", {}),
        ("POST", f"/api/cloudflare/hosts/{GO}/fallback", {"fallback": None}),
        ("POST", "/api/cloudflare/compare/apply", {}),
    ],
)
def test_the_setup_endpoints_refuse_a_key_without_the_scope_and_a_change_without_csrf(world, method, path, body):
    answer = world.narrow(method, path, json=body)
    assert answer.status_code == 403 and answer.get_json() == {"error": "scope_denied"}
    if method == "POST":
        for token in ("", "x" + world.csrf):
            refused = world.session(method, path, json=body, headers={"X-CSRF-Token": token})
            assert refused.status_code == 403 and refused.get_json() == {"error": "csrf"}
        cross = world.session(method, path, json=body, headers={"Sec-Fetch-Site": "cross-site"})
        assert cross.status_code == 403
    assert world.store.cf_host(GO)["fallback"] == WIKI


def test_sync_now_answers_the_bearer_token_too(world):
    with world.store.write() as conn:
        conn.execute("UPDATE cf_hosts SET fallback_state = 'error' WHERE host = ?", (GO,))
    answer = world.bearer("POST", "/api/cloudflare/sync", json={})
    assert answer.status_code == 202 and answer.get_json() == {"retried": 1}
    assert world.store.cf_host(GO)["fallback_state"] == "pending"


def test_zones_and_proposals(world):
    zones = world.session("GET", "/api/cloudflare/zones").get_json()["zones"]
    assert zones == [
        {
            "id": world.zone,
            "name": "example.com",
            "account_id": world.account,
            "account_name": "Main account",
            "status": "active",
        }
    ]
    found = world.session("GET", f"/api/cloudflare/proposals?zone={world.zone}").get_json()
    assert {p["fqdn"]: p["verdict"] for p in found["proposals"]} == {
        GO: "added",
        "redirect.example.com": "create",
        "link.example.com": "create",
    }
    assert world.session("GET", "/api/cloudflare/proposals?zone=nope").status_code == 404


def test_a_host_is_set_up_through_the_plan_it_confirms(env):
    world = World(env, hosts=False)
    plan = world.plan("go", WIKI).get_json()
    assert plan["fqdn"] == GO and plan["blocked"] is None and plan["fingerprint"]
    body = {"zone_id": world.zone, "label": "go", "fallback": WIKI}
    stale = world.session("POST", "/api/cloudflare/apply", json=body | {"fingerprint": "0" * 64})
    assert stale.status_code == 409 and stale.get_json() == {"error": "plan_stale"}
    assert world.fake.writes() == []
    made = world.session("POST", "/api/cloudflare/apply", json=body | {"fingerprint": plan["fingerprint"]})
    assert made.status_code == 201
    assert made.get_json()["host"]["host"] == GO and made.get_json()["host"]["fallback"] == WIKI
    assert {call.method for call in world.fake.writes()} == {"POST"}
    again = world.session("POST", "/api/cloudflare/apply", json=body | {"fingerprint": plan["fingerprint"]})
    assert again.status_code == 409


def test_a_live_host_needs_its_tick(env):
    world = World(env, hosts=False)
    plan = world.plan("www").get_json()
    assert plan["live"] is True
    body = {"zone_id": world.zone, "label": "www", "fallback": None, "fingerprint": plan["fingerprint"]}
    refused = world.session("POST", "/api/cloudflare/apply", json=body)
    assert refused.status_code == 400 and refused.get_json() == {"error": "confirm_live"}
    assert world.session("POST", "/api/cloudflare/apply", json=body | {"confirm_live": True}).status_code == 201


def test_the_host_the_admin_is_reached_on_is_blocked(env):
    world = World(env, hosts=False)
    # The admin reached on the very name being set up, whatever the configured base URL says
    cookie = world.admin.get_cookie("moonie_redirect")
    world.admin.set_cookie("moonie_redirect", cookie.value, domain=GO)
    assert world.plan("go", environ_overrides={"HTTP_HOST": GO}).get_json()["blocked"] == "admin_host"
    world = World(env | {"MOONIE_REDIRECT_PUBLIC_BASE_URL": f"https://{GO}"}, hosts=False)
    assert world.plan("go").get_json()["blocked"] == "admin_host"


@pytest.mark.parametrize(
    ("label", "fallback", "field"),
    [("Go Go", None, "label"), ("go", "ftp://x", "target"), ("go", f"https://{GO}/x", "fallback")],
)
def test_a_plan_refuses_a_bad_label_or_page(env, label, fallback, field):
    world = World(env, hosts=False)
    answer = world.plan(label, fallback)
    assert answer.status_code == 400 and set(answer.get_json()["fields"]) == {field}


def test_the_page_for_unknown_paths_changes(world):
    path = f"/api/cloudflare/hosts/{GO}/fallback"
    answer = world.session("POST", path, json={"fallback": "https://www.google.com/"})
    assert answer.status_code == 200 and answer.get_json()["fallback"] == "https://www.google.com/"
    assert world.session("POST", path, json={"fallback": None}).get_json()["fallback"] is None
    missing = world.session("POST", path, json={})
    assert missing.status_code == 400 and set(missing.get_json()["fields"]) == {"fallback"}
    loop = world.session("POST", path, json={"fallback": f"https://{SITE}/"})
    assert loop.status_code == 400 and loop.get_json()["fields"] == {"fallback": "page_loop"}
    adopted = world.session("POST", f"/api/cloudflare/hosts/{SITE}/fallback", json={"fallback": WIKI})
    assert adopted.status_code == 404 and adopted.get_json() == {"error": "not_found"}


def test_cloudflare_out_of_reach_is_a_502_with_its_code(world):
    world.fake.fault("timeout", path="^/zones$", times=10)
    answer = world.session("GET", "/api/cloudflare/zones")
    assert answer.status_code == 502 and answer.get_json() == {"error": "unreachable"}


def test_a_long_rate_limit_holds_every_call(world):
    world.fake.fault("429", path="^/zones$", retry_after="120")
    answer = world.session("GET", "/api/cloudflare/zones")
    assert answer.status_code == 429 and answer.get_json() == {"error": "rate_limited"}
    calls = len(world.fake.ledger)
    assert world.session("GET", "/api/cloudflare/zones").status_code == 429
    assert len(world.fake.ledger) == calls


# --- Compare ----------------------------------------------------------------------------------------------------------


def test_compare_is_clean_once_synced(world):
    world.create(**LINK, address=GO)
    world.run(4)
    report = world.session("GET", "/api/cloudflare/compare").get_json()
    assert report["accounts"] == [
        {
            "account_id": world.account,
            "missing": [],
            "differs": [],
            "extra": [],
            "sources": report["accounts"][0]["sources"],
        }
    ]
    assert set(report["accounts"][0]["sources"].values()) == {f"https://{GO}/promo", f"https://{GO}/"}
    assert "fingerprint" not in world.narrow("GET", "/api/cloudflare/compare").get_json()
    assert "fingerprint" in world.bearer("GET", "/api/cloudflare/compare").get_json()  # the token file is `*`


def test_compare_finds_the_gaps_and_fixes_what_is_ticked(world):
    one = world.create(**LINK, address=GO)
    two = world.create(**LINK | {"slug": "two"}, address=GO)
    world.run(4)
    items = world.items()
    account, list_id = world.account, world.list_id
    del world.fake.state.lists[account][list_id]["items"][items[f"{GO}/promo"]["id"]]
    items[f"{GO}/two"]["redirect"]["target_url"] = "https://changed.test/"
    foreign = world.fake.add_item(account, list_id, f"{GO}/hand-made", "https://x.test/")
    report = world.session("GET", "/api/cloudflare/compare").get_json()
    gaps = report["accounts"][0]
    assert gaps["missing"] == [one["id"]]
    assert gaps["differs"] == [{"id": two["id"], "remote": {"target_url": "https://changed.test/", "status_code": 302}}]
    assert gaps["extra"] == [
        {
            "remote_id": foreign,
            "source_url": f"{GO}/hand-made",
            "target_url": "https://x.test/",
            "status_code": 302,
            "ours": False,
        }
    ]
    body = {"fingerprint": report["fingerprint"], "push": [one["id"], two["id"]], "remove": [foreign]}
    wrong = world.session("POST", "/api/cloudflare/compare/apply", json=body | {"confirm_remove": 0})
    assert wrong.status_code == 400 and set(wrong.get_json()["fields"]) == {"confirm_remove"}
    stale = world.session(
        "POST", "/api/cloudflare/compare/apply", json=body | {"confirm_remove": 1, "fingerprint": "0"}
    )
    assert stale.status_code == 409 and stale.get_json() == {"error": "remote_changed"}
    unknown = world.session("POST", "/api/cloudflare/compare/apply", json=body | {"confirm_remove": 1, "push": ["zzz"]})
    assert unknown.status_code == 400 and set(unknown.get_json()["fields"]) == {"push"}
    done = world.session("POST", "/api/cloudflare/compare/apply", json=body | {"confirm_remove": 1})
    assert done.status_code == 202 and done.get_json() == {"pushed": 2, "queued_removals": 1}
    world.run(6)
    items = world.items()
    assert f"{GO}/hand-made" not in items and f"{GO}/promo" in items
    assert items[f"{GO}/two"]["redirect"]["target_url"] == "https://shop.test/"
    clean = world.session("GET", "/api/cloudflare/compare").get_json()["accounts"][0]
    assert (clean["missing"], clean["differs"], clean["extra"]) == ([], [], [])


def test_compare_sees_a_page_for_unknown_paths_gone(world):
    world.run(4)
    items = world.items()
    del world.fake.state.lists[world.account][world.list_id]["items"][items[f"{GO}/"]["id"]]
    report = world.session("GET", "/api/cloudflare/compare").get_json()
    assert report["accounts"][0]["missing"] == [f"fallback:{GO}"]
    body = {"fingerprint": report["fingerprint"], "push": [f"fallback:{GO}"], "remove": [], "confirm_remove": 0}
    assert world.session("POST", "/api/cloudflare/compare/apply", json=body).get_json()["pushed"] == 1
    assert world.store.cf_host(GO)["fallback_state"] == "pending"


# --- A slow Cloudflare never holds a request (the waitress threads are few) ----------------------------------------


def test_the_state_on_an_unreachable_cloudflare_tries_once_then_answers_from_its_cache(world):
    world.sync._token = None
    world.fake.fault("timeout", times=100)
    world.fake.ledger.clear()
    start = world.fake.clock()
    state = world.bearer("GET", "/api/cloudflare")
    assert state.status_code == 200 and state.get_json()["token"]["state"] == "unchecked"
    assert len(world.fake.ledger) == 1 and world.fake.clock() - start <= app.REQUEST_BUDGET
    # The failure is kept a little while: the next loads of the page send nothing
    assert world.bearer("GET", "/api/cloudflare").get_json()["token"]["state"] == "unchecked"
    assert len(world.fake.ledger) == 1


def test_the_state_on_a_slow_cloudflare_stops_at_its_budget(world):
    world.sync._token = None
    world.fake.latency = 4.0  # every exchange takes 4 s of the virtual clock, under the 5 s read timeout
    start = world.fake.clock()
    state = world.bearer("GET", "/api/cloudflare").get_json()
    assert state["token"]["state"] == "unchecked"
    assert world.fake.clock() - start <= app.REQUEST_BUDGET + world.fake.latency


def test_the_sync_s_own_token_check_keeps_its_retries(world):
    world.fake.fault("status", status=503, path="^/user/tokens/verify$", times=2)
    world.fake.ledger.clear()
    assert world.sync.token_state(refresh=True)["state"] == "ok"
    assert len(world.fake.calls("GET", "^/user/tokens/verify$")) == 3


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/cloudflare/zones", None),
        ("GET", "/api/cloudflare/proposals?zone={zone}", None),
        ("POST", "/api/cloudflare/plan", {"zone_id": "{zone}", "label": "new", "fallback": None}),
        ("POST", "/api/cloudflare/apply", {"zone_id": "{zone}", "label": "new", "fallback": None, "fingerprint": "0"}),
        ("GET", "/api/cloudflare/compare", None),
        ("POST", "/api/cloudflare/compare/apply", {"fingerprint": "0", "push": [], "remove": [], "confirm_remove": 0}),
    ],
)
def test_the_admin_s_cloudflare_calls_are_tried_once(world, method, path, body):
    path = path.format(zone=world.zone)
    body = (
        None if body is None else {k: v.format(zone=world.zone) if isinstance(v, str) else v for k, v in body.items()}
    )
    world.fake.fault("status", status=503, times=100)
    world.fake.ledger.clear()
    answer = world.session(method, path, json=body)
    assert answer.status_code == 502 and answer.get_json() == {"error": "refused"}
    assert len(world.fake.ledger) == 1 and not [s for s in world.fake.clock.slept if s >= 1]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/cloudflare/proposals?zone={zone}", None),
        ("POST", "/api/cloudflare/plan", {"zone_id": "{zone}", "label": "new", "fallback": None}),
    ],
)
def test_the_admin_s_cloudflare_calls_stop_at_their_budget(world, method, path, body):
    path = path.format(zone=world.zone)
    body = (
        None if body is None else {k: v.format(zone=world.zone) if isinstance(v, str) else v for k, v in body.items()}
    )
    world.fake.latency = 6.0
    start = world.fake.clock()
    answer = world.session(method, path, json=body)
    assert answer.status_code == 502 and answer.get_json() == {"error": "unreachable"}
    assert world.fake.clock() - start <= app.REQUEST_BUDGET + world.fake.latency


def test_a_setup_has_a_longer_budget_than_a_read(world):
    world.fake.latency = 3.0  # a slow but working Cloudflare: the whole setup takes longer than a read may
    plan = world.plan("new").get_json()
    body = {"zone_id": world.zone, "label": "new", "fallback": None, "fingerprint": plan["fingerprint"]}
    start = world.fake.clock()
    answer = world.session("POST", "/api/cloudflare/apply", json=body)
    assert answer.status_code == 201, answer.get_json()
    assert app.REQUEST_BUDGET < world.fake.clock() - start <= app.SETUP_BUDGET


# --- D18: the admin's own host takes no link -------------------------------------------------------------------------


ADMIN_HOST = {"address": "this instance's own host: choose another"}


def test_a_link_is_refused_the_host_the_admin_is_configured_on(world, env):
    moved = app.create_app(env | {"MOONIE_REDIRECT_PUBLIC_BASE_URL": f"https://{GO}/"}, cloudflare=world.fake)
    client = moved.test_client()
    refused = client.post("/api/links", json=LINK | {"address": GO}, headers=AUTH)
    assert refused.status_code == 400 and refused.get_json()["fields"] == ADMIN_HOST
    link = client.post("/api/links", json=LINK, headers=AUTH).get_json()
    moved_to = client.patch(f"/api/links/{link['id']}", json={"address": GO}, headers=AUTH)
    assert moved_to.status_code == 400 and moved_to.get_json()["fields"] == ADMIN_HOST
    assert moved.extensions["store"].get(link["id"])["address"] is None


def test_a_link_is_refused_the_host_the_admin_is_reached_on(world):
    refused = world.bearer("POST", "/api/links", json=LINK | {"address": GO}, environ_overrides={"HTTP_HOST": GO})
    assert refused.status_code == 400 and refused.get_json()["fields"] == ADMIN_HOST
    assert world.bearer("POST", "/api/links", json=LINK | {"address": GO}).status_code == 201
