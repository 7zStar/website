#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build the static pages under public/ from src/.

  src/page.template.html   the page, with every translatable string left empty
  src/root.template.html   the language-picking page served at /
  src/i18n.json            the copy, one dictionary per language

Output (all generated, none of it is committed):
  public/index.html            redirects to the right language page
  public/<slug>/index.html     one page per language in PAGES (en, zh-hant, zh-hans, ...)
  public/sitemap.xml

Each language page carries its own language in the raw HTML: title, meta tags, body
text, aria labels. The benchmark table, the bar chart and the file-format icons are
drawn by the page's script, so they are not in the raw HTML. Asset paths on the language
pages are relative (../icon.svg), so a page also opens straight from disk. Running the
script twice gives byte-identical files.

Usage: uv run tools/build-pages.py     (or: python3 tools/build-pages.py)
"""
import json
import re
import sys
from collections import Counter
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://www.7zstar.com"

# The widest window, in px, at which each step of the narrow header applies. English links are
# long, so English swaps them for icons early. Chinese links are short, so Chinese keeps them
# as text and drops the wordmark first. Each number comes from adding up the padding, the logo,
# the links, the language button and the theme button in that state, plus about 15px because
# media query widths include a classic scrollbar. After changing the header or a nav label,
# rerun that sum and look at the header from 720px down to 300px in every language.
# What each key switches on when the window is at most that wide:
#   w_short     the language button shows its short name
#   w_narrow    the third link (source) is dropped and the wordmark gets smaller
#   w_icons     the download and screenshot links become icons
#   w_wordmark  the wordmark is hidden
#   w_globe     the language button keeps only the globe
# The order in which these steps happen is not the same in every language, only the numbers
# decide it: English drops the third link first (719), Vietnamese, Esperanto and Japanese shorten
# the language button first, and Chinese switches to icons last (309), after the wordmark.
# The comments on vi, eo and ja give the smallest single-row width measured in each state; each
# key is the measurement of the state before it, plus 14.
HEADER_WIDTHS = {
    "default": {"w_short": 599, "w_narrow": 719, "w_icons": 539, "w_wordmark": 429, "w_globe": 344},
    "zh": {"w_short": 499, "w_narrow": 719, "w_icons": 309, "w_wordmark": 439, "w_globe": 359},
    "vi": {"w_short": 734, "w_narrow": 674, "w_icons": 539, "w_wordmark": 414, "w_globe": 329},  # measured 720 (full) -> w_short, 660 (short language button) -> w_narrow, 525 (third link dropped) -> w_icons, 400 (icons) -> w_wordmark, 315 (no wordmark) -> w_globe
    "eo": {"w_short": 689, "w_narrow": 634, "w_icons": 489, "w_wordmark": 414, "w_globe": 329},  # measured 675, 620, 475, 400, 315 in the same five states as for Vietnamese
    "ja": {"w_short": 814, "w_narrow": 774, "w_icons": 619, "w_wordmark": 434, "w_globe": 349},  # Japanese links are as wide as English ones; measured 800, 760, 605, 420, 335 in the same five states as for Vietnamese
}

# key = value of <html lang> and of localStorage "lang"; name = the language in its own
# words, shown in the language menu. The menu lists these in this order.
PAGES = {
    "en": {"slug": "en", "name": "English", "locale": "en_US", "og": "og.png", "header": "default"},
    "zh-Hant": {"slug": "zh-hant", "name": "繁體中文", "locale": "zh_TW", "og": "og-zh-hant.png", "header": "zh"},
    "zh-Hans": {"slug": "zh-hans", "name": "简体中文", "locale": "zh_CN", "og": "og-zh-hans.png", "header": "zh"},
    "de": {"slug": "de", "name": "Deutsch", "locale": "de_DE", "og": "og-de.png", "header": "default"},
    "fr": {"slug": "fr", "name": "Français", "locale": "fr_FR", "og": "og-fr.png", "header": "default"},
    # es: the copy and the number format follow Latin American Spanish (es-419) and the menu
    # wording follows the real Windows screenshots. og:locale stays the generic es_ES, because
    # es_LA is not an ISO code and only Facebook knows it.
    "es": {"slug": "es", "name": "Español", "locale": "es_ES", "og": "og-es.png", "header": "default"},
    "pt-BR": {"slug": "pt-br", "name": "Português (Brasil)", "locale": "pt_BR", "og": "og-pt-br.png", "header": "default"},
    "ja": {"slug": "ja", "name": "日本語", "locale": "ja_JP", "og": "og-ja.png", "header": "ja"},
    "vi": {"slug": "vi", "name": "Tiếng Việt", "locale": "vi_VN", "og": "og-vi.png", "header": "vi"},
    "eo": {"slug": "eo", "name": "Esperanto", "locale": "eo_EO", "og": "og-eo.png", "header": "eo"},
}
DEFAULT = "en"

SPACELESS = {"ja"}

# Hero lines may wrap only at "|". Joining the phrases (with a space, or with nothing for the
# SPACELESS languages) must give exactly the dictionary text, or the build stops: change this
# table together with the matching hero.l1 / onepass.h / speed.h2 values in src/i18n.json (and
# the BREAKS table in tools/make-og.py). A hero line with no entry here is laid out as plain text.
HERO_PHRASES = {
    "en": {
        "hero.l1": "Skip|“Show more options”.",
        "onepass.h": "One pass.|No .tar on disk.",
        "speed.h2": "10× faster|than 7z.",
    },
    "de": {
        "hero.l1": "Ohne|„Weitere Optionen anzeigen“.",
        "onepass.h": "Ein Durchgang.|Kein .tar auf der Platte.",
        "speed.h2": "10× schneller|als 7z.",
    },
    "fr": {
        "hero.l1": "Sans détour par|« Afficher d’autres options ».",
        "onepass.h": "Une passe.|Aucun .tar sur le disque.",
        "speed.h2": "10× plus rapide|que 7z.",
    },
    "es": {
        "hero.l1": "Olvídate de|«Mostrar Más opciones».",
        "onepass.h": "Un solo paso.|Sin .tar en el disco.",
        "speed.h2": "10× más rápido|que 7z.",
    },
    "ja": {
        "hero.l1": "「その他のオプションを確認」|を飛ばせます。",
        "onepass.h": "一度で完了。|ディスクに.tarは作りません。",
    },
    "vi": {
        "hero.l1": "Không cần bấm|“Xem thêm tùy chọn” nữa.",
        "onepass.h": "Một lượt.|Không có .tar trên đĩa.",
    },
    "eo": {
        "hero.l1": "Preterpasu|«Show more options».",
        "onepass.h": "Unu trairo.|Neniu .tar sur la disko.",
        "speed.h2": "10× pli rapide|ol 7z.",
    },
    "pt-BR": {
        "hero.l1": "Pule o|“Mostrar mais opções”.",
        "onepass.h": "Uma passada.|Nenhum .tar no disco.",
        "speed.h2": "10× mais rápido|que o 7z.",
    },
}

# Where the README's Donate section will be (the repo is private until the first public release,
# so this link is expected to 404 until then).
DONATE_README_URL = "https://github.com/7zStar/7-ZSTar#donate"

# Keys the page script needs at runtime (benchmark row labels, the copy button's two messages)
# and the head keys built here.
DYNAMIC_KEYS = {"speed.row1", "speed.row2", "speed.row3", "donate.copied", "donate.copy_fail"}
HEAD_KEYS = {"meta.title", "meta.desc"}


def text(s: str) -> str:
    return escape(s, quote=False)


def attr(s: str) -> str:
    return escape(s, quote=True)


def url(lang: str) -> str:
    return f"{SITE}/{PAGES[lang]['slug']}/"


def image_alt(d: dict, lang: str) -> str:
    """og:image:alt: the three lines printed on the share image, from the dictionary."""
    lines = " ".join(d[k] for k in ("hero.l1", "onepass.h", "speed.h2"))
    return f"7-ZSTar{'：' if lang.startswith('zh') or lang == 'ja' else ': '}{lines}"


def hreflang_links() -> str:
    rows = [f'<link rel="alternate" hreflang="{lang}" href="{url(lang)}">' for lang in PAGES]
    rows.append(f'<link rel="alternate" hreflang="x-default" href="{SITE}/">')
    return "\n".join(rows)


CHECK_ICON = ('<svg class="lang-check" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" '
              'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5l3 3 7-7"/></svg>')


ZOOM_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">'
             '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 20 20M10.5 7.5v6M7.5 10.5h6"/></svg>')


def lang_options(current: str) -> str:
    """The language menu's links, one per entry in PAGES."""
    rows = []
    for lang, page in PAGES.items():
        mark = ' aria-current="true"' if lang == current else ""
        rows.append(f'          <li><a href="/{page["slug"]}/" hreflang="{lang}" lang="{lang}" data-lang-set="{lang}"{mark}>'
                    f'<span>{text(page["name"])}</span>{CHECK_ICON}</a></li>')
    return "\n".join(rows)


def head_block(d: dict, lang: str, canonical: str, assets: str) -> str:
    """Everything in <head> that depends on the language (title, meta, links)."""
    page = PAGES[lang]
    others = [PAGES[k]["locale"] for k in PAGES if k != lang]
    image = f"{SITE}/{page['og']}"
    rows = [
        f"<title>{text(d['meta.title'])}</title>",
        f'<meta name="description" content="{attr(d["meta.desc"])}">',
        f'<link rel="canonical" href="{canonical}">',
        hreflang_links(),
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="7-ZSTar">',
        f'<meta property="og:locale" content="{page["locale"]}">',
        *[f'<meta property="og:locale:alternate" content="{o}">' for o in others],
        f'<meta property="og:url" content="{canonical}">',
        f'<meta property="og:title" content="{attr(d["meta.title"])}">',
        f'<meta property="og:description" content="{attr(d["meta.desc"])}">',
        f'<meta property="og:image" content="{image}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        f'<meta property="og:image:alt" content="{attr(image_alt(d, lang))}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<link rel="icon" type="image/svg+xml" href="{assets}icon.svg">',
    ]
    return "\n".join(rows)


# ---- filling the template ---------------------------------------------------------------

ATTR_TAG = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)\b([^<>]*?\sdata-i18n-attr="([^"]*)"[^<>]*)>')
TEXT_EL = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)\b([^<>]*?\sdata-i18n="([^"]+)"[^<>]*)></\1>')
BRAND = re.compile(r"(7-Z(?:ip|STar))")


def fill_attrs(html: str, d: dict, used: set[str]) -> str:
    def repl(m: re.Match) -> str:
        tag, attrs, spec = m.group(1), m.group(2), m.group(3)
        extra = ""
        for pair in spec.split(";"):
            i = pair.find("=")
            if i < 1:
                continue
            name, key = pair[:i].strip(), pair[i + 1:].strip()
            if re.search(rf'\s{re.escape(name)}="', attrs):
                raise SystemExit(f"template already has {name}= on <{tag}> ({key})")
            used.add(key)
            extra += f' {name}="{attr(d[key])}"'
        return f"<{tag}{attrs}{extra}>"

    return ATTR_TAG.sub(repl, html)


def fill_text(html: str, d: dict, lang: str, used: set[str]) -> str:
    before = Counter(re.findall(r'data-i18n="([^"]+)"', html))
    done: Counter = Counter()
    hero = re.search(r'<h1\b[^>]*\bid="hero-h"[^>]*>.*?</h1>', html, re.S)
    hero_span = hero.span() if hero else (0, 0)

    def repl(m: re.Match) -> str:
        tag, attrs, key = m.group(1), m.group(2), m.group(3)
        value = d[key]
        used.add(key)
        done[key] += 1
        # Steps in this order: highlight the number, keep brand names unbroken, split hero phrases
        if re.search(r"\sdata-hl(\s|$)", attrs):
            hit = re.search(r"\d+×|\d+ ?倍|\d+ lần", value)
            if hit:
                body = (text(value[:hit.start()]) + f'<span class="hl">{text(hit.group(0))}</span>'
                        + text(value[hit.end():]))
                return f"<{tag}{attrs}>{body}</{tag}>"
        if tag != "text" and BRAND.search(value):  # SVG <text> is left as plain text
            parts = BRAND.split(value)
            body = "".join(f'<span class="nw">{text(p)}</span>' if i % 2 else text(p)
                           for i, p in enumerate(parts) if p)
            return f"<{tag}{attrs}>{body}</{tag}>"
        if hero_span[0] <= m.start() < hero_span[1]:
            hint = HERO_PHRASES.get(lang, {}).get(key)
            joiner = "" if lang in SPACELESS else " "  # Japanese writes no spaces between phrases
            if hint:
                if joiner.join(hint.split("|")) != value:
                    raise SystemExit(f"[{lang}] HERO_PHRASES[{key!r}] = {hint!r} no longer matches the "
                                     f"dictionary text {value!r}; update HERO_PHRASES together with src/i18n.json")
                body = joiner.join(f'<span class="ph">{text(p)}</span>' for p in hint.split("|"))
                return f"<{tag}{attrs}>{body}</{tag}>"
        return f"<{tag}{attrs}>{text(value)}</{tag}>"

    out = TEXT_EL.sub(repl, html)
    # An element that holds anything between its tags (even a space) is not matched and would
    # silently stay empty, so every data-i18n in the template must have been filled.
    skipped = before - done
    if skipped:
        raise SystemExit(f"[{lang}] data-i18n elements left unfilled (keep them empty in the template): {sorted(skipped.elements())}")
    return out


def fill(template: str, values: dict[str, str]) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{\w+\}\}", out)
    if left:
        raise SystemExit(f"unfilled placeholders: {left}")
    return out


def google_fonts_url(lang: str) -> str:
    """Fonts for every Google-fonts page: Unbounded and IBM Plex Mono everywhere, then the body family
    and the CJK family of the language: Figtree and Noto Sans TC on most pages (the Traditional Chinese
    page needs TC), Noto Sans JP on /ja/, and on /vi/ Plus Jakarta Sans, because Figtree has no
    Vietnamese letters (no ơ ư and none of the tone-marked vowels)."""
    if lang == "vi":
        families = "Unbounded:wght@500..900&family=Plus+Jakarta+Sans:wght@400..800&family=IBM+Plex+Mono:wght@400;600"
    else:
        cjk = "Noto+Sans+JP" if lang == "ja" else "Noto+Sans+TC"
        families = ("Unbounded:wght@500..900&family=Figtree:wght@400..800"
                    f"&family=IBM+Plex+Mono:wght@400;600&family={cjk}:wght@400;500;700;900")
    return f"https://fonts.googleapis.com/css2?family={families}&display=swap"


def google_noscript(lang: str) -> str:
    return f'<noscript><link rel="stylesheet" href="{attr(google_fonts_url(lang))}"></noscript>'


LOCAL_NOSCRIPT = '<noscript><link rel="stylesheet" href="../fonts/zh-hans.css"></noscript>'

# Font loading stays in script so a slow or blocked Google never holds the page up.
# zh-Hans only ever names its own files; the other pages only name Google.
def google_fonts_js(lang: str) -> str:
    return f"""addLink('preconnect', 'https://fonts.googleapis.com');
addLink('preconnect', 'https://fonts.gstatic.com', true);
addLink('stylesheet', '{google_fonts_url(lang)}');"""


LOCAL_FONTS_JS = """/* 簡中只用自帶字型，不連 Google Fonts */
addLink('stylesheet', '../fonts/zh-hans.css');"""


def png_size(path: Path) -> tuple[int, int]:
    """Width and height from a PNG's header, so the page always matches the committed image."""
    if not path.is_file():
        raise SystemExit(f"missing {path.relative_to(ROOT)}")
    with path.open("rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise SystemExit(f"not a PNG: {path.relative_to(ROOT)}")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def donate_assets() -> tuple[str, str]:
    """The donation address (shown as selectable text) and the QR made from it by
    tools/make-donate-qr.py. Both are read from src/, so the address is written down once."""
    address = (ROOT / "src" / "donate-address.txt").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
        raise SystemExit("src/donate-address.txt must hold exactly one 0x address")
    qr = (ROOT / "src" / "donate-qr.svg").read_text(encoding="utf-8").strip()
    if not qr.startswith("<svg ") or not qr.endswith("</svg>"):
        raise SystemExit("src/donate-qr.svg is not a single <svg>; run tools/make-donate-qr.py")
    made_from = re.match(r'<svg [^>]*\bdata-address="([^"]*)"', qr)
    if not made_from or made_from.group(1) != address:
        raise SystemExit("src/donate-qr.svg was not made from the address in src/donate-address.txt "
                         "(its data-address differs or is missing); rerun tools/make-donate-qr.py")
    return address, qr


def build_page(template: str, i18n: dict, lang: str) -> str:
    d = i18n[lang]
    used: set[str] = set()
    body = fill_attrs(template, d, used)
    body = fill_text(body, d, lang, used)
    unused = set(d) - used - DYNAMIC_KEYS - HEAD_KEYS
    if unused:
        raise SystemExit(f"[{lang}] dictionary keys the template never uses: {sorted(unused)}")
    row_labels = {k: d[k] for k in sorted(DYNAMIC_KEYS)}
    dict_json = json.dumps(row_labels, ensure_ascii=False, indent=2).replace("</", "<\\/")
    shots = ROOT / "public" / "screenshots" / PAGES[lang]["slug"]
    og_size = png_size(ROOT / "public" / PAGES[lang]["og"])  # head_block states 1200x630
    if og_size != (1200, 630):
        raise SystemExit(f"[{lang}] public/{PAGES[lang]['og']} is {og_size[0]}x{og_size[1]}, expected 1200x630; run tools/make-og.py")
    main_w, main_h = png_size(shots / "main.png")
    menu_w, menu_h = png_size(shots / "menu.png")
    donate_addr, donate_qr = donate_assets()
    return fill(body, {
        "donate_addr": text(donate_addr), "donate_qr": donate_qr, "donate_readme_url": attr(DONATE_README_URL),
        **{k: str(v) for k, v in HEADER_WIDTHS[PAGES[lang]["header"]].items()},
        "main_w": str(main_w), "main_h": str(main_h), "menu_w": str(menu_w), "menu_h": str(menu_h),
        "zoom_icon": ZOOM_ICON,
        "lang": lang,
        "head": head_block(d, lang, url(lang), "../"),
        "assets": "../",
        "slug": PAGES[lang]["slug"],
        "fonts_js": LOCAL_FONTS_JS if lang == "zh-Hans" else google_fonts_js(lang),
        "noscript_fonts": LOCAL_NOSCRIPT if lang == "zh-Hans" else google_noscript(lang),
        "dict_json": dict_json,
        "lang_name": text(PAGES[lang]["name"]),
        "lang_options": lang_options(lang),
    })


def build_root(template: str, i18n: dict) -> str:
    d = i18n[DEFAULT]
    return fill(template, {"head": head_block(d, DEFAULT, f"{SITE}/", "")})


def build_sitemap() -> str:
    rows = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for lang in PAGES:
        rows.append("  <url>")
        rows.append(f"    <loc>{url(lang)}</loc>")
        for other in PAGES:
            rows.append(f'    <xhtml:link rel="alternate" hreflang="{other}" href="{url(other)}"/>')
        rows.append("  </url>")
    rows.append("</urlset>")
    return "\n".join(rows) + "\n"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    print("wrote", path.relative_to(ROOT))


def check_hero_phrases(i18n: dict) -> None:
    """Every HERO_PHRASES entry must name a language in PAGES and a key of its dictionary, and its
    phrases joined must equal the dictionary text. fill_text only meets the entries whose element
    it reaches, so a misspelled key or a renamed dictionary key would otherwise go unnoticed."""
    for lang, table in HERO_PHRASES.items():
        if lang not in PAGES:
            raise SystemExit(f"[{lang}] HERO_PHRASES names a language that is not in PAGES")
        joiner = "" if lang in SPACELESS else " "
        for key, hint in table.items():
            if key not in i18n[lang]:
                raise SystemExit(f"[{lang}] HERO_PHRASES[{key!r}]: no such key in the dictionary")
            if joiner.join(hint.split("|")) != i18n[lang][key]:
                raise SystemExit(f"[{lang}] HERO_PHRASES[{key!r}] = {hint!r} no longer matches the "
                                 f"dictionary text {i18n[lang][key]!r}; update HERO_PHRASES together with src/i18n.json")


def main() -> None:
    i18n = json.loads((ROOT / "src" / "i18n.json").read_text(encoding="utf-8"))
    if set(i18n) != set(PAGES):
        raise SystemExit(f"i18n.json languages {sorted(i18n)} != {sorted(PAGES)}")
    reference = set(i18n[DEFAULT])
    for lang, d in i18n.items():
        if set(d) != reference:
            raise SystemExit(f"[{lang}] keys differ from {DEFAULT}: {sorted(set(d) ^ reference)}")
    check_hero_phrases(i18n)
    template = (ROOT / "src" / "page.template.html").read_text(encoding="utf-8")
    root_template = (ROOT / "src" / "root.template.html").read_text(encoding="utf-8")
    public = ROOT / "public"
    for lang, page in PAGES.items():
        write(public / page["slug"] / "index.html", build_page(template, i18n, lang))
    write(public / "index.html", build_root(root_template, i18n))
    write(public / "sitemap.xml", build_sitemap())


if __name__ == "__main__":
    sys.exit(main())
