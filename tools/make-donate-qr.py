#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["segno==1.6.6", "opencv-python-headless==4.10.0.84"]
# ///
"""Make src/donate-qr.svg from the donation address, then prove the committed file scans back.

  src/donate-address.txt   the one place the address is written down (build-pages.py reads it too)
  src/donate-qr.svg        generated here and committed; build-pages.py inlines it into the donate section

Usage:
  uv run tools/make-donate-qr.py            write src/donate-qr.svg, then verify it
  uv run tools/make-donate-qr.py --check    only verify the committed file (exit 1 on any mismatch)

The QR carries the bare address, with no "ethereum:" prefix and no chain id, so every wallet app
reads it the same way on both networks. Error correction M, same as the approved prototype.

Verification does not trust segno: it parses the committed SVG's own path back into a bitmap,
adds a quiet zone, decodes it with OpenCV and compares the text with the address character by
character (the capitals are the EIP-55 checksum, so case matters). It also checks that the file
is byte-identical to what segno makes from the address now, and that its data-address attribute
(the address the picture was made from) equals the address. build-pages.py checks that attribute
on every build, so changing the address without rerunning this script stops the build.
"""
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import segno

ROOT = Path(__file__).resolve().parent.parent
ADDRESS_FILE = ROOT / "src" / "donate-address.txt"
SVG_FILE = ROOT / "src" / "donate-qr.svg"
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")


def read_address() -> str:
    address = ADDRESS_FILE.read_text(encoding="utf-8").strip()
    if not ADDRESS_RE.fullmatch(address):
        raise SystemExit(f"{ADDRESS_FILE.name} does not hold exactly one 0x address")
    return address


def make_svg(address: str) -> str:
    qr = segno.make(address, error="m", micro=False)
    svg = qr.svg_inline(scale=1, border=2, dark="#000000", light="#ffffff", omitsize=True)
    # Decorative for assistive tech: the section's wrapper carries the aria-label. data-address
    # records which address this picture was made from, so build-pages.py can refuse a QR that was
    # not regenerated after the address changed (it cannot decode a QR itself).
    head = f'<svg shape-rendering="crispEdges" aria-hidden="true" focusable="false" data-address="{address}" '
    return svg.replace("<svg ", head, 1) + "\n"


def svg_to_bitmap(svg: str) -> np.ndarray:
    """Read the dark modules back out of segno's one stroked path (M x y.5 then h/m runs)."""
    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
    d = re.search(r'<path class="qrline"[^>]* d="([^"]+)"', svg)
    if not m or not d:
        raise SystemExit("unexpected SVG layout: no viewBox or no qrline path")
    size = int(m.group(1))
    grid = np.zeros((size, size), dtype=np.uint8)
    tokens = re.findall(r"([Mhm])\s*(-?[\d.]+)(?:[ ,]+(-?[\d.]+))?", d.group(1))
    x = y = 0.0
    for cmd, a, b in tokens:
        if cmd == "M":
            x, y = float(a), float(b)
        elif cmd == "m":
            x, y = x + float(a), y + float(b)
        else:  # h: dark run of `a` modules on the row whose centre line is y
            n = int(float(a))
            grid[int(y - 0.5), int(x):int(x) + n] = 1
            x += n
    return grid


def verify(address: str) -> bool:
    ok = True
    svg = SVG_FILE.read_text(encoding="utf-8")
    fresh = make_svg(address)
    same = svg == fresh
    ok &= same
    print(f"file matches a fresh render of the address: {same}")
    tag = re.match(r'<svg [^>]*\bdata-address="([^"]*)"', svg)
    tagged = bool(tag) and tag.group(1) == address
    ok &= tagged
    print(f"data-address attribute equals the address: {tagged}")
    grid = svg_to_bitmap(svg)
    scale, quiet = 12, 4  # the SVG already has a 2-module border; add more white for the decoder
    img = np.kron(1 - grid, np.ones((scale, scale), dtype=np.uint8)) * 255
    img = cv2.copyMakeBorder(img, quiet * scale, quiet * scale, quiet * scale, quiet * scale,
                             cv2.BORDER_CONSTANT, value=255)
    decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    exact = decoded == address
    ok &= exact
    print(f"decoded from the committed SVG: {decoded!r}\nequals the address, character by character: {exact}")
    return ok


def main() -> int:
    address = read_address()
    if "--check" not in sys.argv[1:]:
        SVG_FILE.write_text(make_svg(address), encoding="utf-8", newline="\n")
        print("wrote", SVG_FILE.relative_to(ROOT))
    ok = verify(address)
    print("QR OK" if ok else "QR FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
