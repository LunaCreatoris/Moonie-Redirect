"""The guide and the licence around it: what `just guide-check` cannot see on its own.

The format itself (front matter, anchors, links, the same pages in every language, forbidden words) is SiteLuna's
checker's job, run by `just guide-check`. These tests hold the rest: the checker is still the byte copy it was vendored
as, the guide's mark is the app's, the wiki's root page leads into both languages, and the licence is the one the
README names.
"""

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "wiki" / "guide"

# SiteLuna's guide_check.py, format 1, as vendored (D31): never edited here, only replaced by a newer copy
CHECKER_SHA256 = "d74b84b0bbf9318272ab43df6c4ccd4844bc87209a93a2f97693d742b0f29a78"
# The GNU AGPL-3.0 text as the FSF publishes it, unmodified
LICENSE_SHA256 = "0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_checker_is_the_vendored_copy():
    assert sha256(ROOT / "tools" / "guide_check.py") == CHECKER_SHA256


def test_the_guide_mark_is_the_app_mark():
    assert (GUIDE / "mark.svg").read_bytes() == (ROOT / "static" / "mark.svg").read_bytes()


def test_every_language_has_the_same_pages():
    # img/ is shared by the languages, not one of them
    folders = [folder for folder in GUIDE.iterdir() if folder.is_dir() and folder.name != "img"]
    pages = {folder.name: sorted(page.name for page in folder.glob("*.md")) for folder in folders}
    assert set(pages) == {"fr", "en"}
    assert pages["fr"] == pages["en"]
    assert "index.md" in pages["fr"]


def test_the_wiki_root_links_into_both_languages():
    text = (ROOT / "wiki" / "index.md").read_text(encoding="utf-8")
    targets = re.findall(r"\]\(([^)]+)\)", text)
    assert sorted(targets) == ["guide/en/index.md", "guide/fr/index.md"]
    for target in targets:
        assert (ROOT / "wiki" / target).is_file()


def test_the_guide_status_is_the_app_version():
    version = re.search(r'^VERSION = "([^"]+)"$', (ROOT / "app.py").read_text(encoding="utf-8"), re.MULTILINE).group(1)
    for language in ("fr", "en"):
        front = (GUIDE / language / "index.md").read_text(encoding="utf-8").split("\n---\n", 1)[0]
        assert f"\nstatus: Version {version}\n" in front + "\n"


def test_the_licence_is_the_agpl_text_the_readme_names():
    assert sha256(ROOT / "LICENSE") == LICENSE_SHA256
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Licence" in readme
    assert "AGPL-3.0-or-later" in readme
    # The third-party licences the README names are the ones shipped beside their files
    assert (ROOT / "static" / "fonts" / "OFL-Manrope.txt").is_file()
    assert (ROOT / "static" / "fonts" / "OFL-IBM-Plex-Mono.txt").is_file()
    assert (ROOT / "static" / "ui" / "LICENSE-material-symbols.txt").is_file()
