#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""List the interface languages the 7-ZSTar program ships, for the "interface languages" section.

Reads the language files of the 7-ZSTar source tree (src/Lang/*.txt and the English base en.ttt, a
sibling of this website folder; read only, never changed) and writes src/app-languages.json: one row
per language file with the name of the language in its own words.

A 7-Zip language file starts with comment lines, then the section "0":

    0
    7-Zip
    Russian        <- the name in English
    Русский        <- the name in the language itself (this is what the website shows)

so the third line after "0" is the native name. Some files add the name in another script to the
English line ("Hindi, Indian, हिन्दुस्तान"); only the native name line is used.

Usage: uv run tools/make-app-languages.py [path/to/src/Lang]
Rerun it when the source tree gains or loses a language file (a new upstream release), then commit
src/app-languages.json: the site build reads that file and never touches the source tree.
"""
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT.parent / "src" / "Lang"
OUT = ROOT / "src" / "app-languages.json"

# File name -> BCP 47 tag, for the files whose name is not already a language tag. Without it the page
# would label "sr-spc" as a language it is not, and screen readers and fonts would guess wrong.
LANG_TAG = {
    "pt-br": "pt-BR", "zh-cn": "zh-CN", "zh-tw": "zh-TW", "pa-in": "pa-IN",
    "sr-spc": "sr-Cyrl", "sr-spl": "sr-Latn", "uz-cyrl": "uz-Cyrl",
    "ku-ckb": "ckb", "mng": "mn-Mong", "va": "ca-valencia", "en": "en",
}

# Files that are another file's language written another way (Portuguese for Portugal and for Brazil, Serbian in
# two scripts, ...). Used only for the "distinct_languages" estimate in the summary line this script prints and in
# app-languages.json; the website shows no such number (it says "interface translations") and lists every name.
GROUPS = {"pt-br": "pt", "sr-spc": "sr", "sr-spl": "sr", "uz-cyrl": "uz", "mng": "mn", "ku-ckb": "ku",
          "zh-cn": "zh", "zh-tw": "zh", "pa-in": "pa", "va": "ca"}


def native_name(path: Path) -> tuple[str, str]:
    """(English name, native name) from the section "0" of a language file."""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "0" and not line.startswith(";"):
            if lines[i + 1].strip() != "7-Zip":
                raise SystemExit(f"{path.name}: expected '7-Zip' after section 0, found {lines[i + 1]!r}")
            return lines[i + 2].strip(), lines[i + 3].strip()
    raise SystemExit(f"{path.name}: no section 0")


def main() -> None:
    lang_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    files = sorted(lang_dir.glob("*.txt")) + [lang_dir / "en.ttt"]
    if not files[-1].is_file() or len(files) < 50:
        raise SystemExit(f"{lang_dir} does not look like the 7-ZSTar src/Lang folder")
    rows, skipped = [], []
    for path in files:
        code = path.stem
        english, native = native_name(path)
        if not native or any(unicodedata.category(c) == "Co" for c in native):
            # mng2 is Mongolian written in a legacy font encoding: its name is made of private-use
            # characters (U+E5xx) that only that font can draw, so a browser would show boxes.
            # Mongolian is listed once, through "mng" (the Unicode script).
            skipped.append({"code": code, "english": english,
                            "reason": "the native name is empty or private-use characters (legacy font encoding)"})
            continue
        rows.append({"code": code, "lang": LANG_TAG.get(code, code), "name": native, "english": english})
    rows.sort(key=lambda r: (r["english"].lower(), r["code"]))
    names = [r["name"] for r in rows]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise SystemExit(f"two language files show the same name: {dupes}")
    data = {
        "_note": "Written by tools/make-app-languages.py from the 7-ZSTar src/Lang folder; do not edit by hand. "
                 "name = the language in its own words (third line of section 0), sorted by the English name.",
        "files": len(files),
        "listed": len(rows),
        "distinct_languages": len({GROUPS.get(r["code"], r["code"]) for r in rows}),
        "languages": rows,
        "skipped": skipped,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(files)} language files, {len(rows)} names listed, {len(skipped)} skipped "
          f"({', '.join(s['code'] for s in skipped) or '-'}), about {data['distinct_languages']} distinct languages -> "
          f"{OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
