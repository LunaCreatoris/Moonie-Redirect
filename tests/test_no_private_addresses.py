"""No text in the repository names a real host's IPv4 address.

Every address written in the repository is a documentation, loopback or other well-known address, a network constant
(such as an RFC 1918 block), or one of the few stand-ins the tests use for a LAN host. Text is read through NFKC and
`unicodedata.digit` first, so an address spelled in full-width or Arabic-Indic digits is caught like an ASCII one.
"""

import ipaddress
import re
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Folders that hold no source: tools' caches, build output, local data and other checkouts
SKIPPED_FOLDERS = {
    ".git",
    ".worktrees",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "data",
    "secrets",
}
# Local files the repository ignores, which may name real hosts on purpose and are never published
SKIPPED_FILES = {".env", "CHANGELOG.md", ".guide-check-private-words"}
SKIPPED_PREFIXES = (".smbdelete", "._")

# Any address inside these is fine to show
ALLOWED_NETWORKS = tuple(
    ipaddress.ip_network(text)
    for text in (
        "192.0.2.0/24",  # TEST-NET-1, RFC 5737
        "198.51.100.0/24",  # TEST-NET-2
        "203.0.113.0/24",  # TEST-NET-3
        "127.0.0.0/8",  # loopback
        "169.254.0.0/16",  # link-local, the cloud metadata address with it
        "224.0.0.0/4",  # multicast
        "240.0.0.0/4",  # reserved, with the broadcast address
        "198.18.0.0/15",  # benchmarking, RFC 2544
        "0.0.0.0/32",  # unspecified
    )
)
# Well-known public services, and the stand-ins the webhook guard's tests use for hosts of a LAN
ALLOWED_ADDRESSES = frozenset(
    ipaddress.ip_address(text)
    for text in (
        "8.8.8.8",
        "1.1.1.1",
        "168.63.129.16",
        "100.100.100.200",
        "100.64.1.1",
        "10.20.30.40",
        "172.16.0.1",
        "172.20.0.3",
        "172.31.255.254",
        "192.168.1.10",
        "192.168.1.20",
    )
)
# A network constant is written as its network address and a short prefix, such as an RFC 1918 block
LONGEST_NETWORK_PREFIX = 16

ADDRESS = re.compile(r"(?<![0-9.])(\d{1,3}(?:\.\d{1,3}){3})(?:/(\d{1,2}))?(?![0-9.])")


def fold(text: str) -> str:
    """NFKC, then every character with a decimal digit value as that ASCII digit."""
    folded = unicodedata.normalize("NFKC", text)
    return "".join(
        str(unicodedata.digit(char)) if not char.isascii() and unicodedata.digit(char, None) is not None else char
        for char in folded
    )


def refused_addresses(text: str) -> list[str]:
    """The IPv4 addresses of `text` that the repository may not show, as folded."""
    refused = []
    for match in ADDRESS.finditer(fold(text)):
        written, prefix = match.group(1), match.group(2)
        try:
            address = ipaddress.ip_address(written)
        except ValueError:
            continue  # a number past 255: a version or a sum, not an address
        if prefix is not None and int(prefix) <= LONGEST_NETWORK_PREFIX:
            try:
                ipaddress.ip_network(f"{written}/{prefix}")
                continue
            except ValueError:
                pass  # host bits set: an address, judged as one
        if address in ALLOWED_ADDRESSES or any(address in network for network in ALLOWED_NETWORKS):
            continue
        refused.append(written)
    return refused


def repository_texts():
    """Each text file of the repository, as its path from the root and its text."""
    for path in sorted(ROOT.rglob("*")):
        parts = path.relative_to(ROOT).parts
        if any(part in SKIPPED_FOLDERS for part in parts[:-1]) or not path.is_file():
            continue
        if path.name in SKIPPED_FILES or path.name.startswith(SKIPPED_PREFIXES):
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue  # an image or a font
        yield "/".join(parts), text


def digits(*groups: str) -> str:
    """An address from its four groups, so that no address is written whole in this file."""
    return ".".join(groups)


def test_fold_reads_full_width_and_arabic_indic_digits_as_ascii():
    assert fold("１０．２") == "10.2"
    assert fold("١٠") == "10"
    assert fold("۴۲") == "42"  # extended Arabic-Indic
    assert fold("Café menu") == "Café menu"


@pytest.mark.parametrize(
    "text",
    [
        "http://" + digits("11", "22", "33", "44") + ":2020/",
        "http://" + digits("١١", "22", "33", "44") + ":2020/",
        "http://" + digits("１１", "２２", "33", "44") + "/x",
        digits("10", "1", "2", "3"),
        digits("10", "1", "2", "3") + "/8",  # host bits set: an address, not a network constant
    ],
    ids=["ascii", "arabic-indic", "full-width", "lan", "lan-with-prefix"],
)
def test_an_address_of_a_real_host_is_refused_in_any_digits(text):
    assert len(refused_addresses(text)) == 1


@pytest.mark.parametrize(
    "text",
    [
        digits("192", "0", "2", "1"),
        digits("١٩٢", "0", "2", "10"),
        digits("127", "0", "0", "1"),
        digits("10", "0", "0", "0") + "/8",
        digits("10", "20", "30", "40"),
        "version " + digits("1", "52", "0") + " and " + digits("300", "1", "2", "3"),
    ],
    ids=["documentation", "documentation-arabic-indic", "loopback", "network-constant", "stand-in", "not-addresses"],
)
def test_documentation_loopback_constants_and_stand_ins_pass(text):
    assert refused_addresses(text) == []


def test_no_file_of_the_repository_shows_the_address_of_a_real_host():
    found = []
    for name, text in repository_texts():
        for number, line in enumerate(text.splitlines(), 1):
            found += [f"{name}:{number}: {address}" for address in refused_addresses(line)]
    assert found == []
