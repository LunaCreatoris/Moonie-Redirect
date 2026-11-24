"""Compare two folders of goldens byte for byte: `python tests/ui/compare.py EXPECTED ACTUAL`.

Says every golden that is new, missing or changed, and exits 1 if there is one. Standard library only, so that it runs
in any image."""

import hashlib
import sys
from pathlib import Path


def digests(folder: Path) -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(folder.glob("*.png"))}


def differences(expected: Path, actual: Path) -> list[str]:
    before, after = digests(expected), digests(actual)
    lines = [f"missing {name}" for name in sorted(before.keys() - after.keys())]
    lines += [f"new {name}" for name in sorted(after.keys() - before.keys())]
    lines += [f"changed {name}" for name in sorted(before.keys() & after.keys()) if before[name] != after[name]]
    return lines


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python tests/ui/compare.py EXPECTED ACTUAL", file=sys.stderr)
        return 2
    expected, actual = map(Path, argv)
    lines = differences(expected, actual)
    for line in lines:
        print(line)
    if not digests(expected):
        print(f"no golden in {expected}")
        return 1
    print(f"{len(digests(expected))} goldens compared, {len(lines)} differences")
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
