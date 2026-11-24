"""The byte comparison behind `just goldens-check` and `just goldens-stability`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "ui"))

import compare  # noqa: E402


def folder(tmp_path: Path, name: str, files: dict[str, bytes]) -> Path:
    path = tmp_path / name
    path.mkdir()
    for file, content in files.items():
        (path / file).write_bytes(content)
    return path


def test_the_same_bytes_pass(tmp_path, capsys):
    a = folder(tmp_path, "a", {"x.png": b"1", "y.png": b"2"})
    b = folder(tmp_path, "b", {"x.png": b"1", "y.png": b"2"})
    assert compare.main([str(a), str(b)]) == 0
    assert "2 goldens compared, 0 differences" in capsys.readouterr().out


def test_one_byte_new_or_missing_fails_and_is_named(tmp_path, capsys):
    a = folder(tmp_path, "a", {"x.png": b"1", "gone.png": b"2", "note.txt": b"not a golden"})
    b = folder(tmp_path, "b", {"x.png": b"1 ", "added.png": b"3"})
    assert compare.main([str(a), str(b)]) == 1
    out = capsys.readouterr().out
    assert "missing gone.png" in out and "new added.png" in out and "changed x.png" in out
    assert "note.txt" not in out


def test_no_golden_at_all_fails(tmp_path):
    assert compare.main([str(folder(tmp_path, "a", {})), str(folder(tmp_path, "b", {}))]) == 1


def test_usage(capsys):
    assert compare.main([]) == 2
