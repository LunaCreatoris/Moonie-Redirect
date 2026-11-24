# /// script
# requires-python = ">=3.11"
# dependencies = ["markdown==3.11.2"]
# ///
"""Checks a project's guide against the rules of the site that publishes it, with nothing else around.

    python guide_check.py <repository>/wiki/guide [--repo <name>] [--plugin <application>/<name>] [--private-words <file>]

It exits 0 with one line of summary, 1 with one problem a line, 2 on a usage error. Lines opening in "notice:" are what it could not judge alone, and never fail it.
A copy of this file must stay byte for byte what it was copied from: --version gives its format and its SHA-256. Decision D-023.

    mark.svg            required
    fr/index.md         required, plus <topic>.md
    en/...              the same names, in every language of the site
    img/                optional, shared by the languages, linked as ../img/name.png

A header sits between two --- lines, one "key: value" a line, the value unquoted, 'single-quoted' with '' for an
apostrophe, or "double-quoted" with \\" and \\\\:

    index.md            title, description, status, github, order
    <topic>.md          title, description, order

Every heading of a body carries an explicit, English {#anchor}. These guides are written elsewhere, some by people outside
the association, and go online on its domain, so what they render to is held to a short list of tags and attributes.

The site's generator (scripts/projects.py) and its copy recipe (scripts/wiki_update.py) read guides through this same file, so a guide
that passes here passes there, but for what only they can see: other guides, and what git holds. Every problem found is listed, none stops the reading of the rest.
"""

import sys

# Before anything this Python may not read: the annotations below are evaluated as the file loads.
if sys.version_info < (3, 11):
    print("guide_check needs Python 3.11 or newer", file=sys.stderr)
    raise SystemExit(2)

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import posixpath  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import xml.etree.ElementTree as ElementTree  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from html.parser import HTMLParser  # noqa: E402
from pathlib import Path  # noqa: E402

try:
    import markdown
except ImportError:
    # main() says what to do. --version needs no Markdown, and nothing else here runs without it.
    markdown = None

# Raised by any change that refuses what was accepted before, so that a repository can tell its copy is behind. A change that only accepts more leaves it.
FORMAT_VERSION = 1
# The pin of the header above, as a page could render differently on another version. A test holds the two, and the build's, together.
MARKDOWN_VERSION = "3.11.2"
# In the site, the languages come from its i18n/ folder, which is not here when this runs on its own. A test holds the two together.
DEFAULT_LANGUAGES = ("fr", "en")
# What can stand for the list in a repository's continuous integration, as this file and its logs are public.
PRIVATE_WORDS_VARIABLE = "GUIDE_CHECK_PRIVATE_WORDS"
GUIDE_FOLDER = ("wiki", "guide")

# Every name pattern goes through fullmatch: with match, a $ would also accept a trailing newline.
SLUG = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
IMAGE_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*\.(png|jpg|jpeg|webp|gif|svg)")
# Far above any real page's name, and well inside what every disk takes once it sits under project/ and public/.
MAX_NAME = 64
NAME_RULE = f"lowercase letters, digits and single hyphens, {MAX_NAME} characters at most, no name Windows reserves"
# Windows cannot hold these names, whatever follows them, and the site's files and folders take a guide's names.
RESERVED_NAMES = {"con", "prn", "aux", "nul", *(f"{port}{digit}" for port in ("com", "lpt") for digit in "0123456789")}
# The files an operating system may leave in a folder, never a folder and never any other name: is_leftover.
LEFTOVER_PREFIX = ".smbdelete"
LEFTOVER_NAME = ".DS_Store"

HOME_FIELDS = ("title", "description", "status", "github", "order")
TOPIC_FIELDS = ("title", "description", "order")
HOME = "index"
# Plain digits, of a length int() and a sort take: isdigit() also says yes to a superscript, which int() refuses.
NUMBER = re.compile(r"[0-9]{1,9}")
# The address /projects/<slug>/plugins/ is the group of an application's plugins, in every project.
PLUGINS_FOLDER = "plugins"
PLUGINS_ANCHOR = "plugins"
RESERVED_TOPICS = (PLUGINS_FOLDER,)
# The values of made_by, which the recipe computes from the repository's history.
MADE_BY = ("luna-creatoris", "community")
ORGANISATION = "LunaCreatoris"
GITHUB_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
GITHUB_REPOSITORY = re.compile(rf"https://github\.com/{ORGANISATION}/([A-Za-z0-9][A-Za-z0-9._-]*)")
GITHUB_FOLDER = re.compile(rf"https://github\.com/{ORGANISATION}/([A-Za-z0-9][A-Za-z0-9._-]*)/tree/main/([A-Za-z0-9._/-]+)")
GITHUB_GUIDE = re.compile(rf"https://github\.com/{ORGANISATION}/([A-Za-z0-9][A-Za-z0-9._-]*)/blob/main/(.*/)?(wiki/guide/.*)")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
OUTSIDE_SCHEMES = ("http:", "https:", "mailto:")

# Far above what a guide with a few screenshots weighs: these pages are served from the site's own storage.
MAX_IMAGE_BYTES = 2_000_000
MAX_GUIDE_BYTES = 20_000_000
# Far above any real page, and small enough for Markdown to take in a reasonable time. A title and a description sit in lists and cards.
MAX_PAGE_BYTES = 256_000
FIELD_LENGTHS = {"title": 120, "description": 300}
# What Markdown takes in a time that grows too fast, or a memory: far above what a reader can follow. Checked before it runs.
MAX_NESTING = 32
MAX_OPEN_BRACKETS = 64
# Past this length, Markdown runs in a process that can be stopped, as Python cannot stop a thread. Below it, its slowest known case takes about 3 s.
RENDER_IN_PROCESS_CHARACTERS = 16_000
RENDER_SECONDS = 20
# Written as bytes: on Windows, the text layer of sys.stdout would turn each newline into CRLF.
RENDER_PROGRAM = "import json, markdown, sys; options = json.loads(sys.argv[1]); sys.stdout.buffer.write(markdown.markdown(sys.stdin.read(), **options).encode('utf-8'))"
# The first bytes of each format: a file of another kind under one of these names would be served as that format.
SIGNATURES = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
}

# Two numbers in the private list stand for every address starting with them.
ADDRESS_PREFIX = re.compile(r"[0-9]+\.[0-9]+")

# Listed one by one: "extra" ignores the setting below, and adds footnotes, whose text is in English on every page.
EXTENSIONS = ["tables", "fenced_code", "attr_list", "sane_lists"]
# Otherwise an aligned column writes a style attribute, which the CSP blocks.
EXTENSION_CONFIGS = {"tables": {"use_align_attribute": True}}

FENCE = re.compile(r"^([ \t]*)(`{3,}|~{3,})")
# Tab and LF are text. A carriage return has its own message, in parse_header.
CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# One level of quote or list at the start of a line, whatever comes before it.
CONTAINER = re.compile(r"([ \t]*)(?:>|(?:[-*+]|[0-9]{1,9}\.)[ \t])")

# The ids of the page around the text, which a heading's anchor would collide with. A test holds this list to the rendered layout.
PAGE_IDS = ("menu", "wiki-toc-title", "i18n-strings")
HEADINGS = {"h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
ALLOWED_TAGS = {
    **{tag: {"id"} for tag in HEADINGS},
    "p": set(), "ul": set(), "ol": {"start"}, "li": set(), "a": {"href", "title"}, "img": {"src", "alt", "title"},
    "code": {"class"}, "pre": set(), "em": set(), "strong": set(), "blockquote": set(), "hr": set(), "br": set(),
    "table": set(), "thead": set(), "tbody": set(), "tr": set(), "th": {"align"}, "td": {"align"},
}
VOID_TAGS = {"img", "hr", "br"}
# A wide table scrolls in this box rather than widen the page. A wrapper, not display: block on the table, which would stop it filling a column and
# take its table semantics away from assistive technology. It can take the focus, to be scrolled from a keyboard.
TABLE_OPEN = '<div class="wiki__table" tabindex="0">'
TABLE_CLOSE = "</div>"
CODE_CLASS = re.compile(r"language-[a-z0-9_+-]+")
ALIGNMENTS = {"left", "right", "center"}

SVG_NAMESPACE = "{http://www.w3.org/2000/svg}"
SVG_ELEMENTS = {
    "svg", "g", "path", "circle", "ellipse", "rect", "line", "polyline", "polygon", "defs", "linearGradient",
    "radialGradient", "stop", "clipPath", "mask", "title", "desc",
}
SVG_OTHER_ENCODING = re.compile(rb"""<\?xml[^>]*\bencoding\s*=\s*["'](?!utf-8["'])""", re.I)
SVG_RAW_REFUSED = re.compile(rb"<!DOCTYPE|<!ENTITY|<\?(?!xml\s)", re.I)
SVG_VALUE_REFUSED = re.compile(r"url\((?!\s*['\"]?#)|@import|javascript:", re.I)


def read_text(path: Path) -> str:
    """Reads as bytes, so that no platform changes the line endings."""
    return path.read_bytes().decode("utf-8")


def escape(text: str) -> str:
    """For text and double-quoted attributes. The apostrophe stays as typed, as in the hand-written pages."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def is_utf8(content: bytes) -> bool:
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def size_text(size: int) -> str:
    return f"{size / 1_000_000:.1f} MB" if size >= 1_000_000 else f"{size / 1_000:.1f} KB"


def exact_size(size: int) -> str:
    """Every digit, for a limit: one byte over must not read as being at the limit."""
    return f"{size:,}".replace(",", " ")


def has_signature(suffix: str, content: bytes) -> bool:
    if suffix == ".webp":
        return content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return content.startswith(SIGNATURES[suffix])


def is_reserved(name: str) -> bool:
    return name.split(".")[0].lower() in RESERVED_NAMES


def is_slug(name: str) -> bool:
    """Whether a name can be a folder or a page of the site, on every OS."""
    return SLUG.fullmatch(name) is not None and len(name) <= MAX_NAME and not is_reserved(name)


def parse_value(raw: str) -> str | None:
    """The text of a header value, or None if it is not written in one of the three accepted forms."""
    if raw.startswith("'"):
        match = re.fullmatch(r"'((?:[^']|'')*)'", raw)
        return match.group(1).replace("''", "'") if match else None
    if raw.startswith('"'):
        match = re.fullmatch(r'"((?:[^"\\]|\\["\\])*)"', raw)
        return re.sub(r"\\(.)", r"\1", match.group(1)) if match else None
    # What YAML would read otherwise, or not at all: refused, rather than read differently from the tools around it.
    if " #" in raw or raw[:1] in tuple("[{&*!|>%@`"):
        return None
    return raw


def split_header(text: str) -> tuple[str, str] | None:
    """(the lines of the header, the body) of a page, or None if it has no header that opens and closes."""
    if not text.startswith("---\n"):
        return None
    # The newline put back in front lets a closing line follow the opening one at once: an empty header is still a header.
    header, closing, body = ("\n" + text[4:]).partition("\n---\n")
    return (header[1:], body) if closing else None


def parse_header(text: str, where: str, problems: list[str]) -> tuple[dict[str, str] | None, str]:
    """(header, Markdown body) of one page. No header that can be read gives None, an empty one gives an empty dict."""
    if "\r" in text or text.startswith("﻿"):
        problems.append(f"{where}: holds a carriage return or a byte order mark, every file is plain LF")
        return None, ""
    if not text.startswith("---\n"):
        problems.append(f"{where}: missing header")
        return None, ""
    parts = split_header(text)
    if parts is None:
        problems.append(f"{where}: header not closed")
        return None, ""
    header, body = parts
    meta: dict[str, str] = {}
    for line in header.split("\n"):
        if not line:
            continue
        key, colon, raw = line.partition(":")
        if not colon or not re.fullmatch(r"[a-z_]+", key):
            problems.append(f"{where}: header line not understood: {line!r}")
            continue
        if key in meta:
            problems.append(f"{where}: '{key}' is given twice")
            continue
        value = parse_value(raw.strip())
        if value is None:
            problems.append(f"{where}: the value of '{key}' is badly quoted: {raw.strip()!r}")
            continue
        meta[key] = value
    return meta, body


def set_header_field(text: str, key: str, value: str) -> str:
    """The page with this header field set, replacing any value it had. The rest stays as written. A page with no header stays as it is."""
    parts = split_header(text)
    if parts is None:
        return text
    header, body = parts
    lines = [line for line in header.split("\n") if line and line.partition(":")[0] != key]
    return "---\n" + "\n".join([*lines, f"{key}: {value}"]) + "\n---\n" + body


def header_field(text: str, key: str) -> str | None:
    """A field of a page's header as written, or None."""
    parts = split_header(text)
    for line in parts[0].split("\n") if parts else ():
        name, colon, raw = line.partition(":")
        if colon and name == key:
            return parse_value(raw.strip())
    return None


def check_svg(content: bytes, where: str) -> list[str]:
    """What is wrong in a mark or an SVG image: it must draw shapes, and do nothing else."""
    # The checks on raw bytes, here and for the private words, only mean something in the encoding they are written for.
    if content.startswith(b"\xef\xbb\xbf") or b"\0" in content or SVG_OTHER_ENCODING.search(content) or not is_utf8(content):
        return [f"{where}: must be plain UTF-8, with no byte order mark and no other encoding declared"]
    if SVG_RAW_REFUSED.search(content):
        return [f"{where}: holds a DOCTYPE, an entity or a processing instruction"]
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        return [f"{where}: not valid XML ({error})"]
    if root.tag != f"{SVG_NAMESPACE}svg":
        return [f"{where}: its root is not an svg element"]
    problems = []
    for element in root.iter():
        name = element.tag.removeprefix(SVG_NAMESPACE)
        if name not in SVG_ELEMENTS:
            problems.append(f"{where}: element {name} is not allowed")
        for attribute, value in element.attrib.items():
            local = attribute.rsplit("}", 1)[-1].lower()
            if local.startswith("on"):
                problems.append(f"{where}: event attribute {local} is not allowed")
            elif local == "href":
                problems.append(f"{where}: a link is not allowed on {name}")
            elif "\\" in value:
                problems.append(f"{where}: attribute {local} holds a backslash, which CSS reads as an escape")
            elif SVG_VALUE_REFUSED.search(value):
                problems.append(f"{where}: attribute {local} reaches outside the image")
    return problems


@dataclass(frozen=True)
class PrivateList:
    """What neither a guide nor an image may name. It is not in this file, which other repositories publish: decision D-023.

    reveal says whether a hit may be told as found: a public log must not say what the list holds.
    """

    words: tuple[str, ...] = ()
    addresses: re.Pattern | None = None
    reveal: bool = True

    def __bool__(self) -> bool:
        return bool(self.words or self.addresses)


def parse_private_list(text: str, reveal: bool = True) -> PrivateList:
    """Entries apart by a line, a blank or a comma, with lines opening in # left out. No entry at all is refused: it would turn the check off without a word."""
    lines = [line for line in text.split("\n") if not line.lstrip().startswith("#")]
    entries = [entry.lower() for entry in re.split(r"[\s,]+", "\n".join(lines)) if entry]
    if not entries:
        raise ValueError("the private list holds no entry")
    prefixes = [re.escape(entry.encode()) for entry in entries if ADDRESS_PREFIX.fullmatch(entry)]
    # An address, not any version number that happens to hold the same digits.
    addresses = re.compile(rb"\b(?:" + b"|".join(prefixes) + rb")\.\d+\.\d+\b") if prefixes else None
    return PrivateList(tuple(entry for entry in entries if not ADDRESS_PREFIX.fullmatch(entry)), addresses, reveal)


# Empty until someone gives one: the build always does (scripts/projects.py), and elsewhere it is an option of the command.
private_list = PrivateList()


def use_private_list(private: PrivateList) -> None:
    global private_list
    private_list = private


def find_private(content: bytes, private: PrivateList) -> list[str]:
    """What of the list a file names, as found, or by its place in the list if the list says so."""
    lowered = content.lower()
    hits = [word if private.reveal else f"entry {place} of the private list" for place, word in enumerate(private.words, 1) if word.encode() in lowered]
    found = [match.group(0).decode() for match in private.addresses.finditer(content)] if private.addresses else []
    return hits + (found if private.reveal else ["an address of the private list"] * len(found))


def private_hits(content: bytes) -> list[str]:
    return find_private(content, private_list)


def indented_fences(body: str) -> int:
    """How many code fences are indented, outside a fenced block: Markdown reads them as text, while GitHub shows a block."""
    found = 0
    open_fence = ""
    for line in body.split("\n"):
        match = FENCE.match(line)
        if not match:
            continue
        indent, fence = match.groups()
        if open_fence:
            if not indent and fence.startswith(open_fence):
                open_fence = ""
        elif indent:
            found += 1
        else:
            open_fence = fence
    return found


def line_nesting(line: str) -> int:
    """How many levels of quote and list a line opens or sits in: each marker, and what its indentation is worth at four spaces a level."""
    markers = 0
    blanks = 0
    position = 0
    while match := CONTAINER.match(line, position):
        markers += 1
        blanks += len(match.group(1).expandtabs(4))
        position = match.end()
    rest = line[position:]
    blanks += len(rest[: len(rest) - len(rest.lstrip(" \t"))].expandtabs(4))
    return markers + blanks // 4


def too_nested(body: str) -> bool:
    """Whether Markdown should not even start. Brackets add up over a block, which ends at a blank line, as Markdown reads links block by block."""
    open_brackets = 0
    for line in body.split("\n"):
        if line_nesting(line) > MAX_NESTING:
            return True
        if not line.strip():
            open_brackets = 0
        for character in line:
            if character == "[":
                open_brackets += 1
                if open_brackets > MAX_OPEN_BRACKETS:
                    return True
            elif character == "]" and open_brackets:
                open_brackets -= 1
    return False


class RenderError(Exception):
    """Markdown could not render a page in the limits it runs under. The message is the problem to list."""


def render_apart(body: str) -> str:
    """Markdown in a process of its own, with a time limit that holds on every OS."""
    options = json.dumps({"extensions": EXTENSIONS, "extension_configs": EXTENSION_CONFIGS})
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(path for path in sys.path if path), "PYTHONUTF8": "1"}
    try:
        result = subprocess.run([sys.executable, "-P", "-c", RENDER_PROGRAM, options], input=body.encode("utf-8"), capture_output=True,
                                env=environment, timeout=RENDER_SECONDS, check=False)
    except subprocess.TimeoutExpired as error:
        raise RenderError(f"takes too long to render, over {RENDER_SECONDS} s") from error
    if result.returncode != 0:
        raise RenderError("cannot be rendered, lists or quotes may be nested too deeply")
    return result.stdout.decode("utf-8")


def render_markdown(body: str) -> str:
    if len(body) > RENDER_IN_PROCESS_CHARACTERS:
        return render_apart(body)
    return markdown.markdown(body, extensions=EXTENSIONS, extension_configs=EXTENSION_CONFIGS)


class _BodyReader(HTMLParser):
    """Goes through what Markdown wrote, holding it to the allowed tags, and writes it again with its links resolved.

    It reads the final HTML rather than Markdown's tree, as raw HTML in a guide never reaches the tree.
    """

    def __init__(self, where: str, resolve):
        super().__init__(convert_charrefs=False)
        self.where = where
        self.resolve = resolve
        self.problems: list[str] = []
        self.out: list[str] = []
        self.open: list[str] = []
        self.headings: list[tuple[int, str, str]] = []
        self.heading: list | None = None
        # How many pieces of markup the parser recognised, each opened by one "<".
        self.markup = 0

    def _problem(self, text: str) -> None:
        self.problems.append(f"{self.where}: {text}")

    def _write_tag(self, tag: str, attrs: list) -> None:
        allowed = ALLOWED_TAGS.get(tag)
        if tag == "h1":
            self._problem("holds an h1, the page's title comes from its header")
            return
        if allowed is None:
            self._problem(f"tag <{tag}> is not allowed")
            return
        written = []
        values = dict(attrs)
        # Only one value would be checked below, while every one is written out and a browser reads the first.
        names = [name for name, _ in attrs]
        for name in sorted({name for name in names if names.count(name) > 1}):
            self._problem(f"attribute {name} is repeated on <{tag}>")
        for name, value in attrs:
            if name not in allowed:
                self._problem(f"attribute {name} is not allowed on <{tag}>")
            elif value is None:
                self._problem(f"attribute {name} of <{tag}> has no value")
            elif name == "class" and not CODE_CLASS.fullmatch(value):
                self._problem(f"class {value!r} is not allowed")
            elif name == "align" and value not in ALIGNMENTS:
                self._problem(f"align {value!r} is not allowed")
            elif name == "start" and not NUMBER.fullmatch(value):
                self._problem(f"start {value!r} is not allowed")
            else:
                if name in ("href", "src") and self.resolve is not None:
                    value = self.resolve(tag, value)
                written.append(f' {name}="{escape(value)}"')
        if tag == "img" and "alt" not in values:
            self._problem("an image has no alt attribute")
        if tag in HEADINGS:
            anchor = values.get("id")
            if not anchor:
                self._problem("a heading has no {#anchor}")
            elif not SLUG.fullmatch(anchor):
                self._problem(f"anchor {anchor!r} is not in lowercase English slug characters")
            elif anchor in PAGE_IDS:
                self._problem(f"anchor {anchor!r} is kept for the page around the text")
            self.heading = [HEADINGS[tag], anchor or "", []]
        if tag == "table":
            self.out.append(TABLE_OPEN)
        self.out.append(f"<{tag}{''.join(written)}>")

    def handle_starttag(self, tag, attrs):
        self.markup += 1
        self._write_tag(tag, attrs)
        if tag not in VOID_TAGS:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.markup += 1
        if tag not in VOID_TAGS:
            self._problem(f"self-closing <{tag}/> is not allowed")
            return
        self._write_tag(tag, attrs)

    def handle_endtag(self, tag):
        self.markup += 1
        if not self.open or self.open.pop() != tag:
            self._problem(f"unbalanced </{tag}>")
            return
        if tag in HEADINGS and self.heading:
            self.headings.append((self.heading[0], self.heading[1], "".join(self.heading[2])))
            self.heading = None
        self.out.append(f"</{tag}>")
        if tag == "table":
            self.out.append(TABLE_CLOSE)

    def _text(self, text: str) -> None:
        self.out.append(text)
        if self.heading:
            self.heading[2].append(text)

    def handle_data(self, data):
        if "<" in data:
            self._problem('holds a raw "<" that is not a tag')
            return
        self._text(data)

    def handle_entityref(self, name):
        self._text(f"&{name};")

    def handle_charref(self, name):
        self._text(f"&#{name};")

    def handle_comment(self, data):
        self.markup += 1
        self._problem("holds an HTML comment")

    def handle_decl(self, decl):
        self.markup += 1
        self._problem("holds an HTML declaration")

    def handle_pi(self, data):
        self.markup += 1
        self._problem("holds a processing instruction")

    def unknown_decl(self, data):
        self.markup += 1
        self._problem("holds a marked section")


def read_body(html: str, where: str, resolve=None) -> tuple[str, list[tuple[int, str, str]], list[str]]:
    """(HTML written again, its headings as (level, anchor, escaped text), problems). resolve(tag, value) gives each link."""
    reader = _BodyReader(where, resolve)
    try:
        reader.feed(html)
        reader.close()
    except AssertionError:
        # What some versions of Python's parser do on a marked section it does not know.
        return "".join(reader.out), reader.headings, [*reader.problems, f"{where}: holds markup that cannot be read"]
    problems = reader.problems + [f"{where}: <{tag}> is not closed" for tag in reader.open]
    # An unterminated tag produces no event, or plain text, depending on Python's version: count instead of asking it.
    if html.count("<") != reader.markup and not any("raw" in problem for problem in problems):
        problems.append(f'{where}: holds a raw "<" that is not a tag')
    anchors = [anchor for _, anchor, _ in reader.headings]
    problems.extend(f"{where}: anchor {anchor!r} is used twice" for anchor in sorted({a for a in anchors if anchors.count(a) > 1}))
    return "".join(reader.out), reader.headings, problems


@dataclass
class Page:
    stem: str
    lang: str
    meta: dict[str, str]
    source: str
    headings: list[tuple[int, str, str]]

    @property
    def order(self) -> int:
        return int(self.meta["order"]) if NUMBER.fullmatch(self.meta.get("order", "")) else 0

    @property
    def anchors(self) -> set[str]:
        return {anchor for _, anchor, _ in self.headings}


@dataclass
class Guide:
    """One guide in every language. The pages are {lang: {stem: Page}}."""

    slug: str
    folder: Path
    where: str
    # The repository the guide comes from, and for a plugin the folder it sits in there, lowercased.
    repository: str
    repository_folder: str = ""
    # Where it sits under /projects/, ending in a slash.
    address: str = ""
    # For a plugin, the slug of the application it belongs to.
    application: str = ""
    # For an application, its plugins whichever repository they come from. For a repository holding plugins, those it holds.
    plugins: list["Guide"] = field(default_factory=list)
    hosted: list["Guide"] = field(default_factory=list)
    pages: dict[str, dict[str, Page]] = field(default_factory=dict)
    images: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    # What the reading has to say that is no problem.
    notices: list[str] = field(default_factory=list)
    # A plugin before it is copied: made_by is written then, from the repository's history.
    made_by_to_come: bool = False

    def home(self, lang: str) -> Page:
        return self.pages[lang][HOME]

    def topics(self, lang: str) -> list[Page]:
        pages = [page for stem, page in self.pages[lang].items() if stem != HOME]
        return sorted(pages, key=lambda page: (page.order, page.stem))

    @property
    def order(self) -> int:
        """That of its home in the first language holding one: a guide missing them all is listed as such, and still gets sorted."""
        return next((pages[HOME].order for pages in self.pages.values() if HOME in pages), 0)


def is_leftover_name(name: str) -> bool:
    return name == LEFTOVER_NAME or name.startswith(LEFTOVER_PREFIX)


def is_leftover(path: Path) -> bool:
    """What the tools left in a copy on this machine, which only a copy can hold: scripts/wiki_update.py refuses such a name from a repository."""
    return is_leftover_name(path.name) and path.is_file()


def only_leftovers(folder: Path) -> bool:
    """Whether a folder holds what the tools left behind and nothing else: it was removed, whatever still sits there."""
    files = [path for path in folder.rglob("*") if not path.is_dir()]
    return bool(files) and all(is_leftover(path) for path in files)


def is_absent(path: Path) -> bool:
    """What a guide is read as not holding: a leftover, or a folder of nothing else. scripts/wiki_update.py lets these through, so the build must too."""
    return is_leftover(path) or (path.is_dir() and only_leftovers(path))


def check_image(content: bytes, suffix: str, where: str) -> list[str]:
    """What is wrong in a mark or an image: its weight, and what it really is."""
    problems = []
    if len(content) > MAX_IMAGE_BYTES:
        problems.append(f"{where}: {exact_size(len(content))} bytes, over the limit of {exact_size(MAX_IMAGE_BYTES)}")
    if suffix == ".svg":
        return problems + check_svg(content, where)
    if not has_signature(suffix, content):
        problems.append(f"{where}: does not start as a {suffix[1:]} file does")
    return problems


def check_github(value: str, repository: str, repository_folder: str, where: str) -> list[str]:
    """The link must name this guide's own repository, and for a plugin its own folder there: a guide cannot claim another's page.

    With no repository to compare, only what can be told without it is checked.
    """
    if repository_folder:
        match = GITHUB_FOLDER.fullmatch(value)
        if not match or any(part in (".", "..", "") for part in match.group(2).split("/")):
            return [f"{where}: 'github' must be the plugin's folder in a repository of {ORGANISATION}"]
        if (repository and match.group(1).lower() != repository) or match.group(2).lower() != repository_folder:
            return [f"{where}: 'github' must be {repository or '<repository>'}/tree/main/{repository_folder}, in any case"]
        return []
    match = GITHUB_REPOSITORY.fullmatch(value)
    if not match:
        return [f"{where}: 'github' must be a repository of {ORGANISATION}"]
    if repository and match.group(1).lower() != repository:
        return [f"{where}: 'github' names {match.group(1)}, while the folder is {repository}"]
    return []


def stamp_as_a_copy_would(text: str, where: str, notices: list[str]) -> str:
    """A copy replaces made_by whatever it says, so that the page is checked as it will be, and what is written here has no effect."""
    parts = split_header(text)
    if parts and any(line.partition(":")[0] == "made_by" for line in parts[0].split("\n")):
        notices.append(f"{where}: 'made_by' is computed when the guide is copied, the one written here is ignored")
    return set_header_field(text, "made_by", MADE_BY[-1])


def _read_page(path: Path, lang: str, guide: Guide, plugin: bool) -> Page:
    where = f"{guide.where}/{lang}/{path.name}"
    stem = path.stem
    problems = guide.problems
    if not is_slug(stem) or len(path.name) > MAX_NAME:
        problems.append(f"{where}: bad file name ({NAME_RULE})")
    if stem in RESERVED_TOPICS:
        problems.append(f"{where}: {stem} is reserved, for the address of the plugins")
    try:
        text = read_text(path)
    except UnicodeDecodeError:
        problems.append(f"{where}: not in UTF-8")
        return Page(stem, lang, {}, "", [])
    if stem == HOME and guide.made_by_to_come:
        text = stamp_as_a_copy_would(text, where, guide.notices)
    size = len(text.encode("utf-8"))
    if size > MAX_PAGE_BYTES:
        problems.append(f"{where}: {exact_size(size)} bytes, over the limit of {exact_size(MAX_PAGE_BYTES)} bytes for a page")
        return Page(stem, lang, {}, "", [])
    control = CONTROL_CHARACTER.search(text)
    if control:
        problems.append(f"{where}: holds a control character (U+{ord(control.group(0)):04X})")
        return Page(stem, lang, {}, "", [])
    header, body = parse_header(text, where, problems)
    meta = header or {}
    required = HOME_FIELDS if stem == HOME else TOPIC_FIELDS
    allowed = set(required)
    if stem == HOME and plugin:
        allowed.add("made_by")
    # Without a readable header, that is the one problem to tell. An empty header has every field missing.
    if header is not None:
        if stem == HOME and plugin and meta.get("made_by") not in MADE_BY:
            problems.append(f"{where}: 'made_by' must be one of {', '.join(MADE_BY)}: just wiki-update writes it")
        problems.extend(f"{where}: missing '{key}'" for key in required if not meta.get(key))
        problems.extend(f"{where}: unknown field '{key}'" for key in sorted(set(meta) - allowed))
        for key, length in FIELD_LENGTHS.items():
            if len(meta.get(key, "")) > length:
                problems.append(f"{where}: '{key}' is longer than {length} characters")
        if meta.get("order") and not NUMBER.fullmatch(meta["order"]):
            problems.append(f"{where}: 'order' must be a number")
        if meta.get("github"):
            problems.extend(check_github(meta["github"], guide.repository, guide.repository_folder, where))
    if indented_fences(body):
        problems.append(f"{where}: a code fence is indented, as in a list, and would show as text: take it out of the list")
    if too_nested(body):
        problems.append(f"{where}: lists, quotes or brackets nested too deeply")
        return Page(stem, lang, meta, "", [])
    try:
        source = render_markdown(body)
    except RecursionError:
        problems.append(f"{where}: lists or quotes nested too deeply")
        return Page(stem, lang, meta, "", [])
    except RenderError as error:
        problems.append(f"{where}: {error}")
        return Page(stem, lang, meta, "", [])
    _, headings, body_problems = read_body(source, where)
    problems.extend(body_problems)
    return Page(stem, lang, meta, source, headings)


def _compare_languages(guide: Guide, languages: list[str]) -> None:
    reference = languages[0]
    for stem, page in guide.pages[reference].items():
        for lang in languages[1:]:
            other = guide.pages[lang].get(stem)
            if other is None:
                continue
            where = f"{guide.where}/{stem}.md"
            if page.anchors != other.anchors:
                different = sorted(page.anchors ^ other.anchors)
                guide.problems.append(f"{where}: anchors differ between {reference} and {lang}: {', '.join(different)}")
            for key in ("order", "github", "made_by"):
                if page.meta.get(key) != other.meta.get(key):
                    guide.problems.append(f"{where}: '{key}' differs between {reference} and {lang}")


def read_guide(folder: Path, languages: list[str], where: str, repository: str, repository_folder: str = "",
               extra: tuple[str, ...] = (), named_by_folder: bool = True, made_by_to_come: bool = False) -> Guide:
    """Everything about one guide folder, with every problem found. extra: other entries the folder may hold.

    named_by_folder: whether the folder's name and where are the guide's own, which those of a checkout, anywhere on a disk, are not.
    """
    guide = Guide(folder.name, folder, where, repository, repository_folder, made_by_to_come=made_by_to_come)
    if named_by_folder and not is_slug(folder.name):
        guide.problems.append(f"{where}: bad folder name ({NAME_RULE})")
    # Read no further: where one leads is no part of the guide, and git would never hand it over as a file.
    linked = [path for path in sorted(folder.rglob("*")) if path.is_symlink() and path.relative_to(folder).parts[0] not in extra]
    if linked:
        guide.problems.extend(f"{where}/{path.relative_to(folder).as_posix()}: a symbolic link cannot be part of a guide" for path in linked)
        return guide
    own_files = [path for path in folder.rglob("*") if path.is_file() and not is_leftover(path) and path.relative_to(folder).parts[0] not in extra]
    total = sum(path.stat().st_size for path in own_files)
    if total > MAX_GUIDE_BYTES:
        # Read no further: a guide this large is not rendered to find out what else is wrong with it.
        guide.problems.append(f"{where}: {exact_size(total)} bytes in all, over the limit of {exact_size(MAX_GUIDE_BYTES)}")
        return guide
    allowed = {"mark.svg", "img", *languages, *extra}
    for entry in sorted(folder.iterdir()):
        if not is_absent(entry) and entry.name not in allowed:
            guide.problems.append(f"{where}: {entry.name} does not belong in a guide")

    mark = folder / "mark.svg"
    if mark.is_file():
        guide.problems.extend(check_image(mark.read_bytes(), ".svg", f"{where}/mark.svg"))
    else:
        guide.problems.append(f"{where}: mark.svg is missing")

    for name in ("img", *extra):
        if (folder / name).exists() and not (folder / name).is_dir():
            guide.problems.append(f"{where}/{name}: must be a folder")
    images = folder / "img"
    if images.is_dir():
        for image in sorted(images.iterdir()):
            if is_absent(image):
                continue
            if not image.is_file() or not IMAGE_NAME.fullmatch(image.name) or is_reserved(image.name) or len(image.name) > MAX_NAME:
                guide.problems.append(f"{where}/img/{image.name}: bad image name ({NAME_RULE}, png, jpg, jpeg, webp, gif or svg)")
                continue
            guide.images.append(image.name)
            guide.problems.extend(check_image(image.read_bytes(), image.suffix, f"{where}/img/{image.name}"))

    for lang in languages:
        guide.pages[lang] = {}
        base = folder / lang
        if not base.is_dir():
            guide.problems.append(f"{where}: {lang}/ is missing")
            continue
        for path in sorted(base.iterdir()):
            if is_absent(path):
                continue
            if path.suffix != ".md" or not path.is_file():
                guide.problems.append(f"{where}/{lang}/{path.name}: only Markdown pages go in a language folder")
                continue
            guide.pages[lang][path.stem] = _read_page(path, lang, guide, bool(repository_folder))
        if HOME not in guide.pages[lang]:
            guide.problems.append(f"{where}: {lang}/index.md is missing")

    stems = {stem for pages in guide.pages.values() for stem in pages}
    for lang in languages:
        for stem in sorted(stems - set(guide.pages[lang])):
            guide.problems.append(f"{where}: {stem}.md is missing in {lang}: a page goes online in every language or not at all")
    _compare_languages(guide, languages)

    for hit in private_hits(os.fsencode(where)) if named_by_folder else ():
        guide.problems.append(f"{where}: its name holds something private: {hit}")
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder).as_posix()
        if not is_leftover(path) and relative.split("/")[0] in allowed - set(extra):
            # fsencode: a name on a disk need not be text.
            hits = private_hits(os.fsencode(relative)) + (private_hits(path.read_bytes()) if path.is_file() else [])
            guide.problems.extend(f"{where}/{relative}: names something private: {hit}" for hit in hits)
    return guide


def repository_path(guide: Guide, lang: str, stem: str) -> str:
    """Where a page sits in its source repository, lowercased, as relative links there are written against it."""
    return posixpath.join(guide.repository_folder, "wiki", "guide", lang, f"{stem}.md")


class AcrossProblem(str):
    """A problem another repository's next update can mend. Told apart by what it is, as two links can give one same message."""


class Links:
    """Every page and image of the guides, by where it sits in its source repository: relative links are written against that."""

    def __init__(self, guide_list: list[Guide], problems: list[str]):
        self.problems = problems
        self.repositories = {guide.repository for guide in guide_list}
        self.pages: dict[tuple[str, str], tuple[Guide, str, str]] = {}
        self.images: dict[tuple[str, str], str] = {}
        # The links waiting for a project.
        self.not_here: list[str] = []
        for guide in guide_list:
            for lang, pages in guide.pages.items():
                for stem in pages:
                    self.pages[(guide.repository, repository_path(guide, lang, stem))] = (guide, lang, stem)
            for name in guide.images:
                path = posixpath.join(guide.repository_folder, "wiki", "guide", "img", name)
                self.images[(guide.repository, path)] = self.image_url(guide, name)

    def page_url(self, guide: Guide, stem: str, lang: str) -> str:
        """What a link to this page becomes. Only the site has addresses."""
        return f"{lang}/{stem}.md"

    def image_url(self, guide: Guide, name: str) -> str:
        return f"img/{name}"

    def knows_anchor(self, guide: Guide, lang: str, stem: str, anchor: str, where: str) -> bool:
        return anchor in guide.pages[lang][stem].anchors

    def can_tell(self, path: str, value: str, where: str) -> bool:
        """Whether a path of a guide's own repository can be judged from the guides at hand."""
        return True

    def waiting(self, value: str, repository: str, where: str) -> str:
        return f"{where}: {value} stays a link to GitHub until project/{repository}/ is here"

    def _problem(self, text: str, across: bool) -> None:
        self.problems.append(AcrossProblem(text) if across else text)

    def _page(self, target: tuple[Guide, str, str], lang: str, anchor: str, where: str, across: bool = False) -> str:
        guide, target_lang, stem = target
        if target_lang != lang:
            self.problems.append(f"{where}: a link leads to the {target_lang} page {stem}.md")
        elif anchor and not self.knows_anchor(guide, lang, stem, anchor, where):
            self._problem(f"{where}: {stem}.md has no anchor {anchor!r}", across)
        url = self.page_url(guide, stem, lang)
        return f"{url}#{anchor}" if anchor else url

    def resolve(self, guide: Guide, page: Page, tag: str, value: str, where: str) -> str:
        """What a link of a page becomes. Anything that would be dead on the site is a problem."""
        problems = self.problems
        github = GITHUB_GUIDE.fullmatch(value)
        if github:
            repository = github.group(1).lower()
            if repository in self.repositories:
                if tag == "img":
                    problems.append(f"{where}: an image cannot lead to a page, nor take a full URL: {value}")
                    return value
                across = repository != guide.repository
                path, _, anchor = ((github.group(2) or "") + github.group(3)).partition("#")
                target = self.pages.get((repository, path.lower()))
                if target is None:
                    if self.can_tell(path.lower(), value, where):
                        self._problem(f"{where}: {value} leads to no page of the site", across)
                    return value
                return self._page(target, page.lang, anchor, where, across)
            self.not_here.append(self.waiting(value, repository, where))
        if SCHEME.match(value):
            if tag == "img":
                problems.append(f"{where}: an outside image would be blocked by the site's CSP: {value}")
            elif not value.lower().startswith(OUTSIDE_SCHEMES):
                problems.append(f"{where}: this kind of link is not allowed: {value}")
            return value
        if value.startswith(("/", "\\")):
            problems.append(f"{where}: an address from the root of the site is not allowed: {value}")
            return value
        path, _, anchor = value.partition("#")
        if "?" in path:
            problems.append(f"{where}: a local link holds a query: {value}")
            return value
        if not path:
            if tag == "img":
                problems.append(f"{where}: an image has no address")
            elif not self.knows_anchor(guide, page.lang, page.stem, anchor, where):
                problems.append(f"{where}: this page has no anchor {anchor!r}")
            return value
        own = repository_path(guide, page.lang, page.stem)
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(own), path)).lower()
        if resolved.startswith(".."):
            problems.append(f"{where}: {value} leaves the repository")
            return value
        image = self.images.get((guide.repository, resolved))
        if image:
            return image
        target = self.pages.get((guide.repository, resolved))
        if target is None or tag == "img":
            if target is not None or self.can_tell(resolved, value, where):
                problems.append(f"{where}: {value} leads to no page or image of the site (a file of the repository takes a full URL)")
            return value
        return self._page(target, page.lang, anchor, where)


class OneGuideLinks(Links):
    """The links of a guide read on its own: what rests on another guide is listed, not judged. The copy recipe judges it, with every guide at hand."""

    def __init__(self, guide: Guide):
        super().__init__([guide], guide.problems)
        self.own = guide
        self.prefix = posixpath.join(guide.repository_folder, *GUIDE_FOLDER, "")

    def waiting(self, value: str, repository: str, where: str) -> str:
        return f"{where}: {value} is in another project, not judged here"

    def can_tell(self, path: str, value: str, where: str) -> bool:
        if path.startswith(self.prefix) or f"{'/'.join(GUIDE_FOLDER)}/" not in path:
            return True
        self.not_here.append(f"{where}: {value} is in another guide of this repository, not judged here")
        return False

    def knows_anchor(self, guide: Guide, lang: str, stem: str, anchor: str, where: str) -> bool:
        if super().knows_anchor(guide, lang, stem, anchor, where):
            return True
        if stem != HOME or guide.repository_folder or not is_plugin_list_anchor(anchor):
            return False
        self.not_here.append(f"{where}: #{anchor} belongs to the list of plugins of a repository holding plugins, not judged here")
        return True


def is_plugin_list_anchor(anchor: str) -> bool:
    return anchor == PLUGINS_ANCHOR or (anchor.startswith(f"{PLUGINS_ANCHOR}-") and is_slug(anchor[len(PLUGINS_ANCHOR) + 1:]))


def one_line(text: str) -> str:
    """A name on a disk can hold anything: a problem stays on its line, whatever it quotes."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]", lambda match: match.group(0).encode("unicode_escape").decode(), text)


def repository_named_by(guide: Guide) -> str:
    """The repository the guide's own github field names, lowercased, or nothing if it names none."""
    for pages in guide.pages.values():
        if HOME in pages:
            link = pages[HOME].meta.get("github", "")
            match = (GITHUB_FOLDER if guide.repository_folder else GITHUB_REPOSITORY).fullmatch(link)
            if match:
                return match.group(1).lower()
    return ""


def check_alone(folder: Path, where: str, repository: str, plugin: tuple[str, str] | None) -> tuple[list[str], list[str], Guide]:
    """(problems, notices, the guide) of one guide read with nothing around it."""
    problems = []
    application, name = plugin or ("", "")
    for label, value in (("repository", repository), ("application", application), ("plugin", name)):
        if value and not is_slug(value):
            problems.append(f"{where}: bad {label} name {value!r} ({NAME_RULE})")
        problems.extend(f"{where}: the {label} name names something private: {hit}" for hit in private_hits(value.encode()))
    # A copy holds its plugins in plugins/. A repository holds them in <Application>-plugins/, and the copy recipe refuses this folder in its guide.
    in_repository = folder.resolve().parts[-len(GUIDE_FOLDER):] == GUIDE_FOLDER
    extra = () if plugin or in_repository else (PLUGINS_FOLDER,)
    repository_folder = f"{application}-plugins/{name}" if plugin else ""
    guide = read_guide(folder, list(DEFAULT_LANGUAGES), where, repository, repository_folder, extra, named_by_folder=False, made_by_to_come=bool(plugin))
    notices = list(guide.notices)
    if not repository:
        notices.append("'github' is checked for its shape only: --repo <name> also matches it against the repository")
        guide.repository = repository_named_by(guide)
        if guide.repository and not is_slug(guide.repository):
            problems.append(f"{where}: 'github' names {guide.repository}, which cannot give an address ({NAME_RULE})")
    links = OneGuideLinks(guide)
    for lang, pages in guide.pages.items():
        for stem, page in pages.items():
            page_where = f"{where}/{lang}/{stem}.md"
            read_body(page.source, page_where, lambda tag, value, page=page, page_where=page_where: links.resolve(guide, page, tag, value, page_where))
            if not plugin and stem == HOME:
                notices.extend(f"{page_where}: anchor {anchor!r} is kept for the list of plugins in a repository holding plugins" for anchor in sorted(page.anchors) if is_plugin_list_anchor(anchor))
    notices.extend(links.not_here)
    if PLUGINS_FOLDER in extra:
        notices.extend(f"{where}/{path.relative_to(folder).as_posix()}: a plugin of this copy, not checked with it: run this again on it with --plugin {path.parent.name}/{path.name}"
                       for path in sorted(folder.glob(f"{PLUGINS_FOLDER}/*/*")) if path.is_dir() and not is_absent(path))
    notices.extend(f"{where}/{path.relative_to(folder).as_posix()}: left by a machine and skipped here, the copy recipe refuses it if it is committed"
                   for path in sorted(folder.rglob("*")) if is_leftover(path) and path.relative_to(folder).parts[0] not in extra)
    if not private_list:
        notices.append(f"private words not checked, as no list was given (--private-words <file> or {PRIVATE_WORDS_VARIABLE}): just wiki-update checks them when it copies the guide")
    return [*problems, *guide.problems], notices, guide


def private_list_given(option: str | None, parser: argparse.ArgumentParser) -> PrivateList | None:
    """The list of the option, or of the variable. A variable that is empty is no list, as a fork of a repository is given no secret. A file that gives none is a mistake."""
    try:
        text = os.environ.get(PRIVATE_WORDS_VARIABLE, "") if option is None else read_text(Path(option))
        text.encode()
        return None if option is None and not text.strip() else parse_private_list(text, reveal=False)
    except (OSError, ValueError) as error:
        parser.error(f"private words: {error}")


def parse_arguments(arguments: list[str] | None) -> tuple[argparse.Namespace, argparse.ArgumentParser]:
    digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    purpose = "Checks a project's guide against the rules of the site that publishes it."
    parser = argparse.ArgumentParser(prog="guide_check.py", description=purpose, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="the guide's folder: <repository>/wiki/guide, or a copy, whose plugins/ are named and left to their own run")
    parser.add_argument("--repo", metavar="NAME", help="the repository's name, in any case. Without it, 'github' is checked for its shape only")
    parser.add_argument("--plugin", metavar="APPLICATION/NAME", help="this is a plugin's guide, in <Application>-plugins/<Name>/wiki/guide: its made_by comes with the copy")
    parser.add_argument("--private-words", metavar="FILE", help=f"the list of what must not appear, kept out of this public file. Without it, {PRIVATE_WORDS_VARIABLE}, then no such check")
    parser.add_argument("--version", action="version", version=f"guide_check format {FORMAT_VERSION}, sha256 {digest}\n{purpose}")
    options = parser.parse_args(arguments)
    if options.repo is not None and not GITHUB_NAME.fullmatch(options.repo):
        parser.error(f"--repo: not a repository's name: {one_line(options.repo)}")
    if options.plugin is not None:
        parts = options.plugin.split("/")
        if len(parts) != 2 or not all(GITHUB_NAME.fullmatch(part) for part in parts):
            parser.error(f"--plugin: give <application>/<name>: {one_line(options.plugin)}")
        if parts[0].lower().endswith(f"-{PLUGINS_FOLDER}"):
            parser.error(f"--plugin: give the application's own name, with no -{PLUGINS_FOLDER}: {one_line(options.plugin)}")
    if not Path(options.path).is_dir():
        parser.error(f"not a folder: {one_line(options.path)}")
    return options, parser


def main(arguments: list[str] | None = None) -> int:
    # Plain UTF-8 and LF on every OS, and a name that is not text stays readable rather than stopping the output.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace", newline="\n")
    options, parser = parse_arguments(arguments)
    if markdown is None or markdown.__version__ != MARKDOWN_VERSION:
        found = "no markdown" if markdown is None else f"markdown {markdown.__version__}"
        print(f"guide_check needs markdown=={MARKDOWN_VERSION} and found {found}: run it with uv run guide_check.py, or pip install markdown=={MARKDOWN_VERSION}", file=sys.stderr)
        return 2
    private = private_list_given(options.private_words, parser)
    if private is not None:
        use_private_list(private)
    folder = Path(options.path)
    where = folder.as_posix()
    repository = (options.repo or "").lower()
    plugin = tuple(options.plugin.lower().split("/")) if options.plugin else None
    try:
        problems, notices, guide = check_alone(folder, where, repository, plugin)
    except Exception as error:  # Whatever a disk or a parser does on what it is handed: this command never answers with a traceback.
        print(one_line(f"{where}: cannot be read: {error!r}"))
        return 1
    for notice in dict.fromkeys(notices):
        print(one_line(f"notice: {notice}"))
    for problem in dict.fromkeys(problems):
        print(one_line(problem))
    if problems:
        return 1
    count = len({stem for pages in guide.pages.values() for stem in pages})
    images = f"{len(guide.images)} image{'s' if len(guide.images) > 1 else ''}" if guide.images else "no image"
    print(f"{where}: clean, {count} page{'s' if count > 1 else ''} in {', '.join(DEFAULT_LANGUAGES)}, {images}, format {FORMAT_VERSION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
