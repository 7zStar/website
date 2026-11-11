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

Usage: uv run tools/build-pages.py             (or: python3 tools/build-pages.py)
       uv run tools/build-pages.py --strict    what the deploy workflow runs

Without --strict a language that is not ready to ship (draft copy, no screenshots of its
own, no share image of its own, no measured header widths) builds anyway, so it can be previewed,
and the build only prints a warning for it. With --strict the same problems stop the build with
exit status 1, so a draft can never reach the published site.
"""
import argparse
import functools
import hashlib
import json
import re
import sys
from collections import Counter
from html import escape, unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://www.7zstar.com"

# The widest window, in px, at which each step of the narrow header applies, per language, in
# src/header-widths.json. tools/measure-header.py writes that file by measuring every language page
# in headless Chromium; do not edit it by hand. After changing the header's CSS or a nav or
# language-button label, rerun the tool and commit the file (--check compares without writing).
# What each key switches on when the window is at most that wide:
#   w_short     the language button shows its short name
#   w_narrow    the third link (source) is dropped and the wordmark gets smaller
#   w_icons     the download and screenshot links become icons
#   w_wordmark  the wordmark is hidden
#   w_globe     the language button keeps only the globe
# The order in which these steps happen is not the same in every language, only the numbers decide it.
WIDTH_KEYS = ("w_short", "w_narrow", "w_icons", "w_wordmark", "w_globe")
HEADER_WIDTHS_FILE = ROOT / "src" / "header-widths.json"

# Languages whose copy is not final (an English placeholder, or a first draft). They build, but --strict
# refuses to build while any language is listed here or looks like an untranslated copy of English.
DRAFT_FILE = ROOT / "src" / "draft-languages.json"

# The language names the app itself ships, written by tools/make-app-languages.py from src/Lang/ of the
# 7-ZSTar source tree. Dictionary strings may use {n} for the number of names listed.
APP_LANGS_FILE = ROOT / "src" / "app-languages.json"
APP_LANGS: dict = {}
HEADER_WIDTHS: dict[str, dict[str, int]] = {}

# Problems that keep a language from shipping: (language, text). --strict turns them into a failure.
PROBLEMS: list[tuple[str, str]] = []


def warn(lang: str, message: str) -> None:
    PROBLEMS.append((lang, message))


def fill_counts(d: dict) -> dict:
    """A language's dictionary with {n} (the number of interface translations listed) replaced in every value.
    The only place that is done: every page (language pages and the root page) works from this copy, so the
    head, the image alt, the labels the script carries and the checks of HERO_PHRASES all see the same text."""
    count = str(len(APP_LANGS["languages"]))
    return {k: v.replace("{n}", count) for k, v in d.items()}


def check_no_placeholder(html: str, who: str) -> None:
    """A {n} left in a built page would be shown to readers; it means a place that fill_counts does not cover."""
    if "{n}" in html:
        warn(who, "the built page still contains a literal {n}")


def app_language_items() -> str:
    """The <li> rows of the "interface languages" list: each name in its own words, tagged with its
    own language so screen readers and font selection treat it right."""
    return "\n".join(f'      <li lang="{attr(e["lang"])}" dir="auto">{text(e["name"])}</li>'
                     for e in APP_LANGS["languages"])

# key = value of <html lang> and of localStorage "lang"; name = the language in its own
# words, shown in the language menu. The menu lists these in this order.
PAGES = {
    "en": {"slug": "en", "name": "English", "locale": "en_US", "og": "og.png"},
    "zh-Hant": {"slug": "zh-hant", "name": "繁體中文", "locale": "zh_TW", "og": "og-zh-hant.png"},
    "zh-Hans": {"slug": "zh-hans", "name": "简体中文", "locale": "zh_CN", "og": "og-zh-hans.png"},
    "de": {"slug": "de", "name": "Deutsch", "locale": "de_DE", "og": "og-de.png"},
    "fr": {"slug": "fr", "name": "Français", "locale": "fr_FR", "og": "og-fr.png"},
    # es: the copy and the number format follow Latin American Spanish (es-419) and the menu
    # wording follows the real Windows screenshots. og:locale stays the generic es_ES, because
    # es_LA is not an ISO code and only Facebook knows it.
    "es": {"slug": "es", "name": "Español", "locale": "es_ES", "og": "og-es.png"},
    "pt-BR": {"slug": "pt-br", "name": "Português (Brasil)", "locale": "pt_BR", "og": "og-pt-br.png"},
    "ja": {"slug": "ja", "name": "日本語", "locale": "ja_JP", "og": "og-ja.png"},
    "vi": {"slug": "vi", "name": "Tiếng Việt", "locale": "vi_VN", "og": "og-vi.png"},
    # Batch 1 of the languages beyond ten. Until a language's own public/og-<slug>.png and
    # public/screenshots/<slug>/ exist, its page borrows the English ones (see resolve_assets) and
    # --strict refuses to build; --strict also refuses while the language is listed in
    # src/draft-languages.json.
    "ru": {"slug": "ru", "name": "Русский", "locale": "ru_RU", "og": "og-ru.png"},
    "ko": {"slug": "ko", "name": "한국어", "locale": "ko_KR", "og": "og-ko.png"},
    "it": {"slug": "it", "name": "Italiano", "locale": "it_IT", "og": "og-it.png"},
    "pl": {"slug": "pl", "name": "Polski", "locale": "pl_PL", "og": "og-pl.png"},
    "tr": {"slug": "tr", "name": "Türkçe", "locale": "tr_TR", "og": "og-tr.png"},
    "nl": {"slug": "nl", "name": "Nederlands", "locale": "nl_NL", "og": "og-nl.png"},
    "uk": {"slug": "uk", "name": "Українська", "locale": "uk_UA", "og": "og-uk.png"},
    "id": {"slug": "id", "name": "Bahasa Indonesia", "locale": "id_ID", "og": "og-id.png"},
    # Batch 2, same rules as batch 1. ar, fa and he are written right to left ("dir": "rtl"): their pages get
    # <html dir="rtl"> and the layout mirrors (see RTL below and the logical properties in src/page.template.html).
    "th": {"slug": "th", "name": "ไทย", "locale": "th_TH", "og": "og-th.png"},
    "cs": {"slug": "cs", "name": "Čeština", "locale": "cs_CZ", "og": "og-cs.png"},
    "hu": {"slug": "hu", "name": "Magyar", "locale": "hu_HU", "og": "og-hu.png"},
    "ro": {"slug": "ro", "name": "Română", "locale": "ro_RO", "og": "og-ro.png"},
    "sv": {"slug": "sv", "name": "Svenska", "locale": "sv_SE", "og": "og-sv.png"},
    "el": {"slug": "el", "name": "Ελληνικά", "locale": "el_GR", "og": "og-el.png"},
    "hi": {"slug": "hi", "name": "हिन्दी", "locale": "hi_IN", "og": "og-hi.png"},
    "ar": {"slug": "ar", "name": "العربية", "locale": "ar_SA", "og": "og-ar.png", "dir": "rtl"},
    "fa": {"slug": "fa", "name": "فارسی", "locale": "fa_IR", "og": "og-fa.png", "dir": "rtl"},
    "he": {"slug": "he", "name": "עברית", "locale": "he_IL", "og": "og-he.png", "dir": "rtl"},
    # Esperanto stays last: the menu is read top to bottom and it is the one constructed language.
    "eo": {"slug": "eo", "name": "Esperanto", "locale": "eo_EO", "og": "og-eo.png"},
}
DEFAULT = "en"

# Languages written right to left. Their pages carry <html dir="rtl">; every other page has no dir attribute.
RTL = {lang for lang, page in PAGES.items() if page.get("dir") == "rtl"}
LRM, RLM = chr(0x200E), chr(0x200F)  # left-to-right / right-to-left marks; see isolate_ltr


def strip_marks(value: str) -> str:
    """A value of a right-to-left page without U+200E / U+200F. The page isolates Latin words itself (isolate_ltr), so a
    mark in a text element would double it. fill_text, check_hero_phrases and tools/make-og.py all use this one rule,
    so the page, the HERO_PHRASES check and the share image never disagree about what the text is."""
    return value.replace(LRM, "").replace(RLM, "")

# A script font per language whose letters Unbounded, Figtree and IBM Plex Mono do not have. Checked against Google
# Fonts' unicode-range subsets on 2026-11-10: Unbounded and Figtree have no Greek, Thai, Devanagari, Arabic or Hebrew;
# IBM Plex Mono has none either; Latin Extended (cs hu ro sv: ě š č ř ž ő ű ă â î ș ț å ä ö) is in all three.
# Noto Sans is the one family that has Greek here; Vazirmatn is the Persian face (Noto Sans Arabic would also cover
# every Persian letter, but Vazirmatn is the one Persian readers expect).
# The same table is written in two more places, and a language added here must be added there too:
#   - src/page.template.html: html[lang="xx"]{--script:'Family'}, and xx in the html:is(...) list that sets
#     --font-display / --font-body (build_page calls check_script_fonts, which stops the build, and tools/measure-header.py, when they differ);
#   - tools/og.html: a <link> for the family and an html[lang="xx"] .lines rule (tools/make-og.py checks them).
SCRIPT_FONTS = {"th": "Noto Sans Thai", "el": "Noto Sans", "hi": "Noto Sans Devanagari", "ar": "Noto Sans Arabic",
                "fa": "Vazirmatn", "he": "Noto Sans Hebrew"}

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
    "ru": {
        "hero.l1": "Обойдитесь|без «Показать дополнительные параметры».",
        "onepass.h": "Один проход.|Без .tar на диске.",
        "speed.h2": "10× быстрее,|чем 7z.",
    },
    "ko": {
        "hero.l1": "“추가 옵션 표시”는|이제 건너뛰세요.",
        "onepass.h": "한 번에.|디스크에 .tar 없이.",
        "speed.h2": "7z보다|10배 빠릅니다.",
    },
    "it": {
        "hero.l1": "Niente più|«Mostra altre opzioni».",
        "onepass.h": "Un solo passaggio.|Nessun .tar su disco.",
        "speed.h2": "10× più veloce|di 7z.",
    },
    "pl": {
        "hero.l1": "Koniec|z „Pokaż więcej opcji”.",
        "onepass.h": "Jeden przebieg.|Bez .tar na dysku.",
        "speed.h2": "10× szybciej|niż 7z.",
    },
    "tr": {
        "hero.l1": "“Daha fazla seçenek göster”|adımına son.",
        "onepass.h": "Tek geçiş.|Diskte .tar yok.",
        "speed.h2": "7z’den|10× hızlı.",
    },
    "nl": {
        "hero.l1": "Sla|“Meer opties weergeven” over.",
        "onepass.h": "In één keer.|Geen .tar op schijf.",
        "speed.h2": "10× sneller|dan 7z.",
    },
    "uk": {
        "hero.l1": "Обійдіться|без «Показати додаткові параметри».",
        "onepass.h": "Один прохід.|Без .tar на диску.",
        "speed.h2": "10× швидше,|ніж 7z.",
    },
    "id": {
        "hero.l1": "Tak perlu lagi|“Tampilkan opsi lainnya”.",
        "onepass.h": "Sekali jalan.|Tanpa .tar di disk.",
        "speed.h2": "10× lebih cepat|dari 7z.",
    },
    # Batch 2. The right-to-left ones (ar, fa, he) hold no U+200E / U+200F: the Latin words are isolated by the
    # page (isolate_ltr below), not by control characters in the text.
    "th": {
        "hero.l1": "ไม่ต้องกด|“แสดงตัวเลือกเพิ่มเติม” อีกต่อไป",
        "onepass.h": "จบในขั้นเดียว|ไม่มี .tar บนดิสก์",
        "speed.h2": "เร็วกว่า 7z|10 เท่า",
    },
    "cs": {
        "hero.l1": "Už žádné|„Zobrazit další možnosti“.",
        "onepass.h": "Jeden průchod.|Žádný .tar na disku.",
        "speed.h2": "10× rychleji|než 7z.",
    },
    "hu": {
        "hero.l1": "Ugord át|a „További lehetőségek megjelenítése” lépést.",
        "onepass.h": "Egyetlen menet.|Nincs .tar a lemezen.",
        "speed.h2": "10× gyorsabb,|mint a 7z.",
    },
    "ro": {
        "hero.l1": "Fără|„Afișați mai multe opțiuni”.",
        "onepass.h": "O singură trecere.|Fără .tar pe disc.",
        "speed.h2": "De 10 ori mai rapid|decât 7z.",
    },
    "sv": {
        "hero.l1": "Hoppa över|”Visa fler alternativ”.",
        "onepass.h": "Ett svep.|Ingen .tar på disk.",
        "speed.h2": "10× snabbare|än 7z.",
    },
    "el": {
        "hero.l1": "Τέλος στο|«Εμφάνιση περισσότερων επιλογών».",
        "onepass.h": "Ένα πέρασμα.|Κανένα .tar στον δίσκο.",
        "speed.h2": "10× ταχύτερα|από το 7z.",
    },
    "hi": {
        "hero.l1": "अब “Show more options” की|ज़रूरत नहीं।",
        "onepass.h": "एक ही बार में।|डिस्क पर कोई .tar नहीं।",
        "speed.h2": "7z से|10× तेज़।",
    },
    "ar": {
        "hero.l1": "لا حاجة بعد الآن|إلى «إظهار المزيد من الخيارات».",
        "onepass.h": "خطوة واحدة.|لا ملف .tar على القرص.",
        "speed.h2": "أسرع 10 مرات|من 7z.",
    },
    "fa": {
        "hero.l1": "دیگر نیازی به|«Show more options» نیست.",
        "onepass.h": "یک مرحله.|بدون .tar روی دیسک.",
        "speed.h2": "10 برابر|سریع‌تر از 7z.",
    },
    "he": {
        "hero.l1": "בלי ללחוץ על|“הצג אפשרויות נוספות”.",
        "onepass.h": "מעבר אחד.|בלי .tar בדיסק.",
        "speed.h2": "דחיסה מהירה|פי 10 מ־7z.",
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
    """The language menu's links, one per entry in PAGES. Each language's own name carries its lang and its
    writing direction, so a right-to-left name keeps its own order inside a left-to-right menu (and the other way round)."""
    rows = []
    for lang, page in PAGES.items():
        mark = ' aria-current="true"' if lang == current else ""
        way = "rtl" if lang in RTL else "ltr"
        rows.append(f'          <li><a href="/{page["slug"]}/" hreflang="{lang}" lang="{lang}" data-lang-set="{lang}"{mark}>'
                    f'<span lang="{lang}" dir="{way}">{text(page["name"])}</span>{CHECK_ICON}</a></li>')
    return "\n".join(rows)


def head_block(d: dict, lang: str, canonical: str, assets: str, og: str) -> str:
    """Everything in <head> that depends on the language (title, meta, links). og = file name of the
    share image under public/ (the language's own, or the English one while it has none)."""
    page = PAGES[lang]
    others = [PAGES[k]["locale"] for k in PAGES if k != lang]
    image = f"{SITE}/{og}"
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


# The ways a language writes "10 times" in speed.h2, which fill_text highlights in amber: (regular expression, an
# example for the warning). A language that writes it another way needs its form added here, or the build warns.
HIGHLIGHT_FORMS = (
    # Written together with the number (×, 倍, 배) needs no word boundary. A phrase written as separate words has one at
    # both ends, so "10 orice" or a word that merely ends in פי is not taken for "10 ori" / "פי 10". Thai has no spaces
    # between words, so its form only has the boundary before the number.
    (r"\d+×", "10×"), (r"\d+ ?倍", "10 倍"), (r"(?<!\w)\d+ lần(?!\w)", "10 lần"), (r"\d+배", "10배"),
    (r"(?<!\w)\d+ ori(?!\w)", "10 ori"), (r"(?<!\w)\d+ เท่า", "10 เท่า"), (r"(?<!\w)\d+ مرات(?!\w)", "10 مرات"),
    (r"(?<!\w)\d+ برابر(?!\w)", "10 برابر"), (r"(?<!\w)פי \d+(?!\w)", "פי 10"),
)
HIGHLIGHT_RULE = re.compile("|".join(pattern for pattern, _ in HIGHLIGHT_FORMS))

# A run of Latin words in a right-to-left sentence: words of ASCII letters, digits and . _ + - / : × joined by single
# spaces (".tar", "tar.zst", "7-ZSTar 26.05.1", "Show more options", "Windows 11"). Only runs that hold an ASCII letter
# are isolated; a bare number needs no help from the page.
LTR_WORD = r"\.?[A-Za-z0-9][A-Za-z0-9._+\-/:×]*"
LTR_RUN = re.compile(rf"{LTR_WORD}(?: {LTR_WORD})*")


def isolate_ltr(value: str) -> str:
    """HTML for one piece of text on a right-to-left page: every run of Latin words (brand names, file extensions,
    versions, dates like 2026-11, English menu words) is wrapped in <bdi dir="ltr">, so it keeps its own order and the full stop or
    quote next to it stays where the sentence needs it, whatever the surrounding Arabic, Persian or Hebrew is.
    The page does this itself; the dictionary carries no U+200E / U+200F for these places. A run that holds a brand
    name also gets class nw (no break after the hyphen of 7-ZSTar)."""
    out, at = [], 0
    for m in LTR_RUN.finditer(value):
        run = m.group(0)
        trimmed = run.rstrip(".:-/")  # a full stop after the last word belongs to the sentence
        # A run with a letter, or a number with a hyphen or slash inside ("2026-11"): after an Arabic or Persian letter
        # the digits count as Arabic-Indic numbers, whose hyphen is not a number separator, so "2026-11" would show as
        # "11-2026" (Hebrew does not do this). A plain number needs nothing.
        if not (re.search(r"[A-Za-z]", trimmed) or re.search(r"\d[-/]\d", trimmed)):
            continue
        out.append(text(value[at:m.start()]))
        css = ' class="nw"' if BRAND.search(trimmed) else ""
        out.append(f'<bdi dir="ltr"{css}>{text(trimmed)}</bdi>')
        at = m.start() + len(trimmed)
    out.append(text(value[at:]))
    return "".join(out)


def fill_text(html: str, d: dict, lang: str, used: set[str]) -> str:
    before = Counter(re.findall(r'data-i18n="([^"]+)"', html))
    done: Counter = Counter()
    hero = re.search(r'<h1\b[^>]*\bid="hero-h"[^>]*>.*?</h1>', html, re.S)
    hero_span = hero.span() if hero else (0, 0)
    rtl = lang in RTL
    plain = isolate_ltr if rtl else text  # one piece of text -> HTML

    def repl(m: re.Match) -> str:
        tag, attrs, key = m.group(1), m.group(2), m.group(3)
        value = d[key]
        used.add(key)
        done[key] += 1
        if rtl and tag != "text":
            # U+200E / U+200F in a value would double what isolate_ltr already does; SVG <text> cannot hold <bdi>
            # and keeps them, and so do the values used outside text elements (head, aria-label, alt, script strings).
            value = strip_marks(value)
        # Steps in this order: highlight the number, keep brand names unbroken, split hero phrases
        if re.search(r"\sdata-hl(\s|$)", attrs):
            hit = HIGHLIGHT_RULE.search(value)
            if hit:
                body = (plain(value[:hit.start()]) + f'<span class="hl">{text(hit.group(0))}</span>'
                        + plain(value[hit.end():]))
                return f"<{tag}{attrs}>{body}</{tag}>"
            # A language whose "10 times" is written another way would silently lose the amber highlight.
            warn(lang, f"{key} has no number the highlight rule knows ({', '.join(example for _, example in HIGHLIGHT_FORMS)}): "
                       f"{value!r}; add its form to HIGHLIGHT_FORMS")
        if tag != "text" and not rtl and BRAND.search(value):  # SVG <text> is left as plain text
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
                body = joiner.join(f'<span class="ph">{plain(p)}</span>' for p in hint.split("|"))
                return f"<{tag}{attrs}>{body}</{tag}>"
        return f"<{tag}{attrs}>{text(value) if tag == 'text' else plain(value)}</{tag}>"

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
    Vietnamese letters (no ơ ư and none of the tone-marked vowels).
    Checked against Google Fonts' unicode-range subsets on 2026-11-09: Unbounded and IBM Plex
    Mono cover Latin, Latin Extended (Polish, Turkish), Vietnamese and Cyrillic but no Hangul; Figtree
    covers only Latin and Latin Extended, so /ru/ and /uk/ take Onest (Latin + Cyrillic) for the body
    text and /ko/ takes Noto Sans KR for Hangul and the Latin letters around it, the way /ja/ does.
    The other new languages (pl, tr, it, nl, id) need no CJK family, so they leave Noto Sans TC out.
    Batch 2 (checked against the same unicode-range subsets on 2026-11-10): cs, hu, ro and sv are Latin Extended and
    take the same three families as pl and tr; th, el, hi, ar, fa and he keep those three for the Latin letters
    around them (7z, .tar, 26.05.1) and add the language's script family from SCRIPT_FONTS, which the page's font
    stack falls back to for every letter the first families do not have."""
    if lang == "vi":
        families = "Unbounded:wght@500..900&family=Plus+Jakarta+Sans:wght@400..800&family=IBM+Plex+Mono:wght@400;600"
    elif lang in ("ru", "uk"):
        families = "Unbounded:wght@500..900&family=Onest:wght@400..800&family=IBM+Plex+Mono:wght@400;600"
    elif lang == "ko":
        families = ("Unbounded:wght@500..900&family=IBM+Plex+Mono:wght@400;600"
                    "&family=Noto+Sans+KR:wght@400;500;700;900")
    elif lang in ("pl", "tr", "it", "nl", "id", "cs", "hu", "ro", "sv"):
        families = "Unbounded:wght@500..900&family=Figtree:wght@400..800&family=IBM+Plex+Mono:wght@400;600"
    elif lang in SCRIPT_FONTS:
        families = ("Unbounded:wght@500..900&family=Figtree:wght@400..800&family=IBM+Plex+Mono:wght@400;600"
                    f"&family={SCRIPT_FONTS[lang].replace(' ', '+')}:wght@400..800")
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


def resolve_assets(lang: str) -> tuple[str, str]:
    """(share image file, screenshot folder) the page of `lang` uses. A language that has no image or
    screenshots of its own yet borrows the English ones, so it can still be previewed; each borrowed
    asset is recorded as a problem for --strict."""
    page = PAGES[lang]
    og, shots = page["og"], page["slug"]
    if not (ROOT / "public" / og).is_file():
        warn(lang, f"no public/{og}; the page borrows the English share image")
        og = PAGES[DEFAULT]["og"]
    if not all((ROOT / "public" / "screenshots" / shots / f).is_file() for f in ("main.png", "menu.png")):
        warn(lang, f"no public/screenshots/{shots}/main.png and menu.png; the page borrows the English screenshots")
        shots = PAGES[DEFAULT]["slug"]
    return og, shots


def load_header_widths() -> dict[str, dict[str, int]]:
    """src/header-widths.json without its "_" keys (notes written by the measuring tool)."""
    if not HEADER_WIDTHS_FILE.is_file():
        raise SystemExit("src/header-widths.json is missing; run tools/measure-header.py")
    table = {k: v for k, v in json.loads(HEADER_WIDTHS_FILE.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    for lang, row in table.items():
        if lang not in PAGES:
            raise SystemExit(f"src/header-widths.json names a language that is not in PAGES: {lang}")
        if set(row) != set(WIDTH_KEYS) or not all(isinstance(v, int) for v in row.values()):
            raise SystemExit(f"src/header-widths.json[{lang}] must hold exactly the integers {list(WIDTH_KEYS)}")
    return table


def header_inputs(lang: str, d: dict, template: str) -> str:
    """A fingerprint of everything that decides where the header changes step, for one language: the parts of
    the template between `header-widths:begin` and `header-widths:end` markers (the header's HTML and CSS, the
    font stacks, the base rules it uses, and the 480px rule that shrinks the page padding), with comments
    removed and whitespace collapsed; the text of the nav links and of the language button; and the URL of
    the web fonts the page loads. tools/measure-header.py stores it next to the numbers it measured
    (src/header-widths.json "_inputs"); when it no longer matches, the numbers are stale.
    It cannot see a web font that Google changes behind the same URL; remeasure now and then."""
    begins, ends = template.count("header-widths:begin"), template.count("header-widths:end")
    parts = re.findall(r"(?:/\*|<!--)\s*header-widths:begin\s*(?:\*/|-->)(.*?)(?:/\*|<!--)\s*header-widths:end\s*(?:\*/|-->)",
                       template, re.S)
    if not parts or begins != ends or len(parts) != begins:
        raise SystemExit("src/page.template.html: the header-widths:begin / header-widths:end markers are missing or "
                         f"unbalanced ({begins} begin, {ends} end, {len(parts)} complete pairs); they must surround "
                         "everything that decides where the header changes step")
    chunks = [re.sub(r"\s+", " ", re.sub(r"/\*.*?\*/|<!--.*?-->", "", part, flags=re.S)).strip() for part in parts]
    labels = [d[k] for k in ("nav.download", "nav.shots", "nav.source", "lang.short")] + [PAGES[lang]["name"]]
    fonts = "self-hosted zh-hans.css" if lang == "zh-Hans" else google_fonts_url(lang)
    parts_of_blob = [chunks, labels, fonts]
    if lang in RTL:
        parts_of_blob.append("rtl")  # a mirrored header is a different header; LTR pages keep their old fingerprint
    blob = json.dumps(parts_of_blob, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def load_header_inputs() -> dict[str, str]:
    return json.loads(HEADER_WIDTHS_FILE.read_text(encoding="utf-8")).get("_inputs", {})


def header_widths_for(lang: str, table: dict[str, dict[str, int]]) -> dict[str, int]:
    if lang in table:
        return table[lang]
    warn(lang, "no measured header widths in src/header-widths.json (run tools/measure-header.py); using English's")
    return table[DEFAULT]


def build_page(template: str, i18n: dict, lang: str, widths: dict[str, int] | None = None) -> str:
    """One language page. `widths` replaces the language's measured header widths (the measuring tool
    passes impossible sentinel values here, so that it can switch each step on and off itself)."""
    check_script_fonts(template)  # every way in (the build, tools/measure-header.py) meets the font-table check
    d = fill_counts(i18n[lang])
    used: set[str] = set()
    body = fill_attrs(template, d, used)
    body = fill_text(body, d, lang, used)
    unused = set(d) - used - DYNAMIC_KEYS - HEAD_KEYS
    if unused:
        raise SystemExit(f"[{lang}] dictionary keys the template never uses: {sorted(unused)}")
    row_labels = {k: d[k] for k in sorted(DYNAMIC_KEYS)}
    dict_json = json.dumps(row_labels, ensure_ascii=False, indent=2).replace("</", "<\\/")
    og, shots_slug = resolve_assets(lang)
    og_size = png_size(ROOT / "public" / og)  # head_block states 1200x630
    if og_size != (1200, 630):
        raise SystemExit(f"[{lang}] public/{og} is {og_size[0]}x{og_size[1]}, expected 1200x630; run tools/make-og.py")
    shots = ROOT / "public" / "screenshots" / shots_slug
    main_w, main_h = png_size(shots / "main.png")
    menu_w, menu_h = png_size(shots / "menu.png")
    donate_addr, donate_qr = donate_assets()
    html = fill(body, {
        "donate_addr": text(donate_addr), "donate_qr": donate_qr, "donate_readme_url": attr(DONATE_README_URL),
        **{k: str(v) for k, v in (widths or header_widths_for(lang, HEADER_WIDTHS)).items()},
        "main_w": str(main_w), "main_h": str(main_h), "menu_w": str(menu_w), "menu_h": str(menu_h),
        "zoom_icon": ZOOM_ICON,
        "lang": lang,
        "dir_attr": ' dir="rtl"' if lang in RTL else "",
        "head": head_block(d, lang, url(lang), "../", og),
        "assets": "../",
        "slug": PAGES[lang]["slug"],
        "shots_slug": shots_slug,
        "fonts_js": LOCAL_FONTS_JS if lang == "zh-Hans" else google_fonts_js(lang),
        "noscript_fonts": LOCAL_NOSCRIPT if lang == "zh-Hans" else google_noscript(lang),
        "dict_json": dict_json,
        "lang_name": text(PAGES[lang]["name"]),
        "lang_options": lang_options(lang),
        "lang_rows": str((len(PAGES) + 1) // 2),    # rows per column when the menu has two columns
        "lang_rows3": str((len(PAGES) + 2) // 3),   # and when it has three
        "app_lang_items": app_language_items(),
    })
    check_no_placeholder(html, lang)
    return html


# Browser language tags the root page maps to a page. The first subtag decides, except Chinese
# (script or region) and Portuguese (every variant lands on pt-BR); "in" is Indonesian's old code.
def tag_table() -> dict[str, str]:
    table = {lang.split("-")[0].lower(): lang for lang in PAGES if not lang.startswith("zh")}
    table["in"] = "id"
    table["iw"] = "he"  # Hebrew's old code, still what some browsers and Java report
    return table


def build_root(template: str, i18n: dict) -> str:
    d = fill_counts(i18n[DEFAULT])
    paths = {lang: f"/{page['slug']}/" for lang, page in PAGES.items()}
    links = "\n".join(f'    <li><a href="/{page["slug"]}/" lang="{lang}" dir="{"rtl" if lang in RTL else "ltr"}" '
                      f'hreflang="{lang}">{text(page["name"])}</a></li>' for lang, page in PAGES.items())
    html = fill(template, {
        "head": head_block(d, DEFAULT, f"{SITE}/", "", PAGES[DEFAULT]["og"]),
        "paths_js": json.dumps(paths, ensure_ascii=False),
        "tags_js": json.dumps(tag_table(), ensure_ascii=False),
        "root_links": links,
    })
    check_no_placeholder(html, "root page")
    return html


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
            value = i18n[lang][key]
            if lang in RTL:  # fill_text drops the direction marks of a right-to-left value before it compares
                value = strip_marks(value)
            if joiner.join(hint.split("|")) != value:
                raise SystemExit(f"[{lang}] HERO_PHRASES[{key!r}] = {hint!r} no longer matches the "
                                 f"dictionary text {i18n[lang][key]!r}; update HERO_PHRASES together with src/i18n.json")


def draft_languages(i18n: dict) -> dict[str, str]:
    """Languages whose copy is not final: the ones listed in src/draft-languages.json, plus any that
    still carries three or more long strings identical to English (an untranslated copy is a draft
    whether or not someone remembered to list it)."""
    out: dict[str, str] = {}
    if DRAFT_FILE.is_file():
        for lang, note in json.loads(DRAFT_FILE.read_text(encoding="utf-8")).items():
            if lang not in PAGES:
                raise SystemExit(f"src/draft-languages.json names a language that is not in PAGES: {lang}")
            out[lang] = f"listed in src/draft-languages.json ({note})"
    en = i18n[DEFAULT]
    for lang, d in i18n.items():
        if lang == DEFAULT or lang in out:
            continue
        same = [k for k in en if len(en[k]) >= 20 and d[k] == en[k]]
        if len(same) >= 3:
            out[lang] = f"{len(same)} long strings are identical to English ({same[0]}, ...)"
    return out


def load_app_languages() -> dict:
    if not APP_LANGS_FILE.is_file():
        raise SystemExit("src/app-languages.json is missing; run tools/make-app-languages.py")
    data = json.loads(APP_LANGS_FILE.read_text(encoding="utf-8"))
    rows = data.get("languages")
    if not rows or not all(isinstance(e, dict) and {"code", "lang", "name"} <= set(e) and e["name"].strip() for e in rows):
        raise SystemExit('src/app-languages.json: every entry in "languages" needs code, lang and a non-empty name')
    return data


@functools.cache  # build_page asks once per page; a template that passes is checked once (a failure raises, so it is not cached)
def check_script_fonts(template: str) -> None:
    """SCRIPT_FONTS (which families the page loads from Google, see google_fonts_url) and the page's CSS (which family a
    language falls back to) are two copies of one table. If they drift, the page loads a font it never uses (the
    browser then never downloads it, and tools/measure-header.py waits for it in vain) or uses one it never loaded.
    Every SCRIPT_FONTS entry needs html[lang="xx"]{--script:'Family'} in the template and xx in the html:is(...) list
    that gives the page its font stacks, and the template must declare no --script that SCRIPT_FONTS does not have.
    tools/make-og.py makes the same check for tools/og.html."""
    declared = dict(re.findall(r"""html\[lang="([\w-]+)"\]\{--script:'([^']+)'\}""", template))
    block = re.search(r"html:is\(([^)]*)\)\{\s*--font-display", template)
    listed = set(re.findall(r'\[lang="([\w-]+)"\]', block.group(1))) if block else set()
    problems = []
    if not block:
        problems.append("src/page.template.html has no html:is(...){ --font-display ... } rule for the script languages")
    for lang, family in SCRIPT_FONTS.items():
        if lang not in PAGES:
            problems.append(f"SCRIPT_FONTS names {lang}, which is not in PAGES")
        if declared.get(lang) != family:
            problems.append(f"src/page.template.html should have html[lang=\"{lang}\"]{{--script:'{family}'}} "
                            f"(SCRIPT_FONTS), found {declared.get(lang)!r}")
        if block and lang not in listed:
            problems.append(f"src/page.template.html: add [lang=\"{lang}\"] to the html:is(...) list that sets --font-display "
                            "and --font-body")
    for lang in declared:
        if lang not in SCRIPT_FONTS:
            problems.append(f"src/page.template.html declares --script for {lang}, which SCRIPT_FONTS does not have")
    for lang in listed:
        if lang not in SCRIPT_FONTS:
            problems.append(f"src/page.template.html lists [lang=\"{lang}\"] in the script-font html:is(...) rule, "
                            "but SCRIPT_FONTS does not have it")
    if problems:
        raise SystemExit("SCRIPT_FONTS in tools/build-pages.py and src/page.template.html do not match:\n  "
                         + "\n  ".join(problems))


ZH_HANS_CHARS = ROOT / "public" / "fonts" / "zh-hans-chars.txt"


def check_zh_hans_font(html: str) -> None:
    """The zh-Hans page loads only its own subset fonts (no Google), so a character outside them falls back to a
    system font. tools/subset-fonts.py writes the characters the subsets really have to zh-hans-chars.txt; every
    character of the page's own text must be in it. The two lists of other languages' names (the language menu and
    the interface-languages section) are left out: they are meant to be in those languages."""
    if not ZH_HANS_CHARS.is_file():
        warn("zh-Hans", "public/fonts/zh-hans-chars.txt is missing; run tools/subset-fonts.py (README, step 8)")
        return
    have = set(ZH_HANS_CHARS.read_text(encoding="utf-8").strip())
    text_only = re.sub(r"/\*.*?\*/", "", html, flags=re.S)
    text_only = re.sub(r"<!--.*?-->", "", text_only, flags=re.S)
    text_only = re.sub(r'<ul class="(?:app-langs|lang-list)".*?</ul>', "", text_only, flags=re.S)
    need = {c for c in unescape(text_only) if ord(c) > 0x7E}
    missing = sorted(need - have)
    if missing:
        warn("zh-Hans", f"{len(missing)} characters of the page are not in the self-hosted font subsets "
                        f"({''.join(missing)}); rebuild them with tools/subset-fonts.py (README, step 8)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the static pages under public/ from src/.")
    parser.add_argument("--strict", action="store_true",
                        help="fail (exit 1) if any language is a draft or lacks its own screenshots, share image "
                             "or measured header widths; the deploy workflow runs this")
    args = parser.parse_args()
    i18n = json.loads((ROOT / "src" / "i18n.json").read_text(encoding="utf-8"))
    if set(i18n) != set(PAGES):
        raise SystemExit(f"i18n.json languages {sorted(i18n)} != {sorted(PAGES)}")
    reference = set(i18n[DEFAULT])
    for lang, d in i18n.items():
        if set(d) != reference:
            raise SystemExit(f"[{lang}] keys differ from {DEFAULT}: {sorted(set(d) ^ reference)}")
    APP_LANGS.update(load_app_languages())
    check_hero_phrases({lang: fill_counts(d) for lang, d in i18n.items()})
    HEADER_WIDTHS.update(load_header_widths())
    if DEFAULT not in HEADER_WIDTHS:
        raise SystemExit(f"src/header-widths.json has no entry for {DEFAULT}")
    for lang, why in draft_languages(i18n).items():
        warn(lang, f"draft copy: {why}")
    template = (ROOT / "src" / "page.template.html").read_text(encoding="utf-8")
    measured_with = load_header_inputs()
    for lang in HEADER_WIDTHS:
        if lang in PAGES and measured_with.get(lang) != header_inputs(lang, i18n[lang], template):
            warn(lang, "src/header-widths.json is stale: the nav labels, the language button text or the header CSS "
                       "changed after it was measured; run tools/measure-header.py")
    root_template = (ROOT / "src" / "root.template.html").read_text(encoding="utf-8")
    public = ROOT / "public"
    for lang, page in PAGES.items():
        html = build_page(template, i18n, lang)
        if lang == "zh-Hans":
            check_zh_hans_font(html)
        write(public / page["slug"] / "index.html", html)
    write(public / "index.html", build_root(root_template, i18n))
    write(public / "sitemap.xml", build_sitemap())
    for lang, message in PROBLEMS:
        print(f"{'ERROR' if args.strict else 'warning'}: [{lang}] {message}", file=sys.stderr)
    if PROBLEMS and args.strict:
        langs = sorted({lang for lang, _ in PROBLEMS})
        print(f"--strict: {len(PROBLEMS)} problem(s) in {len(langs)} language(s): {', '.join(langs)}; "
              "nothing here may be published yet", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
