#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["fonttools==4.60.1", "brotli==1.1.0"]
# ///
"""Build the self-hosted fonts for the zh-Hans page.

Usage:
  uv run tools/build-pages.py
  uv run tools/subset-fonts.py --src <dir> --html public/zh-hans/index.html --out public/fonts

The page must be built first: the character set is read from the generated zh-Hans page.
<dir> must hold NotoSansSC[wght].ttf (2.004) and Unbounded[wght].ttf (1.701), the variable
fonts from google/fonts. Rerun whenever the zh-Hans copy changes, or new characters fall
back to a system font.

Licensing (SIL OFL 1.1):
- Noto Sans SC: the Reserved Font Name is "Source", which is not in the font's name.
- Unbounded: no Reserved Font Name.
- IBM Plex Mono is not handled here: its Reserved Font Name "Plex" rules out subsetting
  under that name, so the official woff2 files from @ibm/plex-mono ship unmodified.
The OFL-*.txt files and the Plex woff2 files are placed in the output folder by hand.
"""
import argparse
import re
from html import unescape
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ASCII = {chr(c) for c in range(0x20, 0x7F)}
LATIN_EXTRA = set("“”‘’–—…·×→")


def page_chars(html: str) -> set[str]:
    """Every character the zh-Hans page can show: its body text and meta tags, plus the
    benchmark row labels its script embeds. Nothing else of the dictionary is embedded."""
    if '<html lang="zh-Hans">' not in html:
        raise SystemExit("not the zh-Hans page: the font would silently grow")
    html = re.sub(r"/\*.*?\*/", "", html, flags=re.S)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return {c for c in unescape(html) if ord(c) > 0x7E} | ASCII


def build(src: Path, out: Path, chars: set[str], wght: tuple[int, int]) -> None:
    font = TTFont(src)
    options = subset.Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.notdef_outline = True
    subsetter = subset.Subsetter(options)
    subsetter.populate(text="".join(sorted(chars)))
    subsetter.subset(font)
    # Limit the axis after subsetting: the other order drops gvar entries the subsetter needs.
    font = instancer.instantiateVariableFont(font, {"wght": wght})
    font.flavor = "woff2"
    font.save(out)
    print(f"{out.name}: {len(chars)} chars requested, {out.stat().st_size // 1024} KB")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--html", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    chars = page_chars(args.html.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    build(args.src / "NotoSansSC[wght].ttf", args.out / "noto-sans-sc.woff2", chars, (400, 900))
    build(args.src / "Unbounded[wght].ttf", args.out / "unbounded.woff2", ASCII | LATIN_EXTRA, (500, 900))
    write_manifest(args.out)


def write_manifest(out: Path) -> None:
    """public/fonts/zh-hans-chars.txt: every character the two subsets really contain (read back from their
    cmap tables, not the list that was asked for). tools/build-pages.py --strict compares the zh-Hans page against
    it, using only the standard library, so a character the subsets lack cannot ship unnoticed."""
    have: set[str] = set()
    for name in ("noto-sans-sc.woff2", "unbounded.woff2"):
        have |= {chr(c) for c in TTFont(out / name).getBestCmap()}
    (out / "zh-hans-chars.txt").write_text("".join(sorted(have)) + "\n", encoding="utf-8", newline="\n")
    print(f"zh-hans-chars.txt: {len(have)} characters in the two subsets")


if __name__ == "__main__":
    main()
