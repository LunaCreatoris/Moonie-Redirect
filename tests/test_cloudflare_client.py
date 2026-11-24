"""The Cloudflare client on the wire, through `responses`: no request leaves the process."""

import json
import logging

import pytest
import requests
import responses
import urllib3
from fake_cloudflare import INSTALL, TOKEN, Clock, FakeCloudflare

import app

ROOT = "https://cloudflare.test/client/v4"


@pytest.fixture(autouse=True)
def api_root(monkeypatch):
    monkeypatch.setattr(app, "API_ROOT", ROOT)


@pytest.fixture
def wire():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def client(clock):
    return app.Cloudflare(TOKEN, sleep=clock.sleep, clock=clock)


def ok(result, info=None):
    body = {"success": True, "errors": [], "messages": [], "result": result}
    return body | ({"result_info": info} if info is not None else {})


def refused(code=10001, message="bad"):
    return {"success": False, "errors": [{"code": code, "message": message}], "result": None}


LISTS = f"{ROOT}/accounts/acc1/rules/lists"
ITEMS = f"{LISTS}/list1/items"


# --- Methods, redirects, token ---


@pytest.mark.parametrize("method", ["PUT", "PATCH", "HEAD"])
def test_only_get_post_and_delete_are_ever_sent(client, wire, method):
    with pytest.raises(ValueError):
        client._request(method, "/accounts")
    assert len(wire.calls) == 0


def test_a_redirect_is_never_followed(client, wire):
    wire.get(LISTS, status=302, headers={"Location": "https://elsewhere.test/steal"})
    with pytest.raises(app.CfUnreachable) as raised:
        client.lists("acc1")
    assert raised.value.kind == "redirect"
    assert len(wire.calls) == 1  # not followed, and not retried


def test_the_token_goes_in_the_authorization_header_only(client, wire):
    wire.get(LISTS, json=ok([]))
    client.lists("acc1")
    request = wire.calls[0].request
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in request.url


def test_the_token_is_never_in_repr_errors_or_logs(client, wire, caplog):
    caplog.set_level(logging.DEBUG)
    assert TOKEN not in repr(client) and TOKEN not in str(client)
    wire.get(LISTS, status=403, json=refused(9109, f"token {TOKEN} is not allowed"))
    with pytest.raises(app.CfError) as raised:
        client.lists("acc1")
    assert TOKEN not in str(raised.value) and "[redacted]" in raised.value.message
    wire.get(ITEMS, status=503, json=refused())
    with pytest.raises(app.CfError):
        list(client.list_items("acc1", "list1"))
    assert TOKEN not in caplog.text
    with pytest.raises(TypeError):
        import pickle

        pickle.dumps(client)


def test_a_bad_token_is_refused_without_echoing_it():
    with pytest.raises(ValueError) as raised:
        app.Cloudflare("has a space")
    assert "space" not in str(raised.value)


def test_messages_are_one_clean_line():
    text = "line one\nline\u202etwo\x00 " + "x" * 300
    cleaned = app.clean_message(text, "secret")
    assert "\n" not in cleaned and "\u202e" not in cleaned and "\x00" not in cleaned
    assert len(cleaned) == app.MESSAGE_LIMIT
    assert app.clean_message("echo secret back", "secret") == "echo [redacted] back"


@pytest.mark.parametrize("bad", ["../zones", "a/b", "", "a" * 65, "-lead", None])
def test_a_bad_id_sends_no_request(client, wire, bad):
    with pytest.raises(ValueError):
        client.lists(bad)
    assert len(wire.calls) == 0


def test_an_id_in_an_answer_that_could_climb_out_of_its_path_is_malformed(client, wire):
    wire.get(LISTS, json=ok([{"id": "../x", "name": "moonie_redirect", "kind": "redirect", "num_items": 0}]))
    with pytest.raises(app.CfUnreachable) as raised:
        client.lists("acc1")
    assert raised.value.kind == "malformed"


def test_proxies_from_the_environment_are_ignored(client, wire, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:3128")
    monkeypatch.setenv("https_proxy", "http://proxy.test:3128")
    wire.get(LISTS, json=ok([]))
    client.lists("acc1")
    kwargs = wire.calls[0].request.req_kwargs
    assert not kwargs.get("proxies")
    assert kwargs["timeout"] == app.CF_TIMEOUT


def test_success_false_is_a_refusal(client, wire):
    wire.get(LISTS, json=refused(10000, "nope") | {"success": False})
    with pytest.raises(app.CfError) as raised:
        client.lists("acc1")
    assert raised.value.codes == (10000,)


@pytest.mark.parametrize("body", [b"{not json", b"[]", b'"text"'])
def test_an_answer_that_is_not_a_json_object_is_malformed(client, wire, body):
    wire.get(LISTS, body=body, content_type="application/json")
    with pytest.raises(app.CfUnreachable) as raised:
        client.lists("acc1")
    assert raised.value.kind == "malformed"


def test_an_answer_over_the_cap_is_refused(client, wire):
    wire.get(LISTS, body=b" " * (app.MAX_ANSWER + 1), content_type="application/json")
    with pytest.raises(app.CfUnreachable) as raised:
        client.lists("acc1")
    assert raised.value.kind == "too_large"


# --- Paging ---


def test_paging_ends_on_an_empty_page(client, wire):
    zone = {"id": "z1", "name": "example.com", "status": "active", "account": {"id": "a1", "name": "A"}}
    wire.get(f"{ROOT}/zones", match=[responses.matchers.query_param_matcher({"page": "1", "per_page": "50"})],
             json=ok([zone] * 50))  # fmt: skip
    wire.get(f"{ROOT}/zones", match=[responses.matchers.query_param_matcher({"page": "2", "per_page": "50"})],
             json=ok([]))  # fmt: skip
    assert len(client.zones()) == 50


def test_paging_ends_on_a_short_page(client, wire):
    zone = {"id": "z1", "name": "example.com", "status": "active", "account": {"id": "a1", "name": "A"}}
    wire.get(f"{ROOT}/zones", json=ok([zone] * 3))
    assert len(client.zones()) == 3
    assert len(wire.calls) == 1


def test_paging_refuses_the_same_page_twice(client, wire):
    zone = {"id": "z1", "name": "example.com", "status": "active", "account": {"id": "a1", "name": "A"}}
    wire.get(f"{ROOT}/zones", json=ok([zone] * 50))
    with pytest.raises(app.CfUnreachable) as raised:
        client.zones()
    assert raised.value.kind == "malformed"


def test_item_paging_follows_the_cursor_and_ends_without_one(client, wire):
    item = {"id": "i1", "redirect": {"source_url": "go.example.com/a", "target_url": "https://t.test/"}}
    wire.get(ITEMS, match=[responses.matchers.query_param_matcher({"per_page": "500"})],
             json=ok([item], {"cursors": {"after": "c1"}}))  # fmt: skip
    wire.get(ITEMS, match=[responses.matchers.query_param_matcher({"per_page": "500", "cursor": "c1"})],
             json=ok([item | {"id": "i2"}], {"cursors": {}}))  # fmt: skip
    assert [item.id for item in client.list_items("acc1", "list1")] == ["i1", "i2"]


def test_item_paging_refuses_a_repeated_cursor(client, wire):
    item = {"id": "i1", "redirect": {"source_url": "go.example.com/a", "target_url": "https://t.test/"}}
    wire.get(ITEMS, json=ok([item], {"cursors": {"after": "c1"}}))
    with pytest.raises(app.CfUnreachable):
        list(client.list_items("acc1", "list1"))


def test_a_full_last_page_with_no_cursor_while_the_list_holds_more_is_malformed(client, wire):
    items = [
        {"id": f"i{n}", "redirect": {"source_url": f"go.example.com/{n}", "target_url": "https://t.test/"}}
        for n in range(500)
    ]
    wire.get(ITEMS, json=ok(items, {"cursors": {}}))
    wire.get(LISTS, json=ok([{"id": "list1", "name": "moonie_redirect", "kind": "redirect", "num_items": 501}]))
    with pytest.raises(app.CfUnreachable):
        list(client.list_items("acc1", "list1"))


# --- Retries ---


def test_a_get_is_retried_on_5xx_with_back_off(client, clock, wire):
    wire.get(LISTS, status=503, json=refused())
    wire.get(LISTS, status=502, json=refused())
    wire.get(LISTS, json=ok([]))
    assert client.lists("acc1") == []
    assert len(wire.calls) == 3
    assert [s for s in clock.slept if s >= 1] == [1.0, 2.0]


def test_a_get_gives_up_after_four_tries(client, wire):
    wire.get(LISTS, status=503, json=refused())
    with pytest.raises(app.CfError) as raised:
        client.lists("acc1")
    assert raised.value.status == 503 and len(wire.calls) == app.ATTEMPTS


def test_a_post_is_not_retried_on_5xx(client, wire):
    wire.post(LISTS, status=503, json=refused())
    with pytest.raises(app.CfError):
        client.create_list("acc1")
    assert len(wire.calls) == 1


def test_a_post_is_not_retried_after_a_read_timeout(client, wire):
    wire.post(LISTS, body=requests.exceptions.ReadTimeout("slow"))
    with pytest.raises(app.CfUnreachable) as raised:
        client.create_list("acc1")
    assert raised.value.kind == "timeout" and not raised.value.not_sent
    assert len(wire.calls) == 1


def test_a_post_is_retried_when_it_never_reached_cloudflare(client, wire):
    never = urllib3.exceptions.NewConnectionError(None, "connection refused")
    wire.post(LISTS, body=requests.exceptions.ConnectionError(urllib3.exceptions.MaxRetryError(None, LISTS, never)))
    wire.post(LISTS, json=ok({"id": "list1", "name": "moonie_redirect", "kind": "redirect", "num_items": 0}))
    assert client.create_list("acc1").id == "list1"
    assert len(wire.calls) == 2


def test_a_delete_is_retried_on_a_dropped_connection(client, wire):
    wire.delete(ITEMS, body=requests.exceptions.ConnectionError("reset"))
    wire.delete(ITEMS, json=ok({"operation_id": "op1"}))
    assert client.delete_items("acc1", "list1", ["i1"]) == "op1"


def test_a_short_retry_after_is_slept(client, clock, wire):
    wire.get(LISTS, status=429, json=refused(971), headers={"Retry-After": "2"})
    wire.get(LISTS, json=ok([]))
    assert client.lists("acc1") == []
    assert 2.0 in clock.slept


def test_a_long_retry_after_raises(client, clock, wire):
    wire.post(ITEMS, status=429, json=refused(971), headers={"Retry-After": "120"})
    item = app.make_item("go.example.com/a", "https://t.test/", 302, INSTALL, "abcd2345")
    with pytest.raises(app.RateLimited) as raised:
        client.add_items("acc1", "list1", [item])
    assert raised.value.retry_after == 120
    assert 120 not in clock.slept and len(wire.calls) == 1


def test_calls_keep_their_gap(client, clock, wire):
    wire.get(LISTS, json=ok([]))
    client.lists("acc1")
    client.lists("acc1")
    assert clock.slept == [pytest.approx(app.MIN_GAP)]


# --- Calls made for a request: bounded (a waitress thread is never held on a slow Cloudflare) ---


def test_a_bounded_get_is_tried_once(client, clock, wire):
    wire.get(LISTS, status=503, json=refused())
    with client.bounded(app.REQUEST_BUDGET), pytest.raises(app.CfError):
        client.lists("acc1")
    assert len(wire.calls) == 1 and not [s for s in clock.slept if s >= 1]


def test_a_bounded_get_is_not_retried_after_a_timeout(client, wire):
    wire.get(LISTS, body=requests.exceptions.ReadTimeout("slow"))
    with client.bounded(app.REQUEST_BUDGET), pytest.raises(app.CfUnreachable):
        client.lists("acc1")
    assert len(wire.calls) == 1


def test_a_bounded_call_never_sleeps_a_retry_after(client, clock, wire):
    wire.get(LISTS, status=429, json=refused(971), headers={"Retry-After": "2"})
    with client.bounded(app.REQUEST_BUDGET), pytest.raises(app.RateLimited) as raised:
        client.lists("acc1")
    assert raised.value.retry_after == 2 and 2.0 not in clock.slept and len(wire.calls) == 1


def test_a_bounded_call_waits_short_timeouts(client, wire):
    wire.get(LISTS, json=ok([]))
    client.lists("acc1")
    with client.bounded(app.REQUEST_BUDGET):
        client.lists("acc1")
    assert wire.calls[0].request.req_kwargs["timeout"] == app.CF_TIMEOUT
    assert wire.calls[1].request.req_kwargs["timeout"] == app.REQUEST_TIMEOUT


def test_a_bounded_call_never_waits_past_what_is_left(client, clock, wire):
    wire.get(LISTS, json=ok([]))
    with client.bounded(4.0):
        clock.now += 2.0
        client.lists("acc1")
    connect, read = wire.calls[0].request.req_kwargs["timeout"]
    assert connect <= 2.0 and read <= 2.0


def test_no_call_starts_once_the_budget_is_spent(client, clock, wire):
    wire.get(LISTS, json=ok([]))
    with client.bounded(1.0):
        client.lists("acc1")
        clock.now += 1.0
        with pytest.raises(app.CfUnreachable) as raised:
            client.lists("acc1")
    assert raised.value.kind == "timeout" and raised.value.not_sent and len(wire.calls) == 1


def test_the_bound_ends_with_its_block_and_holds_its_thread_only(client, wire):
    import threading

    wire.get(LISTS, status=503, json=refused())
    wire.get(LISTS, json=ok([]))
    found = []
    with client.bounded(app.REQUEST_BUDGET):
        other = threading.Thread(target=lambda: found.append(client.lists("acc1")))
        other.start()
        other.join()
    assert found == [[]] and len(wire.calls) == 2  # the other thread retried as the sync does
    wire.calls.reset()
    assert client.lists("acc1") == [] and len(wire.calls) == 1


# --- Bodies ---


def test_items_are_checked_before_they_are_sent(client, wire):
    item = app.make_item("go.example.com/a", "https://t.test/", 302, INSTALL, "abcd2345")
    stray = json.loads(json.dumps(item))
    stray["redirect"]["subpath_matching"] = True
    unmarked = json.loads(json.dumps(item)) | {"comment": "mine"}
    for bad in ([stray], [unmarked], [], [item] * 501):
        with pytest.raises(ValueError):
            client.add_items("acc1", "list1", bad)
    assert len(wire.calls) == 0
    root = app.make_item("go.example.com/", "https://www.google.com/", 302, INSTALL, app.FALLBACK_MARKER)
    assert root["redirect"]["subpath_matching"] is True and app.checked_items([root]) == [root]


def test_the_bodies_written_are_the_plugins(client, wire):
    wire.post(f"{ROOT}/zones/z1/dns_records", json=ok({"id": "r1", "type": "A", "name": "go.example.com",
              "content": "192.0.2.1", "proxied": True}))  # fmt: skip
    client.create_dns_record("z1", "go.example.com")
    assert json.loads(wire.calls[0].request.body) == {
        "type": "A",
        "name": "go.example.com",
        "content": "192.0.2.1",
        "proxied": True,
        "ttl": 1,
        "comment": "moonie-redirect",
    }
    assert app.rule_body()["expression"] == "http.request.full_uri in $moonie_redirect"
    assert app.names_our_list(app.rule_body()) and not app.names_our_list({"expression": "x in $moonie_redirect2"})


# --- Pure helpers ---


@pytest.mark.parametrize(
    ("given", "key"),
    [
        ("HTTPS://GO.example.com.:443/%7e%c3%a4/", "go.example.com/~%C3%A4/"),
        ("go.example.com", "go.example.com/"),
        ("http://go.example.com:80/Promo", "go.example.com/Promo"),
        ("go.example.com:8443/a", "go.example.com:8443/a"),
        ("go.example.com/a%zz", "go.example.com/a%25zz"),
        ("go.example.com/promo/", "go.example.com/promo/"),
    ],
)
def test_source_key(given, key):
    assert app.source_key(given) == key
    assert app.source_key(key) == key


def test_markers():
    comment = app.marker(INSTALL, "abcd2345")
    assert app.marker_of(comment) == (INSTALL, "abcd2345")
    assert app.entry_of(comment, INSTALL) == "abcd2345"
    assert app.entry_of(comment, "other") is None
    assert app.marker_of("moonie:abcd2345") is None and app.marker_of(None) is None
    with pytest.raises(ValueError):
        app.marker(INSTALL, "bad:id")


def test_fold_host():
    assert app.fold_host("GO.Example.COM.") == "go.example.com"
    assert app.fold_host("bücher.example") == "xn--bcher-kva.example"


def test_backoff():
    assert [app.backoff_delay(n) for n in (0, 1, 2, 3, 20)] == [0.0, 1.0, 2.0, 4.0, app.BACKOFF_CAP]


# --- Token check, through the fake ---


def test_verify_token_ok_and_missing_permissions():
    fake = FakeCloudflare()
    account = fake.add_account()
    fake.add_zone("example.com", account)
    assert fake.verify_token() == app.TokenCheck("ok", (), ())
    fake.denied.add("lists")
    assert fake.verify_token().missing == ("Account Rule Lists Write",)


def test_verify_token_invalid():
    fake = FakeCloudflare()
    fake.token_status = "disabled"
    fake.add_account()
    assert fake.verify_token().state == "invalid"


def test_no_test_reaches_the_network(client):
    # Outside `responses`, the conftest guard stops the call before any socket opens
    with pytest.raises(AssertionError, match="real GET"):
        client.lists("acc1")
