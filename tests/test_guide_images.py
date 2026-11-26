"""The guide's screenshots (tools/guide_images.py): byte copies of goldens, each shown in every language."""

import shutil
from pathlib import Path

import pytest

from tools import guide_images

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A copy of the goldens and the guide pages the images need, with the module pointed at it."""
    goldens = tmp_path / "goldens"
    goldens.mkdir()
    for golden in guide_images.IMAGES.values():
        shutil.copyfile(guide_images.GOLDENS / golden, goldens / golden)
    guide = tmp_path / "guide"
    for language in guide_images.LANGUAGES:
        shutil.copytree(guide_images.GUIDE / language, guide / language)
    monkeypatch.setattr(guide_images, "GOLDENS", goldens)
    monkeypatch.setattr(guide_images, "GUIDE", guide)
    monkeypatch.setattr(guide_images, "IMAGES_DIR", guide / "img")
    guide_images.copy()
    return tmp_path


def test_the_committed_images_are_their_goldens_and_all_shown():
    assert guide_images.problems() == []


def test_every_name_suits_siteluna():
    for name in guide_images.IMAGES:
        assert guide_images.NAME.fullmatch(name)
        assert len(name) <= guide_images.MAX_NAME


def test_img_holds_only_the_mapped_images():
    assert sorted(path.name for path in guide_images.IMAGES_DIR.iterdir()) == sorted(guide_images.IMAGES)


def test_copy_is_byte_for_byte_and_drops_stale_images(tree):
    img = tree / "guide" / "img"
    (img / "old-screen.png").write_bytes(b"stale")
    (img / "sign-in.png").write_bytes(b"older capture")
    guide_images.copy()
    assert not (img / "old-screen.png").exists()
    for name, golden in guide_images.IMAGES.items():
        assert (img / name).read_bytes() == (tree / "goldens" / golden).read_bytes()
    assert guide_images.problems() == []


def test_a_regenerated_golden_is_caught_until_copied_again(tree):
    golden = tree / "goldens" / guide_images.IMAGES["links-list.png"]
    golden.write_bytes(golden.read_bytes() + b"\0")
    assert guide_images.problems() == ["links-list.png: differs from its golden links-list.png, run just guide-images"]
    guide_images.copy()
    assert guide_images.problems() == []


def test_a_missing_or_unknown_image_is_caught(tree):
    img = tree / "guide" / "img"
    (img / "sign-in.png").unlink()
    (img / "extra.png").write_bytes(b"x")
    assert guide_images.problems() == [
        "sign-in.png: missing from wiki/guide/img, run just guide-images",
        "extra.png: in wiki/guide/img but copies no golden",
    ]


def test_an_image_shown_in_one_language_only_is_caught(tree):
    page = tree / "guide" / "en" / "usage.md"
    page.write_text(page.read_text(encoding="utf-8").replace("(../img/sign-in.png)", ""), encoding="utf-8")
    assert guide_images.problems() == ["sign-in.png: shown by no page in en"]


def test_a_reference_to_no_image_is_caught(tree):
    page = tree / "guide" / "fr" / "usage.md"
    page.write_text(page.read_text(encoding="utf-8") + "\n![Absent](../img/absent.png)\n", encoding="utf-8")
    assert guide_images.problems() == ["fr: a page shows ../img/absent.png, which is not a guide image"]


def test_a_heavy_image_is_caught(tree, monkeypatch):
    monkeypatch.setattr(guide_images, "MAX_BYTES", 1000)
    found = guide_images.problems()
    assert len(found) == len(guide_images.IMAGES)
    assert all("over 1000" in line for line in found)


def test_a_bad_name_is_caught(tree, monkeypatch):
    images = dict(guide_images.IMAGES)
    images["Sign_In.png"] = images.pop("sign-in.png")
    monkeypatch.setattr(guide_images, "IMAGES", images)
    assert any(line.startswith("Sign_In.png: not a name SiteLuna takes") for line in guide_images.problems())


def test_regenerating_the_goldens_refreshes_the_guide_images():
    justfile = (ROOT / "justfile").read_text(encoding="utf-8")
    goldens = justfile.split("\ngoldens *WALKS:\n", 1)[1].split("\n\n", 1)[0]
    assert "python tools/guide_images.py copy" in goldens
    ci = next(line for line in justfile.splitlines() if line.startswith("ci:"))
    assert "guide-images-check" in ci.split()


def test_main_answers_usage_and_check(capsys):
    assert guide_images.main([]) == 2
    assert guide_images.main(["check"]) == 0
    assert f"{len(guide_images.IMAGES)} guide images checked, 0 problems" in capsys.readouterr().out
