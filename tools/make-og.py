#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright==1.55.0"]
# ///
"""Render the share images (1200x630), one per language, with the locally installed Edge.

The output file of each language is listed in OUTPUT below (public/og.png for English,
public/og-<slug>.png for the others).

The three lines are the dictionary values hero.l1, onepass.h and speed.h2 from
src/i18n.json, so the images always say what the page says. Rerun after changing
those strings. tools/og.html loads Noto Sans TC, Noto Sans JP and the full Unbounded
from Google Fonts, so it needs an internet connection; look at the result before committing.
"""
import json
from html import escape
from pathlib import Path

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent.parent
i18n = json.loads((root / "src" / "i18n.json").read_text(encoding="utf-8"))

OUTPUT = {"en": "og.png", "zh-Hant": "og-zh-hant.png", "zh-Hans": "og-zh-hans.png", "de": "og-de.png", "fr": "og-fr.png", "es": "og-es.png", "pt-BR": "og-pt-br.png", "ja": "og-ja.png", "vi": "og-vi.png", "eo": "og-eo.png"}
KEYS = ("hero.l1", "onepass.h", "speed.h2")


# The German, French, Spanish, Portuguese, Japanese, Vietnamese and Esperanto lines are longer than
# the space beside the icon, or need their own breaks, so each line breaks at the listed places.
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
