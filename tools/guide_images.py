"""The guide's screenshots are goldens, copied byte for byte: `python tools/guide_images.py copy|check`.

`copy` refreshes wiki/guide/img/ from tests/goldens, following IMAGES; `just goldens` runs it after every capture, so
the guide never shows an older screen than the one the goldens pin. `check` fails when an image differs from its
golden, is missing or unknown, has a name SiteLuna refuses, weighs too much, or is not shown by a page in every
language. Standard library only, so that it runs in any image.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDENS = ROOT / "tests" / "goldens"
GUIDE = ROOT / "wiki" / "guide"
IMAGES_DIR = GUIDE / "img"
LANGUAGES = ("fr", "en")

# The guide image's name -> the golden it copies. A new screenshot in the guide is one line here.
IMAGES = {
    "sign-in.png": "frame-login.png",
    "links-list.png": "links-list.png",
    "link-new.png": "links-new.png",
    "link-address.png": "address-links-list.png",
    "nanourls-list.png": "nanourls-list.png",
    "qrcode-design.png": "qrcodes-designed.png",
    "qrcode-logo.png": "qrcodes-logo.png",
    "settings-security.png": "settings-security.png",
    "settings-webhook.png": "settings-webhook-saved.png",
    "settings-api-keys.png": "settings-keys-list.png",
    "settings-new-key.png": "settings-keys-new.png",
    "cloudflare-hosts.png": "settings-cloudflare-hosts.png",
    "cloudflare-new-host.png": "settings-cloudflare-plan-live-ticked.png",
}

# SiteLuna's rules for a guide image (guide_check.py, format 1)
NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*\.png")
MAX_NAME = 64
MAX_BYTES = 2_000_000
# A Markdown image pointing into the shared img/ folder: ![alt](../img/name)
REFERENCE = re.compile(r"!\[[^\]]*\]\(\.\./img/([^)\s]+)\)")


def copy() -> list[str]:
    """Write every image from its golden, and drop any image no longer listed. The folder is refilled in place, never
    deleted, so that it survives the network share."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    for name, golden in IMAGES.items():
        content = (GOLDENS / golden).read_bytes()
        target = IMAGES_DIR / name
        if not target.is_file() or target.read_bytes() != content:
            target.write_bytes(content)
    for stale in IMAGES_DIR.iterdir():
        if stale.is_file() and stale.name not in IMAGES:
            stale.unlink()
    return sorted(IMAGES)


def references(language: str) -> set[str]:
    """Every image the pages of one language show."""
    found = set()
    for page in sorted((GUIDE / language).glob("*.md")):
        found.update(REFERENCE.findall(page.read_text(encoding="utf-8")))
    return found


def problems() -> list[str]:
    """Everything wrong between the goldens, wiki/guide/img/ and the pages; empty when all is well."""
    found = []
    for name, golden in IMAGES.items():
        if not NAME.fullmatch(name) or len(name) > MAX_NAME:
            found.append(f"{name}: not a name SiteLuna takes (lowercase words joined by hyphens, .png, <= {MAX_NAME})")
        source = GOLDENS / golden
        if not source.is_file():
            found.append(f"{name}: its golden {golden} does not exist")
            continue
        target = IMAGES_DIR / name
        if not target.is_file():
            found.append(f"{name}: missing from wiki/guide/img, run just guide-images")
        elif target.read_bytes() != source.read_bytes():
            found.append(f"{name}: differs from its golden {golden}, run just guide-images")
        elif target.stat().st_size > MAX_BYTES:
            found.append(f"{name}: {target.stat().st_size} bytes, over {MAX_BYTES}")
    if IMAGES_DIR.is_dir():
        for extra in sorted(IMAGES_DIR.iterdir()):
            if extra.name not in IMAGES:
                found.append(f"{extra.name}: in wiki/guide/img but copies no golden")
    for language in LANGUAGES:
        shown = references(language)
        for name in sorted(set(IMAGES) - shown):
            found.append(f"{name}: shown by no page in {language}")
        for name in sorted(shown - set(IMAGES)):
            found.append(f"{language}: a page shows ../img/{name}, which is not a guide image")
    return found


def main(argv: list[str]) -> int:
    if argv == ["copy"]:
        names = copy()
        print(f"{len(names)} guide images copied from tests/goldens")
        return 0
    if argv == ["check"]:
        found = problems()
        for line in found:
            print(line)
        print(f"{len(IMAGES)} guide images checked, {len(found)} problems")
        return 1 if found else 0
    print("usage: python tools/guide_images.py copy|check", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
