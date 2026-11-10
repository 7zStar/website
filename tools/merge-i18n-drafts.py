#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Put drafted copy for some languages into src/i18n.json.

Usage: uv run tools/merge-i18n-drafts.py DRAFTS_DIR [lang ...]

DRAFTS_DIR holds one <lang>.json per language (the language key of PAGES in tools/build-pages.py, e.g. ru or
pt-BR). With no language given, every <lang>.json in the folder whose name is a key of PAGES is merged. For each
language:
  - the file is a flat {key: text} object (or {"<lang>": {key: text}}); its strings replace the language's
    current ones;
  - keys the draft does not have keep the language's current text, or English if it has none yet;
  - keys the draft has but English does not, and values that are not strings, are errors (a typo would
    otherwise vanish silently).
The language is also listed in src/draft-languages.json, because merged copy is a draft until a person takes
it off that list. Nothing here ever removes a language from the list.
"""
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "src" / "i18n.json"
DRAFTS = ROOT / "src" / "draft-languages.json"

spec = importlib.util.spec_from_file_location("build_pages", ROOT / "tools" / "build-pages.py")
build_pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_pages)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, help="folder with one <lang>.json per language")
    parser.add_argument("langs", nargs="*", help="language keys of PAGES (default: every <lang>.json in the folder that is one)")
    args = parser.parse_args()
    if not args.folder.is_dir():
        raise SystemExit(f"{args.folder} is not a folder")
    langs = args.langs or [p.stem for p in sorted(args.folder.glob("*.json")) if p.stem in build_pages.PAGES]
    unknown = [lang for lang in langs if lang not in build_pages.PAGES]
    if unknown or not langs:
        raise SystemExit(f"language(s) {unknown or 'none found'}: not keys of PAGES ({', '.join(build_pages.PAGES)})")
    i18n = json.loads(I18N.read_text(encoding="utf-8"))
    en = i18n["en"]
    drafts = json.loads(DRAFTS.read_text(encoding="utf-8")) if DRAFTS.is_file() else {}
    for lang in langs:
        current = i18n.get(lang, {})
        source = args.folder / f"{lang}.json"
        note = "English placeholder"
        incoming: dict = {}
        if source.is_file():
            incoming = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(incoming, dict):
                raise SystemExit(f"[{lang}] {source.name}: expected a JSON object of {{key: text}}, "
                                 f"found {type(incoming).__name__}")
            incoming = incoming[lang] if isinstance(incoming.get(lang), dict) else incoming
            unknown_keys = sorted(set(incoming) - set(en))
            if unknown_keys:
                raise SystemExit(f"[{lang}] {source.name} has keys English does not: {unknown_keys}")
            not_text = sorted(k for k, v in incoming.items() if not isinstance(v, str))
            if not_text:
                raise SystemExit(f"[{lang}] {source.name}: these values are not strings: {not_text}")
            note = f"merged from {source.name}"
        merged = {k: incoming.get(k, current.get(k, en[k])) for k in en}
        if source.is_file():
            missing = sorted(set(en) - set(incoming))
            print(f"[{lang}] {len(incoming)} strings from {source.name}; {len(missing)} keys not in it"
                  + (f" ({', '.join(missing[:6])}{', ...' if len(missing) > 6 else ''})" if missing else ""))
        else:
            print(f"[{lang}] no {source}; {'kept the current' if current else 'copied the English'} text")
        i18n[lang] = merged
        drafts[lang] = note if lang not in drafts or source.is_file() else drafts[lang]
    I18N.write_text(json.dumps(i18n, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    DRAFTS.write_text(json.dumps(drafts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
