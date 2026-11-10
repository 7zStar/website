#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright==1.55.0"]
# ///
"""Render the share images (1200x630), one per language, with the locally installed Edge.

The output file of each language is listed in OUTPUT below (public/og.png for English,
public/og-<slug>.png for the others).

Usage: uv run tools/make-og.py            render every language in OUTPUT
       uv run tools/make-og.py ru ko      render only these languages (keys of OUTPUT, e.g. zh-Hant, pt-BR);
                                          an unknown key stops the script before anything is rendered

The three lines are the dictionary values hero.l1, onepass.h and speed.h2 from
src/i18n.json, so the images always say what the page says. Rerun after changing
those strings. tools/og.html loads Noto Sans TC, Noto Sans JP, Noto Sans KR and the full
Unbounded from Google Fonts, so it needs an internet connection; look at the result before committing.
"""
import json
import sys
from html import escape
from pathlib import Path

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent.parent
i18n = json.loads((root / "src" / "i18n.json").read_text(encoding="utf-8"))

OUTPUT = {"en": "og.png", "zh-Hant": "og-zh-hant.png", "zh-Hans": "og-zh-hans.png", "de": "og-de.png", "fr": "og-fr.png", "es": "og-es.png", "pt-BR": "og-pt-br.png", "ja": "og-ja.png", "vi": "og-vi.png", "ru": "og-ru.png", "ko": "og-ko.png", "it": "og-it.png", "pl": "og-pl.png", "tr": "og-tr.png", "nl": "og-nl.png", "uk": "og-uk.png", "id": "og-id.png", "eo": "og-eo.png"}
KEYS = ("hero.l1", "onepass.h", "speed.h2")
SELECTED = sys.argv[1:]
if [a for a in SELECTED if a not in OUTPUT]:
    raise SystemExit(f"unknown language {[a for a in SELECTED if a not in OUTPUT]}; the keys of OUTPUT are: {', '.join(OUTPUT)}")


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
}


def lines(lang: str) -> list[str]:
    out = [i18n[lang][k] for k in KEYS]
    if lang == "en":
        # The English image breaks the first line after "Show"
        assert out[0] == "Skip “Show more options”.", out[0]
        out[0] = "Skip “Show<br>more options”."
        out[1] = escape(out[1], quote=False)  # the second line is set as HTML, like the other languages'
    elif lang in BREAKS:
        for text, pieces in zip(out, BREAKS[lang]):
            assert SEP.get(lang, " ").join(pieces) == text, (lang, text, pieces)
        third = out[2]  # set as plain text (textContent), so it must not be escaped
        out = ["<br>".join(escape(piece, quote=False) for piece in pieces) for pieces in BREAKS[lang][:2]]
        out.append(third)
    else:
        out[0] = escape(out[0], quote=False)  # the first line is set as HTML
        out[1] = escape(out[1], quote=False)  # so is the second
    return out


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1200, "height": 630})
    for lang, name in OUTPUT.items():
        if SELECTED and lang not in SELECTED:
            continue
        page.goto((root / "tools" / "og.html").as_uri())
        page.evaluate(
            """([lang, l1, l2, l3]) => {
                document.documentElement.lang = lang;
                document.getElementById('l1').innerHTML = l1;
                document.getElementById('l2').innerHTML = l2;
                document.getElementById('l3').textContent = l3;
                return document.body.offsetHeight;
            }""",
            [lang, *lines(lang)],
        )
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(500)
        page.screenshot(path=root / "public" / name)
        print("wrote", root / "public" / name)
    browser.close()
