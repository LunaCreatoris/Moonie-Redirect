# Copyright (C) 2026 LunaCreatoris
# SPDX-License-Identifier: AGPL-3.0-or-later

"""moonie-redirect: fixed links that answer a redirect to a target which can change, so links and printed QR codes keep
working. It never serves or proxies the target.

- Public: `GET|HEAD /redirect/<slug>` and `/links/<id>`, the same path shapes as 7.0.1, so printed codes keep working.
- Admin UI under `/admin`: the 7.0.1 pages, run by the browser from `static/ui`, on the JSON API with the session cookie
  (one password, signed session cookie, CSRF token on every change).
- JSON API under `/api` (scoped bearer keys, or the admin session); the settings under `/api/settings`, session only.
- `python app.py import-v7 <old.db>` copies the rows of a 7.0.1 database.
- `python app.py reset-password` drops the password set in the settings and ends every session.

Everything is in this one file on purpose. Logs carry the path and the status of a visit, never its target.
"""

import base64
import errno
import hashlib
import hmac
import http.client
import ipaddress
import json
import logging
import os
import posixpath
import random
import re
import secrets
import socket
import sqlite3
import ssl
import sys
import threading
import time
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from ipaddress import IPv6Address
from pathlib import Path
from urllib.parse import quote, unquote, urlencode, urlsplit
from xml.parsers import expat

import idna
import requests
import segno
import urllib3
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request, session, url_for

VERSION = "9.3.1"
log = logging.getLogger("moonie-redirect")

TABLE = "redirect_links"
COLUMNS = (
    "id",
    "kind",
    "link_host",
    "slug",
    "name",
    "target",
    "http_status",
    "expires_on",
    "design",
    "created_at",
    "updated_at",
)
SCHEMA = f"""CREATE TABLE IF NOT EXISTS {TABLE} (
    id          TEXT    PRIMARY KEY,
    kind        TEXT    NOT NULL DEFAULT 'link' CHECK (kind IN ('link', 'nano', 'qrcode')),
    link_host   TEXT    CHECK (link_host IN ('ip', 'hostname')),
    slug        TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    target      TEXT    NOT NULL,
    http_status INTEGER NOT NULL DEFAULT 302 CHECK (http_status IN (301, 302)),
    expires_on  TEXT,
    design      TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
)"""
# PRAGMA user_version of a database this app wrote: 1 is the table of 8.0.0, 2 adds the Cloudflare address and state,
# 3 the admin sessions, 4 the settings (plain values, sealed secrets, API keys) and the webhook's outbox
SCHEMA_VERSION = 4
# Version 2: the columns added to the table, each with a default, so 8.0.0's INSERT still works on a migrated database
CF_COLUMNS = {
    "address": "TEXT",  # NULL: the LAN base URL; else a host of cf_hosts
    "rev": "INTEGER NOT NULL DEFAULT 1",
    "cf_synced_rev": "INTEGER NOT NULL DEFAULT 0",
    "cf_state": "TEXT CHECK (cf_state IN ('pending', 'active', 'error', 'expired'))",  # NULL when address is NULL
    "cf_error": "TEXT",  # JSON {"code", "detail"}
}
CF_SCHEMA = (
    # One list item per (host, path): the database refuses two links on one source
    f"""CREATE UNIQUE INDEX IF NOT EXISTS redirect_links_source ON {TABLE}
        (address, CASE kind WHEN 'link' THEN slug ELSE id END) WHERE address IS NOT NULL""",
    "CREATE TABLE IF NOT EXISTS cf_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS cf_accounts (
        id TEXT PRIMARY KEY, name TEXT NOT NULL,
        list_id TEXT, ruleset_id TEXT, rule_id TEXT,
        op_kind TEXT CHECK (op_kind IN ('upsert', 'delete')), op_items TEXT, op_id TEXT, op_started_at TEXT,
        hold_until TEXT, items_used INTEGER, lists_used INTEGER, quota_checked_at TEXT,
        last_sync_at TEXT, last_error TEXT)""",
    """CREATE TABLE IF NOT EXISTS cf_hosts (
        host TEXT PRIMARY KEY, zone_id TEXT NOT NULL, zone_name TEXT NOT NULL,
        account_id TEXT NOT NULL REFERENCES cf_accounts(id), record_id TEXT,
        created_by_us INTEGER NOT NULL CHECK (created_by_us IN (0, 1)),
        fallback TEXT,
        fallback_rev INTEGER NOT NULL DEFAULT 0, fallback_synced_rev INTEGER NOT NULL DEFAULT 0,
        fallback_state TEXT CHECK (fallback_state IN ('pending', 'active', 'error')), fallback_error TEXT,
        created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS cf_removals (
        id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, source TEXT NOT NULL,
        marker TEXT NOT NULL,
        remote_id TEXT,
        reason TEXT NOT NULL CHECK (reason IN ('deleted', 'moved', 'expired', 'fallback', 'resync')),
        after_link TEXT,
        queued_at TEXT NOT NULL)""",
)

# Version 3: one row per admin session signed in. The cookie names its row; a logout deletes it, so a copied cookie dies
# with it, and the login time stored here ends the session SESSION_HOURS after the login however much it is used
SESSIONS_SCHEMA = "CREATE TABLE IF NOT EXISTS admin_sessions (id TEXT PRIMARY KEY, started_at REAL NOT NULL)"
SESSION_HOURS = 12

# Version 4: what the Settings page keeps (D21 to D28). Nothing moves: 9.1 opens such a database and ignores them
SETTINGS_SCHEMA = (
    # admin_password, cloudflare_item_limit, webhook_url, webhook_events (JSON list), webhook_disabled_reason,
    # token_file_last_used
    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)",
    # Values the app must read back, sealed with the store key (D23)
    """CREATE TABLE IF NOT EXISTS secrets (
        name TEXT PRIMARY KEY CHECK (name IN ('cloudflare_token', 'webhook_secret')),
        key_id TEXT NOT NULL, nonce BLOB NOT NULL, value BLOB NOT NULL, updated_at TEXT NOT NULL)""",
    # The SHA-256 of each key's token, never the token (D25)
    """CREATE TABLE IF NOT EXISTS api_keys (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, prefix TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
        scopes TEXT NOT NULL, created_at TEXT NOT NULL, last_used_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS webhook_outbox (
        id TEXT PRIMARY KEY, event TEXT NOT NULL, body BLOB NOT NULL, created_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'failed')),
        attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT NOT NULL,
        last_status INTEGER, last_error TEXT, finished_at TEXT)""",
    "CREATE INDEX IF NOT EXISTS webhook_outbox_due ON webhook_outbox (status, next_attempt_at)",
)
SECRET_NAMES = ("cloudflare_token", "webhook_secret")

KINDS = ("link", "nano", "qrcode")
# The admin pages static/ui/shell.js draws, by the last part of their address
ADMIN_PAGES = ("links", "nanourls", "qrcodes", "settings")
ADMIN_HOME = "/admin/links"
# The Cloudflare page is the Cloudflare tab of Settings since 9.3.0 (D29): its address, bookmarked, goes there
CLOUDFLARE_TAB = "/admin/settings?tab=cloudflare"
# The path of a NanoURL or a QR code is `<section>/<name>`; a link typed by hand cannot start with these, in any case
NAMED_SECTION = {"nano": "NanoURL", "qrcode": "QRcodes"}
RESERVED = ("api", "nanourl", "qrcodes")
REDIRECT_PREFIX, LINKS_PREFIX = "/redirect/", "/links/"
# Letters and digits without the ones people confuse (0 O o 1 l I), as 7.0.1 drew them
CODE_ALPHABET = "23456789abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LENGTH = 8
# A suggested slug: 6 characters of the same alphabet, as 7.0.1 drew them
SLUG_LENGTH = 6
# A suggestion already taken is drawn again, this many times at most
DRAWS = 5
# What a preview of a QR code not yet saved holds in place of its id: as long as a real one, so the drawing has its size
PREVIEW_ID = "Preview0"
CODE = re.compile(r"[A-Za-z0-9]{1,32}")
SEGMENT = re.compile(r"[A-Za-z0-9._-]+")
NOT_IN_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")
ASCII_HOST = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.?")
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
LOGO = re.compile(r"data:image/(png|jpeg|webp|svg\+xml);base64,([A-Za-z0-9+/]+={0,2})")
SLUG_MAX, NAME_MAX, TARGET_MAX = 255, 100, 2048
# Characters that draw nothing although Unicode does not file them under C: the combining grapheme joiner, the Hangul
# fillers, the Khmer inherent vowels and the braille blank. Variation selectors stay allowed: an emoji needs
# U+FE0F
INVISIBLE = frozenset("\u034f\u115f\u1160\u17b4\u17b5\u2800\u3164\uffa0")
TOKEN_MIN = 32
SESSION_KEY_FILE, SESSION_KEY_BYTES = "session.key", 32
LOGO_MAX_BYTES = 256 * 1024
MAX_LOGGED = 300
# A login attempt within this many seconds of a failed one is answered 429 at once, by every thread of the process
LOGIN_BRAKE = 1.0
_last_failure = float("-inf")
_failure_lock = threading.Lock()
# What the 7.0.1 server left unquoted in a Location besides letters, digits and `_.-~`: a target is stored in this form,
# so the Location sent is the stored target, byte for byte, as 7.0.1 sent it
LOCATION_SAFE = ":/%#?=@[]!$&'()*+,;"
NO_STORE = {"Cache-Control": "no-store"}
SVG_POLICY = "default-src 'none'; img-src data:; frame-ancestors 'none'"
# The admin runs modules from static/ui alone; none of them writes HTML, so the policy closes every HTML sink as well
PAGE_POLICY = (
    "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; font-src 'self';"
    " img-src 'self' data:; worker-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none';"
    " require-trusted-types-for 'script'; trusted-types 'none'"
)
# What a change through the session may come from: the browser says so in Sec-Fetch-Site, or says nothing (an old one)
SAME_ORIGIN = (None, "same-origin")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class Invalid(ValueError):
    """A field breaks a rule: `field` says which, the message says why (in English, shown as it is)."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


# --- Validation ----------------------------------------------------------------------------------------------------


def check_slug(value: str, field: str = "slug") -> str:
    slug = value.strip()
    if not slug:
        raise Invalid(field, "required")
    if len(slug) > SLUG_MAX:
        raise Invalid(field, f"at most {SLUG_MAX} characters")
    segments = slug.split("/")
    # Three refusals, as 7.0.1 told them apart: an empty segment, a dot segment, any other character
    if "" in segments:
        raise Invalid(field, "no empty segment: no '/' at either end, no '//'")
    if any(s in (".", "..") for s in segments):
        raise Invalid(field, "no '.' or '..' segment")
    if not all(SEGMENT.fullmatch(s) for s in segments):
        raise Invalid(field, "letters, digits, '.', '_', '-' in '/'-separated segments")
    return slug


def is_valid_slug(value: str) -> bool:
    try:
        return check_slug(value) == value
    except Invalid:
        return False


def check_user_slug(value: str) -> str:
    slug = check_slug(value)
    if slug.split("/", 1)[0].casefold() in RESERVED:
        raise Invalid("slug", "starts with a reserved section (Api, NanoURL, QRcodes)")
    return slug


def check_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise Invalid("name", "required")
    if len(name) > NAME_MAX:
        raise Invalid("name", f"at most {NAME_MAX} characters")
    # Unicode category C (controls, format characters that disguise a text, private use, unassigned), the blanks that
    # Unicode files as letters, symbols or marks, and a name with nothing to see: each shows an empty or look-alike name
    if any(unicodedata.category(c).startswith("C") or c in INVISIBLE for c in name) or not any(
        unicodedata.category(c)[0] in "LNPS" for c in name
    ):
        raise Invalid("name", "holds control or invisible characters")
    return name


def slug_from_name(section: str, name: str) -> str:
    """`<section>/<name>` with accents dropped and other characters made dashes, as 7.0.1 made it."""
    unmarked = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.category(c).startswith("M"))
    segment = re.sub(r"-{2,}", "-", NOT_IN_SEGMENT.sub("-", unmarked).strip("-."))
    try:
        return check_slug(f"{section}/{segment}")
    except Invalid:
        raise Invalid("name", "makes no usable path") from None


def _ascii_host(host: str) -> str:
    if host.startswith("[") and host.endswith("]") and "%" not in host:
        try:
            IPv6Address(host[1:-1])
            return host
        except ValueError:
            pass
        raise Invalid("target", "invalid host")
    try:
        ascii_host = host if host.isascii() else idna.encode(host, uts46=True).decode("ascii")
    except idna.IDNAError:
        raise Invalid("target", "invalid host") from None
    if not ASCII_HOST.fullmatch(ascii_host):
        raise Invalid("target", "invalid host")
    return ascii_host


def check_target(value: str) -> str:
    """An absolute http(s) URL with a valid host, stored ASCII and quoted as it will be sent: anything else, such as
    `javascript:` or a relative path, is refused."""
    target = value.strip()
    if not target:
        raise Invalid("target", "required")
    if len(target) > TARGET_MAX:
        raise Invalid("target", f"at most {TARGET_MAX} characters")
    if any(ord(c) < 32 or ord(c) == 127 or c.isspace() for c in target):
        raise Invalid("target", "holds spaces or control characters")
    try:
        parts = urlsplit(target)
        _ = parts.port  # reading the port is what refuses an invalid one
    except ValueError:
        raise Invalid("target", "not a valid URL") from None
    scheme = parts.scheme
    if scheme.lower() not in ("http", "https") or not target[len(scheme) :].startswith("://") or not parts.netloc:
        raise Invalid("target", "must be an http or https URL")
    # A browser ends the host at a backslash, so what would look like a user here is the host it opens
    if "\\" in parts.netloc:
        raise Invalid("target", "invalid host")
    user, at, place = parts.netloc.rpartition("@")
    cut = place.rfind(":")
    host, port = (place[:cut], place[cut:]) if cut > place.rfind("]") else (place, "")
    rest = target[len(scheme) + 3 + len(parts.netloc) :]
    target = quote(f"{scheme}://{user}{at}{_ascii_host(host)}{port}{rest}", safe=LOCATION_SAFE)
    if len(target) > TARGET_MAX:
        raise Invalid("target", f"at most {TARGET_MAX} characters once encoded")
    return target


def check_http_status(value: object) -> int:
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value)
    if isinstance(value, bool) or value not in (301, 302):
        raise Invalid("http_status", "301 or 302")
    return value  # type: ignore[return-value]


def check_expires_on(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not DAY.fullmatch(value):
        raise Invalid("expires_on", "YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise Invalid("expires_on", "not a real date") from None
    return value


@dataclass(frozen=True)
class Design:
    """How a QR code looks: the fields and defaults of 7.0.1, so stored designs read the same."""

    color: str = "#1b1f24"
    eye_color: str = "#1b1f24"
    background: str = "#ffffff"  # or "transparent"
    module_style: str = "square"  # square, rounded, dots
    eye_style: str = "square"  # square, rounded, circle
    logo: str | None = None  # a data URI with its image in base64
    logo_size: float = 0.22  # side of the logo, as a share of the code's side
    margin: int = 4  # blank border, in modules


def _luminance(color: str) -> float:
    def channel(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _logo_ok(kind: str, content: bytes) -> bool:
    if kind == "png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if kind == "jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if kind == "webp":
        return content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return _is_svg(content)


def _is_svg(content: bytes) -> bool:
    """One well-formed XML document whose root is `svg` in the SVG namespace. An entity can only be declared in a
    DOCTYPE, so refusing a DOCTYPE leaves nothing to expand and nothing to fetch for whoever parses the logo later."""
    roots: list[str] = []

    def refuse_doctype(*_details: object) -> None:
        raise ValueError("a logo has no DOCTYPE")

    def element(name: str, _attributes: object) -> None:
        if not roots:
            roots.append(name)

    parser = expat.ParserCreate(namespace_separator=" ")
    parser.StartDoctypeDeclHandler = refuse_doctype
    parser.StartElementHandler = element
    try:
        parser.Parse(content, True)
    # ValueError also covers a declared encoding that cannot decode, and LookupError one that does not exist
    except (expat.ExpatError, ValueError, LookupError):
        return False
    return roots == ["http://www.w3.org/2000/svg svg"]


def check_design(value: object, *, open_logo: bool = True) -> Design:
    """The clean design, or Invalid("design", ...). Unknown fields are ignored, absent ones take their default. With
    `open_logo` False, a logo is checked by its shape alone, never decoded nor parsed: for designs already checked
    whole when they were written."""
    if not isinstance(value, dict):
        raise Invalid("design", "must be an object")
    d = {k: value[k] for k in Design.__dataclass_fields__ if k in value}
    for key in ("color", "eye_color", "background"):
        if key in d and not (key == "background" and d[key] == "transparent"):
            if not isinstance(d[key], str) or not HEX_COLOR.fullmatch(d[key]):
                raise Invalid("design", f"{key} must be #rrggbb")
            d[key] = d[key].lower()
    if d.get("module_style", "square") not in ("square", "rounded", "dots"):
        raise Invalid("design", "module_style is square, rounded or dots")
    if d.get("eye_style", "square") not in ("square", "rounded", "circle"):
        raise Invalid("design", "eye_style is square, rounded or circle")
    margin = d.get("margin", 4)
    if isinstance(margin, bool) or not isinstance(margin, int) or not 0 <= margin <= 10:
        raise Invalid("design", "margin is a whole number from 0 to 10")
    size = d.get("logo_size", 0.22)
    if isinstance(size, bool) or not isinstance(size, (int, float)) or not 0.1 <= size <= 0.3:
        raise Invalid("design", "logo_size is from 0.1 to 0.3")
    d["logo_size"] = float(size)
    logo = d.get("logo")
    if logo is not None:
        match = LOGO.fullmatch(logo) if isinstance(logo, str) else None
        if match and not open_logo:
            return _checked_rest(d)
        try:
            content = base64.b64decode(match.group(2), validate=True) if match else b""
        except ValueError:
            content = b""
        if len(content) > LOGO_MAX_BYTES:
            raise Invalid("design", "logo is at most 256 KiB")
        if not match or not _logo_ok(match.group(1), content):
            raise Invalid("design", "logo is a PNG, JPEG, WebP or SVG data URI")
    return _checked_rest(d)


def _checked_rest(d: dict) -> Design:
    design = Design(**d)
    if design.background != "transparent":
        if min(contrast(design.color, design.background), contrast(design.eye_color, design.background)) < 3.0:
            raise Invalid("design", "colours need a contrast of 3:1 with the background to scan")
    return design


def read_design(stored: str | None, *, open_logo: bool = True) -> Design | None:
    """The design of a row (defaults when none), or None when what is stored breaks the rules. `open_logo` as in
    check_design."""
    try:
        return check_design({} if stored is None else json.loads(stored), open_logo=open_logo)
    except (ValueError, TypeError, RecursionError):
        return None


def check_fields(kind: str, data: dict, *, creating: bool) -> dict:
    """The clean values of a create (every field, defaults filled) or of an update (the fields given). Raises a dict of
    field -> message when any field is refused."""
    values: dict = {}
    errors: dict[str, str] = {}
    rules = {"name": check_name, "target": check_target}
    if kind == "link":
        rules |= {"slug": check_user_slug, "http_status": check_http_status, "expires_on": check_expires_on}
    if kind == "qrcode":
        rules["design"] = lambda v: json.dumps(asdict(check_design(v)))
    for field, rule in rules.items():
        if field not in data:
            if creating and field in ("slug", "name", "target"):
                errors[field] = "required"
            continue
        value = data[field]
        try:
            if field in ("slug", "name", "target") and not isinstance(value, str):
                raise Invalid(field, "must be a string")
            values[field] = rule(value)
        except Invalid as refused:
            errors[field] = str(refused)
    if kind != "link" and "name" in values:
        try:
            values["slug"] = slug_from_name(NAMED_SECTION[kind], values["name"])
        except Invalid as refused:
            errors["name"] = str(refused)
    if errors:
        raise InvalidFields(errors)
    if creating:
        defaults = {"http_status": 302, "expires_on": None, "design": None, "link_host": None}
        if kind != "link":
            defaults["link_host"] = "hostname"
        if kind == "qrcode":
            defaults["design"] = json.dumps(asdict(Design()))
        values = defaults | values
    return values


class InvalidFields(Exception):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__(errors)
        self.errors = errors


# --- QR codes ------------------------------------------------------------------------------------------------------
# segno computes the matrix; the drawing is ours so modules and eyes can take their own style. Coordinates are in
# modules and every number is written the same way, so one design and one link always give the same bytes.

EYE = 7


def _n(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _rounded_square(x: float, y: float, s: float, r: float) -> str:
    if r == 0:
        return f"M{_n(x)} {_n(y)}h{_n(s)}v{_n(s)}h-{_n(s)}z"
    a, e = f"a{_n(r)} {_n(r)} 0 0 1", _n(s - 2 * r)
    return (
        f"M{_n(x + r)} {_n(y)}h{e}{a} {_n(r)} {_n(r)}v{e}{a} -{_n(r)} {_n(r)}h-{e}{a} -{_n(r)} -{_n(r)}"
        f"v-{e}{a} {_n(r)} -{_n(r)}z"
    )


def _eye(x: int, y: int, style: str) -> str:
    """A finder pattern: a 7x7 ring and a 3x3 center, as one even-odd path."""
    if style == "circle":
        cx, cy = x + 3.5, y + 3.5
        return "".join(
            f"M{_n(cx - r)} {_n(cy)}a{_n(r)} {_n(r)} 0 1 0 {_n(2 * r)} 0a{_n(r)} {_n(r)} 0 1 0 -{_n(2 * r)} 0z"
            for r in (3.5, 2.5, 1.5)
        )
    radii = (2.0, 1.4, 0.9) if style == "rounded" else (0.0, 0.0, 0.0)
    return "".join(_rounded_square(x + i, y + i, 7 - 2 * i, radii[i]) for i in range(3))


def _modules(cells: list[tuple[int, int]], style: str) -> str:
    if style == "rounded":
        return "".join(f'<rect x="{x}.05" y="{y}.05" width=".9" height=".9" rx=".3"/>' for x, y in cells)
    if style == "dots":
        return "".join(f'<circle cx="{x}.5" cy="{y}.5" r=".45"/>' for x, y in cells)
    # Square: each run of dark modules on a row is one rectangle
    runs, i = [], 0
    rows = sorted(cells, key=lambda c: (c[1], c[0]))
    while i < len(rows):
        x, y = rows[i]
        length = 1
        while i + length < len(rows) and rows[i + length] == (x + length, y):
            length += 1
        runs.append(f"M{x} {y}h{length}v1h-{length}z")
        i += length
    return f'<path d="{"".join(runs)}"/>'


def render_svg(data: str, design: Design) -> str:
    """The QR code of `data` as a standalone SVG. Error correction as 7.0.1: H with a logo, which hides modules, else
    M."""
    qr = segno.make(data, error="h" if design.logo else "m", micro=False, boost_error=False)
    matrix = qr.matrix
    size = len(matrix)
    area = None
    if design.logo:
        side = round(size * design.logo_size)
        side += (size - side) % 2
        start = (size - side) // 2
        area = (start, side)

    def drawn(x: int, y: int) -> bool:
        in_eye = (x < EYE and y < EYE) or (x >= size - EYE and y < EYE) or (x < EYE and y >= size - EYE)
        in_logo = area is not None and area[0] <= x < area[0] + area[1] and area[0] <= y < area[0] + area[1]
        return not in_eye and not in_logo

    cells = sorted(((x, y) for y, row in enumerate(matrix) for x, dark in enumerate(row) if dark and drawn(x, y)))
    m = design.margin
    full = size + 2 * m
    crisp = ' shape-rendering="crispEdges"' if design.module_style == design.eye_style == "square" else ""
    size_attrs = f'viewBox="0 0 {full} {full}" width="{full * 10}" height="{full * 10}"'
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" {size_attrs}{crisp}>']
    if design.background != "transparent":
        parts.append(f'<rect width="{full}" height="{full}" fill="{design.background}"/>')
    parts.append(
        f'<g transform="translate({m} {m})"><g fill="{design.color}">{_modules(cells, design.module_style)}</g>'
    )
    eyes = "".join(_eye(x, y, design.eye_style) for x, y in ((0, 0), (size - EYE, 0), (0, size - EYE)))
    parts.append(f'<path fill="{design.eye_color}" fill-rule="evenodd" d="{eyes}"/>')
    if area is not None:
        inset = 1 if area[1] > 4 else 0
        pos, side = area[0] + inset, area[1] - 2 * inset
        parts.append(
            f'<image href="{design.logo}" x="{pos}" y="{pos}" width="{side}" height="{side}"'
            ' preserveAspectRatio="xMidYMid meet"/>'
        )
    parts.append("</g></svg>")
    return "".join(parts)


# --- Storage -------------------------------------------------------------------------------------------------------


def draw_code(length: int) -> str:
    """`length` random characters of CODE_ALPHABET: an id, or a suggested slug."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class SlugTaken(Exception):
    """The path is taken. `field` says which field to change: `slug`, or `address` when the source on that Cloudflare
    host is another link's."""

    def __init__(self, slug: str = "", field: str = "slug") -> None:
        super().__init__(slug)
        self.field = field


class QuotaFull(Exception):
    """The Cloudflare account of that address has no list item left for one more link."""


def link_source(address: str | None, kind: str, slug: str, id_: str) -> str | None:
    """The source of a link's list item: `<host>/<slug>` for a link, `<host>/<id>` for a NanoURL or a QR code. None
    on the LAN."""
    if address is None:
        return None
    return f"{address}/{slug if kind == 'link' else id_}"


def well_known(kind: str, slug: str, address: str | None) -> bool:
    """`.well-known` at a Cloudflare host's root is where certificates and security contacts are read: no link answers
    there, in any case."""
    return address is not None and kind == "link" and slug.split("/", 1)[0].casefold() == ".well-known"


def fallback_source(host: str) -> str:
    """The source of a host's page for unknown paths: its root, which subpath matching extends to every path."""
    return f"{host}/"


def error_text(code: str, detail: str | None = None) -> str:
    """An error as the tables keep it: JSON `{"code", "detail"}`, never a target or the token."""
    return json.dumps({"code": code, "detail": detail or None}, separators=(",", ":"))


class Store:
    """The table, through the standard library. One connection per call: SQLite opens in microseconds."""

    def __init__(self, path: Path, *, item_limit: int = 10000) -> None:
        self.path = path
        self.default_item_limit = item_limit  # MOONIE_REDIRECT_CLOUDFLARE_ITEM_LIMIT, or the free plan's 10 000
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Every step not yet run, in order, inside the caller's transaction; each one may run again harmlessly."""
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            conn.execute(SCHEMA)  # a fresh database, or one of 8.0.0, which never set a version
        if version < 2:
            have = {row["name"] for row in conn.execute(f"PRAGMA table_info({TABLE})")}
            for name, declaration in CF_COLUMNS.items():
                if name not in have:
                    conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN {name} {declaration}")
            for statement in CF_SCHEMA:
                conn.execute(statement)
        if version < 3:
            conn.execute(SESSIONS_SCHEMA)
        if version < 4:
            for statement in SETTINGS_SCHEMA:
                conn.execute(statement)
        if version < SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            conn = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True, timeout=5)
        else:
            conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """One write transaction, taken at once: committed when the block ends, rolled back when it raises."""
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            yield conn

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect(readonly=True)) as conn:
            yield conn

    def hop(self, column: str, value: str) -> sqlite3.Row | None:
        """What a visit needs, on a read-only connection: a visit never writes."""
        with closing(self._connect(readonly=True)) as conn:
            query = f"SELECT target, http_status, expires_on FROM {TABLE} WHERE {column} = ?"
            return conn.execute(query, (value,)).fetchone()

    def ping(self) -> None:
        with closing(self._connect(readonly=True)) as conn:
            conn.execute(f"SELECT 1 FROM {TABLE} LIMIT 1").fetchall()

    def count(self) -> int:
        """The number of links of every kind, without reading one row."""
        with closing(self._connect(readonly=True)) as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]

    def open_session(self, started_at: float) -> str:
        """A new admin session's id. The sessions already over are dropped on the way."""
        id_ = secrets.token_urlsafe(32)
        with self.write() as conn:
            conn.execute("DELETE FROM admin_sessions WHERE started_at <= ?", (started_at - SESSION_HOURS * 3600,))
            conn.execute("INSERT INTO admin_sessions (id, started_at) VALUES (?, ?)", (id_, started_at))
        return id_

    def session_alive(self, id_: object, now: float) -> bool:
        """Whether the session `id_` is signed in: not logged out, and started less than SESSION_HOURS before `now`."""
        if not isinstance(id_, str) or not id_:
            return False
        with closing(self._connect(readonly=True)) as conn:
            row = conn.execute("SELECT started_at FROM admin_sessions WHERE id = ?", (id_,)).fetchone()
        return row is not None and 0 <= now - row["started_at"] < SESSION_HOURS * 3600

    def close_session(self, id_: object) -> None:
        if isinstance(id_, str):
            with self.write() as conn:
                conn.execute("DELETE FROM admin_sessions WHERE id = ?", (id_,))

    def end_sessions(self, keep: object = None) -> int:
        """Every admin session ends but `keep` (an id, or None for none). Answers how many ended."""
        with self.write() as conn:
            return conn.execute("DELETE FROM admin_sessions WHERE id IS NOT ?", (keep,)).rowcount

    def sessions_active(self, now: float) -> int:
        with closing(self._connect(readonly=True)) as conn:
            query = "SELECT COUNT(*) FROM admin_sessions WHERE started_at > ? AND started_at <= ?"
            return conn.execute(query, (now - SESSION_HOURS * 3600, now)).fetchone()[0]

    # Settings (version 4)

    def setting(self, key: str) -> str | None:
        with closing(self._connect(readonly=True)) as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return None if row is None else row["value"]

    def set_setting(self, key: str, value: str) -> None:
        with self.write() as conn:
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, value, now()),
            )

    def drop_setting(self, key: str) -> bool:
        with self.write() as conn:
            return conn.execute("DELETE FROM settings WHERE key = ?", (key,)).rowcount > 0

    @property
    def item_limit(self) -> int:
        """List items allowed per Cloudflare account: the setting, read at each use (D27), else the start's value."""
        value = self.setting(ITEM_LIMIT_SETTING)
        if value is not None and value.isdigit() and int(value) >= 1:
            return int(value)
        return self.default_item_limit

    def write_sealed(self, box: "SecretBox", name: str, text: str) -> None:
        key_id, nonce, value = box.seal(name, text)
        with self.write() as conn:
            conn.execute(
                "INSERT INTO secrets (name, key_id, nonce, value, updated_at) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (name) DO UPDATE SET key_id = excluded.key_id, nonce = excluded.nonce,"
                " value = excluded.value, updated_at = excluded.updated_at",
                (name, key_id, nonce, value, now()),
            )

    def read_sealed(self, box: "SecretBox", name: str) -> tuple[str, str | None]:
        """`("stored", text)`, `("missing", None)`, or `("unreadable", None)` when the row was sealed with another key
        or is damaged: never an error."""
        with closing(self._connect(readonly=True)) as conn:
            row = conn.execute("SELECT key_id, nonce, value FROM secrets WHERE name = ?", (name,)).fetchone()
        if row is None:
            return "missing", None
        text = box.open(name, row["key_id"], row["nonce"], row["value"])
        return ("unreadable", None) if text is None else ("stored", text)

    def drop_sealed(self, name: str) -> bool:
        with self.write() as conn:
            return conn.execute("DELETE FROM secrets WHERE name = ?", (name,)).rowcount > 0

    def api_keys(self) -> "list[dict]":
        with closing(self._connect(readonly=True)) as conn:
            rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at, id").fetchall()
        return [dict(row) | {"scopes": json.loads(row["scopes"])} for row in rows]

    def api_key(self, digest: str) -> dict | None:
        with closing(self._connect(readonly=True)) as conn:
            row = conn.execute("SELECT * FROM api_keys WHERE digest = ?", (digest,)).fetchone()
        return None if row is None else dict(row) | {"scopes": json.loads(row["scopes"])}

    def add_api_key(self, name: str, scopes: "list[str]", digest: str, prefix: str) -> dict:
        row = {
            "id": draw_code(CODE_LENGTH),
            "name": name,
            "prefix": prefix,
            "digest": digest,
            "scopes": json.dumps(scopes),
            "created_at": now(),
            "last_used_at": None,
        }
        with self.write() as conn:
            conn.execute(
                f"INSERT INTO api_keys ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values())
            )
        return row | {"scopes": scopes}

    def drop_api_key(self, id_: str) -> bool:
        with self.write() as conn:
            return conn.execute("DELETE FROM api_keys WHERE id = ?", (id_,)).rowcount > 0

    def touch_api_key(self, id_: str, stamp: str) -> None:
        with self.write() as conn:
            conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (stamp, id_))

    def list(self, kind: str | None = None) -> list[dict]:
        with closing(self._connect(readonly=True)) as conn:
            where, args = ("WHERE kind = ?", (kind,)) if kind else ("", ())
            rows = conn.execute(f"SELECT * FROM {TABLE} {where} ORDER BY updated_at DESC, id", args).fetchall()
        return [dict(row) for row in rows]

    def get(self, id_: str) -> dict | None:
        if not CODE.fullmatch(id_):
            return None
        with closing(self._connect(readonly=True)) as conn:
            row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (id_,)).fetchone()
        return None if row is None else dict(row)

    def free_slug(self) -> str:
        """A slug of a link nobody has now, kept by check_user_slug. Nothing holds it, so a create may still find it
        taken."""
        with closing(self._connect(readonly=True)) as conn:
            for _ in range(DRAWS):
                slug = draw_code(SLUG_LENGTH)
                if (
                    check_user_slug(slug) == slug
                    and not conn.execute(f"SELECT 1 FROM {TABLE} WHERE slug = ?", (slug,)).fetchone()
                ):
                    return slug
        raise RuntimeError(f"no free slug after {DRAWS} draws")

    def _slug_free(self, conn: sqlite3.Connection, slug: str, id_: str) -> None:
        if conn.execute(f"SELECT 1 FROM {TABLE} WHERE slug = ? AND id <> ?", (slug, id_)).fetchone():
            raise SlugTaken(slug)

    def create(self, kind: str, values: dict) -> dict:
        """A new link. `values` may hold `address`, a host of cf_hosts (None or absent: the LAN). Raises SlugTaken,
        QuotaFull, or Invalid on `address` for a host not set up here."""
        address = values.get("address")
        with self.write() as conn:
            # The path first: a refused create draws no id
            self._slug_free(conn, values["slug"], "")
            while True:
                id_ = draw_code(CODE_LENGTH)
                if not conn.execute(f"SELECT 1 FROM {TABLE} WHERE id = ?", (id_,)).fetchone():
                    break
            if address is not None:
                self._check_room(conn, address, None)
            stamp = now()
            row = {"id": id_, "kind": kind, **values, "created_at": stamp, "updated_at": stamp}
            row |= {"address": address, "cf_state": None if address is None else "pending"}
            columns = (*COLUMNS, "address", "cf_state")
            try:
                conn.execute(
                    f"INSERT INTO {TABLE} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                    [row[c] for c in columns],
                )
            except sqlite3.IntegrityError as error:
                raise self._clash(error, values["slug"]) from None
            return dict(conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (id_,)).fetchone())

    def update(self, id_: str, values: dict) -> dict | None:
        """Changes the fields given. Every change counts a revision and puts a Cloudflare link back to `pending`; a
        change of source queues the removal of the old item, which waits until the new one is active (`moved`), or
        goes at once when the link moves to the LAN (`deleted`)."""
        with self.write() as conn:
            old = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (id_,)).fetchone()
            if old is None:
                return None
            if "slug" in values:
                self._slug_free(conn, values["slug"], id_)
            new = {**dict(old), **values}
            address = new["address"]
            if address is not None and address != old["address"]:
                self._check_room(conn, address, id_)
            sets = ", ".join(f"{c} = ?" for c in (*values, "updated_at"))
            sets += ", rev = rev + 1, cf_state = ?, cf_error = NULL"
            state = None if address is None else "pending"
            try:
                found = conn.execute(
                    f"UPDATE {TABLE} SET {sets} WHERE id = ? RETURNING *", (*values.values(), now(), state, id_)
                ).fetchone()
            except sqlite3.IntegrityError as error:
                raise self._clash(error, new["slug"]) from None
            before = link_source(old["address"], old["kind"], old["slug"], id_)
            after = link_source(address, new["kind"], new["slug"], id_)
            if before is not None and before != after:
                account_id = self._account_of(conn, old["address"])
                if account_id is not None:
                    reason, after_link = ("moved", id_) if after is not None else ("deleted", None)
                    self._queue_removal(conn, account_id, before, id_, reason, after_link=after_link)
        return dict(found)

    def delete(self, id_: str) -> bool:
        """The row goes and the removal of its Cloudflare item is queued, in one transaction."""
        with self.write() as conn:
            old = conn.execute(f"DELETE FROM {TABLE} WHERE id = ? RETURNING *", (id_,)).fetchone()
            if old is None:
                return False
            source = link_source(old["address"], old["kind"], old["slug"], id_)
            account_id = self._account_of(conn, old["address"]) if source else None
            if account_id is not None:
                self._queue_removal(conn, account_id, source, id_, "deleted")
        return True

    @staticmethod
    def _clash(error: sqlite3.IntegrityError, slug: str) -> Exception:
        if "redirect_links_source" in str(error):
            return SlugTaken(slug, "address")
        if "slug" in str(error):
            return SlugTaken(slug)
        return error

    # --- Cloudflare: what a link save, the admin and the sync share ---

    @staticmethod
    def _account_of(conn: sqlite3.Connection, host: str | None) -> str | None:
        if host is None:
            return None
        found = conn.execute("SELECT account_id FROM cf_hosts WHERE host = ?", (host,)).fetchone()
        return None if found is None else found["account_id"]

    def _check_room(self, conn: sqlite3.Connection, address: str, id_: str | None) -> None:
        """Refuses an address that is no host set up here, and a link the account's list has no item left for: the
        items read at the last quota check, the links not yet sent once and the pages for unknown paths never sent. A
        link that stays in the same account takes no new place."""
        account_id = self._account_of(conn, address)
        if account_id is None:
            raise Invalid("address", "not a host set up here")
        if id_ is not None:
            current = conn.execute(f"SELECT address FROM {TABLE} WHERE id = ?", (id_,)).fetchone()
            if current is not None and self._account_of(conn, current["address"]) == account_id:
                return
        if self.new_items(conn, account_id, exclude=id_) >= self.item_limit:
            raise QuotaFull(account_id)

    @staticmethod
    def new_items(conn: sqlite3.Connection, account_id: str, *, exclude: str | None = None) -> int:
        """The items the account's list holds or was promised: as read last, plus links and pages never sent."""
        used = conn.execute("SELECT items_used FROM cf_accounts WHERE id = ?", (account_id,)).fetchone()
        links = conn.execute(
            f"SELECT count(*) FROM {TABLE} l JOIN cf_hosts h ON h.host = l.address"
            " WHERE h.account_id = ? AND l.cf_synced_rev = 0 AND l.cf_state IN ('pending', 'error') AND l.id IS NOT ?",
            (account_id, exclude),
        ).fetchone()[0]
        roots = conn.execute(
            "SELECT count(*) FROM cf_hosts WHERE account_id = ? AND fallback IS NOT NULL AND fallback_synced_rev = 0",
            (account_id,),
        ).fetchone()[0]
        return ((used["items_used"] or 0) if used is not None else 0) + links + roots

    @staticmethod
    def _queue_removal(
        conn: sqlite3.Connection,
        account_id: str,
        source: str,
        marker: str,
        reason: str,
        *,
        after_link: str | None = None,
        remote_id: str | None = None,
    ) -> None:
        """One row per marker and source: the last one queued says how it goes."""
        conn.execute(
            "DELETE FROM cf_removals WHERE account_id = ? AND source = ? AND marker = ? AND remote_id IS ?",
            (account_id, source, marker, remote_id),
        )
        conn.execute(
            "INSERT INTO cf_removals (account_id, source, marker, remote_id, reason, after_link, queued_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (account_id, source, marker, remote_id, reason, after_link, now()),
        )

    def install_id(self) -> str:
        """This install's id, in every item marker: drawn once, or imported from 7.0.1."""
        with self.write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO cf_meta (key, value) VALUES ('install_id', ?)", (secrets.token_hex(16),)
            )
            return conn.execute("SELECT value FROM cf_meta WHERE key = 'install_id'").fetchone()["value"]

    def cf_accounts(self) -> "list[dict]":
        with self.read() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM cf_accounts ORDER BY id")]

    def cf_account(self, account_id: str) -> dict | None:
        with self.read() as conn:
            row = conn.execute("SELECT * FROM cf_accounts WHERE id = ?", (account_id,)).fetchone()
        return None if row is None else dict(row)

    def cf_hosts(self) -> "list[dict]":
        with self.read() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM cf_hosts ORDER BY host")]

    def cf_host(self, host: str) -> dict | None:
        with self.read() as conn:
            row = conn.execute("SELECT * FROM cf_hosts WHERE host = ?", (host,)).fetchone()
        return None if row is None else dict(row)

    def cf_counts(self) -> dict[str, int]:
        """Links with a Cloudflare address, by state."""
        with self.read() as conn:
            rows = conn.execute(
                f"SELECT cf_state, count(*) AS n FROM {TABLE} WHERE address IS NOT NULL GROUP BY cf_state"
            ).fetchall()
        return dict.fromkeys(("pending", "active", "error", "expired"), 0) | {r["cf_state"]: r["n"] for r in rows}

    def save_setup(self, account: dict, host: dict, fallback: str | None) -> None:
        """A confirmed host plan: its account (kept or created, with the list and rule found or made) and the host, in
        one transaction. Only a host created here takes a page for unknown paths."""
        with self.write() as conn:
            conn.execute(
                "INSERT INTO cf_accounts (id, name, list_id, ruleset_id, rule_id) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (id) DO UPDATE SET name = excluded.name, list_id = excluded.list_id,"
                " ruleset_id = excluded.ruleset_id, rule_id = excluded.rule_id",
                (account["id"], account["name"], account["list_id"], account["ruleset_id"], account["rule_id"]),
            )
            page = fallback if host["created_by_us"] else None
            conn.execute(
                "INSERT INTO cf_hosts (host, zone_id, zone_name, account_id, record_id, created_by_us, fallback,"
                " fallback_rev, fallback_state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    host["host"],
                    host["zone_id"],
                    host["zone_name"],
                    account["id"],
                    host["record_id"],
                    1 if host["created_by_us"] else 0,
                    page,
                    0 if page is None else 1,
                    None if page is None else "pending",
                    now(),
                ),
            )

    def set_fallback(self, host: str, target: str | None) -> bool:
        """A host's page for unknown paths, sent by the next pass, or None: its item is removed. False for a host not
        set up here, or one adopted here (it may serve a site)."""
        with self.write() as conn:
            row = conn.execute("SELECT * FROM cf_hosts WHERE host = ?", (host,)).fetchone()
            if row is None or not row["created_by_us"]:
                return False
            if target is None:
                if row["fallback"] is not None:
                    conn.execute(
                        "UPDATE cf_hosts SET fallback = NULL, fallback_state = NULL, fallback_error = NULL"
                        " WHERE host = ?",
                        (host,),
                    )
                    self._queue_removal(conn, row["account_id"], fallback_source(host), FALLBACK_MARKER, "fallback")
            elif target != row["fallback"]:
                conn.execute(
                    "UPDATE cf_hosts SET fallback = ?, fallback_rev = fallback_rev + 1, fallback_state = 'pending',"
                    " fallback_error = NULL WHERE host = ?",
                    (target, host),
                )
        return True

    def retry_all(self) -> int:
        """Sync now: every link in error and every page for unknown paths goes back to `pending`."""
        with self.write() as conn:
            links = conn.execute(
                f"UPDATE {TABLE} SET cf_state = 'pending', cf_error = NULL WHERE cf_state = 'error'"
            ).rowcount
            roots = conn.execute(
                "UPDATE cf_hosts SET fallback_state = 'pending', fallback_error = NULL WHERE fallback IS NOT NULL"
            ).rowcount
        return links + roots

    def mark_pending(self, links: "list[str]", hosts: "list[str]") -> int:
        """Compare's confirmed pushes: these links and these hosts' pages for unknown paths go back to `pending`, so the
        next pass writes them again as they are here."""
        with self.write() as conn:
            count = 0
            for id_ in links:
                count += conn.execute(
                    f"UPDATE {TABLE} SET cf_state = 'pending', cf_error = NULL"
                    " WHERE id = ? AND address IS NOT NULL AND cf_state IS NOT 'expired'",
                    (id_,),
                ).rowcount
            for host in hosts:
                count += conn.execute(
                    "UPDATE cf_hosts SET fallback_state = 'pending', fallback_error = NULL"
                    " WHERE host = ? AND fallback IS NOT NULL",
                    (host,),
                ).rowcount
        return count

    def queue_resync_removals(self, account_id: str, items: "list[tuple[str, str]]") -> int:
        """Compare's confirmed removals: each `(source, remote id)` deletes that exact item."""
        with self.write() as conn:
            for source, remote_id in items:
                self._queue_removal(conn, account_id, source, "", "resync", remote_id=remote_id)
        return len(items)

    def import_v7(self, old: Path) -> dict[str, int]:
        """Copies the rows of a 7.0.1 `redirect_links` table, unchanged, opened read-only. A row whose id or slug is
        already here is a duplicate, one that breaks a rule of this app is refused. Answers the counts of imported,
        duplicate and refused rows, and of imported rows written with 7.0.1's IP. The file is opened immutable, which
        works on a read-only mount, so a write-ahead log not yet folded in would be missed: that is refused. Raises
        sqlite3.DatabaseError when the file is not a 7.0.1 database."""
        wal = old.with_name(old.name + "-wal")
        if wal.exists() and wal.stat().st_size > 0:
            raise SystemExit(f"{wal.name} holds changes: stop 7.0.1 cleanly, then copy its database again")
        with closing(sqlite3.connect(f"{old.resolve().as_uri()}?mode=ro&immutable=1", uri=True)) as src:
            rows = [
                dict(zip(COLUMNS, row, strict=True)) for row in src.execute(f"SELECT {', '.join(COLUMNS)} FROM {TABLE}")
            ]
        counts = dict.fromkeys(("imported", "duplicates", "refused", "with_ip"), 0)
        insert = f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})"
        with closing(self._connect()) as conn, conn:
            for row in rows:
                if v7_refusal(row):
                    counts["refused"] += 1
                    continue
                if conn.execute(f"SELECT 1 FROM {TABLE} WHERE id = ? OR slug = ?", (row["id"], row["slug"])).fetchone():
                    counts["duplicates"] += 1
                    continue
                try:
                    conn.execute(insert, [row[c] for c in COLUMNS])
                except sqlite3.IntegrityError:  # another rule of the table, such as a missing name
                    counts["refused"] += 1
                    continue
                counts["imported"] += 1
                counts["with_ip"] += row["link_host"] == "ip"
        return counts

    def import_v7_cloudflare(self, old: Path, admin: set[str] = frozenset()) -> dict | None:
        """Copies the state of the 7.0.1 Cloudflare plugin from the same file, opened the same way; None when it holds
        no plugin table. The install id comes first, so the items already in Cloudflare stay this app's: one already
        drawn here with any account or host behind it refuses the whole step (`install` = `refused`); one no marker
        can hold is not taken (`install` = `invalid`, D15), and 7.0.1's items then read as foreign. Then accounts,
        hosts (folded once, two rows folding to one host both refused, as are the admin's hosts `admin` (D18) and a
        name that is no host name), pages for unknown paths (checked as the admin page checks them), entries as links
        with a Cloudflare address (refused under `.well-known`), and pending removals. A row of a wrong type is
        counted in `damaged` and left out. Running it again changes nothing."""
        with closing(sqlite3.connect(f"{old.resolve().as_uri()}?mode=ro&immutable=1", uri=True)) as src:
            src.row_factory = sqlite3.Row
            tables = {row[0] for row in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "cloudflare_accounts" not in tables:
                return None

            def rows(table: str) -> list[dict]:
                return [dict(row) for row in src.execute(f"SELECT * FROM {table}")] if table in tables else []

            install = rows("cloudflare_install")
            accounts, hosts = rows("cloudflare_accounts"), rows("cloudflare_hosts") + rows("cloudflare_parked_hosts")
            entries = rows("cloudflare_entries") + rows("cloudflare_parked_entries")
            removals = rows("cloudflare_removals")
        report: dict = {"install": "kept", "accounts": 0, "busy_accounts": [], "hosts": 0, "hosts_refused": []}
        report |= {"pages": 0, "pages_refused": 0, "entries": 0, "entries_refused": 0, "removals": 0, "damaged": 0}
        old_id = install[0].get("install_id") if install else None
        if old_id is not None and not (isinstance(old_id, str) and _MARKER_PART.fullmatch(old_id)):
            report["install"], old_id = "invalid", None
        stamp = now()
        hold = (datetime.now(UTC) + timedelta(seconds=OP_DEADLINE)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.write() as conn:
            mine = conn.execute("SELECT value FROM cf_meta WHERE key = 'install_id'").fetchone()
            if old_id is not None and (mine is None or mine["value"] != old_id):
                if (
                    mine is not None
                    and conn.execute(
                        "SELECT EXISTS (SELECT 1 FROM cf_accounts) OR EXISTS (SELECT 1 FROM cf_hosts)"
                    ).fetchone()[0]
                ):
                    report["install"] = "refused"
                    return report
                conn.execute("INSERT OR REPLACE INTO cf_meta (key, value) VALUES ('install_id', ?)", (old_id,))
                report["install"] = "taken"
            for account in accounts:
                if not _texts(account, ("id", "name"), ("list_id", "ruleset_id", "rule_id")):
                    report["damaged"] += 1
                    continue
                if conn.execute("SELECT 1 FROM cf_accounts WHERE id = ?", (account["id"],)).fetchone():
                    continue
                busy = account.get("op_kind") is not None
                conn.execute(
                    "INSERT INTO cf_accounts (id, name, list_id, ruleset_id, rule_id, hold_until)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (account["id"], account["name"], account["list_id"], account["ruleset_id"], account["rule_id"],
                     hold if busy else None),
                )  # fmt: skip
                report["accounts"] += 1
                if busy:
                    report["busy_accounts"].append(account["id"])
            by_key: dict[str, list[dict]] = {}
            for host in hosts:
                if not _texts(host, ("host", "zone_id", "zone_name", "account_id"), ("record_id", "created_at")):
                    report["damaged"] += 1
                    continue
                by_key.setdefault(fold_host(host["host"]), []).append(host)
            for key, group in sorted(by_key.items()):
                if conn.execute("SELECT 1 FROM cf_hosts WHERE host = ?", (key,)).fetchone():
                    continue
                known = conn.execute("SELECT 1 FROM cf_accounts WHERE id = ?", (group[0]["account_id"],)).fetchone()
                if len(group) > 1 or not HOST_NAME.fullmatch(key) or not known or key in admin:
                    report["hosts_refused"].extend(sorted(host["host"] for host in group))
                    continue
                host = group[0]
                conn.execute(
                    "INSERT INTO cf_hosts (host, zone_id, zone_name, account_id, record_id, created_by_us, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (key, host["zone_id"], host["zone_name"], host["account_id"], host["record_id"],
                     1 if host["created_by_us"] else 0, host["created_at"] or stamp),
                )  # fmt: skip
                report["hosts"] += 1
            taken = {row["host"] for row in conn.execute("SELECT host FROM cf_hosts")}
            for entry in entries:
                if not _texts(entry, ("kind", "host", "path", "target"), ("name", "expires_on", "created_at")):
                    report["damaged"] += 1
                    continue
                key = fold_host(entry["host"])
                if entry["path"] == "":
                    # A host's root: its page for unknown paths, sent again with the same `fallback` marker
                    try:
                        page = check_fallback(entry["target"], taken, admin, key)
                    except Invalid:
                        report["pages_refused"] += 1
                        continue
                    report["pages"] += conn.execute(
                        "UPDATE cf_hosts SET fallback = ?, fallback_rev = 1, fallback_state = 'pending'"
                        " WHERE host = ? AND created_by_us = 1 AND fallback IS NULL",
                        (page, key),
                    ).rowcount
                    continue
                outcome = self._import_entry(conn, key, entry, stamp)
                report["entries" if outcome == "imported" else "entries_refused"] += outcome != "already"
            for removal in removals:
                if not _texts(removal, ("source_url", "account_id"), ("entry_id", "remote_id", "reason")):
                    report["damaged"] += 1
                    continue
                account_id, marker = removal["account_id"], removal["entry_id"] or ""
                if not conn.execute("SELECT 1 FROM cf_accounts WHERE id = ?", (account_id,)).fetchone():
                    continue
                if conn.execute(
                    "SELECT 1 FROM cf_removals WHERE account_id = ? AND source = ? AND marker = ? AND remote_id IS ?",
                    (account_id, removal["source_url"], marker, removal["remote_id"]),
                ).fetchone():
                    continue
                reason = removal["reason"] if removal["reason"] in ("deleted", "expired", "resync") else "deleted"
                self._queue_removal(
                    conn, account_id, removal["source_url"], marker, reason, remote_id=removal["remote_id"]
                )
                report["removals"] += 1
        return report

    @staticmethod
    def _import_entry(conn: sqlite3.Connection, host: str, entry: dict, stamp: str) -> str:
        """One plugin entry as a link on its Cloudflare host: `imported`, `already` (a run before took it) or
        `refused`. A NanoURL or a QR code keeps its code as id, so its source stays the same."""
        if not conn.execute("SELECT 1 FROM cf_hosts WHERE host = ?", (host,)).fetchone():
            return "refused"
        kind, path = entry["kind"], entry["path"]
        if kind == "link":
            if well_known(kind, path, host):
                return "refused"
            if conn.execute(
                f"SELECT 1 FROM {TABLE} WHERE address = ? AND kind = 'link' AND slug = ?", (host, path)
            ).fetchone():
                return "already"
            id_ = draw_code(CODE_LENGTH)
            slug, design, link_host = path, None, None
        elif kind in NAMED_SECTION:
            if conn.execute(f"SELECT 1 FROM {TABLE} WHERE id = ? AND address = ?", (path, host)).fetchone():
                return "already"
            id_, design, link_host = path, None, "hostname"
            try:
                slug = slug_from_name(NAMED_SECTION[kind], entry["name"] or path)
            except Invalid:
                return "refused"
            if kind == "qrcode":
                design = json.dumps(asdict(Design()))
        else:
            return "refused"
        row = {"id": id_, "kind": kind, "link_host": link_host, "slug": slug, "name": entry["name"] or path}
        row |= {"target": entry["target"], "http_status": entry["http_status"], "expires_on": entry["expires_on"]}
        row |= {"design": design, "created_at": entry["created_at"] or stamp, "updated_at": stamp}
        if v7_refusal(row) or not CODE.fullmatch(id_):
            return "refused"
        columns = (*COLUMNS, "address", "cf_state")
        try:
            conn.execute(
                f"INSERT INTO {TABLE} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                [*(row[c] for c in COLUMNS), host, "pending"],
            )
        except sqlite3.IntegrityError:
            return "refused"
        return "imported"


def _texts(row: dict, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> bool:
    """Whether a plugin row holds text in every `required` column and text or NULL in every `optional` one: a database
    edited by hand, or from a plugin build with no constraints, may hold anything."""
    return all(isinstance(row.get(c), str) for c in required) and all(
        row.get(c) is None or isinstance(row[c], str) for c in optional
    )


def v7_refusal(row: dict) -> str | None:
    """The first rule a 7.0.1 row breaks, by field name, or None: the same rules a visit and the admin pages rely on."""
    id_, slug, target, status = row["id"], row["slug"], row["target"], row["http_status"]
    if not isinstance(id_, str) or not CODE.fullmatch(id_):
        return "id"
    if not isinstance(slug, str) or not is_valid_slug(slug):
        return "slug"
    if row["kind"] not in KINDS:
        return "kind"
    if type(status) is not int or status not in (301, 302):
        return "http_status"
    if not isinstance(target, str) or not target.lower().startswith(("http://", "https://")):
        return "target"
    try:
        check_expires_on(row["expires_on"])
    except Invalid:
        return "expires_on"
    if row["kind"] == "qrcode" and read_design(row["design"]) is None:
        return "design"
    return None


# --- Cloudflare API ------------------------------------------------------------------------------------------------
#
# The client of Cloudflare's v4 API, ported from the 7.0.1 plugin (`cfapi.py`) onto `requests`. What it holds to:
# - `API_ROOT` is a constant: moving it would send the token elsewhere, so only tests patch it.
# - No proxy from the environment, no redirect followed (a 30x would carry the token to another host), timeouts
#   (5, 15) s, an answer capped at MAX_ANSWER bytes, JSON only, `success: true` required.
# - Only GET, POST and DELETE: a PUT would replace a whole ruleset or list, the user's own rules with it.
# - Every id from an answer is checked before it enters a path. Paging is bounded.
# - At least MIN_GAP seconds between two calls of one client. A 429 waits for a short Retry-After, else raises
#   RateLimited. GET and DELETE are retried on 5xx and network errors; a POST only when nothing reached Cloudflare.
# - Calls made for a request (`bounded()`) never hold a waitress thread on a slow Cloudflare: one attempt each, no
#   Retry-After slept, shorter timeouts, and none started once the block's budget is spent. The sync's thread keeps
#   the full retries above.
# - The token lives in one private attribute and goes out in the `Authorization` header only: no repr, exception
#   text or log line holds it, and Cloudflare's own messages are cleaned and redacted before they are kept.

API_ROOT = "https://api.cloudflare.com/client/v4"
CF_TIMEOUT = (5, 15)  # seconds to connect, then between two bytes of the answer
REQUEST_TIMEOUT = (3.05, 5.0)  # the same, for a call made while a request waits
REQUEST_BUDGET = 10.0  # seconds a request's Cloudflare calls may start within: the page's reads
SETUP_BUDGET = 30.0  # the same for setting a host up, a dozen calls Cloudflare's state needs read again then written
MAX_ANSWER = 4 * 1024 * 1024
MIN_GAP = 0.3
ATTEMPTS = 4
MAX_WAIT = 30.0  # the longest Retry-After a call sleeps through
BACKOFF_CAP = 300.0
MESSAGE_LIMIT = 200
ITEMS_PER_CALL = 500
MAX_PAGES = 1000
OP_DEADLINE = 15 * 60  # seconds after which an operation still running, or lost, is dropped
CF_METHODS = frozenset({"GET", "POST", "DELETE"})
LIST_NAME = "moonie_redirect"
LIST_DESCRIPTION = "Moonie Redirect"
REDIRECT_PHASE = "http_request_redirect"
PLACEHOLDER_IPV4, PLACEHOLDER_IPV6 = "192.0.2.1", "100::"
RECORD_COMMENT = "moonie-redirect"
MARKER_PREFIX = "moonie:"
FALLBACK_MARKER = "fallback"  # the marker's link part of a page for unknown paths: no link id is this word
FALLBACK_STATUS = 302
PERM_ZONE_READ, PERM_DNS_EDIT = "Zone Read", "DNS Write"
PERM_LISTS_EDIT, PERM_RULESETS_EDIT = "Account Rule Lists Write", "Account Rulesets Write"
PERMISSIONS = (PERM_ZONE_READ, PERM_DNS_EDIT, PERM_LISTS_EDIT, PERM_RULESETS_EDIT)
CF_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
CF_TOKEN = re.compile(r"[\x21-\x7e]{1,16384}")
HOST_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")
_MARKER_PART = re.compile(r"[0-9A-Za-z_-]{1,64}")
_MARKER = re.compile(r"moonie:([0-9A-Za-z_-]{1,64}):([0-9A-Za-z_-]{1,64})")
_CF_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u00a0\u2028\u2029\u200e\u200f\u202a-\u202e\u2066-\u2069]+")
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_URI_CHARACTERS = "-._~:/?#[]@!$&'()*+,;=%"
_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")
_STRAY_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")
_SCHEME = re.compile(r"https?://", re.IGNORECASE)
_AUTHORITY_END = re.compile(r"[/?#]")
_HOST_PORT = re.compile(r"(\[[^\]]*\]|[^:\[\]]*):([0-9]*)")
_ASCII_FOLD = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


class CfError(Exception):
    """Cloudflare answered with a refusal: an HTTP error or `success: false`."""

    def __init__(self, status: int, codes: tuple[int, ...] | list[int] = (), message: str = "") -> None:
        self.status = int(status)
        self.codes = tuple(int(code) for code in codes)
        self.message = clean_message(message)
        super().__init__(f"cloudflare answered {self.status} {list(self.codes)}: {self.message}".rstrip(": "))


class RateLimited(CfError):
    """A 429 whose Retry-After is longer than a call waits, in seconds."""

    def __init__(self, retry_after: float, codes: tuple[int, ...] | list[int] = (), message: str = "") -> None:
        super().__init__(429, codes, message)
        self.retry_after = float(retry_after)


class CfUnreachable(Exception):
    """No usable answer came back. `kind` says why (timeout, dns, tls, refused, too_large, malformed, redirect) and is
    all its text holds. `not_sent` is True only when the request certainly never reached Cloudflare."""

    def __init__(self, kind: str, *, not_sent: bool = False) -> None:
        self.kind = kind
        self.not_sent = not_sent
        super().__init__(f"cloudflare unreachable: {kind}")


@dataclass(frozen=True)
class CfAccount:
    id: str
    name: str


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    account_id: str
    account_name: str
    status: str


@dataclass(frozen=True)
class DnsRecord:
    id: str
    type: str
    name: str
    content: str
    proxied: bool
    comment: str | None = None


@dataclass(frozen=True)
class RList:
    id: str
    name: str
    kind: str
    num_items: int


@dataclass(frozen=True)
class RemoteItem:
    id: str
    source_url: str
    target_url: str
    status_code: int
    comment: str | None
    subpath_matching: bool = False
    preserve_path_suffix: bool = False
    preserve_query_string: bool = False
    include_subdomains: bool = False


@dataclass(frozen=True)
class Ruleset:
    id: str
    rules: tuple[dict, ...]


@dataclass(frozen=True)
class TokenCheck:
    state: str  # ok or invalid
    missing: tuple[str, ...]
    unverified: tuple[str, ...] = ()  # permissions no probe could look at: neither missing nor granted


def rule_body() -> dict:
    return {
        "ref": LIST_NAME,
        "description": LIST_DESCRIPTION,
        "expression": f"http.request.full_uri in ${LIST_NAME}",
        "action": "redirect",
        "action_parameters": {"from_list": {"name": LIST_NAME, "key": "http.request.full_uri"}},
    }


def entrypoint_body() -> dict:
    return {"name": "default", "kind": "root", "phase": REDIRECT_PHASE, "rules": [rule_body()]}


def list_body() -> dict:
    return {"name": LIST_NAME, "kind": "redirect", "description": LIST_DESCRIPTION}


def dns_record_body(fqdn: str) -> dict:
    return {
        "type": "A",
        "name": fqdn,
        "content": PLACEHOLDER_IPV4,
        "proxied": True,
        "ttl": 1,
        "comment": RECORD_COMMENT,
    }


def fold_host(name: str) -> str:
    """The one form a host is stored and compared in: IDNA (UTS #46) when it holds more than ASCII, A to Z in lower
    case, no root dot. A name IDNA refuses is folded A to Z only: it then equals none of ours."""
    text = name.rstrip(".")
    if not text.isascii():
        try:
            text = idna.encode(text, uts46=True).decode("ascii")
        except (idna.IDNAError, UnicodeError):
            pass
    return text.translate(_ASCII_FOLD).rstrip(".")


def source_key(source_url: str) -> str:
    """The canonical form every source is compared in, ours and Cloudflare's alike: no scheme, the host folded A to Z
    with no root dot, no port 80 or 443, a bare host as its root, and in the rest RFC 3986's percent-encoding
    normalised (unreserved escapes decoded, others in upper-case hex, a stray `%` escaped). The path's case and its
    last slash stay: Cloudflare matches the path as it is. Idempotent. Ported from the plugin's, minus its non-ASCII
    host branch: our hosts are ASCII, so a foreign non-ASCII host never equals one of ours anyway."""
    text = source_url
    scheme = _SCHEME.match(text)
    if scheme:
        text = text[scheme.end() :]
    split = _AUTHORITY_END.search(text)
    authority, rest = (text[: split.start()], text[split.start() :]) if split else (text, "")
    port = None
    found = _HOST_PORT.fullmatch(authority)
    if found:
        host, port = found.group(1).translate(_ASCII_FOLD).rstrip("."), found.group(2)
    else:
        host = authority.translate(_ASCII_FOLD)
        host = host if ":" in authority else host.rstrip(".")
    if port and (len(port) > 5 or int(port) not in (80, 443)):
        host = f"{host}:{int(port) if len(port) <= 5 else port}"
    path = rest if rest.startswith("/") else f"/{rest}"
    path = _STRAY_PERCENT.sub("%25", quote(path, safe=_URI_CHARACTERS, errors="surrogatepass"))
    return host + _ESCAPE.sub(_canonical_escape, path)


def _canonical_escape(found: re.Match) -> str:
    character = chr(int(found.group(1), 16))
    return character if character in _UNRESERVED else f"%{found.group(1).upper()}"


def marker(install_id: str, link_id: str) -> str:
    """The ownership marker an item's comment carries: the install that wrote it and the link it is."""
    if not (_MARKER_PART.fullmatch(install_id) and _MARKER_PART.fullmatch(link_id)):
        raise ValueError("a marker's install and link ids are 1 to 64 of [0-9A-Za-z_-]")
    return f"{MARKER_PREFIX}{install_id}:{link_id}"


def marker_of(comment: str | None) -> tuple[str, str] | None:
    """`(install id, link id)` from an item's comment, or None: any other comment is an item someone else made."""
    found = _MARKER.fullmatch(comment) if isinstance(comment, str) else None
    return (found.group(1), found.group(2)) if found else None


def entry_of(comment: str | None, install_id: str) -> str | None:
    """The link id an item's comment names when this install wrote it, else None: another install's item is as
    foreign as one the user made by hand."""
    found = marker_of(comment)
    return found[1] if found is not None and found[0] == install_id else None


def make_item(source_url: str, target_url: str, status_code: int, install_id: str, link_id: str) -> dict:
    """One list item with the ownership marker in its comment; only a page for unknown paths matches subpaths."""
    root = link_id == FALLBACK_MARKER
    return {
        "redirect": {
            "source_url": source_url,
            "target_url": target_url,
            "status_code": FALLBACK_STATUS if root else status_code,
            "include_subdomains": False,
            "subpath_matching": root,
            "preserve_query_string": False,
            "preserve_path_suffix": False,
        },
        "comment": marker(install_id, link_id),
    }


def is_our_fallback(item: RemoteItem, install_id: str) -> bool:
    return entry_of(item.comment, install_id) == FALLBACK_MARKER


def names_our_list(rule: dict) -> bool:
    """A rule that already redirects from our list, whoever added it."""
    expression = rule.get("expression")
    return isinstance(expression, str) and re.search(rf"\${LIST_NAME}(?![A-Za-z0-9_])", expression) is not None


def backoff_delay(failures: int) -> float:
    """1, 2, 4 ... seconds after the 1st, 2nd, 3rd ... failure in a row, at most BACKOFF_CAP."""
    return 0.0 if failures < 1 else min(BACKOFF_CAP, 2.0 ** min(failures - 1, 16))


def clean_message(text: object, secret: str | None = None) -> str:
    """Cloudflare's text made safe to keep: one line, no control or bidirectional character, at most MESSAGE_LIMIT
    characters, and the token blanked should it ever echo it."""
    value = text if isinstance(text, str) else ""
    if secret:
        value = value.replace(secret, "[redacted]")
    value = re.sub(r" {2,}", " ", _CF_CONTROL.sub(" ", value).strip())
    return value[:MESSAGE_LIMIT]


def checked_id(value: object) -> str:
    """An id that goes into a path. Ids come from Cloudflare's answers, so one is never trusted to stay one segment."""
    if not isinstance(value, str) or CF_ID.fullmatch(value) is None:
        raise ValueError("not a Cloudflare id")
    return value


def _cf_ident(value: object) -> str:
    if not isinstance(value, str) or CF_ID.fullmatch(value) is None:
        raise CfUnreachable("malformed")
    return value


def _cf_text(value: object, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not empty):
        raise CfUnreachable("malformed")
    return value


def _cf_map(value: object) -> dict:
    if not isinstance(value, dict):
        raise CfUnreachable("malformed")
    return value


def _cf_rows(value: object) -> list[dict]:
    if not isinstance(value, list):
        raise CfUnreachable("malformed")
    return [_cf_map(row) for row in value]


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _cf_envelope(body: bytes) -> dict:
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise CfUnreachable("malformed") from None
    if not isinstance(document, dict):
        raise CfUnreachable("malformed")
    return document


def _cf_codes(document: dict) -> tuple[list[int], str]:
    codes, messages = [], []
    errors = document.get("errors")
    for error in errors if isinstance(errors, list) else []:
        if isinstance(error, dict):
            if _is_int(error.get("code")):
                codes.append(error["code"])
            if isinstance(error.get("message"), str):
                messages.append(error["message"])
    return codes, "; ".join(messages)


def parse_zone(row: dict) -> Zone:
    account = _cf_map(row.get("account"))
    return Zone(
        id=_cf_ident(row.get("id")),
        name=_cf_text(row.get("name")),
        account_id=_cf_ident(account.get("id")),
        account_name=_cf_text(account.get("name", ""), empty=True),
        status=_cf_text(row.get("status", ""), empty=True),
    )


def parse_record(row: dict) -> DnsRecord:
    proxied = row.get("proxied", False)
    if not isinstance(proxied, bool):
        raise CfUnreachable("malformed")
    return DnsRecord(
        id=_cf_ident(row.get("id")),
        type=_cf_text(row.get("type")),
        name=_cf_text(row.get("name")),
        content=_cf_text(row.get("content", ""), empty=True),
        proxied=proxied,
        comment=row["comment"] if isinstance(row.get("comment"), str) else None,
    )


def parse_list(row: dict) -> RList:
    count = row.get("num_items", 0)
    if not _is_int(count) or count < 0:
        raise CfUnreachable("malformed")
    return RList(
        id=_cf_ident(row.get("id")), name=_cf_text(row.get("name")), kind=_cf_text(row.get("kind")), num_items=count
    )


def parse_item(row: dict) -> RemoteItem:
    redirect = _cf_map(row.get("redirect"))
    status = redirect.get("status_code", 301)
    if not _is_int(status):
        raise CfUnreachable("malformed")
    comment = row.get("comment")
    return RemoteItem(
        id=_cf_ident(row.get("id")),
        source_url=_cf_text(redirect.get("source_url")),
        target_url=_cf_text(redirect.get("target_url")),
        status_code=status,
        comment=comment if isinstance(comment, str) else None,
        subpath_matching=redirect.get("subpath_matching") is True,
        preserve_path_suffix=redirect.get("preserve_path_suffix") is True,
        preserve_query_string=redirect.get("preserve_query_string") is True,
        include_subdomains=redirect.get("include_subdomains") is True,
    )


def parse_ruleset(row: dict) -> Ruleset:
    rules = row.get("rules", [])
    return Ruleset(id=_cf_ident(row.get("id")), rules=tuple(_cf_rows(rules if rules is not None else [])))


def checked_items(items: list[dict]) -> list[dict]:
    """Items in exactly the shape `make_item` builds, 1 to ITEMS_PER_CALL of them, each with our marker."""
    if not 1 <= len(items) <= ITEMS_PER_CALL:
        raise ValueError(f"between 1 and {ITEMS_PER_CALL} items per call")
    flags = ("include_subdomains", "subpath_matching", "preserve_query_string", "preserve_path_suffix")
    for item in items:
        redirect = item.get("redirect") if isinstance(item, dict) else None
        found = marker_of(item.get("comment")) if isinstance(item, dict) else None
        if not isinstance(redirect, dict) or set(item) != {"redirect", "comment"} or found is None:
            raise ValueError("an item is {redirect, comment} with our marker")
        if set(redirect) != {"source_url", "target_url", "status_code", *flags}:
            raise ValueError("an item's redirect has exactly the fields make_item writes")
        root = found[1] == FALLBACK_MARKER
        source = redirect["source_url"]
        if root and not (isinstance(source, str) and source.endswith("/") and source.count("/") == 1):
            raise ValueError("a page for unknown paths sits at a host's root")
        if any(redirect[flag] is not (root and flag == "subpath_matching") for flag in flags):
            raise ValueError("only a page for unknown paths matches subpaths, and no other flag is set")
        if redirect["status_code"] not in (301, 302):
            raise ValueError("an item's status code is 301 or 302")
        if not all(isinstance(redirect[key], str) and redirect[key] for key in ("source_url", "target_url")):
            raise ValueError("an item's URLs are texts")
    return items


class _Answer:
    __slots__ = ("status", "document")

    def __init__(self, status: int, document: dict) -> None:
        self.status, self.document = status, document

    @property
    def result(self) -> object:
        return self.document.get("result")

    @property
    def info(self) -> dict:
        info = self.document.get("result_info")
        return info if isinstance(info, dict) else {}


def _unreachable(error: requests.RequestException) -> CfUnreachable:
    """What a failed exchange was, and whether it surely never reached Cloudflare (DNS, connection refused, connect
    timeout): only then may a POST go again."""
    if isinstance(error, requests.exceptions.SSLError):
        return CfUnreachable("tls")
    if isinstance(error, requests.exceptions.ConnectTimeout):
        return CfUnreachable("timeout", not_sent=True)
    if isinstance(error, requests.exceptions.Timeout):
        return CfUnreachable("timeout")
    if isinstance(error, requests.exceptions.ConnectionError):
        reason = error.args[0] if error.args else None
        reason = getattr(reason, "reason", reason)
        if isinstance(reason, urllib3.exceptions.NameResolutionError):
            return CfUnreachable("dns", not_sent=True)
        if isinstance(reason, urllib3.exceptions.NewConnectionError):
            return CfUnreachable("refused", not_sent=True)
        return CfUnreachable("refused")
    return CfUnreachable("malformed")


class Cloudflare:
    """The real client. Thread safe: the gap between calls is kept under a lock; the session is shared, which
    `requests` allows for plain requests like these."""

    def __init__(
        self,
        token: str,
        *,
        sleep: Callable[[float], object] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(token, str) or CF_TOKEN.fullmatch(token) is None:
            # The value is never echoed: a wrong one could still be most of a real token
            raise ValueError("the Cloudflare token is not a printable ASCII text")
        self.__token = token
        self._sleep, self._clock = sleep, clock
        self._lock = threading.Lock()
        self._last: float | None = None
        self._bound = threading.local()  # this thread's deadline, inside `bounded()`
        self._session = requests.Session()
        self._session.trust_env = False  # no proxy, netrc or CA bundle from the environment

    def __repr__(self) -> str:
        return f"{type(self).__name__}(token=[redacted])"

    __str__ = __repr__

    def __reduce__(self):  # never pickled, so the token never leaves this way
        raise TypeError("a Cloudflare client cannot be pickled")

    # The wire

    @contextmanager
    def bounded(self, seconds: float) -> Iterator["Cloudflare"]:
        """Calls this thread makes in the block, for a request that waits on them: one attempt each, no Retry-After
        slept (RateLimited at once), REQUEST_TIMEOUT or less, and no call started once `seconds` have passed (an
        unreachable `timeout`, never sent). Other threads, the sync's, keep their retries."""
        previous = getattr(self._bound, "deadline", None)
        deadline = self._clock() + seconds
        self._bound.deadline = deadline if previous is None else min(previous, deadline)
        try:
            yield self
        finally:
            self._bound.deadline = previous

    def _deadline(self) -> float | None:
        return getattr(self._bound, "deadline", None)

    def _timeout(self) -> tuple[float, float]:
        """What `_send` waits: CF_TIMEOUT, or inside `bounded()` REQUEST_TIMEOUT cut to the time left."""
        deadline = self._deadline()
        if deadline is None:
            return CF_TIMEOUT
        left = max(0.5, deadline - self._clock())
        return (min(REQUEST_TIMEOUT[0], left), min(REQUEST_TIMEOUT[1], left))

    def _wait_gap(self) -> None:
        with self._lock:
            moment = self._clock()
            if self._last is not None:
                wait = MIN_GAP - max(0.0, moment - self._last)
                if wait > 0:
                    self._sleep(wait)
                    moment += wait
            self._last = moment

    def _headers(self, body: bytes | None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.__token}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        return headers

    def _send(self, method: str, url: str, body: bytes | None) -> tuple[int, bytes, dict]:
        """One HTTP exchange: (status, body, headers), or CfUnreachable. The fake of the tests replaces it."""
        try:
            with self._session.request(
                method,
                url,
                data=body,
                headers=self._headers(body),
                timeout=self._timeout(),
                allow_redirects=False,
                stream=True,
            ) as answer:
                if 300 <= answer.status_code < 400:
                    raise CfUnreachable("redirect")
                length = answer.headers.get("Content-Length", "")
                if length.strip().isdigit() and int(length) > MAX_ANSWER:
                    raise CfUnreachable("too_large")
                chunks, size = [], 0
                for chunk in answer.iter_content(64 * 1024):
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_ANSWER:
                        raise CfUnreachable("too_large")
                return answer.status_code, b"".join(chunks), dict(answer.headers)
        except requests.RequestException as error:
            # The cause is dropped: a traceback of it would hold the request, and the request holds the token
            raise _unreachable(error) from None

    def _retry_after(self, value: str | None) -> float:
        if not value:
            return 1.0
        try:
            seconds = float(value.strip())
        except ValueError:
            try:
                when = parsedate_to_datetime(value)
                when = when.replace(tzinfo=UTC) if when.tzinfo is None else when
                seconds = (when - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, IndexError, OverflowError):
                return 1.0
        if seconds != seconds or seconds < 0:  # NaN, or a time past
            return 0.0
        return min(seconds, BACKOFF_CAP * 12)

    def _request(
        self, method: str, path: str, *, query: dict | None = None, body: object = None, allow: tuple[int, ...] = ()
    ) -> _Answer:
        """One call, retried as this section says. `allow` lists HTTP statuses answered rather than raised."""
        if method not in CF_METHODS:
            raise ValueError(f"{method} is never sent to Cloudflare")
        url = API_ROOT.rstrip("/") + path
        if query:
            url += "?" + urlencode({key: str(value) for key, value in query.items()})
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        deadline = self._deadline()
        attempts = ATTEMPTS if deadline is None else 1
        failures = 0
        while True:
            if deadline is not None and self._clock() >= deadline:
                raise CfUnreachable("timeout", not_sent=True)
            self._wait_gap()
            try:
                status, raw, headers = self._send(method, url, data)
            except CfUnreachable as error:
                failures += 1
                # A POST that may have reached Cloudflare is not sent twice: it could add a rule twice
                retry = (method != "POST" or error.not_sent) and error.kind not in ("tls", "redirect", "too_large")
                if not retry or failures >= attempts:
                    raise
                self._pause(method, path, error.kind, backoff_delay(failures))
                continue
            if status in allow:
                try:
                    return _Answer(status, _cf_envelope(raw))
                except CfUnreachable:
                    return _Answer(status, {})
            if status == 429:
                wait = self._retry_after((headers or {}).get("Retry-After"))
                failures += 1
                if wait > MAX_WAIT or failures >= attempts:
                    raise RateLimited(wait, *self._error_text(raw))
                self._pause(method, path, "429", wait)
                continue
            if status >= 500:
                failures += 1
                if method != "POST" and failures < attempts:
                    self._pause(method, path, str(status), backoff_delay(failures))
                    continue
            if status >= 400:
                raise CfError(status, *self._error_text(raw))
            document = _cf_envelope(raw)
            if document.get("success") is not True:
                codes, message = _cf_codes(document)
                raise CfError(status, codes, clean_message(message, self.__token))
            return _Answer(status, document)

    def _error_text(self, raw: bytes) -> tuple[list[int], str]:
        try:
            codes, message = _cf_codes(_cf_envelope(raw))
        except CfUnreachable:
            return [], ""
        return codes, clean_message(message, self.__token)

    def _pause(self, method: str, path: str, why: str, seconds: float) -> None:
        # Method, path (ids only, never a query) and the reason: nothing of the request's headers
        log.info("cloudflare %s %s: %s, retry in %.1f s", method, path, why, seconds)
        if seconds > 0:
            self._sleep(seconds)

    def _pages(self, path: str, per_page: int, query: dict | None = None) -> Iterator[dict]:
        """Every row of a paged listing. An empty page ends it, and so do `total_count` rows, `total_pages` pages, or a
        page short of `per_page` with no total at all. A page not served as asked (its `page` echoed wrong, or the rows
        of the page before again) and a listing longer than MAX_PAGES are malformed."""
        previous: list[dict] | None = None
        seen = 0
        for page in range(1, MAX_PAGES + 1):
            answer = self._request("GET", path, query={**(query or {}), "page": page, "per_page": per_page})
            rows = _cf_rows(answer.result)
            if not rows:
                return
            echoed = answer.info.get("page")
            if (_is_int(echoed) and echoed != page) or rows == previous:
                raise CfUnreachable("malformed")
            yield from rows
            seen += len(rows)
            total, count = answer.info.get("total_pages"), answer.info.get("total_count")
            if (_is_int(total) and page >= total) or (_is_int(count) and seen >= count):
                return
            if not _is_int(total) and not _is_int(count) and len(rows) < per_page:
                return
            previous = rows
        raise CfUnreachable("malformed")

    # The interface

    def verify_token(self) -> TokenCheck:
        """Whether the token is active, then which permission it lacks. Network failures raise: the caller says
        unchecked. A permission no probe could look at is `unverified`, never granted by default."""
        if not self._token_active():
            return TokenCheck("invalid", ())
        missing: set[str] = set()
        try:
            zones = self.zones()
        except CfError as error:
            if error.status != 403:
                raise
            missing.add(PERM_ZONE_READ)
            zones = []
        first_zone: dict[str, Zone] = {}
        for zone in zones:
            first_zone.setdefault(zone.account_id, zone)
        accounts = set(first_zone)
        try:
            accounts.update(account.id for account in self.accounts())
        except CfError as error:
            if error.status != 403:
                raise
        probed: set[str] = set()
        for account_id in sorted(accounts):
            account = checked_id(account_id)
            probes = [
                (PERM_LISTS_EDIT, f"/accounts/{account}/rules/lists", None, ()),
                (PERM_RULESETS_EDIT, f"/accounts/{account}/rulesets/phases/{REDIRECT_PHASE}/entrypoint", None, (404,)),
            ]
            if account_id in first_zone:
                zone_path = f"/zones/{checked_id(first_zone[account_id].id)}/dns_records"
                probes.insert(0, (PERM_DNS_EDIT, zone_path, {"per_page": 1}, ()))
            for permission, path, query, allow in probes:
                if permission in missing:
                    continue
                try:
                    self._request("GET", path, query=query, allow=allow)
                except CfError as error:
                    if error.status != 403:
                        raise
                    missing.add(permission)
                probed.add(permission)
        unverified = {name for name in PERMISSIONS[1:] if name not in probed}
        return TokenCheck(
            "ok",
            tuple(name for name in PERMISSIONS if name in missing),
            tuple(name for name in PERMISSIONS if name in unverified),
        )

    def _token_active(self) -> bool:
        answer = self._request("GET", "/user/tokens/verify", allow=(401, 403))
        if answer.status == 200:
            return _cf_map(answer.result).get("status") == "active"
        # Not a user token: an account token verifies under its account
        listing = self._request("GET", "/accounts", query={"per_page": 50}, allow=(401, 403))
        if listing.status != 200:
            return False
        for row in _cf_rows(listing.result):
            account = _cf_ident(row.get("id"))
            answer = self._request("GET", f"/accounts/{account}/tokens/verify", allow=(401, 403, 404))
            if answer.status == 200:
                return _cf_map(answer.result).get("status") == "active"
        return False

    def accounts(self) -> list[CfAccount]:
        return [
            CfAccount(id=_cf_ident(row.get("id")), name=_cf_text(row.get("name"), empty=True))
            for row in self._pages("/accounts", 50)
        ]

    def zones(self) -> list[Zone]:
        return [parse_zone(row) for row in self._pages("/zones", 50)]

    def dns_records(self, zone_id: str, name: str) -> list[DnsRecord]:
        """The records at a name. A DNS name is read with no regard to case: they are filtered again, folded."""
        if not isinstance(name, str) or not name:
            raise ValueError("a record name is a text")
        path = f"/zones/{checked_id(zone_id)}/dns_records"
        records = [parse_record(row) for row in self._pages(path, 100, {"name": name})]
        wanted = fold_host(name)
        return [record for record in records if fold_host(record.name) == wanted]

    def create_dns_record(self, zone_id: str, fqdn: str) -> DnsRecord:
        if not isinstance(fqdn, str) or not fqdn:
            raise ValueError("a record name is a text")
        answer = self._request("POST", f"/zones/{checked_id(zone_id)}/dns_records", body=dns_record_body(fqdn))
        return parse_record(_cf_map(answer.result))

    def lists(self, account_id: str) -> list[RList]:
        answer = self._request("GET", f"/accounts/{checked_id(account_id)}/rules/lists")
        return [parse_list(row) for row in _cf_rows(answer.result)]

    def create_list(self, account_id: str) -> RList:
        answer = self._request("POST", f"/accounts/{checked_id(account_id)}/rules/lists", body=list_body())
        return parse_list(_cf_map(answer.result))

    def list_items(self, account_id: str, list_id: str) -> Iterator[RemoteItem]:
        """Every item of a list, by cursor. An empty page ends it; a cursor seen twice, or a full last page with no
        cursor while the list's count says it holds more, is malformed: a listing cut short would have an item taken
        for missing and a removal for done."""
        path = f"/accounts/{checked_id(account_id)}/rules/lists/{checked_id(list_id)}/items"
        cursor: str | None = None
        seen: set[str] = set()
        count = 0
        for _page in range(MAX_PAGES):
            query: dict = {"per_page": ITEMS_PER_CALL} | ({"cursor": cursor} if cursor else {})
            answer = self._request("GET", path, query=query)
            rows = _cf_rows(answer.result)
            if not rows:
                return
            for row in rows:
                yield parse_item(row)
            count += len(rows)
            cursors = answer.info.get("cursors")
            after = cursors.get("after") if isinstance(cursors, dict) else None
            if not isinstance(after, str) or not after:
                if len(rows) >= ITEMS_PER_CALL and any(
                    row.id == list_id and row.num_items > count for row in self.lists(account_id)
                ):
                    raise CfUnreachable("malformed")
                return
            if after in seen:
                raise CfUnreachable("malformed")
            seen.add(after)
            cursor = after
        raise CfUnreachable("malformed")

    def add_items(self, account_id: str, list_id: str, items: list[dict]) -> str:
        """Adds (or, at a source the list already holds, replaces) up to ITEMS_PER_CALL items: the bulk operation id."""
        path = f"/accounts/{checked_id(account_id)}/rules/lists/{checked_id(list_id)}/items"
        return _cf_ident(_cf_map(self._request("POST", path, body=checked_items(items)).result).get("operation_id"))

    def delete_items(self, account_id: str, list_id: str, ids: list[str]) -> str:
        if not 1 <= len(ids) <= ITEMS_PER_CALL:
            raise ValueError(f"between 1 and {ITEMS_PER_CALL} ids per call")
        path = f"/accounts/{checked_id(account_id)}/rules/lists/{checked_id(list_id)}/items"
        body = {"items": [{"id": checked_id(item)} for item in ids]}
        return _cf_ident(_cf_map(self._request("DELETE", path, body=body).result).get("operation_id"))

    def bulk_operation(self, account_id: str, operation_id: str) -> tuple[str, str | None]:
        """(status, error) of a bulk operation, both cleaned and redacted."""
        path = f"/accounts/{checked_id(account_id)}/rules/lists/bulk_operations/{checked_id(operation_id)}"
        row = _cf_map(self._request("GET", path).result)
        status = clean_message(_cf_text(row.get("status")), self.__token)
        if not status:
            raise CfUnreachable("malformed")
        error = row.get("error")
        return status, (clean_message(error, self.__token) or None) if isinstance(error, str) else None

    def redirect_entrypoint(self, account_id: str) -> Ruleset | None:
        path = f"/accounts/{checked_id(account_id)}/rulesets/phases/{REDIRECT_PHASE}/entrypoint"
        answer = self._request("GET", path, allow=(404,))
        return None if answer.status == 404 else parse_ruleset(_cf_map(answer.result))

    def create_redirect_entrypoint(self, account_id: str) -> Ruleset:
        answer = self._request("POST", f"/accounts/{checked_id(account_id)}/rulesets", body=entrypoint_body())
        return parse_ruleset(_cf_map(answer.result))

    def add_rule(self, account_id: str, ruleset_id: str) -> Ruleset:
        path = f"/accounts/{checked_id(account_id)}/rulesets/{checked_id(ruleset_id)}/rules"
        return parse_ruleset(_cf_map(self._request("POST", path, body=rule_body()).result))


# --- Cloudflare plan -----------------------------------------------------------------------------------------------
#
# Setting up `<label>.<zone>`: a plan shown before anything is done, done only once the admin confirmed that very plan
# (its fingerprint). Nothing is kept in memory between the two requests: apply builds the plan again from Cloudflare
# and refuses when it differs. A plan may create the list, create the redirect entrypoint with our rule or add our rule
# beside the others, and create the placeholder record. It never changes or deletes a record, a rule or a list.

MAX_LISTS = 5  # lists of an account on Cloudflare's free plan
MAX_RULES = 15  # Bulk Redirects rules of the redirect phase on the free plan
ROUTED_TYPES = ("A", "AAAA", "CNAME")
PROPOSED_LABELS = ("go", "redirect", "link")
LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
# The pages for unknown paths offered as they are; any other is an address `check_fallback` takes
FALLBACK_CHOICES = ("https://en.wikipedia.org/wiki/HTTP_404", "https://www.google.com/")
# Held while a plan is applied or a page for unknown paths changes: a second one at the same time is `busy`
setup_lock = threading.Lock()


class PlanRefused(Exception):
    """A plan, or a page for unknown paths, refused: `status` for the answer, `code` for the page."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status, self.code = status, code


@dataclass
class PlanContext:
    """What the steps found or will make, kept beside the plan for apply; never part of an answer."""

    zone: Zone
    fqdn: str
    list_id: str | None = None
    ruleset_id: str | None = None
    rule_id: str | None = None
    record_id: str | None = None


def fingerprint(document: dict) -> str:
    """The sha256 of a document's canonical JSON, its own `fingerprint` key left out."""
    canonical = json.dumps(
        {key: value for key, value in document.items() if key != "fingerprint"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def serves_traffic(records: list[DnsRecord]) -> bool:
    """Whether a routed record at the name points anywhere but the placeholders: that host probably has visitors."""
    return any(r.type in ROUTED_TYPES and r.content not in (PLACEHOLDER_IPV4, PLACEHOLDER_IPV6) for r in records)


def is_our_placeholder(record: DnsRecord) -> bool:
    """The record an apply creates (`dns_record_body`): proxied, to the placeholder address, with our comment. It
    serves nothing, so finding it again (an apply whose answer was lost) is no live site to adopt."""
    return (
        record.type == "A"
        and record.proxied
        and record.content == PLACEHOLDER_IPV4
        and record.comment == RECORD_COMMENT
    )


def record_verdict(records: list[DnsRecord]) -> tuple[str, DnsRecord | None]:
    """`create` with no A, AAAA or CNAME at the name, or with only our own placeholder (reused, D15), `ready` when they
    are all proxied (adopted, its first record used), `conflict` when one is not: traffic it carries would skip
    Cloudflare and its redirects."""
    routed = [record for record in records if record.type in ROUTED_TYPES]
    if any(not record.proxied for record in routed):
        return "conflict", None
    if len(routed) == 1 and is_our_placeholder(routed[0]):
        return "create", routed[0]
    return ("ready", routed[0]) if routed else ("create", None)


def url_host(url: str) -> str:
    """The folded host of an http(s) URL, or '' when it has none."""
    try:
        return fold_host(urlsplit(url).hostname or "")
    except ValueError:
        return ""


def serving_hosts(base: str, request_host: str | None = None) -> set[str]:
    """The hosts the admin answers on (D18): the one of MOONIE_REDIRECT_PUBLIC_BASE_URL, and the one this request
    reached. A list item on either would answer before the admin."""
    hosts = {url_host(base)}
    if request_host:
        hosts.add(url_host(f"http://{request_host}"))
    return hosts - {""}


def find_zone(client: Cloudflare, zone_id: object) -> Zone:
    if isinstance(zone_id, str) and zone_id:
        for zone in client.zones():
            if zone.id == zone_id:
                return zone
    raise PlanRefused(404, "not_found")


def host_of(label: str, zone: Zone) -> str:
    """`<label>.<zone>`, refused (Invalid) when Cloudflare's zone name makes it no host name: it would become a host
    here, the address of links and the start of every source sent."""
    fqdn = f"{label}.{fold_host(zone.name)}"
    if not HOST_NAME.fullmatch(fqdn):
        raise Invalid("zone_id", "this zone's name is no host name")
    return fqdn


def check_label(value: object) -> str:
    if not isinstance(value, str) or not LABEL.fullmatch(value):
        raise Invalid("label", "one DNS label: a to z, 0 to 9 and dashes, at most 63")
    return value


def check_fallback(value: object, hosts: set[str], admin: set[str], fqdn: str | None = None) -> str | None:
    """A page for unknown paths: None, one of FALLBACK_CHOICES, or any target `check_target` takes whose host is no
    host set up here (`hosts`, or `fqdn` being set up: a loop) and not the admin's (`admin`)."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise Invalid("fallback", "must be a string")
    target = check_target(value)
    host = url_host(target)
    if host in hosts or host == fqdn:
        raise Invalid("fallback", "page_loop")
    if host in admin:
        raise Invalid("fallback", "admin_host")
    return target


def proposals(client: Cloudflare, zone: Zone, taken: set[str]) -> dict:
    """The usual labels with their verdict; a host already set up here says `added`."""
    found = []
    for label in PROPOSED_LABELS:
        fqdn = host_of(label, zone)
        verdict, _ = record_verdict(client.dns_records(zone.id, fqdn))
        found.append({"label": label, "fqdn": fqdn, "verdict": "added" if fqdn in taken else verdict})
    return {"zone": {"id": zone.id, "name": zone.name}, "proposals": found}


def build_plan(
    client: Cloudflare,
    zone: Zone,
    label: str,
    fallback: str | None,
    serving: set[str],
    pointed: bool,
    *,
    install: str | None = None,
    taken: set[str] = frozenset(),
    limit: int | None = None,
) -> tuple[dict, PlanContext]:
    """The plan for `<label>.<zone>` from Cloudflare's state now, and the ids apply needs. `serving` are the admin's
    hosts (D18), `pointed` says another host's page for unknown paths targets this name, `install` tells our page at
    the root from anyone else's item, `taken` are the hosts already set up, `limit` the items the list may hold."""
    fqdn = host_of(label, zone)
    context = PlanContext(zone=zone, fqdn=fqdn)
    steps: list[dict] = []
    blocked: str | None = None
    verdict, live = "create", False
    try:
        records = client.dns_records(zone.id, fqdn)
        verdict, used = record_verdict(records)
        live = serves_traffic(records)
        lists = client.lists(zone.account_id)
        ours = next((row for row in lists if row.name == LIST_NAME and row.kind == "redirect"), None)
        if ours is None:
            steps.append({"do": "create_list", "name": LIST_NAME})
            if len(lists) >= MAX_LISTS:
                blocked = "lists_full"
        else:
            context.list_id = ours.id
        entrypoint = client.redirect_entrypoint(zone.account_id)
        if entrypoint is None:
            steps.append({"do": "create_entrypoint"})
        else:
            context.ruleset_id = entrypoint.id
            rule = next((rule for rule in entrypoint.rules if names_our_list(rule)), None)
            if rule is None:
                steps.append({"do": "add_rule"})
                if len(entrypoint.rules) >= MAX_RULES:
                    blocked = blocked or "rules_full"
            else:
                context.rule_id = rule.get("id") if isinstance(rule.get("id"), str) else None
        if verdict == "create" and used is not None:
            # Our own placeholder, left by an apply whose answer was lost: the host stays one created here
            context.record_id = used.id
            steps.append(
                {"do": "use_record", "type": used.type, "name": fqdn, "content": used.content, "proxied": True}
            )
            steps.append({"do": "keep_ours", "name": fqdn})
        elif verdict == "create":
            steps.append(
                {"do": "create_record", "type": "A", "name": fqdn, "content": PLACEHOLDER_IPV4, "proxied": True}
            )
        elif verdict == "ready":
            context.record_id = used.id
            steps.append(
                {"do": "use_record", "type": used.type, "name": fqdn, "content": used.content, "proxied": True}
            )
            # A record found here may serve a real site: an adopted host never takes a page for unknown paths
            steps.append({"do": "no_fallback", "name": fqdn})
        else:
            blocked = "conflict"
        if verdict == "create" and fallback is not None:
            source = fallback_source(fqdn)
            there = []
            if ours is not None:
                wanted = source_key(source)
                items = client.list_items(zone.account_id, ours.id)
                there = [item for item in items if source_key(item.source_url) == wanted]
            used_items = sum(row.num_items for row in lists if row.kind == "redirect")
            if any(install is None or not is_our_fallback(item, install) for item in there):
                steps.append({"do": "root_held", "source": source, "target": fallback})
            elif limit is not None and not there and used_items >= limit:
                steps.append({"do": "root_full", "source": source, "target": fallback})
            else:
                steps.append({"do": "add_fallback", "source": source, "target": fallback})
    except CfError as error:
        if error.status != 403:
            raise
        blocked = "permission"
    if pointed:
        blocked = blocked or "page_points_here"
    if fqdn in taken:
        blocked = "host_exists"
    if fqdn in serving:
        blocked = "admin_host"
    plan = {
        "fqdn": fqdn,
        "zone": {"id": zone.id, "name": zone.name},
        "account_id": zone.account_id,
        "verdict": verdict,
        "live": live,
        "steps": steps,
        "blocked": blocked,
    }
    plan["fingerprint"] = fingerprint(plan)
    return plan, context


def plan_for(
    client: Cloudflare, store: Store, zone_id: object, label: object, fallback: object, serving: set[str]
) -> tuple[dict, PlanContext]:
    """`build_plan` with what this app knows: hosts set up, pages pointing at the name, install id, item limit. Raises
    PlanRefused (unknown zone) or Invalid (label, fallback)."""
    zone = find_zone(client, zone_id)
    fqdn = host_of(check_label(label), zone)
    hosts = store.cf_hosts()
    taken = {row["host"] for row in hosts}
    page = check_fallback(fallback, taken, serving, fqdn)
    pointed = any(row["fallback"] and url_host(row["fallback"]) == fqdn for row in hosts)
    return build_plan(
        client,
        zone,
        label,
        page,
        serving,
        pointed,
        install=store.install_id(),
        taken=taken,
        limit=store.item_limit,
    )


def run_plan(client: Cloudflare, plan: dict, context: PlanContext) -> dict:
    """Run the steps of a plan that is not blocked, in their order: the account and host rows to save."""
    account_id = context.zone.account_id
    created_by_us = False
    for step in plan["steps"]:
        action = step["do"]
        if action == "create_list":
            context.list_id = client.create_list(account_id).id
        elif action == "create_entrypoint":
            ruleset = client.create_redirect_entrypoint(account_id)
            context.ruleset_id, context.rule_id = ruleset.id, _our_rule_id(ruleset)
        elif action == "add_rule":
            context.rule_id = _our_rule_id(client.add_rule(account_id, context.ruleset_id))
        elif action == "create_record":
            context.record_id = client.create_dns_record(context.zone.id, context.fqdn).id
            created_by_us = True
        elif action == "keep_ours":
            created_by_us = True
    account = {
        "id": account_id,
        "name": context.zone.account_name,
        "list_id": context.list_id,
        "ruleset_id": context.ruleset_id,
        "rule_id": context.rule_id,
    }
    host = {
        "host": context.fqdn,
        "zone_id": context.zone.id,
        "zone_name": context.zone.name,
        "record_id": context.record_id,
        "created_by_us": created_by_us,
    }
    return {"account": account, "host": host}


def _our_rule_id(ruleset: Ruleset) -> str | None:
    return next((r["id"] for r in ruleset.rules if names_our_list(r) and isinstance(r.get("id"), str)), None)


def apply_plan(
    client: Cloudflare,
    store: Store,
    *,
    zone_id: object,
    label: object,
    fallback: object,
    fingerprint_sent: object,
    confirm_live: bool,
    serving: set[str],
    sync: "Sync | None" = None,
) -> dict:
    """Builds the plan again from Cloudflare now and runs it only when it is the one confirmed. Raises PlanRefused:
    `busy` (409, another setup runs), `plan_stale` (409), the plan's `blocked` code (409), `confirm_live` (400),
    `not_found` (404); or Invalid. Answers `{"host", "plan"}`."""
    if not setup_lock.acquire(blocking=False):
        raise PlanRefused(409, "busy")
    try:
        plan, context = plan_for(client, store, zone_id, label, fallback, serving)
        if not isinstance(fingerprint_sent, str) or not hmac.compare_digest(plan["fingerprint"], fingerprint_sent):
            raise PlanRefused(409, "plan_stale")
        if plan["blocked"]:
            raise PlanRefused(409, plan["blocked"])
        if plan["live"] and confirm_live is not True:
            raise PlanRefused(400, "confirm_live")
        rows = run_plan(client, plan, context)
        page = next((s["target"] for s in plan["steps"] if s["do"] in ("add_fallback", "root_held", "root_full")), None)
        store.save_setup(rows["account"], rows["host"], page)
        log.info("cloudflare: host %s set up in account %s", context.fqdn, context.zone.account_id)
    finally:
        setup_lock.release()
    if sync is not None:
        sync.wake()
    return {"host": context.fqdn, "plan": plan}


def change_fallback(
    store: Store, host: str, value: object, serving: set[str], sync: "Sync | None" = None
) -> str | None:
    """A created host's page for unknown paths, or None to remove it. Raises PlanRefused `busy` (409) or `not_found`
    (404, also for an adopted host), or Invalid on `fallback`. Answers the page kept."""
    if not setup_lock.acquire(blocking=False):
        raise PlanRefused(409, "busy")
    try:
        hosts = {row["host"] for row in store.cf_hosts()}
        page = check_fallback(value, hosts, serving)
        if not store.set_fallback(host, page):
            raise PlanRefused(404, "not_found")
    finally:
        setup_lock.release()
    if sync is not None:
        sync.wake()
    return page


# --- Cloudflare sync -----------------------------------------------------------------------------------------------
#
# One daemon thread brings each account's `moonie_redirect` list in line with the links that have a Cloudflare address.
# A pass, per account with a list:
# 1. Settle the operation in flight. One recorded with no id (the process stopped between the two writes) is dropped:
#    an upsert is sent again (idempotent per source), removals wait a pass; for OP_DEADLINE after a lost upsert, a
#    removal that finds no item stays queued (`hold_until`), as the lost write may still land.
# 2. Verify the list still exists (one GET, also the quota read).
# 3. Expire: past its last day (UTC) a link keeps its row, its item is removed.
# 4. Upsert at most ITEMS_PER_CALL pending links, oldest first; one at a time after a refused or failed batch, until
#    one succeeds. An item at the source with no marker of this install is never written over.
# 5. Remove, by marker or exact remote id only.
# 6. Pages for unknown paths, one per operation, after links and removals.
# Every list write comes from this thread, one operation at a time per account. Handlers call `wake()`.

IDLE_WAIT = 60.0
POLL_WAIT = 2.0
TOKEN_TTL = 600.0
UNCHECKED_TTL = 60.0  # a check Cloudflare could not answer is kept this long: a page load does not wait on it again
RETRY_AFTER_CAP = 3600.0
STAMP = "%Y-%m-%dT%H:%M:%SZ"


def failure(code: str, detail: str | None = None) -> str:
    return error_text(code, detail)


def failure_of(error: BaseException) -> str:
    """A Cloudflare failure as a row keeps it: its code, and Cloudflare's cleaned text only as `detail`."""
    if isinstance(error, RateLimited):
        return failure("rate_limited", error.message)
    if isinstance(error, CfError):
        code = {401: "token_invalid", 403: "permission"}.get(error.status, "refused")
        return failure(code, f"{error.status}: {error.message}" if error.message else str(error.status))
    if isinstance(error, CfUnreachable):
        return failure("unreachable", error.kind)
    return failure("internal", type(error).__name__)


def describe(error: BaseException) -> str:
    """What a log line says of a failure: its status and Cloudflare's codes, or why Cloudflare was not reached. Never
    Cloudflare's text, which may echo a target, and never the request."""
    if isinstance(error, CfError):
        return f"cloudflare answered {error.status} {list(error.codes)}"
    if isinstance(error, CfUnreachable):
        return str(error)
    return type(error).__name__


def _may_have_landed(error: BaseException) -> bool:
    """Whether a POST that raised may still write its items: a 4xx or a 429 says it did not, `not_sent` that it never
    got there. A timeout, a 5xx or an answer that cannot be read says nothing."""
    if isinstance(error, CfUnreachable):
        return not error.not_sent
    if isinstance(error, CfError):
        return error.status >= 500
    return not isinstance(error, ValueError)  # a ValueError is the client refusing before any I/O


def _names(message: str, source: str) -> bool:
    """Whether Cloudflare's message names this source as a whole, not as the start of a longer one. A message cut at
    MESSAGE_LIMIT names nothing where the cut falls."""
    text = message or ""
    cut = len(text) >= MESSAGE_LIMIT
    pattern = rf"(?<![\w./-]){re.escape(source)}(?![\w./-])"
    return any(not (cut and found.end() == len(text)) for found in re.finditer(pattern, text))


class _Listing:
    """A list's items by `source_key`, read at most once until forgotten, and only when needed."""

    def __init__(self, client: Cloudflare, account_id: str, list_id: str) -> None:
        self._client, self._account_id, self._list_id = client, account_id, list_id
        self._by_source: dict[str, list[RemoteItem]] | None = None

    def by_source(self) -> dict[str, list[RemoteItem]]:
        if self._by_source is None:
            found: dict[str, list[RemoteItem]] = {}
            for item in self._client.list_items(self._account_id, self._list_id):
                found.setdefault(source_key(item.source_url), []).append(item)
            self._by_source = found
        return self._by_source

    def forget(self) -> None:
        """A write went through: an item read before may now be another link's, so the next use reads again."""
        self._by_source = None


class Sync:
    """The sync engine. `client` None: Cloudflare is off and nothing runs. Tests call `run_pass()` with a fake client
    and an injected clock; `start()` runs it in its thread (only `main()` does). `use()` swaps the client while the app
    runs (D27): a pass in flight ends with the client it started with."""

    def __init__(
        self,
        store: Store,
        client: Cloudflare | None,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        admin: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        self.store, self.client = store, client
        self._pass_client: Cloudflare | None = None  # the client of the pass running, which a swap leaves alone
        self._client_lock = threading.Lock()
        self._wanted = False  # start() was called: a client set later starts the thread
        self.admin = frozenset(admin)  # the admin's hosts (D18): no item is ever sent for them
        self.clock = clock or (lambda: datetime.now(UTC))
        self.monotonic = monotonic or (lambda: time.monotonic())
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._pass_lock = threading.Lock()
        self._token: dict | None = None
        self._token_at: float | None = None
        self._token_ttl = TOKEN_TTL
        self._failures = 0
        self._single: set[str] = set()  # accounts sending one link at a time, after a failed batch
        self._thread: threading.Thread | None = None
        self.next_wait = IDLE_WAIT
        self.not_before = float("-inf")  # monotonic time before which nothing is sent: Cloudflare's Retry-After
        self.backoff_until = float("-inf")  # monotonic time before which no pass starts, after a failed pass

    # Life

    def start(self) -> None:
        self._wanted = True
        if self.client is None or (self._thread is not None and self._thread.is_alive()):
            return
        self._thread = threading.Thread(target=self._loop, name="cloudflare-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    def use(self, client: "Cloudflare | None", check: dict | None = None) -> None:
        """Another client from now on, or None to turn Cloudflare off. The token's cached check goes (or becomes
        `check`, the one just made of the new token), the back-off is forgotten, and the thread starts if `start()` was
        called and none runs."""
        with self._client_lock:
            self.client = client
            self._token = None if check is None else dict(check)
            self._token_at = None if check is None else self.monotonic()
            self._token_ttl = TOKEN_TTL if check is None or check["state"] != "unchecked" else UNCHECKED_TTL
            self._failures, self.backoff_until = 0, float("-inf")
            self._single.clear()
        if client is not None and self._wanted:
            self.start()
        self.wake()

    def rate_held(self) -> bool:
        """Whether Cloudflare asked for a wait no call sleeps through: handlers send nothing either until then."""
        return self.monotonic() < self.not_before

    def sync_now(self) -> int:
        """Every link in error and every page for unknown paths back to pending, the back-off forgotten, the thread
        woken. Answers how many rows went back."""
        count = self.store.retry_all()
        self._failures, self.backoff_until = 0, float("-inf")
        self.wake()
        return count

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_pass()
            except Exception as error:  # a pass that crashes is logged and tried again after its back-off
                self._failed_pass()
                log.error("cloudflare sync pass failed: %s", describe(error))
            self._wake.wait(self.next_wait)
            while not self._stop.is_set():
                left = max(self.not_before, self.backoff_until) - self.monotonic()
                if left <= 0:
                    break
                self._stop.wait(left)
            self._wake.clear()

    def _failed_pass(self) -> None:
        self._failures += 1
        self.backoff_until = self.monotonic() + backoff_delay(self._failures)
        self.next_wait = max(self.next_wait, backoff_delay(self._failures))

    def _now(self) -> str:
        return self.clock().strftime(STAMP)

    def _later(self, seconds: float) -> str:
        return (self.clock() + timedelta(seconds=seconds)).strftime(STAMP)

    # The token

    def token_state(self, *, refresh: bool = False) -> dict:
        """`{"state": ok|invalid|unchecked|off, "missing", "unverified", "checked_at"}`, cached TOKEN_TTL seconds. A
        check Cloudflare could not answer is `unchecked`, cached UNCHECKED_TTL seconds only: a page load answers from it
        rather than wait on Cloudflare again. `refresh` checks again whatever is cached."""
        unchecked = {"state": "unchecked", "missing": [], "unverified": [], "checked_at": None}
        client = self.client
        if client is None:
            return unchecked | {"state": "off"}
        fresh = self._token_at is not None and self.monotonic() - self._token_at < self._token_ttl
        if self._token is not None and fresh and not refresh:
            return dict(self._token)
        if self.rate_held():
            return dict(self._token) if self._token else unchecked
        try:
            check = client.verify_token()
        except (CfError, CfUnreachable) as error:
            if isinstance(error, RateLimited):
                self.not_before = self.monotonic() + min(error.retry_after, RETRY_AFTER_CAP)
            log.warning("cloudflare token check failed: %s", describe(error))
            with self._client_lock:
                if self.client is client:  # a check of a token swapped out meanwhile is not kept
                    self._token, self._token_at, self._token_ttl = unchecked, self.monotonic(), UNCHECKED_TTL
            return dict(unchecked)
        found = {
            "state": check.state,
            "missing": list(check.missing),
            "unverified": list(check.unverified),
            "checked_at": self._now(),
        }
        with self._client_lock:
            if self.client is client:
                self._token, self._token_at, self._token_ttl = found, self.monotonic(), TOKEN_TTL
        return dict(found)

    # The pass

    def run_pass(self) -> None:
        with self._pass_lock:
            self.next_wait = IDLE_WAIT
            self._pass_client = self.client
            if self._pass_client is None or self.rate_held():
                return
            if self.token_state()["state"] == "invalid":
                return
            install = self.store.install_id()
            failed = False
            for account in self.store.cf_accounts():
                if not account["list_id"] or self._stop.is_set():
                    continue
                account_id = account["id"]
                try:
                    failed = self._account_pass(account_id, install) or failed
                except (CfError, CfUnreachable) as error:
                    failed = True
                    self._set_account_error(account_id, failure_of(error))
                    log.warning("cloudflare sync of account %s failed: %s", account_id, describe(error))
                    if isinstance(error, RateLimited):
                        self.not_before = self.monotonic() + min(error.retry_after, RETRY_AFTER_CAP)
                        break  # every call waits, the other accounts' too
                except Exception as error:  # what is wrong with one account does not stop the others
                    failed = True
                    self._set_account_error(account_id, failure_of(error))
                    log.error("cloudflare sync of account %s crashed: %s", account_id, describe(error))
            if failed:
                self._failed_pass()
            else:
                self._failures = 0

    def _account_pass(self, account_id: str, install: str) -> bool:
        """One account's share of a pass. True when Cloudflare refused a batch or failed an operation: the pass backs
        off, and the same writes are not sent again a second later."""
        outcome = self._settle(account_id)
        if outcome == "running":
            return False
        failed = outcome == "failed"
        account = self.store.cf_account(account_id)
        lists = self._pass_client.lists(account_id)
        ours = next((row for row in lists if row.id == account["list_id"]), None)
        used = sum(row.num_items for row in lists if row.kind == "redirect")
        with self.store.write() as conn:
            conn.execute(
                "UPDATE cf_accounts SET items_used = ?, lists_used = ?, quota_checked_at = ? WHERE id = ?",
                (used, len(lists), self._now(), account_id),
            )
        if ours is None or ours.name != LIST_NAME:
            self._set_account_error(account_id, failure("list_missing"))
            log.warning("cloudflare: the list of account %s is missing: nothing is sent", account_id)
            return False
        self._expire(account_id)
        held = self._refuse_admin(account_id)
        listing = _Listing(self._pass_client, account_id, account["list_id"])
        sent = self._upsert(account_id, install, listing)
        failed = failed or sent == "refused"
        marked = held or sent == "marked"
        if sent == "sent":
            listing.forget()
            second = self._settle(account_id)
            if second == "running":
                return failed
            failed = failed or second == "failed"
        # After a lost or failed operation, removals wait a pass: the writes behind them go first
        if outcome not in ("lost", "failed"):
            if self._remove(account_id, install, listing) == "sent":
                listing.forget()
                second = self._settle(account_id)
                if second == "running":
                    return failed
                failed = failed or second == "failed"
        sent = self._send_root(account_id, install, listing)
        marked = marked or sent == "marked"
        if sent == "sent":
            listing.forget()
            failed = self._settle(account_id) == "failed" or failed
        if not failed and not marked:
            # A pass with no failure ends the account's last error, so an idle account shows no failure long over
            self._set_account_error(account_id, None)
        return failed

    # Operations

    def _begin_op(self, account_id: str, kind: str, items: list[dict]) -> bool:
        """Record an operation before it is sent; False when one is already recorded."""
        with self.store.write() as conn:
            return (
                conn.execute(
                    "UPDATE cf_accounts SET op_kind = ?, op_items = ?, op_id = NULL, op_started_at = ?"
                    " WHERE id = ? AND op_kind IS NULL",
                    (kind, json.dumps(items, separators=(",", ":")), self._now(), account_id),
                ).rowcount
                == 1
            )

    def _set_op_id(self, account_id: str, op_id: str) -> None:
        with self.store.write() as conn:
            conn.execute("UPDATE cf_accounts SET op_id = ? WHERE id = ?", (op_id, account_id))

    def _clear_op(self, conn: sqlite3.Connection, account_id: str) -> None:
        conn.execute(
            "UPDATE cf_accounts SET op_kind = NULL, op_items = NULL, op_id = NULL, op_started_at = NULL WHERE id = ?",
            (account_id,),
        )

    def _hold(self, conn: sqlite3.Connection, account_id: str, started_at: str | None) -> None:
        """Until OP_DEADLINE after the lost upsert started (never past OP_DEADLINE from now), a removal that finds no
        item stays queued. A later hold never shortens one already set."""
        start = self._now() if started_at is None else min(started_at, self._now())
        until = (datetime.strptime(start, STAMP).replace(tzinfo=UTC) + timedelta(seconds=OP_DEADLINE)).strftime(STAMP)
        conn.execute(
            "UPDATE cf_accounts SET hold_until = ? WHERE id = ? AND (hold_until IS NULL OR hold_until < ?)",
            (until, account_id, until),
        )

    def _holding(self, account: dict) -> bool:
        hold = account["hold_until"]
        return hold is not None and self._now() < min(hold, self._later(OP_DEADLINE))

    def _set_account_error(self, account_id: str, error: str | None) -> None:
        with self.store.write() as conn:
            conn.execute("UPDATE cf_accounts SET last_error = ? WHERE id = ?", (error, account_id))

    def _mark(self, conn: sqlite3.Connection, refs: list[dict], error: str) -> None:
        """Rows in error, where the revision sent is still theirs."""
        for ref in refs:
            if "link" in ref:
                conn.execute(
                    f"UPDATE {TABLE} SET cf_state = 'error', cf_error = ?"
                    " WHERE id = ? AND rev = ? AND address IS NOT NULL",
                    (error, ref["link"], ref["rev"]),
                )
            elif "root" in ref:
                conn.execute(
                    "UPDATE cf_hosts SET fallback_state = 'error', fallback_error = ?"
                    " WHERE host = ? AND fallback_rev = ? AND fallback IS NOT NULL",
                    (error, ref["root"], ref["rev"]),
                )

    def _settle(self, account_id: str) -> str | None:
        """Poll the operation in flight: None with none, else `completed`, `failed`, `running`, `lost` (recorded without
        an id, or unknown to Cloudflare: dropped) or `expired` (past OP_DEADLINE: dropped)."""
        account = self.store.cf_account(account_id)
        if account is None or account["op_kind"] is None:
            return None
        kind, refs = account["op_kind"], json.loads(account["op_items"] or "[]")
        if account["op_id"] is None:
            return self._lost(account, "an unconfirmed")
        try:
            status, error = self._pass_client.bulk_operation(account_id, account["op_id"])
        except (CfError, CfUnreachable, ValueError) as problem:
            if isinstance(problem, ValueError) or (isinstance(problem, CfError) and problem.status == 404):
                return self._lost(account, "a lost")
            if self._age(account) <= OP_DEADLINE:
                raise
            self._expire_op(account)
            if isinstance(problem, RateLimited):
                raise
            return "expired"
        if status == "completed":
            with self.store.write() as conn:
                for ref in refs:
                    if "link" in ref:
                        conn.execute(
                            f"UPDATE {TABLE} SET cf_state = 'active', cf_synced_rev = rev, cf_error = NULL"
                            " WHERE id = ? AND rev = ? AND cf_state = 'pending'",
                            (ref["link"], ref["rev"]),
                        )
                    elif "root" in ref:
                        conn.execute(
                            "UPDATE cf_hosts SET fallback_state = 'active', fallback_synced_rev = fallback_rev,"
                            " fallback_error = NULL WHERE host = ? AND fallback_rev = ? AND fallback_state = 'pending'",
                            (ref["root"], ref["rev"]),
                        )
                    elif ref.get("removal") is not None:
                        conn.execute("DELETE FROM cf_removals WHERE id = ?", (ref["removal"],))
                self._clear_op(conn, account_id)
                conn.execute("UPDATE cf_accounts SET last_sync_at = ? WHERE id = ?", (self._now(), account_id))
            if kind == "upsert":
                self._single.discard(account_id)
            return "completed"
        if status == "failed":
            fault = failure("operation_failed", error)
            with self.store.write() as conn:
                if kind == "upsert" and len(refs) == 1:
                    self._mark(conn, refs, fault)
                elif kind == "upsert":
                    self._single.add(account_id)
                else:  # removals behind these get their turn first
                    for ref in refs:
                        if ref.get("removal") is not None:
                            conn.execute(
                                "UPDATE cf_removals SET queued_at = ? WHERE id = ?", (self._now(), ref["removal"])
                            )
                self._clear_op(conn, account_id)
                conn.execute(
                    "UPDATE cf_accounts SET last_sync_at = ?, last_error = ? WHERE id = ?",
                    (self._now(), fault, account_id),
                )
            log.warning("cloudflare: a %s of %d item(s) of account %s failed", kind, len(refs), account_id)
            return "failed"
        if self._age(account) > OP_DEADLINE:
            self._expire_op(account)
            return "expired"
        self.next_wait = min(self.next_wait, POLL_WAIT)
        return "running"

    def _age(self, account: dict) -> float:
        try:
            started = datetime.strptime(account["op_started_at"] or "", STAMP).replace(tzinfo=UTC)
        except ValueError:
            return OP_DEADLINE + 1.0
        return (self.clock() - started).total_seconds()

    def _lost(self, account: dict, what: str) -> str:
        with self.store.write() as conn:
            if account["op_kind"] == "upsert":
                self._hold(conn, account["id"], account["op_started_at"])
            self._clear_op(conn, account["id"])
        log.info("cloudflare: %s %s of account %s is dropped", what, account["op_kind"], account["id"])
        self.next_wait = min(self.next_wait, POLL_WAIT)
        return "lost"

    def _expire_op(self, account: dict) -> None:
        with self.store.write() as conn:
            if account["op_kind"] == "upsert":
                self._hold(conn, account["id"], self._now())
            self._clear_op(conn, account["id"])
            conn.execute(
                "UPDATE cf_accounts SET last_error = ? WHERE id = ?", (failure("operation_expired"), account["id"])
            )
        log.warning("cloudflare: a %s of account %s ran past its deadline: dropped", account["op_kind"], account["id"])

    def _write(self, account_id: str, refs: list[dict], payload: list[dict], sources: list[str]) -> str | None:
        """Send items as one upsert: `sent`, `refused` (Cloudflare refused the batch and named nobody: the pass backs
        off and one link at a time follows), `marked` (the rows it named, or the lone one, hold the error) or None."""
        account = self.store.cf_account(account_id)
        if not self._begin_op(account_id, "upsert", refs):
            return None
        try:
            op_id = self._pass_client.add_items(account_id, account["list_id"], payload)
        except Exception as error:
            with self.store.write() as conn:
                if _may_have_landed(error):
                    self._hold(conn, account_id, self._now())
                self._clear_op(conn, account_id)
            if (
                not isinstance(error, CfError)
                or isinstance(error, RateLimited)
                or error.status not in (400, 409, 413, 422)
            ):
                raise
            named = [ref for ref, source in zip(refs, sources, strict=True) if _names(error.message, source)]
            if not named and len(refs) == 1:
                named = refs
            with self.store.write() as conn:
                if named:
                    self._mark(conn, named, failure_of(error))
                else:
                    self._single.add(account_id)
                conn.execute("UPDATE cf_accounts SET last_error = ? WHERE id = ?", (failure_of(error), account_id))
            log.warning("cloudflare refused %d item(s) of account %s: %s", len(refs), account_id, describe(error))
            return "marked" if named else "refused"
        self._set_op_id(account_id, op_id)
        return "sent"

    # The steps

    def _expire(self, account_id: str) -> None:
        today = self.clock().date().isoformat()
        with self.store.write() as conn:
            rows = conn.execute(
                f"SELECT l.id, l.kind, l.slug, l.address FROM {TABLE} l JOIN cf_hosts h ON h.host = l.address"
                " WHERE h.account_id = ? AND l.expires_on IS NOT NULL AND l.expires_on < ?"
                " AND l.cf_state IS NOT 'expired' ORDER BY l.id",
                (account_id, today),
            ).fetchall()
            for row in rows:
                conn.execute(f"UPDATE {TABLE} SET cf_state = 'expired', cf_error = NULL WHERE id = ?", (row["id"],))
                source = link_source(row["address"], row["kind"], row["slug"], row["id"])
                Store._queue_removal(conn, account_id, source, row["id"], "expired")
        if rows:
            log.info("cloudflare: %d link(s) of account %s expired", len(rows), account_id)

    def _refuse_admin(self, account_id: str) -> bool:
        """D18: a host of this account that is now the admin's (MOONIE_REDIRECT_PUBLIC_BASE_URL moved onto it) takes
        no item: its pending links and its pending page for unknown paths go to error `admin_host`, and so does the
        account, until the host is no longer the admin's. True when the account has such a host."""
        if not self.admin:
            return False
        with self.store.read() as conn:
            hosts = [
                row["host"]
                for row in conn.execute("SELECT host FROM cf_hosts WHERE account_id = ? ORDER BY host", (account_id,))
                if row["host"] in self.admin
            ]
        if not hosts:
            return False
        error = failure("admin_host")
        marks = ",".join("?" * len(hosts))
        with self.store.write() as conn:
            conn.execute(
                f"UPDATE {TABLE} SET cf_state = 'error', cf_error = ?"
                f" WHERE cf_state = 'pending' AND address IN ({marks})",
                (error, *hosts),
            )
            conn.execute(
                "UPDATE cf_hosts SET fallback_state = 'error', fallback_error = ?"
                f" WHERE fallback_state = 'pending' AND fallback IS NOT NULL AND host IN ({marks})",
                (error, *hosts),
            )
            conn.execute("UPDATE cf_accounts SET last_error = ? WHERE id = ?", (error, account_id))
        log.warning("cloudflare: %s is the admin's host: nothing is sent for it", ", ".join(hosts))
        return True

    def _upsert(self, account_id: str, install: str, listing: _Listing) -> str | None:
        limit = 1 if account_id in self._single else ITEMS_PER_CALL
        with self.store.read() as conn:
            rows = conn.execute(
                f"SELECT l.* FROM {TABLE} l JOIN cf_hosts h ON h.host = l.address"
                " WHERE h.account_id = ? AND l.cf_state = 'pending' ORDER BY l.updated_at, l.id LIMIT ?",
                (account_id, limit),
            ).fetchall()
        if not rows:
            return None
        by_source = listing.by_source()
        refs, payload, sources, foreign = [], [], [], []
        for row in rows:
            source = link_source(row["address"], row["kind"], row["slug"], row["id"])
            there = by_source.get(source_key(source), [])
            ref = {"link": row["id"], "rev": row["rev"]}
            if any(entry_of(item.comment, install) is None for item in there):
                foreign.append(ref)
                continue
            refs.append(ref)
            sources.append(source)
            payload.append(make_item(source, row["target"], row["http_status"], install, row["id"]))
        if foreign:
            with self.store.write() as conn:
                self._mark(conn, foreign, failure("foreign_item"))
            log.warning("cloudflare: %s wait for an item this install did not write", [r["link"] for r in foreign])
        return self._write(account_id, refs, payload, sources) if refs else None

    def _remove(self, account_id: str, install: str, listing: _Listing) -> str | None:
        with self.store.read() as conn:
            removals = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM cf_removals WHERE account_id = ? ORDER BY queued_at, id", (account_id,)
                )
            ]
            if not removals:
                return None
            live: dict[str, str] = {}
            for row in conn.execute(
                f"SELECT kind, slug, id, address FROM {TABLE} WHERE address IS NOT NULL AND cf_state IS NOT 'expired'"
            ):
                live[source_key(link_source(row["address"], row["kind"], row["slug"], row["id"]))] = row["id"]
            for row in conn.execute("SELECT host FROM cf_hosts WHERE fallback IS NOT NULL"):
                live[source_key(fallback_source(row["host"]))] = FALLBACK_MARKER
            states = {
                row["id"]: row["cf_state"]
                for row in conn.execute(
                    f"SELECT id, cf_state FROM {TABLE} WHERE id IN (SELECT after_link FROM cf_removals"
                    " WHERE account_id = ? AND after_link IS NOT NULL)",
                    (account_id,),
                )
            }
        account = self.store.cf_account(account_id)
        holding = self._holding(account)
        dropped, chosen, ids = [], [], {}
        by_source = None
        for removal in removals:
            key = source_key(removal["source"])
            holder = live.get(key)
            if removal["remote_id"] is None and holder == removal["marker"]:
                dropped.append(removal["id"])  # its link holds that source again: the item is that link's now
                continue
            if removal["reason"] == "moved" and states.get(removal["after_link"]) in ("pending", "error"):
                self.next_wait = min(self.next_wait, 5.0)  # waits until the link is active at its new source
                continue
            by_source = listing.by_source() if by_source is None else by_source
            match = None
            for item in by_source.get(key, []):
                if removal["remote_id"] is not None:
                    match = item if item.id == removal["remote_id"] else None
                    if match is not None and holder is not None and entry_of(item.comment, install) == holder:
                        match = None  # Compare's item is now the live link's own, written over in place
                        dropped.append(removal["id"])
                        break
                elif entry_of(item.comment, install) == removal["marker"]:
                    match = item
                if match is not None:
                    break
            if match is None:
                if not holding and removal["id"] not in dropped:
                    dropped.append(removal["id"])
            elif match.id in ids or len(ids) < ITEMS_PER_CALL:
                ids[match.id] = None
                # While held, the item goes and its row stays, for what the lost upsert may still write
                chosen.append({"removal": None if holding else removal["id"], "item": match.id})
        if dropped:
            with self.store.write() as conn:
                conn.executemany("DELETE FROM cf_removals WHERE id = ?", [(rid,) for rid in dropped])
        if not chosen or not self._begin_op(account_id, "delete", chosen):
            return None
        try:
            op_id = self._pass_client.delete_items(account_id, account["list_id"], list(ids))
        except Exception:
            with self.store.write() as conn:
                self._clear_op(conn, account_id)
            raise
        self._set_op_id(account_id, op_id)
        return "sent"

    def _send_root(self, account_id: str, install: str, listing: _Listing) -> str | None:
        """The first pending page for unknown paths that can go, alone; never during a hold."""
        account = self.store.cf_account(account_id)
        if account["op_kind"] is not None or self._holding(account):
            return None
        with self.store.read() as conn:
            roots = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM cf_hosts WHERE account_id = ? AND fallback IS NOT NULL"
                    " AND fallback_state = 'pending' AND created_by_us = 1 ORDER BY host",
                    (account_id,),
                )
            ]
            hosts = {row["host"] for row in conn.execute("SELECT host FROM cf_hosts")}
            promised = Store.new_items(conn, account_id)
        for root in roots:
            ref = {"root": root["host"], "rev": root["fallback_rev"]}
            source = fallback_source(root["host"])
            error = None
            there = listing.by_source().get(source_key(source), [])
            if url_host(root["fallback"]) in hosts:
                error = failure("page_loop")
            elif any(not is_our_fallback(item, install) for item in there):
                error = failure("foreign_item")
            elif root["fallback_synced_rev"] == 0 and not there and promised > self.store.item_limit:
                error = failure("list_full")
            else:
                try:
                    if serves_traffic(self._pass_client.dns_records(root["zone_id"], root["host"])):
                        error = failure("origin_live")
                except CfError as problem:
                    if isinstance(problem, RateLimited) or problem.status in (401, 403) or problem.status >= 500:
                        raise
                    error = failure_of(problem)
            if error is not None:
                with self.store.write() as conn:
                    self._mark(conn, [ref], error)
                log.warning("cloudflare: the page for unknown paths of %s is not sent: %s", root["host"], error)
                continue
            item = make_item(source, root["fallback"], FALLBACK_STATUS, install, FALLBACK_MARKER)
            return self._write(account_id, [ref], [item], [source])
        return None


def cloudflare_item_limit(env: dict) -> int:
    """MOONIE_REDIRECT_CLOUDFLARE_ITEM_LIMIT: list items allowed per account, 10 000 on the free plan by default."""
    value = env.get("MOONIE_REDIRECT_CLOUDFLARE_ITEM_LIMIT", "").strip()
    if not value:
        return 10000
    if not value.isdigit() or int(value) < 1:
        raise SystemExit("MOONIE_REDIRECT_CLOUDFLARE_ITEM_LIMIT must be a whole number of at least 1")
    return int(value)


def cloudflare_client(env: dict, given: Cloudflare | None = None) -> Cloudflare | None:
    """The client of the token in MOONIE_REDIRECT_CLOUDFLARE_TOKEN_FILE, read once at the start, or None: Cloudflare is
    off. Tests hand their fake in `given`."""
    if given is not None:
        return given
    token = read_secret(env, "MOONIE_REDIRECT_CLOUDFLARE_TOKEN_FILE")
    if token is None:
        return None
    try:
        return Cloudflare(token)
    except ValueError:
        raise SystemExit("the Cloudflare token file must hold one printable ASCII token") from None


def cloudflare_import_lines(report: dict | None) -> list[str]:
    """What `import-v7` prints of its Cloudflare step: nothing when 7.0.1 had no plugin tables."""
    if report is None:
        return []
    if report["install"] == "refused":
        return [
            "cloudflare: not imported: this database already set Cloudflare hosts up under another install id,"
            " so every item of 7.0.1 would be foreign (links were imported)"
        ]
    lines = [
        f"cloudflare: accounts {report['accounts']}, hosts {report['hosts']}, pages {report['pages']},"
        f" entries {report['entries']}, entries refused {report['entries_refused']}, removals {report['removals']}"
    ]
    if report["install"] == "invalid":
        lines.append(
            "warning: 7.0.1's install id cannot mark an item, so it was not taken: this app draws its own, and every"
            " item 7.0.1 wrote is foreign (Compare lists them; remove them there, and the links here are sent again)"
        )
    if report["hosts_refused"]:
        refused = ", ".join(report["hosts_refused"])
        lines.append(
            "cloudflare: hosts refused (one host in several spellings, no account, the admin's host, or no host"
            f" name): {refused}"
        )
    if report["pages_refused"]:
        lines.append(
            f"cloudflare: pages for unknown paths refused {report['pages_refused']} (not an http(s) address, on a host"
            " set up here, or on the admin's host): choose them again on the Cloudflare page"
        )
    if report["damaged"]:
        lines.append(f"cloudflare: damaged rows left out {report['damaged']} (a column of the wrong type)")
    lines += [
        f"warning: account {account} had an operation in flight: its removals wait {OP_DEADLINE // 60} minutes"
        for account in report["busy_accounts"]
    ]
    return lines


# --- Cloudflare answers --------------------------------------------------------------------------------------------
#
# What the JSON API says of the Cloudflare state, and Compare: the report of the gaps between the links here and the
# items of each account's list, and the fixes the admin confirmed in it.

LAN = "lan"  # the `address` of a link that answers on MOONIE_REDIRECT_PUBLIC_BASE_URL alone
# Why a host's page for unknown paths is not in place, from its error code; any other error reads `refused`
ROOT_BLOCKS = {"foreign_item": "held", "list_full": "full", "origin_live": "live", "page_loop": "loops"}
# A page for unknown paths held back on purpose is no gap: pushing it again would only end where it is
ROOT_HELD_BACK = ("origin_live", "page_loop")
FALLBACK_ID = "fallback:"  # how Compare names a host's page for unknown paths beside link ids
# The sync's own columns: a link's answer says `cloudflare: {state, error}` instead
SYNC_COLUMNS = ("rev", "cf_synced_rev", "cf_state", "cf_error")
COMPARE_IDS_MAX = 10000


def read_error(text: str | None) -> dict | None:
    """An error column as the API answers it, `{"code", "detail"}`: one that cannot be read is `unknown`."""
    if text is None:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        value = None
    if not isinstance(value, dict) or not isinstance(value.get("code"), str):
        return {"code": "unknown", "detail": None}
    detail = value.get("detail")
    return {"code": value["code"], "detail": detail if isinstance(detail, str) and detail else None}


def host_answer(row: dict) -> dict:
    error = read_error(row["fallback_error"])
    return {
        "host": row["host"],
        "zone_id": row["zone_id"],
        "zone_name": row["zone_name"],
        "account_id": row["account_id"],
        "created_by_us": bool(row["created_by_us"]),
        "fallback": row["fallback"],
        "fallback_state": row["fallback_state"],
        "fallback_error": error,
        "fallback_blocked": None if error is None else ROOT_BLOCKS.get(error["code"], "refused"),
        "created_at": row["created_at"],
    }


def cloudflare_state(store: Store, token: dict, *, enabled: bool) -> dict:
    """The Cloudflare page's state: the token, each account's list and quota, the hosts, the links by state."""
    accounts = []
    for row in store.cf_accounts():
        with store.read() as conn:
            used = Store.new_items(conn, row["id"])
        accounts.append(
            {
                "id": row["id"],
                "name": row["name"],
                "list": {"id": row["list_id"]} if row["list_id"] else None,
                "quota": {"used": used, "limit": store.item_limit, "lists_used": row["lists_used"] or 0},
                "busy": row["op_kind"] is not None,
                "last_sync_at": row["last_sync_at"],
                "last_error": read_error(row["last_error"]),
            }
        )
    with store.read() as conn:
        removals = conn.execute("SELECT count(*) FROM cf_removals").fetchone()[0]
    return {
        "enabled": enabled,
        "token": {key: token[key] for key in ("state", "missing", "unverified")},
        "checked_at": token["checked_at"],
        "accounts": accounts,
        "hosts": [host_answer(row) for row in store.cf_hosts()],
        "counts": store.cf_counts() | {"removals": removals},
    }


def compare_report(client: Cloudflare, store: Store) -> dict:
    """Per account with a list: `missing` (ids here that Cloudflare lacks), `differs` (ids whose item says another
    target), `extra` (items no link or page here holds, ours or not), `sources` (what each id answers at), and the
    report's `fingerprint`. A link or a page on its way (`pending`) is no gap, nor an expired link; each one is matched
    with its own item, by marker, so another install's item at its source shows as extra."""
    install = store.install_id()
    found = []
    for account in store.cf_accounts():
        if not account["list_id"]:
            continue
        remote: dict[str, list[RemoteItem]] = {}
        for item in client.list_items(account["id"], account["list_id"]):
            remote.setdefault(source_key(item.source_url), []).append(item)
        with store.read() as conn:
            links = conn.execute(
                f"SELECT l.* FROM {TABLE} l JOIN cf_hosts h ON h.host = l.address"
                " WHERE h.account_id = ? AND l.cf_state IS NOT 'expired' ORDER BY l.id",
                (account["id"],),
            ).fetchall()
            roots = conn.execute(
                "SELECT * FROM cf_hosts WHERE account_id = ? AND fallback IS NOT NULL ORDER BY host", (account["id"],)
            ).fetchall()
        taken: set[str] = set()
        missing: list[str] = []
        differs: list[dict] = []
        sources: dict[str, str] = {}
        for row in links:
            source = link_source(row["address"], row["kind"], row["slug"], row["id"])
            item = next(
                (i for i in remote.get(source_key(source), []) if entry_of(i.comment, install) == row["id"]), None
            )
            if item is not None:
                taken.add(item.id)
            if row["cf_state"] == "pending":
                continue
            sources[row["id"]] = f"https://{source}"
            if item is None:
                missing.append(row["id"])
            elif (item.target_url, item.status_code) != (row["target"], row["http_status"]):
                differs.append(
                    {"id": row["id"], "remote": {"target_url": item.target_url, "status_code": item.status_code}}
                )
        for root in roots:
            source = fallback_source(root["host"])
            there = remote.get(source_key(source), [])
            item = next((i for i in there if is_our_fallback(i, install)), None)
            if item is not None:
                taken.add(item.id)
            if root["fallback_state"] == "pending":
                continue
            id_ = FALLBACK_ID + root["host"]
            sources[id_] = f"https://{source}"
            if item is None:
                held_back = (read_error(root["fallback_error"]) or {}).get("code") in ROOT_HELD_BACK
                if not held_back and not there:
                    missing.append(id_)
            elif (item.target_url, item.status_code, item.subpath_matching) != (
                root["fallback"],
                FALLBACK_STATUS,
                True,
            ):
                differs.append({"id": id_, "remote": {"target_url": item.target_url, "status_code": item.status_code}})
        extra = [
            {
                "remote_id": item.id,
                "source_url": item.source_url,
                "target_url": item.target_url,
                "status_code": item.status_code,
                "ours": entry_of(item.comment, install) is not None,
            }
            for key in sorted(remote)
            for item in sorted(remote[key], key=lambda one: one.id)
            if item.id not in taken
        ]
        found.append(
            {"account_id": account["id"], "missing": missing, "differs": differs, "extra": extra, "sources": sources}
        )
    report: dict = {"accounts": found}
    report["fingerprint"] = fingerprint(report)
    return report


def _id_list(body: dict, key: str) -> list[str]:
    value = body.get(key, [])
    if not isinstance(value, list) or len(value) > COMPARE_IDS_MAX or not all(isinstance(i, str) for i in value):
        raise InvalidFields({key: "a list of ids"})
    return list(dict.fromkeys(value))


def apply_compare(client: Cloudflare, store: Store, body: dict) -> dict:
    """Compare's confirmed fixes: the ticked ids go back to `pending`, the ticked extra items are queued for removal by
    their exact remote id. `confirm_remove` must be the count of removals, and the report built again now must be the
    one confirmed (PlanRefused `remote_changed`). Raises InvalidFields for ids the report does not hold."""
    if not isinstance(body.get("fingerprint"), str):
        raise InvalidFields({"fingerprint": "required"})
    push, remove = _id_list(body, "push"), _id_list(body, "remove")
    confirm = body.get("confirm_remove", 0)
    if isinstance(confirm, bool) or not isinstance(confirm, int) or confirm != len(remove):
        raise InvalidFields({"confirm_remove": "the count of the removals"})
    report = compare_report(client, store)
    if not hmac.compare_digest(report["fingerprint"], body["fingerprint"]):
        raise PlanRefused(409, "remote_changed")
    pushable = {i for a in report["accounts"] for i in a["missing"]}
    pushable |= {row["id"] for a in report["accounts"] for row in a["differs"]}
    removable = {
        row["remote_id"]: (a["account_id"], row["source_url"]) for a in report["accounts"] for row in a["extra"]
    }
    errors = {}
    if not set(push) <= pushable:
        errors["push"] = "ids no longer in the report"
    if not set(remove) <= set(removable):
        errors["remove"] = "ids no longer in the report"
    if errors:
        raise InvalidFields(errors)
    links = [i for i in push if not i.startswith(FALLBACK_ID)]
    hosts = [i.removeprefix(FALLBACK_ID) for i in push if i.startswith(FALLBACK_ID)]
    pushed = store.mark_pending(links, hosts)
    queued = 0
    for account_id in sorted({removable[r][0] for r in remove}):
        items = [(removable[r][1], r) for r in remove if removable[r][0] == account_id]
        queued += store.queue_resync_removals(account_id, items)
    if queued:
        log.info("cloudflare: %d remote item(s) confirmed for removal", queued)
    return {"pushed": pushed, "queued_removals": queued}


# --- Settings and secrets ------------------------------------------------------------------------------------------
# The database wins; the file or variable is the fallback while the database has none (D22).

ADMIN_PASSWORD_SETTING = "admin_password"
ITEM_LIMIT_SETTING = "cloudflare_item_limit"
TOKEN_FILE_USED_SETTING = "token_file_last_used"
ITEM_LIMIT_MAX = 10_000_000
STORE_KEY_FILE, STORE_KEY_HEX = "store.key", re.compile(r"[0-9a-fA-F]{64}")
# scrypt at 2^14 takes 16 MiB, which fits the container's 128 MiB; one hash at a time (D24)
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_SALT, SCRYPT_LEN = 1 << 14, 8, 1, 16, 32
SCRYPT_MAXMEM = 64 << 20
PASSWORD_MIN, PASSWORD_MAX = 12, 1024
_hash_lock = threading.Lock()
# An API key: `mrk_` and 32 random bytes; the database keeps its SHA-256 and its first characters (D25)
KEY_PREFIX, KEY_SHOWN, KEY_MAX = "mrk_", 8, 256
KEY_USE_EVERY = 60  # seconds between two writes of a key's last use
FILE_KEY_ID = "file"
KIND_SCOPE = {"link": "redirect:links", "nano": "redirect:nanourls", "qrcode": "redirect:qrcodes"}
WILDCARD_SCOPES = ("*", "redirect:*", "cloudflare:*")
KNOWN_SCOPES = (
    "*",
    "redirect:*",
    *(f"{KIND_SCOPE[kind]}.{right}" for kind in KINDS for right in ("read", "write")),
    "cloudflare:*",
    "cloudflare:read",
    "cloudflare:write",
    "cloudflare:setup",
)


class SecretBox:
    """AES-256-GCM over the rows of `secrets` (D23). The row's name is bound as associated data, so a value moved to
    another row does not open; `key_id` names the key a row was sealed with, so a row of another key reads as
    unreadable rather than failing."""

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("the store key is 32 bytes")
        self._aead = AESGCM(key)
        self.key_id = hmac.new(key, b"key id", hashlib.sha256).hexdigest()[:8]

    def __repr__(self) -> str:
        return f"SecretBox(key_id={self.key_id})"

    def __reduce__(self):  # never pickled, so the key never leaves this way
        raise TypeError("a SecretBox cannot be pickled")

    @staticmethod
    def _aad(name: str) -> bytes:
        return f"moonie-redirect:{name}".encode()

    def seal(self, name: str, text: str) -> tuple[str, bytes, bytes]:
        nonce = secrets.token_bytes(12)
        return self.key_id, nonce, self._aead.encrypt(nonce, text.encode(), self._aad(name))

    def open(self, name: str, key_id: object, nonce: object, value: object) -> str | None:
        if key_id != self.key_id or not isinstance(nonce, bytes) or not isinstance(value, bytes) or len(nonce) != 12:
            return None
        try:
            return self._aead.decrypt(nonce, value, self._aad(name)).decode()
        except (InvalidTag, UnicodeDecodeError):
            return None


class WebhookSecrets:
    """What the webhook needs of the secret store (SealedSecrets in the app, a fake in the tests). `state` is `stored`,
    `missing` or `unreadable` (a row the current key cannot open); `read` gives the value, or None for both of the last
    two."""

    def state(self, name: str) -> str:
        raise NotImplementedError

    def read(self, name: str) -> str | None:
        raise NotImplementedError

    def write(self, name: str, value: str) -> None:
        raise NotImplementedError

    def delete(self, name: str) -> None:
        raise NotImplementedError


class SealedSecrets(WebhookSecrets):
    """The sealed rows of `secrets` by name, for the parts of the app that only need a value: `state` says `stored`,
    `missing` or `unreadable`, `read` gives the value or None, `write` seals one, `delete` drops it."""

    def __init__(self, store: "Store", box: SecretBox) -> None:
        self.store, self.box = store, box

    def state(self, name: str) -> str:
        return self.store.read_sealed(self.box, name)[0]

    def read(self, name: str) -> str | None:
        return self.store.read_sealed(self.box, name)[1]

    def write(self, name: str, value: str) -> None:
        self.store.write_sealed(self.box, name, value)

    def delete(self, name: str) -> bool:
        return self.store.drop_sealed(name)


def draw_file(path: Path, content: bytes) -> bool:
    """`content` written whole to a temporary file (mode 0600), then linked to `path` if nothing is there yet, so a
    crash or a second worker starting at the same time never leaves an empty or short file behind: the loser of the
    race keeps the winner's. True when this call made the file."""
    if path.exists():
        return False
    temp = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temp, path)
        except FileExistsError:
            return False  # another worker linked its file first: use that one
        return True
    finally:
        temp.unlink(missing_ok=True)


def store_key(env: dict, data_dir: Path) -> bytes:
    """The key the secrets are sealed with: MOONIE_REDIRECT_STORE_KEY_FILE (64 hex characters, a compose secret kept
    apart from the data volume), else `store.key` beside the database, drawn once. A file named but unreadable or
    malformed stops the start: the app never seals with a key it was not given."""
    name = env.get("MOONIE_REDIRECT_STORE_KEY_FILE")
    if name:
        try:
            text = read_secret(env, "MOONIE_REDIRECT_STORE_KEY_FILE") or ""
        except (OSError, UnicodeDecodeError):
            raise SystemExit("MOONIE_REDIRECT_STORE_KEY_FILE cannot be read") from None
        if STORE_KEY_HEX.fullmatch(text) is None:
            raise SystemExit("MOONIE_REDIRECT_STORE_KEY_FILE must hold 64 hexadecimal characters (just store-key)")
        return bytes.fromhex(text)
    path = data_dir / STORE_KEY_FILE
    if draw_file(path, secrets.token_hex(32).encode() + b"\n"):
        log.info("drew a new store key into %s", path)
    try:
        text = path.read_text(encoding="ascii", errors="replace").strip()
    except OSError:
        raise SystemExit(f"{path} cannot be read: restore it as a file the app can read") from None
    if STORE_KEY_HEX.fullmatch(text) is None:
        raise SystemExit(f"{path} is damaged: restore it, or delete it and enter the stored secrets again")
    log.warning(
        "the store key is %s, in the data volume: a backup of that volume holds both the secrets and their key;"
        " set MOONIE_REDIRECT_STORE_KEY_FILE to keep it apart",
        path,
    )
    return bytes.fromhex(text)


def hash_password(password: str) -> str:
    """`scrypt$n$r$p$salt$hash`, base64 parts (D24)."""
    salt = secrets.token_bytes(SCRYPT_SALT)
    with _hash_lock:
        digest = hashlib.scrypt(
            password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=SCRYPT_MAXMEM, dklen=SCRYPT_LEN
        )
    b64 = base64.b64encode
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt).decode()}${b64(digest).decode()}"


def password_matches(stored: str, given: str) -> bool:
    """Whether `given` is the password of a `hash_password` value. A damaged value matches nothing."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        n, r, p = int(n), int(r), int(p)
        salt, digest = base64.b64decode(salt, validate=True), base64.b64decode(digest, validate=True)
    except ValueError:
        return False
    if scheme != "scrypt" or not (2 <= n <= 1 << 20 and n & (n - 1) == 0 and 1 <= r <= 32 and 1 <= p <= 4):
        return False
    if not digest or len(digest) > 64:
        return False
    try:
        with _hash_lock:
            found = hashlib.scrypt(given.encode(), salt=salt, n=n, r=r, p=p, maxmem=SCRYPT_MAXMEM, dklen=len(digest))
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(found, digest)


def check_new_password(value: object) -> str:
    if not isinstance(value, str) or not PASSWORD_MIN <= len(value) <= PASSWORD_MAX:
        raise Invalid("new_password", f"{PASSWORD_MIN} to {PASSWORD_MAX} characters")
    return value


def brake_claim() -> float | None:
    """The login brake (LOGIN_BRAKE), shared by the login and every check of the password in the settings: the claim
    to try now, or None when a failure is too recent. A success gives the claim back with `brake_release`."""
    global _last_failure
    with _failure_lock:
        moment = time.monotonic()
        if moment - _last_failure < LOGIN_BRAKE:
            return None
        _last_failure = moment
        return moment


def brake_release(claim: float) -> None:
    global _last_failure
    with _failure_lock:
        if _last_failure == claim:
            _last_failure = float("-inf")


def new_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def key_digest(token: str) -> str:
    """A key's token is 32 random bytes: one SHA-256 suffices, no KDF on every call (D25)."""
    return hashlib.sha256(token.encode()).hexdigest()


def scope_allows(granted: "tuple[str, ...] | list[str] | frozenset[str]", scope: str) -> bool:
    """Whether `granted` holds `scope`: itself, `*`, or `<service>:*`."""
    service = scope.split(":", 1)[0]
    return scope in granted or "*" in granted or f"{service}:*" in granted


def check_scopes(value: object) -> list[str]:
    """A key's scopes: a non-empty list of KNOWN_SCOPES, kept in KNOWN_SCOPES' order, without repeats."""
    if not isinstance(value, list) or not value or not all(isinstance(scope, str) for scope in value):
        raise Invalid("scopes", "one scope at least")
    unknown = [scope for scope in value if scope not in KNOWN_SCOPES]
    if unknown:
        raise Invalid("scopes", "unknown scope: " + ", ".join(sorted(set(unknown)))[:MAX_LOGGED])
    return [scope for scope in KNOWN_SCOPES if scope in value]


def check_item_limit(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= ITEM_LIMIT_MAX:
        raise Invalid("value", f"a whole number from 1 to {ITEM_LIMIT_MAX}, or empty for the default")
    return value


# --- Webhook -------------------------------------------------------------------------------------------------------
# The n8n webhook (D26): each link created, changed or deleted through the API becomes one row of `webhook_outbox`,
# which one thread sends as a signed POST, oldest due first, until the receiver answers 2xx, answers 410, or five
# attempts are spent. A row stays `pending` until its attempt is recorded: a crash means one more delivery, never a lost
# one, and `X-Moonie-Event-Id` lets the receiver drop the copy. The headers and the signature are 7.0.1's, so that n8n
# workflows built for it keep checking them.
#
# The URL, the events, why it is off and the last delivery live in `settings`; the signing secret in the sealed
# `secrets` table, read through the four calls of `WebhookSecrets`. The guard opens global unicast and the LAN's ranges
# only, and the socket connects to the very address the guard judged.

WEBHOOK_SOURCE = "redirect"
WEBHOOK_EVENTS = (
    ("redirect.link.created", "Link created"),
    ("redirect.link.updated", "Link updated"),
    ("redirect.link.deleted", "Link deleted"),
)
# 7.0.1's `EVENT_FIELDS`, then where the link answers and when it last changed; never the design or its logo
EVENT_FIELDS = ("id", "kind", "slug", "name", "target", "http_status", "expires_on", "address", "updated_at")
TEST_EVENT = "moonie.webhook.test"
WEBHOOK_SECRET = "webhook_secret"  # the secret store's row name
SETTING_URL = "webhook_url"
SETTING_EVENTS = "webhook_events"
SETTING_DISABLED = "webhook_disabled_reason"
SETTING_LAST = "webhook_last_delivery"
WEBHOOK_SETTINGS = (SETTING_URL, SETTING_EVENTS, SETTING_DISABLED, SETTING_LAST)
GONE = 410
RETRY_DELAYS = (10, 60, 300, 1800)  # seconds before attempts 2 to 5
JITTER = 0.2
RETRIED_STATUSES = frozenset({408, 429})
MAX_PENDING = 10_000
MAX_EVENT_BYTES = 64 * 1024
MAX_REPLY_BYTES = 64 * 1024
CONNECT_SECONDS = 5.0
ATTEMPT_SECONDS = 30.0
WEBHOOK_IDLE = 60.0
PURGE_AFTER = timedelta(days=7)
PURGE_EVERY = timedelta(hours=1)
CUT_INTERVAL = 0.2
MIN_SECRET, MAX_SECRET, MAX_URL = 16, 256, 2048
MAX_ERROR = 300
_URL_CHARS = re.compile(r"[!-\[\]-~]+", re.ASCII)  # printable ASCII, without space and backslash
_ERROR_CODE = re.compile(r"[A-Za-z0-9_ ]{1,80}")  # a TLS reason, an errno symbol: nothing that could carry a name
_WEBHOOK_LAN = tuple(
    ipaddress.ip_network(text)
    for text in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")
)
_METADATA = tuple(
    ipaddress.ip_address(text)
    for text in (
        "168.63.129.16",
        "100.100.100.200",
        "fd00:ec2::254",
        "fd20:ce::254",
        "fd00:c1::a9fe:a9fe",
        "fd00:42::42",
    )
)
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


class AddressClosed(Exception):
    """The receiver resolves to an address the webhook may not reach."""


def _embedded_ipv4(address: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv6 one reaches through a translation: the check is on where the packets end up."""
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address.sixtofour is not None:
        return address.sixtofour
    if address.teredo is not None:
        return address.teredo[1]
    if address in _NAT64:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return None


def address_refused(text: str) -> bool:
    """Whether the webhook may not connect to this address (7.0.1's list). Open is a list, so that a range nobody
    thought of stays shut: global unicast and the LAN's ranges, less loopback, link-local (the metadata address with
    it), multicast, unspecified, reserved and the known metadata services, also when an IPv6 form carries them."""
    try:
        address: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(text.split("%")[0])
    except ValueError:
        return True
    if isinstance(address, ipaddress.IPv6Address):
        # The packets reach a Teredo client through its server, so both are judged
        if address.teredo is not None and address_refused(str(address.teredo[0])):
            return True
        address = _embedded_ipv4(address) or address
    if address.is_loopback or address.is_link_local or address.is_multicast:
        return True
    if address.is_unspecified or address.is_reserved or address in _METADATA:
        return True
    if isinstance(address, ipaddress.IPv6Address) and address.is_site_local:
        return True
    return not (address.is_global or any(address in network for network in _WEBHOOK_LAN))


def numeric_addresses(host: str) -> list[str]:
    """What the system reads a numeric host as, in every spelling it takes (`127.1`, `2130706433`, `0177.0.0.1`), with
    no lookup. Empty for a name."""
    try:
        return [str(ipaddress.ip_address(host.strip("[]")))]
    except ValueError:
        pass
    try:
        return [socket.inet_ntoa(socket.inet_aton(host))]
    except OSError:
        return []


def valid_webhook_url(url: object) -> bool:
    """http or https with a host, ASCII, at most MAX_URL characters, no user or password, a port of 1 to 65535."""
    if not isinstance(url, str) or len(url) > MAX_URL or _URL_CHARS.fullmatch(url) is None:
        return False
    try:
        parts = urlsplit(url)
        port = parts.port  # raises on a port out of range or not a number
    except ValueError:
        return False
    if port == 0 or "@" in parts.netloc:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def url_origin(url: str) -> str:
    """The scheme, host and port: what a log line may say of the receiver. Its path or query may carry a token."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def sign(secret: str, event_id: str, timestamp: int, body: bytes) -> str:
    """7.0.1's `X-Moonie-Signature`: HMAC-SHA256 of `<id>.<timestamp>.` followed by the body, keyed by the secret."""
    message = f"{event_id}.{timestamp}.".encode() + body
    return "sha256=" + hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def wire_body(event_id: str, event: str, at: str, data: dict) -> bytes:
    """7.0.1's body: `{"id","event","source","at","data"}`, compact UTF-8 JSON."""
    document = {"id": event_id, "event": event, "source": WEBHOOK_SOURCE, "at": at, "data": data}
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def event_data(row: dict) -> dict:
    """What an event says of a link. A link on the LAN says `lan`, as the API does."""
    data = {field: row.get(field) for field in EVENT_FIELDS}
    data["address"] = row.get("address") or LAN
    return data


def describe_failure(exc: BaseException) -> str:
    """One line for the row and the API, from fixed codes only: an exception's own text may quote the receiver (a TLS
    verify message names the host it expected). The type, plus the TLS reason and verify code, or the errno's symbol."""
    if isinstance(exc, AddressClosed):
        return "address_closed"
    if isinstance(exc, TimeoutError):
        return "deadline"
    detail: list[str] = []
    if isinstance(exc, ssl.SSLCertVerificationError):
        detail = [str(exc.reason or ""), f"verify code {exc.verify_code}" if exc.verify_code else ""]
    elif isinstance(exc, ssl.SSLError):
        detail = [str(exc.reason or "")]
    elif isinstance(exc, OSError) and isinstance(exc.errno, int):
        detail = [errno.errorcode.get(exc.errno, "")]
    words = " ".join(part for part in detail if part and _ERROR_CODE.fullmatch(part))
    name = type(exc).__name__
    return (f"{name}: {words}" if words else name)[:MAX_ERROR]


@dataclass(frozen=True)
class Outcome:
    """What one attempt came to. `status` is None when no answer arrived, and `error` says why."""

    status: int | None = None
    body: bytes = b""
    oversize: bool = False
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    @property
    def retried(self) -> bool:
        return self.status is None or self.status in RETRIED_STATUSES or 500 <= self.status < 600


class _Attempt:
    """One POST under a whole deadline. A socket timeout bounds each read only, so a reply that drips one byte at a time
    would outlive it: a watchdog cuts the socket at the deadline, whichever phase the attempt is in. Name resolution
    cannot be cut (getaddrinfo)."""

    def __init__(self, webhook: "Webhook", url: str, headers: dict, body: bytes) -> None:
        self._webhook = webhook
        self._url = url
        self._headers = headers
        self._body = body
        self._limit = webhook.attempt_seconds
        self._conn: http.client.HTTPConnection | None = None
        self._sock: socket.socket | None = None
        self._finished = threading.Event()
        self._expired = False

    def run(self) -> Outcome:
        watchdog = threading.Thread(target=self._watch, name="webhook-deadline", daemon=True)
        try:
            watchdog.start()
            outcome = self._exchange()
        except Exception as exc:  # whatever the network or the peer causes is a failed attempt, never a dead thread
            outcome = Outcome(error=describe_failure(exc))
        finally:
            self._finished.set()
            if self._conn is not None:
                self._conn.close()
        return Outcome(error="deadline") if self._expired else outcome

    def _watch(self) -> None:
        if self._finished.wait(self._limit):
            return
        self._expired = True
        while not self._finished.wait(CUT_INTERVAL):  # a socket a TLS handshake replaced is cut on the next round
            self._cut()

    def _cut(self) -> None:
        conn = self._conn
        for sock in (self._sock, None if conn is None else conn.sock):
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def _exchange(self) -> Outcome:
        parts = urlsplit(self._url)
        host = parts.hostname or ""
        secure = parts.scheme == "https"
        port = parts.port or (http.client.HTTPS_PORT if secure else http.client.HTTP_PORT)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        context = ssl.create_default_context() if secure else None
        conn: http.client.HTTPConnection
        if context is not None:
            conn = http.client.HTTPSConnection(host, port, timeout=self._limit, context=context)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=self._limit)
        self._conn = conn
        sock = self._webhook.connect(host, port, min(CONNECT_SECONDS, self._limit))
        sock.settimeout(self._limit)
        self._sock = conn.sock = sock
        if context is not None:
            # The handshake runs apart from the wrap, so that the watchdog holds the socket a slow handshake is on
            secured = context.wrap_socket(sock, server_hostname=host, do_handshake_on_connect=False)
            self._sock = conn.sock = secured
            secured.do_handshake()
        # Host comes from the name, never the address the socket went to: virtual hosts and TLS see the name
        conn.request("POST", target, body=self._body, headers=self._headers)
        response = conn.getresponse()
        if not 200 <= response.status < 300:
            return Outcome(status=response.status)
        body = bytearray()
        while len(body) <= MAX_REPLY_BYTES:
            chunk = response.read1(MAX_REPLY_BYTES + 1 - len(body))
            if not chunk:
                return Outcome(status=response.status, body=bytes(body))
            body += chunk
        return Outcome(status=response.status, oversize=True)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(STAMP)


def _parse_stamp(text: str) -> datetime:
    return datetime.strptime(text, STAMP).replace(tzinfo=UTC)


class Webhook:
    """The configuration, the outbox and its delivery thread. `resolver`, `allow`, the clocks and `rand` are there for
    the tests alone, which reach a receiver on loopback by opening its network here, never through the environment."""

    def __init__(
        self,
        store: "Store",
        secrets_store: WebhookSecrets,
        *,
        resolver: Callable[..., list] = socket.getaddrinfo,
        allow: tuple = (),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        rand: Callable[[], float] = random.random,
        attempt_seconds: float = ATTEMPT_SECONDS,
    ) -> None:
        self.store = store
        self.secrets = secrets_store
        self.resolver = resolver
        self.allow = tuple(ipaddress.ip_network(network) for network in allow)
        self.clock = clock
        self.monotonic = monotonic
        self.rand = rand
        self.attempt_seconds = attempt_seconds
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._test_lock = threading.Lock()
        self._last_purge: datetime | None = None
        self._secret_reported = False
        # Set by pump() when due rows wait on the admin (webhook off, or its secret unreadable): the thread then sleeps
        # WEBHOOK_IDLE, woken early by a save, instead of polling a due row it cannot send
        self._held = False

    # --- The guard ---

    def address_closed(self, text: str) -> bool:
        try:
            address = ipaddress.ip_address(text.split("%")[0])
        except ValueError:
            return True
        if any(address in network for network in self.allow):
            return False
        return address_refused(text)

    def url_refusal(self, url: str) -> str | None:
        """`url_closed` for an address that can be told closed from its text: `localhost` and numeric hosts. A name is
        judged on what it resolves to, at each attempt."""
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
        if host == "localhost" or host.endswith(".localhost"):
            return "url_closed"
        if any(self.address_closed(address) for address in numeric_addresses(host)):
            return "url_closed"
        return None

    def connect(self, host: str, port: int, limit: float) -> socket.socket:
        """A socket to `host`, connected to an address the guard passed. Every address the name resolves to is judged
        before any is tried, and the socket goes to that literal: a resolver asked again could answer otherwise."""
        deadline = self.monotonic() + limit
        found = self.resolver(host, port, type=socket.SOCK_STREAM)
        if not found or any(self.address_closed(str(entry[4][0])) for entry in found):
            raise AddressClosed
        failure: OSError = OSError("no address")
        for position, entry in enumerate(found):
            share = (deadline - self.monotonic()) / (len(found) - position)
            if share <= 0:
                raise TimeoutError("deadline")
            try:
                sock = socket.create_connection(entry[4][:2], share)
            except OSError as exc:
                failure = exc
                continue
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return sock
        raise failure

    # --- Configuration ---

    def _settings(self, conn: sqlite3.Connection) -> dict:
        rows = conn.execute(
            f"SELECT key, value FROM settings WHERE key IN ({', '.join('?' * len(WEBHOOK_SETTINGS))})",
            WEBHOOK_SETTINGS,
        ).fetchall()
        found = {row["key"]: row["value"] for row in rows}
        events = json.loads(found[SETTING_EVENTS]) if SETTING_EVENTS in found else []
        last = json.loads(found[SETTING_LAST]) if SETTING_LAST in found else None
        return {"url": found.get(SETTING_URL), "events": events, "disabled": found.get(SETTING_DISABLED), "last": last}

    @staticmethod
    def _put(conn: sqlite3.Connection, key: str, value: str, stamp: str) -> None:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, stamp),
        )

    def answer(self) -> dict:
        """The GET answer: the URL in full (the session alone reads it), never the secret, only its state."""
        with self.store.read() as conn:
            current = self._settings(conn)
            waiting = conn.execute("SELECT COUNT(*) FROM webhook_outbox WHERE status = 'pending'").fetchone()[0]
        url = current["url"]
        return {
            "configured": url is not None,
            "url": url,
            "events": current["events"] if url is not None else [],
            "available": [{"name": name, "label": label} for name, label in WEBHOOK_EVENTS],
            "secret": self.secrets.state(WEBHOOK_SECRET),
            "cleartext": url is not None and urlsplit(url).scheme != "https",
            "disabled_reason": current["disabled"] if url is not None else None,
            "last_delivery": current["last"],
            "waiting": waiting,
            "timeout_seconds": int(self.attempt_seconds),
        }

    def save(self, body: dict) -> dict:
        """Checks then stores `{url, events, secret?}`. A secret absent, null or empty keeps the stored one; there must
        be a readable one after the save. A save turns a webhook a 410 disabled back on. Raises InvalidFields."""
        fields: dict[str, str] = {}
        url = body.get("url")
        if not valid_webhook_url(url):
            fields["url"] = "url_invalid"
        else:
            refusal = self.url_refusal(url)
            if refusal is not None:
                fields["url"] = refusal
        known = [name for name, _ in WEBHOOK_EVENTS]
        events = body.get("events")
        if not isinstance(events, list) or not all(isinstance(name, str) and name in known for name in events):
            fields["events"] = "events_invalid"
        secret = body.get("secret")
        if secret in (None, ""):
            secret = None
            if self.secrets.state(WEBHOOK_SECRET) != "stored":
                fields["secret"] = "secret_required"
        elif not isinstance(secret, str) or not MIN_SECRET <= len(secret) <= MAX_SECRET:
            fields["secret"] = "secret_invalid"
        if fields:
            raise InvalidFields(fields)
        if secret is not None:
            self.secrets.write(WEBHOOK_SECRET, secret)
        stamp = _stamp(self.clock())
        with self.store.write() as conn:
            self._put(conn, SETTING_URL, url, stamp)
            self._put(conn, SETTING_EVENTS, json.dumps([name for name in known if name in events]), stamp)
            conn.execute("DELETE FROM settings WHERE key = ?", (SETTING_DISABLED,))
        self._secret_reported = False
        log.info("webhook saved: %s", url_origin(url))
        self.wake()
        return self.answer()

    def clear(self) -> None:
        """The settings first, so that nothing goes out from the moment they commit; the waiting rows with them."""
        with self.store.write() as conn:
            conn.execute(
                f"DELETE FROM settings WHERE key IN ({', '.join('?' * len(WEBHOOK_SETTINGS))})", WEBHOOK_SETTINGS
            )
            conn.execute("DELETE FROM webhook_outbox WHERE status = 'pending'")
        self.secrets.delete(WEBHOOK_SECRET)
        log.info("webhook deleted")

    # --- Events ---

    def emit(self, event: str, row: dict) -> None:
        """Queues `event` for `row`, if the webhook is set, readable, on, and wants it. Never raises: a link saved stays
        saved whatever happens here."""
        try:
            self._emit(event, row)
        except Exception as exc:
            log.warning("webhook event %s not queued: %s", event, type(exc).__name__)

    def _emit(self, event: str, row: dict) -> None:
        if self.secrets.state(WEBHOOK_SECRET) != "stored":
            with self.store.read() as conn:
                configured = self._settings(conn)["url"] is not None
            if configured:
                log.warning("webhook event %s not queued: the signing secret cannot be read", event)
            return
        moment = self.clock()
        stamp = _stamp(moment)
        event_id = "evt_" + secrets.token_hex(16)
        body = wire_body(event_id, event, stamp, event_data(row))
        if len(body) > MAX_EVENT_BYTES:
            log.warning("webhook event %s not queued: larger than %d bytes", event, MAX_EVENT_BYTES)
            return
        with self.store.write() as conn:
            current = self._settings(conn)
            if current["url"] is None or current["disabled"] is not None or event not in current["events"]:
                return
            pending = conn.execute("SELECT COUNT(*) FROM webhook_outbox WHERE status = 'pending'").fetchone()[0]
            if pending >= MAX_PENDING:
                log.warning("webhook outbox full (%d waiting): event %s dropped", MAX_PENDING, event)
                return
            conn.execute(
                "INSERT INTO webhook_outbox (id, event, body, created_at, status, attempts, next_attempt_at)"
                " VALUES (?, ?, ?, ?, 'pending', 0, ?)",
                (event_id, event, body, stamp, stamp),
            )
        self.wake()

    # --- Delivery ---

    def headers(self, secret: str, event_id: str, event: str, body: bytes) -> dict:
        timestamp = int(self.clock().timestamp())
        return {
            "Content-Type": "application/json",
            "User-Agent": f"moonie-redirect/{VERSION}",
            "X-Moonie-Event": event,
            "X-Moonie-Event-Id": event_id,
            "X-Moonie-Timestamp": str(timestamp),
            "X-Moonie-Signature": sign(secret, event_id, timestamp, body),
        }

    def wake(self) -> None:
        self._wake.set()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            if not self._stop.is_set():
                return
            # A stop() that timed out mid-attempt: the old thread ends after that attempt, never beside a new one
            self._thread.join(self.attempt_seconds + 5.0)
            if self._thread.is_alive():
                raise RuntimeError("the previous webhook thread has not stopped yet")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="webhook", daemon=True)
        self._thread.start()

    def stop(self, wait: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(wait)
            # Still in an attempt: kept, so start() waits for it rather than run a second thread beside it
            if not self._thread.is_alive():
                self._thread = None

    def _loop(self) -> None:
        failing = False
        while not self._stop.is_set():
            try:
                while not self._stop.is_set() and self.pump():
                    pass
                failing = False
                pause = WEBHOOK_IDLE if self._held else self.idle_seconds()
            except Exception as exc:  # a database busy for a moment must not end delivery for good
                if not failing:
                    log.warning("webhook thread: %s", type(exc).__name__)
                failing = True
                pause = WEBHOOK_IDLE
            self._wake.wait(pause)
            self._wake.clear()

    def idle_seconds(self) -> float:
        """Until the next due row, at most WEBHOOK_IDLE."""
        with self.store.read() as conn:
            row = conn.execute("SELECT MIN(next_attempt_at) FROM webhook_outbox WHERE status = 'pending'").fetchone()
        if row[0] is None:
            return WEBHOOK_IDLE
        wait = (_parse_stamp(row[0]) - self.clock()).total_seconds()
        return min(WEBHOOK_IDLE, max(0.0, wait))

    def purge(self) -> int:
        """Finished rows older than PURGE_AFTER go, once an hour."""
        moment = self.clock()
        if self._last_purge is not None and abs(moment - self._last_purge) < PURGE_EVERY:
            return 0
        self._last_purge = moment
        with self.store.write() as conn:
            return conn.execute(
                "DELETE FROM webhook_outbox WHERE status <> 'pending' AND finished_at < ?",
                (_stamp(moment - PURGE_AFTER),),
            ).rowcount

    def pump(self) -> bool:
        """One attempt for the oldest due row, when the webhook is set, on, and its secret readable. True when an
        attempt was made, so the caller goes on with the next."""
        self._held = False
        self.purge()
        moment = self.clock()
        with self.store.read() as conn:
            current = self._settings(conn)
            if current["url"] is None or current["disabled"] is not None:
                self._held = True
                return False
            row = conn.execute(
                "SELECT id, event, body FROM webhook_outbox WHERE status = 'pending' AND next_attempt_at <= ?"
                " ORDER BY next_attempt_at, rowid LIMIT 1",
                (_stamp(moment),),
            ).fetchone()
        if row is None:
            return False
        secret = self.secrets.read(WEBHOOK_SECRET)
        if secret is None:
            # The rows wait, with no attempt counted, until a secret is entered again
            if not self._secret_reported:
                self._secret_reported = True
                log.warning("webhook: the signing secret cannot be read, events wait until it is entered again")
            self._held = True
            return False
        url = current["url"]
        body = bytes(row["body"])
        outcome = _Attempt(self, url, self.headers(secret, row["id"], row["event"], body), body).run()
        self._record(url, row["id"], row["event"], outcome)
        return True

    def _record(self, url: str, event_id: str, event: str, outcome: Outcome) -> None:
        moment = self.clock()
        stamp = _stamp(moment)
        last = {"event_id": event_id, "event": event, "status": outcome.status, "at": stamp, "error": outcome.error}
        note: str | None = None
        with self.store.write() as conn:
            found = conn.execute("SELECT attempts FROM webhook_outbox WHERE id = ?", (event_id,)).fetchone()
            current = self._settings(conn)
            # Deleted, or the webhook moved, while the attempt ran: its answer says nothing of the webhook now
            if found is None or current["url"] != url:
                return
            attempts = found["attempts"] + 1
            if outcome.status == GONE:
                self._put(conn, SETTING_DISABLED, "gone", stamp)
                conn.execute("UPDATE webhook_outbox SET last_status = ? WHERE id = ?", (GONE, event_id))
                note = "webhook disabled: the receiver answered 410, Save turns it back on"
            elif outcome.success:
                self._finish(conn, event_id, "delivered", attempts, outcome, stamp)
            elif outcome.retried and attempts <= len(RETRY_DELAYS):
                delay = RETRY_DELAYS[attempts - 1] * (1 - JITTER + 2 * JITTER * self.rand())
                conn.execute(
                    "UPDATE webhook_outbox SET attempts = ?, next_attempt_at = ?, last_status = ?, last_error = ?"
                    " WHERE id = ?",
                    (attempts, _stamp(moment + timedelta(seconds=delay)), outcome.status, outcome.error, event_id),
                )
            else:
                self._finish(conn, event_id, "failed", attempts, outcome, stamp)
                note = f"webhook gave up on {event_id} after {attempts} attempt(s): {outcome.status or outcome.error}"
            self._put(conn, SETTING_LAST, json.dumps(last), stamp)
        if note is not None:
            log.warning(note)

    @staticmethod
    def _finish(conn: sqlite3.Connection, event_id: str, status: str, attempts: int, outcome: Outcome, at: str) -> None:
        conn.execute(
            "UPDATE webhook_outbox SET status = ?, attempts = ?, last_status = ?, last_error = ?, finished_at = ?"
            " WHERE id = ?",
            (status, attempts, outcome.status, outcome.error, at, event_id),
        )

    def test(self) -> dict | None:
        """One `moonie.webhook.test`, now, outside the outbox, never retried. None while another test runs.
        Raises LookupError when there is nothing to test."""
        if not self._test_lock.acquire(blocking=False):
            return None
        try:
            with self.store.read() as conn:
                url = self._settings(conn)["url"]
            secret = self.secrets.read(WEBHOOK_SECRET)
            if url is None or secret is None:
                raise LookupError("not_configured")
            event_id = "evt_" + secrets.token_hex(16)
            body = wire_body(event_id, TEST_EVENT, _stamp(self.clock()), {})
            started = self.monotonic()
            outcome = _Attempt(self, url, self.headers(secret, event_id, TEST_EVENT, body), body).run()
            duration = max(0, int((self.monotonic() - started) * 1000))
            log.info("webhook test to %s: %s", url_origin(url), outcome.status or outcome.error)
            return {
                "status": outcome.status,
                "duration_ms": duration,
                "error": outcome.error,
                "reply_is_json": outcome.success and not outcome.oversize and _is_json(outcome.body),
            }
        finally:
            self._test_lock.release()


def _is_json(body: bytes) -> bool:
    try:
        json.loads(body.decode("utf-8"))
    except (ValueError, RecursionError):
        return False
    return True


# --- Web -----------------------------------------------------------------------------------------------------------


def read_secret(env: dict, name: str) -> str | None:
    path = env.get(name)
    if not path:
        return None
    # utf-8-sig drops the byte order mark some Windows editors write first
    text = Path(path).read_text(encoding="utf-8-sig").strip()
    return text or None


def session_key(data_dir: Path) -> bytes:
    """32 random bytes, drawn once at the first start into `session.key` (mode 0600) beside the database (`draw_file`:
    the loser of a race between two workers reads the winner's key)."""
    path = data_dir / SESSION_KEY_FILE
    draw_file(path, secrets.token_bytes(SESSION_KEY_BYTES))
    key = path.read_bytes()
    if len(key) != SESSION_KEY_BYTES:
        raise SystemExit(f"{path} is damaged: delete it to sign everyone out with a new key")
    return key


def public_base(env: dict) -> str:
    """The address every link and QR code is written with. Never the request's Host header, which the client sets."""
    base = env.get("MOONIE_REDIRECT_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base:
        raise SystemExit(
            "MOONIE_REDIRECT_PUBLIC_BASE_URL is required: the address links and QR codes are written with,"
            " such as https://go.example.test"
        )
    if not re.fullmatch(r"https?://[^/?#\s@]+(/[^?#\s]*)?", base, re.I):
        raise SystemExit("MOONIE_REDIRECT_PUBLIC_BASE_URL must be an http(s) URL with no query or fragment")
    return base


def safe_next(value: object) -> str | None:
    """`value` when it is an address of the admin pages, to go back to after the login, else None. Read as a browser
    reads it: encoded dots and `..` that leave /admin/, a backslash, a scheme or a host are refused."""
    if not isinstance(value, str) or not value.startswith("/admin/") or value.startswith("//"):
        return None
    if "\\" in value or any(ord(c) < 33 or ord(c) == 127 for c in value):
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return None
    path = unquote(parts.path)
    if "\\" in path or not (posixpath.normpath(path) + "/").startswith("/admin/"):
        return None
    return value


def create_app(
    env: dict | None = None,
    *,
    cloudflare: "Cloudflare | None" = None,
    cloudflare_factory: "Callable[[str], Cloudflare] | None" = None,
    secret_store: "WebhookSecrets | None" = None,
    webhook: "Callable[[Store, WebhookSecrets], Webhook] | None" = None,
) -> Flask:
    """The app. Tests hand their fake client in `cloudflare` (as if read from the token file), in
    `cloudflare_factory` what makes a client of a token set in the settings, in `secret_store` a fake secret store for
    the webhook, and in `webhook` a Webhook built with a resolver and an allow-list that reach a loopback receiver."""
    env = dict(os.environ if env is None else env)
    make_client = cloudflare_factory or Cloudflare
    app = Flask(__name__)
    # A double slash is part of a slug's shape, never something to redirect away
    app.url_map.merge_slashes = False
    store = Store(Path(env.get("MOONIE_REDIRECT_DB", "/data/redirect.db")), item_limit=cloudflare_item_limit(env))
    password = read_secret(env, "MOONIE_REDIRECT_PASSWORD_FILE")
    token = read_secret(env, "MOONIE_REDIRECT_API_TOKEN_FILE")
    if token is not None and len(token) < TOKEN_MIN:
        raise SystemExit(f"the API token must be at least {TOKEN_MIN} characters")
    secret_key = read_secret(env, "MOONIE_REDIRECT_SECRET_KEY_FILE")
    if secret_key is None:
        # A random key mixed with the password: a cookie cannot be checked offline against guessed passwords, and a new
        # password still signs everyone out
        hashed = hashlib.sha256((password or "").encode()).digest()
        secret_key = hmac.new(session_key(store.path.parent), hashed, hashlib.sha256).hexdigest()
    base = public_base(env)
    app.config.update(
        SECRET_KEY=secret_key,
        MAX_CONTENT_LENGTH=1 << 20,
        SESSION_COOKIE_NAME="moonie_redirect",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=base.lower().startswith("https://"),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=SESSION_HOURS),
    )
    app.extensions["store"] = store
    box = app.extensions["box"] = SecretBox(store_key(env, store.path.parent))
    sealed = app.extensions["secrets"] = SealedSecrets(store, box)
    file_client = cloudflare_client(env, cloudflare)

    def cloudflare_source() -> tuple[str, "Cloudflare | None"]:
        """Where the Cloudflare token comes from, and its client (D22): the one set in the settings, else the file's.
        A stored token that cannot be read says so, and the file's is used meanwhile."""
        state, stored = store.read_sealed(box, "cloudflare_token")
        if stored is not None:
            try:
                return "stored", make_client(stored)
            except ValueError:
                state = "unreadable"
        if file_client is not None:
            return ("unreadable" if state == "unreadable" else "file"), file_client
        return state, None

    token_origin, first_client = cloudflare_source()
    cf_origin = {"token": token_origin}
    # Cloudflare is off (client None) without a token; its thread starts in main() only
    sync = app.extensions["sync"] = Sync(store, first_client, admin=serving_hosts(base))
    # The webhook's thread starts in main() only, as the sync's
    hook = app.extensions["webhook"] = (webhook or Webhook)(store, secret_store or sealed)

    def address_url(row: dict) -> str:
        """The address to share, the one a QR code holds: on the LAN the public URL of a link or a NanoURL and the short
        link of a QR code, as 8.0.0 drew them; on a Cloudflare host `https://<host>/<slug or id>`."""
        source = link_source(row.get("address"), row["kind"], row["slug"], row["id"])
        if source is not None:
            return f"https://{source}"
        return base + (LINKS_PREFIX + row["id"] if row["kind"] == "qrcode" else REDIRECT_PREFIX + row["slug"])

    def described(row: dict, *, listed: bool = False) -> dict:
        """A row as the API answers it. In a list, a QR code's logo is sent as stored, never opened: it was checked
        whole when written, and a list of many big logos would otherwise decode every one of them on each load."""
        out = {key: value for key, value in row.items() if key not in SYNC_COLUMNS}
        out |= {
            "public_url": base + REDIRECT_PREFIX + row["slug"],
            "short_url": base + LINKS_PREFIX + row["id"],
            "address": row["address"] or LAN,
            "address_url": address_url(row),
            "cloudflare": None
            if row["address"] is None
            else {"state": row["cf_state"], "error": read_error(row["cf_error"])},
        }
        if row["kind"] == "qrcode":
            design = read_design(row["design"], open_logo=not listed)
            out["design"] = None if design is None else asdict(design)
        return out

    def qr_svg(row: dict) -> str | None:
        design = read_design(row["design"])
        return None if design is None else render_svg(address_url(row), design)

    # --- Public routes ---

    def refusal(status: int) -> Response:
        if "text/html" in request.headers.get("Accept", ""):
            return Response(render_template("state.html", status=status), status, NO_STORE)
        return Response(str(status), status, NO_STORE, mimetype="text/plain")

    def follow(column: str, value: str | None) -> Response:
        try:
            hop = None if value is None else store.hop(column, value)
        except sqlite3.Error:
            status, hop = 503, None
        else:
            status = 404
        # A link works through the whole of its day, in UTC; a row edited by hand to another scheme is never followed
        today = datetime.now(UTC).date().isoformat()
        if hop is not None and (hop["expires_on"] is None or hop["expires_on"] >= today):
            if hop["target"].lower().startswith(("http://", "https://")) and hop["http_status"] in (301, 302):
                status = hop["http_status"]
        log.info("visit path=%r status=%d", request.path[:MAX_LOGGED], status)
        if status not in (301, 302):
            response = refusal(status)
            if status == 503:
                response.headers["Retry-After"] = "5"
            return response
        # The stored target alone, never the visit's query string
        response = Response("", status, NO_STORE)
        response.headers["Location"] = quote(hop["target"], safe=LOCATION_SAFE)
        return response

    @app.get("/redirect/<path:_slug>")
    def visit_slug(_slug: str) -> Response:
        # From the raw path: a route's parameter also matches before a final newline
        slug = request.path.removeprefix(REDIRECT_PREFIX)
        return follow("slug", slug if is_valid_slug(slug) else None)

    @app.get("/links/<path:_code>")
    def visit_code(_code: str) -> Response:
        code = request.path.removeprefix(LINKS_PREFIX)
        return follow("id", code if CODE.fullmatch(code) else None)

    @app.get("/health")
    def health() -> Response:
        try:
            store.ping()
        except sqlite3.Error:
            return jsonify(status="unavailable"), 503
        return jsonify(status="ok", version=VERSION)

    @app.errorhandler(404)
    def not_found(_error) -> Response:
        return refusal(404)

    # --- Guards ---

    def csrf_token() -> str:
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    def same_token(sent: str) -> bool:
        return bool(session.get("csrf")) and hmac.compare_digest(sent.encode(), session["csrf"].encode())

    app.jinja_env.globals.update(csrf_token=csrf_token, version=VERSION)

    def signed_in() -> bool:
        """The cookie is signed, but a copy of it outlives the browser's: its row on the server is what says it is
        still signed in (no logout since, and under SESSION_HOURS since the login, however often it was used)."""
        return bool(session.get("admin")) and store.session_alive(session.get("sid"), time.time())

    def unauthorized() -> Response:
        return Response(
            json.dumps({"error": "unauthorized"}), 401, {"WWW-Authenticate": "Bearer"}, mimetype="application/json"
        )

    file_used = {"at": None}  # when the token file's use was last written: at most once a minute

    def used(stamp: str, last: str | None) -> bool:
        """Whether a key last used at `last` should be written as used at `stamp`."""
        if last is None:
            return True
        then = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ") - timedelta(seconds=KEY_USE_EVERY)
        return last <= then.strftime("%Y-%m-%dT%H:%M:%SZ")

    def bearer_scopes(given: str) -> tuple[str, ...] | None:
        """The scopes of the key `given`: the token file's (`*`) first, then a database key's. None: no such key."""
        stamp = now()
        if token and hmac.compare_digest(given.encode(), token.encode()):
            if used(stamp, file_used["at"]):
                file_used["at"] = stamp
                store.set_setting(TOKEN_FILE_USED_SETTING, stamp)
            g.key_id = FILE_KEY_ID
            return ("*",)
        if not given.startswith(KEY_PREFIX) or len(given) > KEY_MAX:
            return None
        row = store.api_key(key_digest(given))
        if row is None:
            return None
        if used(stamp, row["last_used_at"]):
            store.touch_api_key(row["id"], stamp)
        g.key_id = row["id"]
        return tuple(row["scopes"])

    def api_guard() -> Response | None:
        """A bearer header, valid or not, is the only proof read: it never falls back to the cookie. With no header, the
        admin session; a change through it also sends the session's token in X-CSRF-Token, from this origin."""
        header = request.headers.get("Authorization")
        # The session holds every scope; a key holds its own (D25), and never reaches the settings (D28)
        g.admin_session = header is None
        g.scopes, g.key_id = (), None
        if header is not None:
            scheme, _, given = header.partition(" ")
            scopes = bearer_scopes(given.strip()) if scheme.lower() == "bearer" else None
            if scopes is None:
                return unauthorized()
            g.scopes = scopes
            path = request.path
            if path == "/api/session" or path == "/api/settings" or path.startswith("/api/settings/"):
                return Response(json.dumps({"error": "needs_admin"}), 403, mimetype="application/json")
            return None
        if not signed_in():
            return unauthorized()
        if request.method not in SAFE_METHODS and not (
            same_token(request.headers.get("X-CSRF-Token", "")) and request.headers.get("Sec-Fetch-Site") in SAME_ORIGIN
        ):
            log.warning("api change refused: no CSRF token from this origin")
            return Response(json.dumps({"error": "csrf"}), 403, mimetype="application/json")
        return None

    @app.before_request
    def guard() -> Response | None:
        path = request.path
        if path.startswith("/api/"):
            return api_guard()
        if request.method == "POST" and path in ("/login", "/logout"):
            if not same_token(request.form.get("csrf", "")):
                abort(400)
        if (path == "/admin" or path.startswith("/admin/")) and not signed_in():
            return redirect(url_for("login", next=safe_next(request.full_path.rstrip("?"))))
        return None

    @app.after_request
    def headers(response: Response) -> Response:
        response.headers.setdefault("Content-Security-Policy", PAGE_POLICY)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.path.startswith(("/admin", "/api", "/login")):
            response.headers["Cache-Control"] = "no-store"
        return response

    # --- Admin UI ---

    @app.get("/")
    def home() -> Response:
        return redirect(ADMIN_HOME)

    def password_origin() -> str:
        if store.setting(ADMIN_PASSWORD_SETTING) is not None:
            return "stored"
        return "file" if password else "missing"

    def is_password(given: str) -> bool:
        """The password set in the settings, else the file's (D22)."""
        stored = store.setting(ADMIN_PASSWORD_SETTING)
        if stored is not None:
            return password_matches(stored, given)
        if not password:
            return False
        return hmac.compare_digest(hashlib.sha256(given.encode()).digest(), hashlib.sha256(password.encode()).digest())

    @app.route("/login", methods=["GET", "POST"])
    def login():
        flags = request.args
        notice = "expired" if flags.get("expired") == "1" else "out" if flags.get("out") == "1" else None
        back = safe_next(request.values.get("next"))

        def page(status: int, *, form_error: str | None = None, field_error: str | None = None):
            shown = None if status != 200 else notice
            return render_template(
                "login.html", notice=shown, next=back, form_error=form_error, field_error=field_error
            ), status

        if request.method == "GET":
            return page(200)
        # Check the brake and claim the slot in one step, so concurrent attempts get one try per window
        claim = brake_claim()
        if claim is None:
            log.warning("login braked")
            return page(429, form_error="Too many attempts. Try again in 1 s.")
        if is_password(request.form.get("password", "")):
            brake_release(claim)
            store.close_session(session.get("sid"))
            session.clear()
            session.permanent = True
            session["admin"] = True
            session["sid"] = store.open_session(time.time())
            log.info("login ok")
            return redirect(back or ADMIN_HOME)
        log.warning("login refused")
        if password_origin() == "missing":
            return page(401, form_error="No password is configured: set MOONIE_REDIRECT_PASSWORD_FILE.")
        return page(401, field_error="Wrong password. Try again.")

    @app.post("/logout")
    def logout() -> Response:
        store.close_session(session.get("sid"))
        session.clear()
        return redirect(url_for("login", out=1))

    @app.get("/admin")
    def admin_home() -> Response:
        return redirect(ADMIN_HOME)

    @app.get("/admin/cloudflare")
    def admin_cloudflare() -> Response:
        return redirect(CLOUDFLARE_TAB)

    @app.get("/admin/<path:rest>")
    def admin_page(rest: str):
        """The frame of the admin pages, which the browser fills from static/ui. Any other address under /admin gets the
        same frame, which says the page does not exist, with the status that says so."""
        return render_template("app.html"), 200 if rest in ADMIN_PAGES else 404

    def svg_response(row: dict) -> Response:
        svg = qr_svg(row)
        if svg is None:
            abort(422)
        filename = row["slug"].rsplit("/", 1)[-1] + ".svg"
        disposition = "attachment" if request.args.get("download") else "inline"
        headers = {
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Content-Security-Policy": SVG_POLICY,
        }
        return Response(svg, 200, headers, mimetype="image/svg+xml")

    # --- JSON API ---

    def api_error(status: int, error: str, fields: dict | None = None) -> Response:
        response = jsonify({"error": error} | ({"fields": fields} if fields else {}))
        response.status_code = status
        return response

    def api_row(id_: str) -> dict:
        row = store.get(id_)
        if row is None:
            abort(api_error(404, "not_found"))
        return row

    def api_body() -> dict:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            abort(api_error(400, "body must be a JSON object"))
        return body

    def allowed(scope: str) -> bool:
        return bool(g.admin_session) or scope_allows(g.scopes, scope)

    def needs(scope: str) -> None:
        """Refuses (as an answer) a call whose key lacks `scope` (D25)."""
        if not allowed(scope):
            abort(api_error(403, "scope_denied"))

    def readable_row(id_: str) -> dict:
        """The link `id_`, if the caller may read its kind: a row of a kind it cannot read is not found."""
        row = api_row(id_)
        if not allowed(f"{KIND_SCOPE[row['kind']]}.read"):
            abort(api_error(404, "not_found"))
        return row

    def writable_row(id_: str) -> dict:
        row = readable_row(id_)
        needs(f"{KIND_SCOPE[row['kind']]}.write")
        return row

    @app.get("/api/status")
    def api_status():
        """What the admin frame's status says: the version, and the count of links of every kind."""
        return jsonify(version=VERSION, links=store.count())

    @app.get("/api/session")
    def api_session():
        """The session's CSRF token, for a page whose token a login in another tab replaced. Only the page's own origin
        can read the answer; a bearer caller has no session (the guard answers it `403 needs_admin`)."""
        return jsonify(csrf=csrf_token())

    def addresses() -> list[dict]:
        """What a link's `address` may be: the LAN first, then each Cloudflare host set up here, while Cloudflare is
        on. An adopted host may serve a site, so only the admin may give it to a link."""
        found = [{"address": LAN, "url": base, "adopted": False}]
        if sync.client is not None:
            for row in store.cf_hosts():
                found.append(
                    {"address": row["host"], "url": f"https://{row['host']}", "adopted": not row["created_by_us"]}
                )
        return found

    def asked_address(body: dict, current: str | None = None, *, writing: bool = True) -> str | None:
        """The host of `address` in a body, None for `lan`. Refuses (as an answer) a value that is no host set up
        here, any host while Cloudflare is off, the admin's own host (D18), and an adopted host to a key without
        `cloudflare:setup`; the last two unless the link already has it. A write to a host also needs `cloudflare:write`
        (D25); a preview (`writing` False) writes nothing and needs neither."""
        value = body["address"]
        if value == LAN:
            return None
        if writing:
            needs("cloudflare:write")
        if not isinstance(value, str) or not value:
            abort(api_error(400, "invalid", {"address": "lan or a host set up here"}))
        if sync.client is None:
            abort(api_error(409, "cloudflare_off"))
        host = store.cf_host(value)
        if host is None:
            abort(api_error(400, "invalid", {"address": "not a host set up here"}))
        if value != current and value in serving_hosts(base, request.host):
            abort(api_error(400, "invalid", {"address": "this instance's own host: choose another"}))
        if writing and not host["created_by_us"] and value != current and not allowed("cloudflare:setup"):
            abort(api_error(403, "scope_denied"))
        return value

    def check_source(kind: str, slug: str, address: str | None) -> None:
        """Refuses (as an answer) a source no link may have: see `well_known`."""
        if well_known(kind, slug, address):
            abort(api_error(400, "invalid", {"address": ".well-known is reserved on a Cloudflare host"}))

    def confirmed_break(body: dict | None) -> bool:
        """What a change that stops a Cloudflare address sends to say it was asked: `confirm_break: true` in the body,
        or `?confirm_break=true` for a DELETE sent with no body."""
        return (isinstance(body, dict) and body.get("confirm_break") is True) or request.args.get(
            "confirm_break"
        ) == "true"

    def saved(action: Callable[[], dict | None]) -> dict | None | Response:
        """A store write, its refusals as answers."""
        try:
            return action()
        except SlugTaken as taken:
            fields = {"address": "this path is taken on this host"} if taken.field == "address" else None
            return api_error(409, "slug_taken", fields)
        except QuotaFull:
            return api_error(409, "quota_full")
        except Invalid as refused:
            return api_error(400, "invalid", {refused.field: str(refused)})

    @app.get("/api/links")
    def api_list():
        kind = request.args.get("kind")
        if kind is not None and kind not in KINDS:
            return api_error(400, "invalid", {"kind": "link, nano or qrcode"})
        if kind is not None:
            needs(f"{KIND_SCOPE[kind]}.read")
            rows = store.list(kind)
        else:
            # Only the kinds the key reads; a key that reads none is refused
            kinds = {k for k in KINDS if allowed(f"{KIND_SCOPE[k]}.read")}
            if not kinds:
                return api_error(403, "scope_denied")
            rows = [row for row in store.list() if row["kind"] in kinds]
        return jsonify(links=[described(r, listed=True) for r in rows], addresses=addresses())

    @app.post("/api/links")
    def api_create():
        body = api_body()
        kind = body.get("kind", "link")
        if kind not in KINDS:
            return api_error(400, "invalid", {"kind": "link, nano or qrcode"})
        needs(f"{KIND_SCOPE[kind]}.write")
        try:
            values = check_fields(kind, body, creating=True)
        except InvalidFields as refused:
            return api_error(400, "invalid", refused.errors)
        values["address"] = asked_address(body) if "address" in body else None
        check_source(kind, values["slug"], values["address"])
        row = saved(lambda: store.create(kind, values))
        if isinstance(row, Response):
            return row
        sync.wake()
        hook.emit("redirect.link.created", row)
        log.info("created id=%s kind=%s", row["id"], kind)
        return jsonify(described(row)), 201

    @app.get("/api/links/suggest")
    def api_suggest():
        kind = request.args.get("kind", "link")
        if kind not in KINDS:
            return api_error(400, "invalid", {"kind": "link, nano or qrcode"})
        needs(f"{KIND_SCOPE[kind]}.write")
        return jsonify(slug=store.free_slug())

    @app.post("/api/qrcodes/preview")
    def api_preview():
        """The SVG a QR code would have, as `{"svg": ...}`, writing nothing. With `id`, that QR code's address, and its
        stored design when `design` is absent; without, a code of the same length stands for the id to come. With
        `address`, the code as it would be at that address."""
        needs("redirect:qrcodes.read")
        body = api_body()
        row = None
        if body.get("id") is not None:
            if not isinstance(body["id"], str):
                return api_error(400, "invalid", {"id": "must be a string"})
            row = store.get(body["id"])
            if row is None or row["kind"] != "qrcode":
                return api_error(404, "not_found")
        fields = {k: body[k] for k in ("name", "design") if k in body}
        try:
            values = check_fields("qrcode", fields, creating=False)
        except InvalidFields as refused:
            return api_error(400, "invalid", refused.errors)
        design = read_design(values["design"] if "design" in values else row and row["design"])
        if design is None:
            return api_error(422, "design_unreadable")
        current = row["address"] if row else None
        address = asked_address(body, current, writing=False) if "address" in body else current
        drawn = {"kind": "qrcode", "id": row["id"] if row else PREVIEW_ID, "slug": "", "address": address}
        return jsonify(svg=render_svg(address_url(drawn), design))

    @app.get("/api/links/<id_>")
    def api_get(id_: str):
        return jsonify(described(readable_row(id_)))

    @app.patch("/api/links/<id_>")
    def api_update(id_: str):
        row = writable_row(id_)
        body = api_body()
        try:
            values = check_fields(row["kind"], body, creating=False)
        except InvalidFields as refused:
            return api_error(400, "invalid", refused.errors)
        if "address" in body:
            values["address"] = asked_address(body, row["address"])
        new = row | values
        # A link on a Cloudflare host, before or after, is written to Cloudflare too
        if row["address"] is not None or new["address"] is not None:
            needs("cloudflare:write")
        check_source(row["kind"], new["slug"], new["address"])
        before = link_source(row["address"], row["kind"], row["slug"], row["id"])
        after = link_source(new["address"], row["kind"], new["slug"], row["id"])
        # A new path on an adopted host may shadow its live site, whatever field moved it there: a setup's call (D25)
        if after is not None and after != before and not allowed("cloudflare:setup"):
            host = store.cf_host(new["address"])
            if host is not None and not host["created_by_us"]:
                return api_error(403, "scope_denied")
        # A Cloudflare source given up (another host, the LAN, or a new slug) stops what was printed or shared with it,
        # even if the LAN keeps answering
        if before is not None and after != before and not confirmed_break(body):
            return api_error(400, "confirm_break")
        if values:
            row = saved(lambda: store.update(id_, values))
            if isinstance(row, Response):
                return row
        if row is None:
            return api_error(404, "not_found")
        sync.wake()
        if values:
            hook.emit("redirect.link.updated", row)
        log.info("updated id=%s kind=%s", id_, row["kind"])
        return jsonify(described(row))

    @app.delete("/api/links/<id_>")
    def api_delete(id_: str):
        row = writable_row(id_)
        if row["address"] is not None:
            needs("cloudflare:write")
        if row["address"] is not None and not confirmed_break(request.get_json(silent=True)):
            return api_error(400, "confirm_break")
        if not store.delete(id_):
            return api_error(404, "not_found")
        sync.wake()
        hook.emit("redirect.link.deleted", row)
        log.info("deleted id=%s", id_)
        return "", 204

    @app.get("/api/links/<id_>/qr.svg")
    def api_svg(id_: str) -> Response:
        row = readable_row(id_)
        if row["kind"] != "qrcode":
            return api_error(404, "not_found")
        return svg_response(row)

    # --- Cloudflare JSON API ---
    # The state and Compare's report need `cloudflare:read`, Sync now `cloudflare:write`; what sets a host up, changes
    # its page for unknown paths or removes items needs `cloudflare:setup` (D25). The session holds all three.

    def cloudflare_on() -> "Cloudflare":
        if sync.client is None:
            abort(api_error(409, "cloudflare_off"))
        return sync.client

    def setup_only() -> "Cloudflare":
        needs("cloudflare:setup")
        return cloudflare_on()

    def calling(action: Callable[[], Response], budget: float = REQUEST_BUDGET) -> Response:
        """A call that reaches Cloudflare, its refusals as answers. Nothing goes while Cloudflare asked for a wait, and
        its calls are bounded (`Cloudflare.bounded`): the request never waits on the sync's retries."""
        if sync.rate_held():
            return api_error(429, "rate_limited")
        try:
            with cloudflare_on().bounded(budget):
                return action()
        except PlanRefused as refused:
            return api_error(refused.status, refused.code)
        except InvalidFields as refused:
            return api_error(400, "invalid", refused.errors)
        except Invalid as refused:
            return api_error(400, "invalid", {refused.field: str(refused)})
        except (CfError, CfUnreachable, ValueError) as error:
            if isinstance(error, RateLimited):
                sync.not_before = sync.monotonic() + min(error.retry_after, RETRY_AFTER_CAP)
            log.warning("cloudflare call of %s failed: %s", request.path, describe(error))
            code = json.loads(failure_of(error))["code"]
            return api_error(429 if isinstance(error, RateLimited) else 502, code)

    def serving() -> set[str]:
        return serving_hosts(base, request.host)

    def token_now() -> dict:
        client = sync.client
        if client is None:
            return sync.token_state()
        with client.bounded(REQUEST_BUDGET):
            return sync.token_state()

    @app.get("/api/cloudflare")
    def api_cloudflare():
        needs("cloudflare:read")
        token = token_now()
        return jsonify(cloudflare_state(store, token, enabled=sync.client is not None))

    @app.post("/api/cloudflare/sync")
    def api_cloudflare_sync():
        needs("cloudflare:write")
        cloudflare_on()
        return jsonify(retried=sync.sync_now()), 202

    @app.get("/api/cloudflare/compare")
    def api_cloudflare_compare():
        needs("cloudflare:read")
        client = cloudflare_on()

        def report() -> Response:
            found = compare_report(client, store)
            if not allowed("cloudflare:setup"):
                found.pop("fingerprint")  # only a setup confirms a report
            return jsonify(found)

        return calling(report)

    @app.post("/api/cloudflare/compare/apply")
    def api_cloudflare_compare_apply():
        client = setup_only()
        body = api_body()

        def run() -> Response:
            done = apply_compare(client, store, body)
            sync.wake()
            return jsonify(done), 202

        return calling(run)

    @app.get("/api/cloudflare/zones")
    def api_cloudflare_zones():
        client = setup_only()
        return calling(lambda: jsonify(zones=[asdict(zone) for zone in client.zones()]))

    @app.get("/api/cloudflare/proposals")
    def api_cloudflare_proposals():
        client = setup_only()
        taken = {row["host"] for row in store.cf_hosts()}
        return calling(lambda: jsonify(proposals(client, find_zone(client, request.args.get("zone")), taken)))

    @app.post("/api/cloudflare/plan")
    def api_cloudflare_plan():
        client = setup_only()
        body = api_body()

        def plan() -> Response:
            found, _ = plan_for(client, store, body.get("zone_id"), body.get("label"), body.get("fallback"), serving())
            return jsonify(found)

        return calling(plan)

    @app.post("/api/cloudflare/apply")
    def api_cloudflare_apply():
        client = setup_only()
        body = api_body()

        def apply() -> Response:
            done = apply_plan(
                client,
                store,
                zone_id=body.get("zone_id"),
                label=body.get("label"),
                fallback=body.get("fallback"),
                fingerprint_sent=body.get("fingerprint"),
                confirm_live=body.get("confirm_live") is True,
                serving=serving(),
                sync=sync,
            )
            return jsonify(host=host_answer(store.cf_host(done["host"])), plan=done["plan"]), 201

        return calling(apply, SETUP_BUDGET)

    @app.post("/api/cloudflare/hosts/<host>/fallback")
    def api_cloudflare_fallback(host: str):
        setup_only()
        body = api_body()
        if "fallback" not in body:
            return api_error(400, "invalid", {"fallback": "required: an address, or null for none"})

        def change() -> Response:
            change_fallback(store, host, body["fallback"], serving(), sync)
            log.info("cloudflare: the page for unknown paths of %s changed", host)
            return jsonify(host_answer(store.cf_host(host)))

        return calling(change)

    # --- Settings JSON API ---
    # Session only (D28): the guard answers every key `403 needs_admin` under /api/settings. Nothing secret is ever
    # answered: a secret is told by where it comes from.

    def checked_password(body: dict) -> Response | None:
        """The admin's password in `password`, under the login brake: None when it is right, else the refusal."""
        claim = brake_claim()
        if claim is None:
            log.warning("settings: password check braked")
            return api_error(429, "too_many_attempts")
        given = body.get("password")
        if isinstance(given, str) and is_password(given):
            brake_release(claim)
            return None
        log.warning("settings: wrong password")
        return api_error(400, "login_failed", {"password": "wrong password"})

    @app.get("/api/settings/security")
    def api_settings_security():
        return jsonify(
            password={"origin": password_origin()},
            sessions={"active": store.sessions_active(time.time()), "hours": SESSION_HOURS},
            login_brake_seconds=int(LOGIN_BRAKE),
        )

    @app.post("/api/settings/password")
    def api_settings_password():
        body = api_body()
        try:
            new = check_new_password(body.get("new_password"))
        except Invalid as refused:
            return api_error(400, "invalid", {refused.field: str(refused)})
        refusal = checked_password(body)
        if refusal is not None:
            return refusal
        store.set_setting(ADMIN_PASSWORD_SETTING, hash_password(new))
        ended = store.end_sessions(keep=session.get("sid"))
        log.info("settings: password changed, %d other sessions ended", ended)
        return "", 204

    @app.post("/api/settings/sessions/end")
    def api_settings_sessions_end():
        ended = store.end_sessions()
        session.clear()
        log.info("settings: every session ended (%d)", ended)
        return "", 204

    def key_answer(row: dict) -> dict:
        fields = ("id", "name", "prefix", "scopes", "created_at", "last_used_at")
        return {field: row[field] for field in fields} | {"origin": "stored"}

    @app.get("/api/settings/keys")
    def api_settings_keys():
        keys = [key_answer(row) for row in store.api_keys()]
        if token:
            # The token file: every scope, revoked by removing the file (D22)
            file_row = {
                "id": FILE_KEY_ID,
                "name": "Token file",
                "prefix": None,
                "scopes": ["*"],
                "created_at": None,
                "last_used_at": store.setting(TOKEN_FILE_USED_SETTING),
                "origin": "file",
            }
            keys.insert(0, file_row)
        return jsonify(keys=keys, known_scopes=list(KNOWN_SCOPES))

    @app.post("/api/settings/keys")
    def api_settings_keys_create():
        body = api_body()
        errors = {}
        try:
            name = check_name(body.get("name") if isinstance(body.get("name"), str) else "")
        except Invalid as refused:
            errors[refused.field] = str(refused)
        try:
            scopes = check_scopes(body.get("scopes"))
        except Invalid as refused:
            errors[refused.field] = str(refused)
        if errors:
            return api_error(400, "invalid", errors)
        refusal = checked_password(body)
        if refusal is not None:
            return refusal
        secret = new_api_key()
        row = store.add_api_key(name, scopes, key_digest(secret), secret[:KEY_SHOWN])
        log.info("settings: api key %s created, scopes %s", row["id"], " ".join(scopes))
        answer = {field: row[field] for field in ("id", "name", "prefix", "scopes")} | {"secret": secret}
        return jsonify(answer), 201

    @app.delete("/api/settings/keys/<id_>")
    def api_settings_keys_delete(id_: str):
        if not store.drop_api_key(id_):
            return api_error(404, "not_found")
        log.info("settings: api key %s revoked", id_)
        return "", 204

    def cloudflare_settings() -> dict:
        limit_origin = "stored" if store.setting(ITEM_LIMIT_SETTING) is not None else "default"
        if limit_origin == "default" and env.get("MOONIE_REDIRECT_CLOUDFLARE_ITEM_LIMIT", "").strip():
            limit_origin = "env"
        check = token_now()
        return {
            "token": {"origin": cf_origin["token"]} | check,
            "item_limit": {"value": store.item_limit, "origin": limit_origin},
        }

    def switch_cloudflare(stored: "Cloudflare | None" = None, check: dict | None = None) -> None:
        """The client of the token now in force goes to the sync (D27): `stored`, the client of the token just stored
        with `check` the check just made of it, or else the one `cloudflare_source` finds."""
        if stored is not None:
            cf_origin["token"] = "stored"
            sync.use(stored, check)
            return
        cf_origin["token"], client = cloudflare_source()
        sync.use(client)

    @app.get("/api/settings/cloudflare")
    def api_settings_cloudflare():
        return jsonify(cloudflare_settings())

    @app.put("/api/settings/cloudflare/token")
    def api_settings_cloudflare_token():
        body = api_body()
        value = body.get("token")
        value = value.strip() if isinstance(value, str) else ""
        try:
            client = make_client(value)
        except ValueError:
            return api_error(400, "invalid", {"token": "a printable ASCII token"})
        # Refused only when Cloudflare says the token is not active; a check it could not answer stores it unchecked
        unchecked = {"state": "unchecked", "missing": [], "unverified": [], "checked_at": None}
        try:
            with client.bounded(REQUEST_BUDGET):
                found = client.verify_token()
        except (CfError, CfUnreachable) as error:
            log.warning("cloudflare: the new token could not be checked: %s", describe(error))
            check = unchecked
        else:
            if found.state == "invalid":
                log.warning("cloudflare: the new token is refused by Cloudflare")
                return api_error(400, "token_invalid")
            stamp = sync._now()
            check = {
                "state": found.state,
                "missing": list(found.missing),
                "unverified": list(found.unverified),
                "checked_at": stamp,
            }
        store.write_sealed(box, "cloudflare_token", value)
        switch_cloudflare(client, check)
        log.info("cloudflare: token set in the settings")
        return jsonify(cloudflare_settings())

    @app.delete("/api/settings/cloudflare/token")
    def api_settings_cloudflare_token_clear():
        store.drop_sealed("cloudflare_token")
        switch_cloudflare()
        log.info("cloudflare: token cleared from the settings, now %s", cf_origin["token"])
        return jsonify(cloudflare_settings())

    @app.put("/api/settings/cloudflare/item-limit")
    def api_settings_cloudflare_item_limit():
        body = api_body()
        if "value" not in body:
            return api_error(400, "invalid", {"value": "required: a whole number, or null for the default"})
        try:
            value = check_item_limit(body["value"])
        except Invalid as refused:
            return api_error(400, "invalid", {refused.field: str(refused)})
        if value is None:
            store.drop_setting(ITEM_LIMIT_SETTING)
        else:
            store.set_setting(ITEM_LIMIT_SETTING, str(value))
        log.info("cloudflare: item limit set to %s", value if value is not None else "its default")
        return jsonify(cloudflare_settings())

    # --- Webhook settings JSON API (D26) ---
    # The admin session alone (the guard, D28): the URL may carry a token, and the secret signs what n8n trusts.

    @app.get("/api/settings/webhook")
    def api_webhook():
        return jsonify(hook.answer())

    @app.put("/api/settings/webhook")
    def api_webhook_save():
        try:
            return jsonify(hook.save(api_body()))
        except InvalidFields as refused:
            return api_error(400, "invalid", refused.errors)

    @app.delete("/api/settings/webhook")
    def api_webhook_clear():
        hook.clear()
        return "", 204

    @app.post("/api/settings/webhook/test")
    def api_webhook_test():
        try:
            result = hook.test()
        except LookupError:
            return api_error(409, "not_configured")
        if result is None:
            return api_error(429, "busy")
        return jsonify(result)

    return app


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if argv[1:2] == ["import-v7"]:
        if len(argv) != 3 or not Path(argv[2]).is_file():
            print("usage: python app.py import-v7 <path to the 7.0.1 moonie.db>", file=sys.stderr)
            return 2
        store = Store(Path(os.environ.get("MOONIE_REDIRECT_DB", "/data/redirect.db")))
        try:
            counts = store.import_v7(Path(argv[2]))
        except sqlite3.DatabaseError as error:
            print(f"cannot read the 7.0.1 database: {error}", file=sys.stderr)
            return 1
        print(f"imported {counts['imported']}, duplicates {counts['duplicates']}, refused {counts['refused']}")
        if counts["with_ip"]:
            print(
                f"warning: {counts['with_ip']} imported rows have link_host 'ip': their printed codes hold the old"
                " container IP and port, and work only while that address reaches this app"
            )
        # The admin's host takes no Cloudflare item (D18); without the variable no host is known to be it
        admin = serving_hosts(os.environ.get("MOONIE_REDIRECT_PUBLIC_BASE_URL", ""))
        for line in cloudflare_import_lines(store.import_v7_cloudflare(Path(argv[2]), admin)):
            print(line)
        return 0
    if argv[1:] == ["reset-password"]:
        # Run in the deployed container: the password set in the settings goes, the file's counts again (D24)
        store = Store(Path(os.environ.get("MOONIE_REDIRECT_DB", "/data/redirect.db")))
        dropped = store.drop_setting(ADMIN_PASSWORD_SETTING)
        ended = store.end_sessions()
        if dropped:
            print("the password set in the settings is removed: sign in with MOONIE_REDIRECT_PASSWORD_FILE's")
        else:
            print("no password was set in the settings: MOONIE_REDIRECT_PASSWORD_FILE's is already in force")
        print(f"sessions ended: {ended}")
        return 0
    if len(argv) > 1:
        print("usage: python app.py [import-v7 <path> | reset-password]", file=sys.stderr)
        return 2
    from waitress import serve

    app = create_app()
    app.extensions["sync"].start()
    app.extensions["webhook"].start()
    serve(app, host="0.0.0.0", port=int(os.environ.get("MOONIE_HTTP_PORT", "8080")), threads=4)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
