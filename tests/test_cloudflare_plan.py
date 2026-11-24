"""Setting a host up: the plan, its fingerprint and apply, against the in-memory fake."""

import pytest
from fake_cloudflare import FakeCloudflare

import app

ADMIN = {"admin.example.com"}
WIKI = app.FALLBACK_CHOICES[0]


@pytest.fixture
def fake():
    return FakeCloudflare()


@pytest.fixture
def store(tmp_path):
    return app.Store(tmp_path / "redirect.db")


def plan(fake, store, zone, label="go", fallback=None, serving=ADMIN):
    return app.plan_for(fake, store, zone, label, fallback, serving)[0]


def apply(fake, store, zone, label="go", fallback=None, *, fingerprint=None, confirm_live=False, serving=ADMIN):
    if fingerprint is None:
        fingerprint = plan(fake, store, zone, label, fallback, serving)["fingerprint"]
    return app.apply_plan(
        fake,
        store,
        zone_id=zone,
        label=label,
        fallback=fallback,
        fingerprint_sent=fingerprint,
        confirm_live=confirm_live,
        serving=serving,
    )


def steps(found):
    return [step["do"] for step in found["steps"]]


def test_a_fresh_account_plans_list_entrypoint_and_record(fake, store):
    account = fake.add_account()
    zone = fake.add_zone("Example.COM", account)
    found = plan(fake, store, zone)
    assert found["fqdn"] == "go.example.com" and found["verdict"] == "create" and found["blocked"] is None
    assert steps(found) == ["create_list", "create_entrypoint", "create_record"]
    assert not found["live"]


def test_an_existing_list_and_rule_are_reused(fake, store):
    _, zone, _ = fake.setup()
    assert steps(plan(fake, store, zone)) == ["create_record"]


def test_a_rule_is_added_beside_the_others(fake, store):
    account = fake.add_account()
    zone = fake.add_zone("example.com", account)
    fake.add_list(account)
    fake.add_entrypoint(account, [{"expression": "true", "action": "redirect"}])
    assert steps(plan(fake, store, zone)) == ["add_rule", "create_record"]


def test_full_lists_and_rules_block(fake, store):
    account = fake.add_account()
    zone = fake.add_zone("example.com", account)
    for n in range(app.MAX_LISTS):
        fake.add_list(account, f"other{n}")
    fake.add_entrypoint(account, [{"expression": f"r{n}"} for n in range(app.MAX_RULES)])
    assert plan(fake, store, zone)["blocked"] == "lists_full"
    fake.add_list(account)  # ours now exists: only the rules are full
    assert plan(fake, store, zone)["blocked"] == "rules_full"


@pytest.mark.parametrize(
    ("records", "verdict", "live", "blocked"),
    [
        ([("A", "192.0.2.1", True)], "ready", False, None),
        ([("A", "203.0.113.5", True)], "ready", True, None),
        ([("CNAME", "site.example.net", True)], "ready", True, None),
        ([("A", "203.0.113.5", False)], "conflict", True, "conflict"),
        ([("TXT", "v=spf1", False)], "create", False, None),
    ],
)
def test_record_verdicts(fake, store, records, verdict, live, blocked):
    _, zone, _ = fake.setup()
    for type_, content, proxied in records:
        fake.add_record(zone, type_, "go.example.com", content, proxied)
    found = plan(fake, store, zone, fallback=WIKI)
    assert (found["verdict"], found["live"], found["blocked"]) == (verdict, live, blocked)
    if verdict == "ready":
        # An adopted host never takes a page for unknown paths
        assert steps(found) == ["use_record", "no_fallback"]


def test_the_admin_host_is_refused_from_config_and_from_the_request(fake, store):
    _, zone, _ = fake.setup()
    assert plan(fake, store, zone, serving={"go.example.com"})["blocked"] == "admin_host"
    serving = app.serving_hosts("https://redirect.lan", "GO.example.com:8443")
    assert serving == {"redirect.lan", "go.example.com"}
    assert plan(fake, store, zone, serving=serving)["blocked"] == "admin_host"


def test_a_permission_refusal_blocks(fake, store):
    _, zone, _ = fake.setup()
    fake.denied.add("lists")
    assert plan(fake, store, zone)["blocked"] == "permission"


def test_a_page_that_loops_is_refused(fake, store):
    _, zone, _ = fake.setup()
    apply(fake, store, zone, "go")
    with pytest.raises(app.Invalid, match="page_loop"):
        plan(fake, store, zone, "link", fallback="https://go.example.com/x")
    with pytest.raises(app.Invalid, match="page_loop"):
        plan(fake, store, zone, "link", fallback="https://link.example.com/")
    with pytest.raises(app.Invalid, match="admin_host"):
        plan(fake, store, zone, "link", fallback="https://admin.example.com/")
    with pytest.raises(app.Invalid):
        plan(fake, store, zone, "link", fallback="javascript:alert(1)")


def test_a_host_another_page_points_at_is_blocked(fake, store):
    _, zone, _ = fake.setup()
    apply(fake, store, zone, "go", fallback="https://link.example.com/")
    assert plan(fake, store, zone, "link")["blocked"] == "page_points_here"


def test_a_host_set_up_already_is_blocked(fake, store):
    _, zone, _ = fake.setup()
    apply(fake, store, zone)
    assert plan(fake, store, zone)["blocked"] == "host_exists"


def test_a_bad_label_or_zone_is_refused(fake, store):
    _, zone, _ = fake.setup()
    with pytest.raises(app.Invalid):
        plan(fake, store, zone, label="Go")
    with pytest.raises(app.Invalid):
        plan(fake, store, zone, label="-go")
    with pytest.raises(app.PlanRefused) as refused:
        plan(fake, store, "fake-999")
    assert refused.value.status == 404


def test_the_root_step_says_who_holds_it(fake, store):
    account, zone, list_id = fake.setup()
    assert steps(plan(fake, store, zone, fallback=WIKI))[-1] == "add_fallback"
    fake.add_item(account, list_id, "go.example.com/", "https://someone.test/", subpath=True)
    assert steps(plan(fake, store, zone, fallback=WIKI))[-1] == "root_held"


def test_a_full_list_says_root_full(fake, store, tmp_path):
    account, zone, list_id = fake.setup()
    small = app.Store(tmp_path / "small.db", item_limit=1)
    fake.add_item(account, list_id, "x.example.com/a", "https://t.test/")
    assert steps(plan(fake, small, zone, fallback=WIKI))[-1] == "root_full"


def test_the_fingerprint_is_stable_and_binds_the_plan(fake, store):
    account, zone, _ = fake.setup()
    first, second = plan(fake, store, zone, fallback=WIKI), plan(fake, store, zone, fallback=WIKI)
    assert first == second and first["fingerprint"] == app.fingerprint(first)
    assert plan(fake, store, zone, fallback=None)["fingerprint"] != first["fingerprint"]
    # Cloudflare changed between the plan and its confirmation
    fake.add_record(zone, "A", "go.example.com", "203.0.113.5", True)
    with pytest.raises(app.PlanRefused) as refused:
        apply(fake, store, zone, fallback=WIKI, fingerprint=first["fingerprint"])
    assert (refused.value.status, refused.value.code) == (409, "plan_stale")
    assert store.cf_hosts() == [] and fake.writes() == []


def test_apply_creates_and_saves_and_never_sends_put_or_delete(fake, store):
    account = fake.add_account("Team")
    zone = fake.add_zone("example.com", account)
    answer = apply(fake, store, zone, fallback=WIKI)
    assert answer["host"] == "go.example.com"
    assert {call.method for call in fake.ledger} <= {"GET", "POST"}
    assert [call.path.rsplit("/", 1)[-1] for call in fake.writes()] == ["lists", "rulesets", "dns_records"]
    [saved] = store.cf_accounts()
    assert saved["name"] == "Team" and saved["list_id"] and saved["ruleset_id"] and saved["rule_id"]
    [host] = store.cf_hosts()
    assert host["created_by_us"] == 1 and host["record_id"] and host["fallback"] == WIKI
    assert (host["fallback_state"], host["fallback_rev"]) == ("pending", 1)


def test_an_adopted_host_saves_no_page(fake, store):
    _, zone, _ = fake.setup()
    fake.add_record(zone, "A", "go.example.com", "192.0.2.1", True)
    apply(fake, store, zone, fallback=WIKI)
    [host] = store.cf_hosts()
    assert host["created_by_us"] == 0 and host["fallback"] is None
    assert fake.writes() == []


def test_a_live_host_needs_the_tick(fake, store):
    _, zone, _ = fake.setup()
    fake.add_record(zone, "CNAME", "go.example.com", "site.example.net", True)
    with pytest.raises(app.PlanRefused) as refused:
        apply(fake, store, zone)
    assert (refused.value.status, refused.value.code) == (400, "confirm_live")
    apply(fake, store, zone, confirm_live=True)
    assert [h["host"] for h in store.cf_hosts()] == ["go.example.com"]


def test_a_blocked_plan_is_refused(fake, store):
    _, zone, _ = fake.setup()
    with pytest.raises(app.PlanRefused) as refused:
        apply(fake, store, zone, serving={"go.example.com"})
    assert refused.value.code == "admin_host"


def test_a_second_setup_at_the_same_time_is_busy(fake, store):
    _, zone, _ = fake.setup()
    with app.setup_lock:
        with pytest.raises(app.PlanRefused) as refused:
            apply(fake, store, zone, fingerprint="x")
        with pytest.raises(app.PlanRefused):
            app.change_fallback(store, "go.example.com", None, ADMIN)
    assert refused.value.code == "busy"


def test_proposals(fake, store):
    _, zone, _ = fake.setup()
    fake.add_record(zone, "A", "redirect.example.com", "203.0.113.5", False)
    apply(fake, store, zone, "link")
    found = app.proposals(fake, app.find_zone(fake, zone), {h["host"] for h in store.cf_hosts()})
    assert [(p["label"], p["verdict"]) for p in found["proposals"]] == [
        ("go", "create"),
        ("redirect", "conflict"),
        ("link", "added"),
    ]


def test_change_fallback(fake, store):
    account, zone, _ = fake.setup()
    apply(fake, store, zone, "go")
    fake.add_record(zone, "A", "link.example.com", "192.0.2.1", True)
    apply(fake, store, zone, "link")
    with pytest.raises(app.PlanRefused) as refused:
        app.change_fallback(store, "link.example.com", WIKI, ADMIN)  # adopted
    assert refused.value.status == 404
    with pytest.raises(app.Invalid):
        app.change_fallback(store, "go.example.com", "https://link.example.com/", ADMIN)
    assert app.change_fallback(store, "go.example.com", WIKI, ADMIN) == WIKI
    assert store.cf_host("go.example.com")["fallback_state"] == "pending"
    assert app.change_fallback(store, "go.example.com", None, ADMIN) is None
    host = store.cf_host("go.example.com")
    assert host["fallback"] is None and host["fallback_state"] is None
    with store.read() as conn:
        [removal] = conn.execute("SELECT * FROM cf_removals").fetchall()
    assert (removal["source"], removal["marker"], removal["reason"]) == ("go.example.com/", "fallback", "fallback")


def test_our_own_placeholder_found_again_is_reused_and_stays_ours(fake, store):
    """D15: the record an earlier apply made (its answer lost) is no site: reused, the host still created here."""
    _, zone, _ = fake.setup()
    record = fake.add_record(zone, "A", "go.example.com", app.PLACEHOLDER_IPV4, True)
    fake.state.records[zone][-1]["comment"] = app.RECORD_COMMENT
    found = plan(fake, store, zone, fallback=WIKI)
    assert (found["verdict"], found["live"], found["blocked"]) == ("create", False, None)
    assert steps(found) == ["use_record", "keep_ours", "add_fallback"]
    apply(fake, store, zone, fallback=WIKI)
    [host] = store.cf_hosts()
    assert (host["created_by_us"], host["record_id"], host["fallback"]) == (1, record, WIKI)
    assert not fake.calls("POST", r"/dns_records$")


@pytest.mark.parametrize("comment", [None, "someone else", "moonie-redirect "])
def test_a_placeholder_with_another_comment_is_adopted(fake, store, comment):
    _, zone, _ = fake.setup()
    fake.add_record(zone, "A", "go.example.com", app.PLACEHOLDER_IPV4, True)
    if comment is not None:
        fake.state.records[zone][-1]["comment"] = comment
    assert steps(plan(fake, store, zone, fallback=WIKI)) == ["use_record", "no_fallback"]
