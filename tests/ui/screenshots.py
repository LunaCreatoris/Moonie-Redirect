"""The GUI goldens: every screen and state of the admin, captured from the real app in a pinned Chromium.

Run in the pinned Playwright image through `just goldens`, `just goldens-check` and `just goldens-stability`, never
with a browser of the host. Each walk starts the app in this process on a fresh database, with a clock and random draws
the walk owns, so two runs on any machine write the same bytes. The names are 7.0.1's golden names, less `-en-desktop`.

    python tests/ui/screenshots.py --out DIR [WALK ...]
"""

import argparse
import sys
from pathlib import Path

from kit import Run, running
from playwright.sync_api import sync_playwright
from walk_address import walk as address
from walk_frame import walk as frame
from walk_links import walk as links
from walk_nanourls import walk as nanourls
from walk_qrcodes import walk as qrcodes
from walk_settings import walk as settings
from walk_settings_cloudflare import walk as settings_cloudflare

WALKS = {
    "frame": frame,
    "links": links,
    "nanourls": nanourls,
    "qrcodes": qrcodes,
    "settings-cloudflare": settings_cloudflare,
    "address": address,
    "settings": settings,
}
# Chromium rasterizes on several threads and may round an antialiased edge one way or the other from run to run: one
# thread, no GPU and no partial raster make every pixel the same on every run
CHROMIUM_ARGS = [
    "--disable-gpu",
    "--disable-lcd-text",
    "--font-render-hinting=none",
    "--num-raster-threads=1",
    "--disable-partial-raster",
    "--force-color-profile=srgb",
]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("walks", nargs="*", metavar="WALK", help=", ".join(WALKS))
    args = parser.parse_args(argv)
    unknown = [name for name in args.walks if name not in WALKS]
    if unknown:
        parser.error(f"unknown walk {', '.join(unknown)}: choose from {', '.join(WALKS)}")
    chosen = args.walks or list(WALKS)
    args.out.mkdir(parents=True, exist_ok=True)
    run = Run(args.out)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=CHROMIUM_ARGS)
        try:
            for name in chosen:
                with running(browser, playwright, run, name) as live:
                    WALKS[name](live)
                print(f"{name}: done", flush=True)
        finally:
            browser.close()
    # A full run leaves no golden of a screen that is gone; the folder is emptied in place, never removed
    if not args.walks:
        for stale in sorted({path.stem for path in args.out.glob("*.png")} - set(run.written)):
            (args.out / f"{stale}.png").unlink()
            print(f"removed {stale}.png", flush=True)
    print(f"{len(run.written)} goldens", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
