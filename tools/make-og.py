#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright==1.55.0"]
# ///
"""Render the share images (1200x630), one per language, with the locally installed Edge.

The output file of each language is the "og" entry of its page in PAGES (tools/build-pages.py):
public/og.png for English, public/og-<slug>.png for the others.

Usage: uv run tools/make-og.py            render every language in PAGES
       uv run tools/make-og.py ru ko      render only these languages (keys of PAGES, e.g. zh-Hant, pt-BR);
                                          an unknown key stops the script before anything is rendered

The three lines are the dictionary values hero.l1, onepass.h and speed.h2 from
src/i18n.json, so the images always say what the page says. Rerun after changing
those strings. tools/og.html loads Noto Sans TC, Noto Sans JP, Noto Sans KR, the script families of
SCRIPT_FONTS (build-pages.py: Thai, Greek, Devanagari, Arabic, Persian, Hebrew) and the full Unbounded
from Google Fonts, so it needs an internet connection; look at the result before committing. The script
stops before rendering when tools/og.html does not match SCRIPT_FONTS (see check_og_fonts).
"""
import importlib.util
import json
import re
import sys
from html import escape
from pathlib import Path

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent.parent
i18n = json.loads((root / "src" / "i18n.json").read_text(encoding="utf-8"))

# The right-to-left languages isolate their Latin words the way the pages do (build-pages.py isolate_ltr)
spec = importlib.util.spec_from_file_location("build_pages", root / "tools" / "build-pages.py")
build_pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_pages)
RTL = build_pages.RTL

OUTPUT = {lang: page["og"] for lang, page in build_pages.PAGES.items()}  # the order of PAGES
KEYS = ("hero.l1", "onepass.h", "speed.h2")
SELECTED = sys.argv[1:]
if [a for a in SELECTED if a not in OUTPUT]:
    raise SystemExit(f"unknown language {[a for a in SELECTED if a not in OUTPUT]}; the keys of OUTPUT are: {', '.join(OUTPUT)}")


def check_og_fonts() -> None:
    """The language -> script font table is written in three places: SCRIPT_FONTS in tools/build-pages.py, the
    --script rules in src/page.template.html (build-pages.py checks that one) and here, tools/og.html (its <link>
    for each family and its .lines rule for each language). Stop with a message that says what to change if og.html
    does not match SCRIPT_FONTS, instead of rendering a share image in a fallback font."""
    og = (root / "tools" / "og.html").read_text(encoding="utf-8")
    problems = []
    for lang, family in build_pages.SCRIPT_FONTS.items():
        if f"family={family.replace(' ', '+')}:" not in og:
            problems.append(f"tools/og.html has no <link> for {family!r} (the script font of {lang} in SCRIPT_FONTS): "
                            f"add <link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?family={family.replace(' ', '+')}"
                            ":wght@800&amp;display=swap\">")
        # the .lines rule of the language must exist and name this very family in its font-family
        rule = re.search(rf'html\[lang="{re.escape(lang)}"\] \.lines\{{[^}}]*font-family:[^;}}]*\'{re.escape(family)}\'', og)
        if not rule:
            problems.append(f"tools/og.html has no 'html[lang=\"{lang}\"] .lines' rule with font-family '{family}' "
                            f"({lang} is in SCRIPT_FONTS): give it font-family 'Unbounded','{family}',sans-serif and letter-spacing:0")
    if problems:
        raise SystemExit("tools/og.html does not match SCRIPT_FONTS in tools/build-pages.py:\n  " + "\n  ".join(problems))


check_og_fonts()


# Every language except English (its first line is handled in lines() below) and the two Chinese ones has its
# lines broken at the listed places: they are longer than the space beside the icon, or need their own breaks.
# Joined with a space (with nothing for Japanese, see SEP), the pieces must equal the dictionary
# text (the check below), so changing the copy stops the script until the breaks are revisited.
NB = "\u00a0"
SEP = {"ja": ""}  # Japanese has no spaces between the pieces
BREAKS = {
    "de": [["Ohne", "„Weitere Optionen", "anzeigen“."], ["Ein Durchgang.", "Kein .tar auf der Platte."],
           ["10× schneller als 7z."]],
    "fr": [["Sans détour par", f"«{NB}Afficher d’autres", f"options{NB}»."], ["Une passe.", "Aucun .tar sur le disque."],
           ["10× plus rapide que 7z."]],
    "es": [["Olvídate de", "«Mostrar Más", "opciones»."], ["Un solo paso.", "Sin .tar en el disco."],
           ["10× más rápido que 7z."]],
    "ja": [["「その他のオプションを確認」", "を飛ばせます。"], ["一度で完了。", "ディスクに.tarは作りません。"],
           ["7zの10倍速い。"]],
    "vi": [["Không cần bấm", "“Xem thêm tùy chọn” nữa."], ["Một lượt.", "Không có .tar trên đĩa."],
           ["Nhanh gấp 10 lần 7z."]],
    "eo": [["Preterpasu", "«Show more options»."], ["Unu trairo.", "Neniu .tar sur la disko."],
           ["10× pli rapide ol 7z."]],
    "pt-BR": [["Pule o", "“Mostrar mais", "opções”."], ["Uma passada.", "Nenhum .tar no disco."],
              ["10× mais rápido que o 7z."]],
    "ru": [["Обойдитесь", "без «Показать", "дополнительные", "параметры»."], ["Один проход.", "Без .tar на диске."], ["10× быстрее, чем 7z."]],
    "ko": [["“추가 옵션 표시”는", "이제 건너뛰세요."], ["한 번에.", "디스크에 .tar 없이."], ["7z보다 10배 빠릅니다."]],
    "it": [["Niente più", "«Mostra", "altre opzioni»."], ["Un solo passaggio.", "Nessun .tar su disco."], ["10× più veloce di 7z."]],
    "pl": [["Koniec", "z „Pokaż więcej opcji”."], ["Jeden przebieg.", "Bez .tar na dysku."], ["10× szybciej niż 7z."]],
    "tr": [["“Daha fazla", "seçenek göster”", "adımına son."], ["Tek geçiş.", "Diskte .tar yok."], ["7z’den 10× hızlı."]],
    "nl": [["Sla", "“Meer opties weergeven”", "over."], ["In één keer.", "Geen .tar op schijf."], ["10× sneller dan 7z."]],
    "uk": [["Обійдіться", "без «Показати", "додаткові параметри»."], ["Один прохід.", "Без .tar на диску."], ["10× швидше, ніж 7z."]],
    "id": [["Tak perlu lagi", "“Tampilkan", "opsi lainnya”."], ["Sekali jalan.", "Tanpa .tar di disk."], ["10× lebih cepat dari 7z."]],
    # Batch 2. Where a quotation mark falls inside a phrase of the page (ro, el, hi), the image breaks inside it
    # too, because the image has less room than the page. The right-to-left ones hold no U+200E / U+200F.
    "th": [["ไม่ต้องกด", "“แสดงตัวเลือกเพิ่มเติม”", "อีกต่อไป"], ["จบในขั้นเดียว", "ไม่มี .tar บนดิสก์"], ["เร็วกว่า 7z 10 เท่า"]],
    "cs": [["Už žádné „Zobrazit", "další možnosti“."], ["Jeden průchod.", "Žádný .tar na disku."], ["10× rychleji než 7z."]],
    "hu": [["Ugord át", "a „További lehetőségek", "megjelenítése” lépést."], ["Egyetlen menet.", "Nincs .tar a lemezen."], ["10× gyorsabb, mint a 7z."]],
    "ro": [["Fără „Afișați", "mai multe opțiuni”."], ["O singură trecere.", "Fără .tar pe disc."], ["De 10 ori mai rapid decât 7z."]],
    "sv": [["Hoppa över", "”Visa fler alternativ”."], ["Ett svep.", "Ingen .tar på disk."], ["10× snabbare än 7z."]],
    "el": [["Τέλος στο «Εμφάνιση", "περισσότερων επιλογών»."], ["Ένα πέρασμα.", "Κανένα .tar στον δίσκο."], ["10× ταχύτερα από το 7z."]],
    "hi": [["अब “Show more options” की", "ज़रूरत नहीं।"], ["एक ही बार में।", "डिस्क पर कोई .tar नहीं।"], ["7z से 10× तेज़।"]],
    "ar": [["لا حاجة بعد الآن إلى", "«إظهار المزيد من الخيارات»."], ["خطوة واحدة.", "لا ملف .tar على القرص."], ["أسرع 10 مرات من 7z."]],
    "fa": [["دیگر نیازی به", "«Show more options» نیست."], ["یک مرحله.", "بدون .tar روی دیسک."], ["10 برابر سریع‌تر از 7z."]],
    "he": [["בלי ללחוץ על", "“הצג אפשרויות נוספות”."], ["מעבר אחד.", "בלי .tar בדיסק."], ["דחיסה מהירה פי 10 מ־7z."]],
}


def lines(lang: str) -> list[str]:
    out = [i18n[lang][k] for k in KEYS]
    if lang in RTL:
        out = [build_pages.strip_marks(s) for s in out]  # the same rule as the page (fill_text), so BREAKS stay mark-free
    # One piece of text -> HTML. A right-to-left language isolates its Latin words like its page does, on every path
    # below, so a language without BREAKS entries gets the same treatment.
    html = build_pages.isolate_ltr if lang in RTL else lambda s: escape(s, quote=False)
    if lang == "en":
        # The English image breaks the first line after "Show"
        assert out[0] == "Skip “Show more options”.", out[0]
        out[0] = "Skip “Show<br>more options”."
        out[1] = html(out[1])  # all three lines are set as HTML
        out[2] = html(out[2])
    elif lang in BREAKS:
        for text, pieces in zip(out, BREAKS[lang]):
            assert SEP.get(lang, " ").join(pieces) == text, (lang, text, pieces)
        third = html(out[2])  # set as HTML like the other two, so it is escaped (or isolated) the same way
        out = ["<br>".join(html(piece) for piece in pieces) for pieces in BREAKS[lang][:2]]
        out.append(third)
    else:
        out = [html(s) for s in out]
    return out


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1200, "height": 630})
    for lang, name in OUTPUT.items():
        if SELECTED and lang not in SELECTED:
            continue
        page.goto((root / "tools" / "og.html").as_uri())
        page.evaluate(
            """([lang, rtl, l1, l2, l3]) => {
                document.documentElement.lang = lang;
                if (rtl) document.documentElement.dir = 'rtl'; else document.documentElement.removeAttribute('dir');
                document.getElementById('l1').innerHTML = l1;
                document.getElementById('l2').innerHTML = l2;
                document.getElementById('l3').innerHTML = l3;
                return document.body.offsetHeight;
            }""",
            [lang, lang in RTL, *lines(lang)],
        )
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(500)
        page.screenshot(path=root / "public" / name)
        print("wrote", root / "public" / name)
    browser.close()
