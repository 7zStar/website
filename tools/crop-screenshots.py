#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Crop raw VM screenshots into the images the site shows.

    uv run tools/crop-screenshots.py --slug zh-hant --main raw/main.png --menu raw/menu.png

Writes public/screenshots/<slug>/main.png and menu.png. The boxes below fit one VM screen
size, so a new capture size needs new boxes; the script stops if the size is different.
Both images use the same box, so they show at the same scale side by side, and the page's
enlarged view relies on every screenshot having the same size.
"""
import argparse
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SCREEN = (1920, 1200)
# The VM places the window at 1000x760 from (460, 220) in every shot. The box is tall enough for
# the expanded 7-ZSTar submenu, which reaches y=1108, and stops above the taskbar (y=1152). Its
# width then follows from the 1.312 aspect ratio of the earlier screenshots, centred on the window,
# which keeps it right of the desktop icons (x<70).
FRAME = (316, 162, 1596, 1138)  # left, top, right, bottom
BOXES = {"main": FRAME, "menu": FRAME}


def check(src: Path) -> None:
    with Image.open(src) as image:
        if image.size != SCREEN:
            raise SystemExit(f"{src}: size {image.size} is not {SCREEN}, update SCREEN and BOXES")


def crop(src: Path, box: tuple[int, int, int, int], dest: Path) -> None:
    with Image.open(src) as image:
        dest.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").crop(box).save(dest, optimize=True)
    print("wrote", dest.relative_to(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slug", required=True, help="language folder, such as zh-hant")
    parser.add_argument("--main", required=True, type=Path, help="raw screenshot of the main window")
    parser.add_argument("--menu", required=True, type=Path, help="raw screenshot of the right-click menu")
    parser.add_argument("--new", action="store_true", help="the language folder does not exist yet")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z]+(-[a-z]+)*", args.slug):
        raise SystemExit(f"--slug must look like zh-hant, got {args.slug!r}")
    if not args.new and not (ROOT / "public" / "screenshots" / args.slug).is_dir():
        raise SystemExit(f"public/screenshots/{args.slug} does not exist; check the slug, or pass --new for a new language")
    check(args.main)  # both first, so a bad file never leaves a half-updated pair
    check(args.menu)
    out = ROOT / "public" / "screenshots" / args.slug
    crop(args.main, BOXES["main"], out / "main.png")
    crop(args.menu, BOXES["menu"], out / "menu.png")


if __name__ == "__main__":
    sys.exit(main())
