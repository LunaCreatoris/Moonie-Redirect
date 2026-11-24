"""An in-memory Cloudflare v4 API for the tests, ported from the 7.0.1 plugin's fake.

`FakeCloudflare` is the app's real `Cloudflare` client whose one HTTP exchange (`_send`) is answered from the state
held here: the client's own paging, retries, parsing and checks all run, and no socket opens. Ids are `fake-<n>`, so
runs are stable. Every call lands in `ledger`. Knobs: `denied` permissions, `fault()` for HTTP errors, 429s and
unreachable answers, `next_op` for a bulk operation that fails, runs or is unknown, `bad_sources`, `token_status`,
`latency` for the seconds of the virtual clock every exchange takes (a slow Cloudflare, with no real sleep).
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import app

TOKEN = "fake-token-0123456789abcdefghijklmnopqrstuv"  # a sentinel: tests scan texts for it
STAMP = "2026-01-15T09:30:00Z"
INSTALL = "0123456789abcdef0123456789abcdef"
OTHER_INSTALL = "fedcba9876543210fedcba9876543210"

# The fake's error codes (Cloudflare's own where they are documented)
INVALID_TOKEN = 1000
AUTH_ERROR = 10000
NOT_PERMITTED = 9109
NO_ROUTE = 7003
BAD_REQUEST = 10001
ITEM_INVALID = 10021
LIST_DUPLICATE = 10014
LISTS_FULL = 10027
LIST_BUSY = 10028
RULES_FULL = 20200
PHASE_TAKEN = 20217
LIST_UNKNOWN = 20218

# Which permission guards which endpoint, for `denied`
ZONES, DNS, LISTS, RULESETS = "zones", "dns", "lists", "rulesets"


class Clock:
    """A monotonic clock that moves only when slept on; `slept` lists every sleep, in seconds."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@dataclass
class Call:
    method: str
    path: str
    query: dict[str, str]
    body: Any
    headers: dict[str, str]


@dataclass
class Fault:
    kind: str  # status, 429, or an unreachable kind (timeout, refused, malformed, ...)
    status: int = 503
    times: int = 1
    method: str | None = None
    path: str | None = None  # a regular expression searched in the path
    retry_after: str | None = "1"
    message: str = "fault injected by the fake"
    not_sent: bool = False


@dataclass
class Op:
    id: str
    account: str
    list_id: str
    kind: str  # upsert, delete
    payload: list[Any]
    status: str = "pending"
    error: str | None = None
    fail: str | None = None
    stuck: bool = False


@dataclass
class State:
    accounts: dict[str, str] = field(default_factory=dict)
    zones: dict[str, dict] = field(default_factory=dict)
    records: dict[str, list[dict]] = field(default_factory=dict)
    lists: dict[str, dict[str, dict]] = field(default_factory=dict)
    rulesets: dict[str, dict[str, dict]] = field(default_factory=dict)
    ops: dict[str, Op] = field(default_factory=dict)


def _error(status: int, code: int, message: str) -> tuple[int, dict, dict]:
    return status, {"success": False, "errors": [{"code": code, "message": message}], "result": None}, {}


def _ok(result: Any, info: dict | None = None) -> tuple[int, dict, dict]:
    envelope = {"success": True, "errors": [], "messages": [], "result": result}
    if info is not None:
        envelope["result_info"] = info
    return 200, envelope, {}


def _int(query: dict, key: str, default: int, low: int, high: int) -> int:
    try:
        value = int(query.get(key, default))
    except ValueError:
        value = default
    return max(low, min(high, value))


class FakeCloudflare(app.Cloudflare):
    def __init__(self, token: str = TOKEN, *, max_lists: int = 5, max_rules: int = 15, max_items: int = 10000):
        self.clock = Clock()
        super().__init__(token, sleep=self.clock.sleep, clock=self.clock)
        self.token = token
        self.token_status = "active"
        self.latency = 0.0  # seconds of the virtual clock each exchange takes
        self.max_lists, self.max_rules, self.max_items = max_lists, max_rules, max_items
        self.denied: set[str] = set()
        self.bad_sources: set[str] = set()  # source_url values a POST of items refuses with 400, naming them
        self.failing_sources: set[str] = set()  # source_url values whose bulk operation ends `failed`
        self.op_polls = 0  # polls a bulk operation answers "running" before it completes
        self.next_op: dict = {}  # fail=<error> or stuck=True for the next bulk operation
        self.state = State()
        self.ledger: list[Call] = []
        self.parallel_writes = 0
        self._faults: list[Fault] = []
        self._counter = 0
        self._polls: dict[str, int] = {}

    # Seeding

    def new_id(self) -> str:
        self._counter += 1
        return f"fake-{self._counter}"

    def add_account(self, name: str = "Main account") -> str:
        account = self.new_id()
        self.state.accounts[account] = name
        self.state.lists[account] = {}
        self.state.rulesets[account] = {}
        return account

    def add_zone(self, name: str, account: str) -> str:
        zone = self.new_id()
        self.state.zones[zone] = {"id": zone, "name": name, "status": "active", "account": account}
        self.state.records[zone] = []
        return zone

    def add_record(self, zone: str, type_: str, name: str, content: str, proxied: bool = True) -> str:
        record = self.new_id()
        self.state.records[zone].append(
            {"id": record, "type": type_, "name": name, "content": content, "proxied": proxied, "ttl": 1}
        )
        return record

    def add_list(self, account: str, name: str = "moonie_redirect", kind: str = "redirect") -> str:
        list_id = self.new_id()
        self.state.lists[account][list_id] = {"id": list_id, "name": name, "kind": kind, "description": "", "items": {}}
        return list_id

    def add_item(
        self,
        account: str,
        list_id: str,
        source: str,
        target: str,
        status: int = 302,
        comment: str | None = None,
        subpath: bool = False,
    ) -> str:
        item = self.new_id()
        redirect = {"source_url": source, "target_url": target, "status_code": status}
        flags = {"include_subdomains": False, "subpath_matching": subpath}
        row = {"id": item, "redirect": redirect | flags} | ({"comment": comment} if comment is not None else {})
        self.state.lists[account][list_id]["items"][item] = row
        return item

    def add_entrypoint(self, account: str, rules: list[dict] | tuple = ()) -> str:
        ruleset = self.new_id()
        stored = [dict(rule) | {"id": self.new_id()} for rule in rules]
        self.state.rulesets[account][ruleset] = {
            "id": ruleset,
            "name": "default",
            "kind": "root",
            "phase": "http_request_redirect",
            "rules": stored,
        }
        return ruleset

    def setup(self, zone_name: str = "example.com") -> tuple[str, str, str]:
        """An account with one zone, our list and our rule: (account, zone, list)."""
        account = self.add_account()
        zone = self.add_zone(zone_name, account)
        list_id = self.add_list(account)
        self.add_entrypoint(account, [app.rule_body()])
        return account, zone, list_id

    # Knobs and reading back

    def fault(self, kind: str, **options: Any) -> Fault:
        fault = Fault(kind, **options)
        self._faults.append(fault)
        return fault

    def items(self, account: str, list_id: str) -> list[dict]:
        return [dict(row) for row in self.state.lists[account][list_id]["items"].values()]

    def sources(self, account: str, list_id: str) -> dict[str, dict]:
        return {row["redirect"]["source_url"]: row for row in self.items(account, list_id)}

    def calls(self, method: str | None = None, path: str | None = None) -> list[Call]:
        return [
            call
            for call in self.ledger
            if (method is None or call.method == method) and (path is None or re.search(path, call.path))
        ]

    def writes(self) -> list[Call]:
        return [call for call in self.ledger if call.method != "GET"]

    # The transport

    def _send(self, method: str, url: str, body: bytes | None) -> tuple[int, bytes, dict]:
        self.clock.now += self.latency
        parts = urlsplit(url)
        root = urlsplit(app.API_ROOT).path.rstrip("/")
        path = parts.path[len(root) :]
        query = dict(parse_qsl(parts.query))
        document = json.loads(body) if body else None
        headers = self._headers(body)
        self.ledger.append(Call(method, path, query, document, headers))
        fault = self._take_fault(method, path)
        if fault is not None:
            if fault.kind == "status":
                status, envelope, extra = _error(fault.status, BAD_REQUEST, fault.message)
            elif fault.kind == "429":
                status, envelope, _ = _error(429, 971, "rate limited by the fake")
                extra = {"Retry-After": fault.retry_after} if fault.retry_after is not None else {}
            elif fault.kind == "malformed":
                return 200, b"{not json", {}
            else:
                raise app.CfUnreachable(fault.kind, not_sent=fault.not_sent)
        else:
            status, envelope, extra = self._route(method, path, query, document, headers)
        return status, json.dumps(envelope).encode("utf-8"), extra

    def _take_fault(self, method: str, path: str) -> Fault | None:
        for fault in self._faults:
            if fault.method not in (None, method) or (fault.path is not None and not re.search(fault.path, path)):
                continue
            fault.times -= 1
            if fault.times <= 0:
                self._faults.remove(fault)
            return fault
        return None

    def _route(self, method: str, path: str, query: dict, body: Any, headers: dict) -> tuple[int, dict, dict]:
        token = headers.get("Authorization", "").removeprefix("Bearer ")
        if path == "/user/tokens/verify" and method == "GET":
            if token != self.token:
                return _error(401, INVALID_TOKEN, "Invalid API Token")
            return _ok({"id": "fake-token", "status": self.token_status})
        if token != self.token or self.token_status != "active":
            return _error(401, AUTH_ERROR, "Authentication error")
        account = r"/accounts/([^/]+)"
        lists = account + r"/rules/lists"
        routes = (
            (r"/accounts", "GET", self._get_accounts),
            (r"/zones", "GET", self._get_zones),
            (r"/zones/([^/]+)/dns_records", "GET", self._get_records),
            (r"/zones/([^/]+)/dns_records", "POST", self._post_record),
            (lists, "GET", self._get_lists),
            (lists, "POST", self._post_list),
            (lists + r"/bulk_operations/([^/]+)", "GET", self._get_op),
            (lists + r"/([^/]+)/items", "GET", self._get_items),
            (lists + r"/([^/]+)/items", "POST", self._post_items),
            (lists + r"/([^/]+)/items", "DELETE", self._delete_items),
            (account + r"/rulesets/phases/http_request_redirect/entrypoint", "GET", self._get_entrypoint),
            (account + r"/rulesets", "POST", self._post_ruleset),
            (account + r"/rulesets/([^/]+)/rules", "POST", self._post_rule),
        )
        for pattern, verb, handler in routes:
            match = re.fullmatch(pattern, path)
            if match and verb == method:
                return handler(*match.groups(), query=query, body=body)
        return _error(404 if method in ("GET", "POST", "DELETE") else 405, NO_ROUTE, "No route for that URI")

    def _denied(self, permission: str, account: str | None = None):
        if permission in self.denied or (account is not None and account not in self.state.accounts):
            return _error(403, NOT_PERMITTED, "Unauthorized to access requested resource")
        return None

    @staticmethod
    def _page(rows: list, query: dict, low: int, high: int):
        per_page = _int(query, "per_page", 20, low, high)
        page = _int(query, "page", 1, 1, 10**6)
        chunk = rows[(page - 1) * per_page : page * per_page]
        info = {"page": page, "per_page": per_page, "count": len(chunk), "total_count": len(rows)}
        return _ok(chunk, info | {"total_pages": max(1, -(-len(rows) // per_page))})

    def _list_row(self, row: dict) -> dict:
        return {k: row[k] for k in ("id", "name", "kind", "description")} | {"num_items": len(row["items"])}

    def _get_accounts(self, *, query, body):
        rows = [{"id": a, "name": n, "type": "standard"} for a, n in self.state.accounts.items()]
        return self._page(rows, query, 5, 50)

    def _get_zones(self, *, query, body):
        if refused := self._denied(ZONES):
            return refused
        rows = [
            {
                "id": z["id"],
                "name": z["name"],
                "status": z["status"],
                "account": {"id": z["account"], "name": self.state.accounts[z["account"]]},
            }
            for z in self.state.zones.values()
        ]
        return self._page(rows, query, 5, 50)

    def _get_records(self, zone, *, query, body):
        if refused := self._denied(DNS):
            return refused
        if zone not in self.state.zones:
            return _error(404, NO_ROUTE, "Invalid zone identifier")
        name = query.get("name")
        rows = [dict(r) for r in self.state.records[zone] if name is None or r["name"] == name]
        return self._page(rows, query, 5, 5000)

    def _post_record(self, zone, *, query, body):
        if refused := self._denied(DNS):
            return refused
        row = self.state.zones.get(zone)
        if row is None:
            return _error(404, NO_ROUTE, "Invalid zone identifier")
        if not isinstance(body, dict) or set(body) != {"type", "name", "content", "proxied", "ttl", "comment"}:
            return _error(400, BAD_REQUEST, "unexpected record body")
        if not body["name"].endswith("." + row["name"]):
            return _error(400, BAD_REQUEST, "record name outside the zone")
        record = {"id": self.new_id(), **body}
        self.state.records[zone].append(record)
        return _ok(dict(record))

    def _get_lists(self, account, *, query, body):
        if refused := self._denied(LISTS, account):
            return refused
        return _ok([self._list_row(row) for row in self.state.lists[account].values()])

    def _post_list(self, account, *, query, body):
        if refused := self._denied(LISTS, account):
            return refused
        lists = self.state.lists[account]
        if any(row["name"] == body.get("name") for row in lists.values()):
            return _error(400, LIST_DUPLICATE, "a list with that name already exists")
        if len(lists) >= self.max_lists:
            return _error(400, LISTS_FULL, "the maximum number of lists is reached")
        list_id = self.add_list(account, body["name"], body["kind"])
        lists[list_id]["description"] = body.get("description", "")
        return _ok(self._list_row(lists[list_id]))

    def _list(self, account, list_id):
        if refused := self._denied(LISTS, account):
            return None, refused
        row = self.state.lists[account].get(list_id)
        return (row, None) if row is not None else (None, _error(404, NO_ROUTE, "list not found"))

    def _get_items(self, account, list_id, *, query, body):
        row, refused = self._list(account, list_id)
        if refused:
            return refused
        per_page = _int(query, "per_page", 25, 1, 500)
        start = int(query.get("cursor", "c0")[1:])
        rows = list(row["items"].values())[start : start + per_page]
        info: dict = {"cursors": {}}
        if start + per_page < len(row["items"]):
            info["cursors"]["after"] = f"c{start + per_page}"
        return _ok(rows, info)

    def _busy(self, list_id: str):
        if any(op.list_id == list_id and op.status in ("pending", "running") for op in self.state.ops.values()):
            self.parallel_writes += 1
            status, envelope, _ = _error(429, LIST_BUSY, "a bulk operation of this list is still pending")
            return status, envelope, {"Retry-After": "1"}
        return None

    def _post_items(self, account, list_id, *, query, body):
        row, refused = self._list(account, list_id)
        if refused:
            return refused
        if busy := self._busy(list_id):
            return busy
        bad = [item["redirect"]["source_url"] for item in body if item["redirect"]["source_url"] in self.bad_sources]
        if bad:
            return _error(400, ITEM_INVALID, f"invalid source_url: {bad[0]}")
        return self._new_op(account, list_id, "upsert", body)

    def _delete_items(self, account, list_id, *, query, body):
        row, refused = self._list(account, list_id)
        if refused:
            return refused
        if busy := self._busy(list_id):
            return busy
        return self._new_op(account, list_id, "delete", [item["id"] for item in body["items"]])

    def _new_op(self, account: str, list_id: str, kind: str, payload: list):
        knobs, self.next_op = self.next_op, {}
        op = Op(self.new_id(), account, list_id, kind, payload, fail=knobs.get("fail"), stuck=knobs.get("stuck", False))
        self.state.ops[op.id] = op
        self._polls[op.id] = self.op_polls
        if knobs.get("unknown"):
            del self.state.ops[op.id]  # Cloudflare forgot it: polling answers 404
        elif not op.stuck and self.op_polls <= 0:
            self._complete(op)
        return _ok({"operation_id": op.id})

    def _complete(self, op: Op) -> None:
        if op.fail is not None:
            op.status, op.error = "failed", op.fail
            return
        if op.kind == "upsert" and any(item["redirect"]["source_url"] in self.failing_sources for item in op.payload):
            op.status, op.error = "failed", "an item was rejected by the fake"
            return
        items = self.state.lists[op.account][op.list_id]["items"]
        if op.kind == "delete":
            for item in op.payload:
                items.pop(item, None)
        else:
            total = sum(len(row["items"]) for row in self.state.lists[op.account].values())
            by_source = {row["redirect"]["source_url"]: key for key, row in items.items()}
            fresh = [item for item in op.payload if item["redirect"]["source_url"] not in by_source]
            if total + len(fresh) > self.max_items:
                op.status, op.error = "failed", "the account's maximum number of list items is exceeded"
                return
            for item in op.payload:
                # A POST at a source the list holds replaces that item, keeping its id (assumed, not
                # measured against Cloudflare)
                key = by_source.get(item["redirect"]["source_url"]) or self.new_id()
                items[key] = {"id": key, **item}
                by_source[item["redirect"]["source_url"]] = key
        op.status = "completed"

    def finish_ops(self) -> None:
        """Every operation still running completes now, as Cloudflare would in the background."""
        for op in self.state.ops.values():
            if op.status in ("pending", "running"):
                op.stuck = False
                self._complete(op)

    def _get_op(self, account, op_id, *, query, body):
        if refused := self._denied(LISTS, account):
            return refused
        op = self.state.ops.get(op_id)
        if op is None or op.account != account:
            return _error(404, NO_ROUTE, "operation not found")
        if op.status in ("pending", "running") and not op.stuck:
            if self._polls[op_id] > 0:
                self._polls[op_id] -= 1
                op.status = "running"
            else:
                self._complete(op)
        result = {"id": op.id, "status": op.status}
        if op.status == "failed":
            result["error"] = op.error
        return _ok(result)

    def _entrypoint(self, account: str) -> dict | None:
        return next(iter(self.state.rulesets[account].values()), None)

    def _get_entrypoint(self, account, *, query, body):
        if refused := self._denied(RULESETS, account):
            return refused
        row = self._entrypoint(account)
        if row is None:
            return _error(404, NO_ROUTE, "Could not find entrypoint ruleset in the http_request_redirect phase")
        return _ok(dict(row))

    def _post_ruleset(self, account, *, query, body):
        if refused := self._denied(RULESETS, account):
            return refused
        if self._entrypoint(account) is not None:
            return _error(400, PHASE_TAKEN, "an entrypoint ruleset already exists for this phase")
        for rule in body.get("rules", []):
            name = rule["action_parameters"]["from_list"]["name"]
            if not any(row["name"] == name for row in self.state.lists[account].values()):
                return _error(400, LIST_UNKNOWN, f"the list {name} does not exist")
        ruleset = self.add_entrypoint(account, body.get("rules", []))
        return _ok(dict(self.state.rulesets[account][ruleset]))

    def _post_rule(self, account, ruleset, *, query, body):
        if refused := self._denied(RULESETS, account):
            return refused
        row = self.state.rulesets[account].get(ruleset)
        if row is None:
            return _error(404, NO_ROUTE, "ruleset not found")
        if len(row["rules"]) >= self.max_rules:
            return _error(400, RULES_FULL, "the ruleset holds the maximum number of rules")
        row["rules"].append(dict(body) | {"id": self.new_id()})
        return _ok(dict(row))
