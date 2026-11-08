# 7-ZSTar website

Source of the 7-ZSTar website, <https://www.7zstar.com/>.

7-ZSTar itself lives in [7zStar/7-ZSTar](https://github.com/7zStar/7-ZSTar).

## Pages

Each language has its own address, so a shared link previews in that language and search engines index all ten:

| Address | Language |
| --- | --- |
| `/en/` | English |
| `/zh-hant/` | Traditional Chinese |
| `/zh-hans/` | Simplified Chinese |
| `/de/` | German |
| `/fr/` | French |
| `/es/` | Spanish |
| `/pt-br/` | Brazilian Portuguese |
| `/ja/` | Japanese |
| `/vi/` | Vietnamese |
| `/eo/` | Esperanto |
| `/` | Sends the visitor to one of the above: the language saved by the language menu, then the browser's language, then English. Without JavaScript it goes to `/en/`. |

The text and meta tags of every language page are already in that language in the raw HTML. Only the benchmark table, the bar chart and the file-format icons are drawn by the page's script.

## Layout

- `src/` - what you edit. `page.template.html` is the page with its text left empty, `i18n.json` holds the copy for all ten languages, `root.template.html` is the page at `/`. `donate-address.txt` is the one place the donation address is written down, and `donate-qr.svg` is the QR made from it (committed, see `tools/make-donate-qr.py`).
- `public/` - the site. Committed: `icon.svg`, the ten share images (`og.png`, `og-zh-hant.png`, `og-zh-hans.png`, `og-de.png`, `og-fr.png`, `og-es.png`, `og-pt-br.png`, `og-ja.png`, `og-vi.png`, `og-eo.png`), `robots.txt`, `fonts/` and `screenshots/`. Generated and not committed: `index.html`, `en/`, `zh-hant/`, `zh-hans/`, `de/`, `fr/`, `es/`, `pt-br/`, `ja/`, `vi/`, `eo/` and `sitemap.xml`. This is the only directory that gets published.
- `tools/` - helper scripts, not published, all run with `uv run`:
  - `build-pages.py` builds the generated files in `public/` from `src/` (standard library only, same input gives the same output).
  - `make-og.py` renders `tools/og.html` into the ten share images, using the headline lines from `src/i18n.json`.
  - `subset-fonts.py` rebuilds the Simplified Chinese font subsets from the built `public/zh-hans/index.html`.
  - `crop-screenshots.py` crops raw screenshots into `public/screenshots/<slug>/`.
  - `make-donate-qr.py` makes `src/donate-qr.svg` from `src/donate-address.txt`, then decodes the committed SVG and checks it equals the address character by character (`--check` only verifies). Rerun it if the address ever changes.
- `.github/workflows/pages.yml` - runs `build-pages.py`, then deploys `public/` to GitHub Pages on every push to `main`.

## Build and preview locally

```
uv run tools/build-pages.py
uv run python -m http.server --directory public
```

Then open <http://localhost:8000/>. Preview through the local server: the language menu and the redirect at `/` need real addresses. (The images and fonts on a language page use relative paths, so opening `public/zh-hant/index.html` straight from disk shows the page, but the menu's links and the redirect do not work there.) Change the copy in `src/i18n.json` and the markup or script in `src/page.template.html`, then build again. Never edit the generated files in `public/`; the next build overwrites them.

## When the copy changes

The workflow only rebuilds the pages. The Simplified Chinese font subset and the share images are committed files, and CI does not regenerate them, so after changing the copy do this by hand, in this order, and commit the results:

1. `uv run tools/build-pages.py`
2. If the Simplified Chinese copy changed: `uv run tools/subset-fonts.py --src <dir> --html public/zh-hans/index.html --out public/fonts`. `<dir>` must hold `NotoSansSC[wght].ttf` and `Unbounded[wght].ttf`, the variable fonts from [google/fonts](https://github.com/google/fonts) (the versions are in the script's docstring). Without it, new characters fall back to a system font.
3. If the headline copy changed (`hero.l1`, `onepass.h`, `speed.h2`): `uv run tools/make-og.py`, then look at the ten images. It needs Microsoft Edge installed locally. `tools/og.html` loads Noto Sans TC, Noto Sans JP and the full Unbounded (for accented letters) from Google Fonts, so it also needs a connection.

## Adding a language

The language menu, the `hreflang` links and the sitemap are all built from `PAGES` in `tools/build-pages.py`, so a new language shows up in all of them on every page once it has an entry there. For a language with the tag `xx`:

1. Add an entry to `PAGES`: `slug` (the address), `name` (the language in its own words, shown in the menu), `locale`, `og` (the share image's file name) and `header` (which `HEADER_WIDTHS` entry sets its narrow-window header). The menu lists the languages in this order. Add `/public/<slug>/` to `.gitignore` too, since the generated pages are not committed.
2. Add an `xx` dictionary to `src/i18n.json` with every key of the `en` one. The build stops if a key is missing or extra.
3. Add the language to `OUTPUT` in `tools/make-og.py` and give it font rules for `.lines` in `tools/og.html` if the English ones do not suit it. If the three lines are longer than the space beside the icon, add an entry to `BREAKS` in the same script: the pieces of each line, which must join (with a space, or with `SEP` for a language written without spaces, like Japanese) to exactly the dictionary text. Run the script and look at the new image. The build stops if `public/<og>` is missing or is not 1200×630.
4. In `src/root.template.html`, add it to `PATHS`, `mapTag` and the fallback links, so `/` can send visitors there.
5. If the language needs a font the page does not load yet, add it to `google_fonts_url(lang)` in `tools/build-pages.py` (it picks the body and CJK families per language) and set `--font-display` and `--font-body` for `html[lang="xx"]` in `src/page.template.html`.
6. Check the rules that name languages, because a new language gets none of them by default:
   - In `src/page.template.html`, the `html[lang=...]` rules set letter spacing, line height and the English hero size.
   - In `tools/build-pages.py`, `HEADER_WIDTHS` sets when the header shrinks. Its comment says how the numbers are worked out; check the new language at phone width.
   - In `tools/build-pages.py`, `image_alt` uses a full-width colon only for `zh-*` and `ja` (the others get `: `), and `fill_text` highlights only numbers written as `10×`, `10 倍` (the space is optional) or `10 lần`.
   - In `tools/build-pages.py`, `HERO_PHRASES` has one table per language and sets where its hero lines may wrap. The phrases joined with a space must equal the dictionary text, or the build stops. `SPACELESS` lists the languages written without spaces (Japanese), whose phrases are joined with nothing.
   - In the page script of `src/page.template.html`, `NUM_STYLE` sets the decimal mark and the thousands separator of the benchmark table (without an entry the numbers print as `4.1` and `13,371`, and nothing warns you), and `MB` sets the file-size unit (`Mo` for French).
   - In `src/page.template.html`, the `.dn-addr` font size is lowered for German and Vietnamese so the address stays on one line beside the copy button; check the new language at desktop width.
7. Add `public/screenshots/<slug>/main.png` and `menu.png` with `tools/crop-screenshots.py --new`. Windows and 7-ZSTar should both be in the new language, because the right-click menu shows the system's own text. The one exception is Esperanto: Windows 11 has no Esperanto language pack, so its screenshots are an English Windows with a 7-ZSTar in Esperanto, and the page says so in `a11y.shot_menu`. The build stops if the files are missing.
8. Rebuild the font subset as in "When the copy changes": the new language's name now appears in the menu on the Simplified Chinese page too. Characters that Noto Sans SC does not have fall back to a system font on that page.

## Fonts

The English, Traditional Chinese, Japanese and the other Latin-script pages load their fonts from Google Fonts: Noto Sans JP on the Japanese page, Noto Sans TC on the others. The Vietnamese page loads Plus Jakarta Sans instead of Figtree, because Figtree has no Vietnamese letters. The Simplified Chinese page uses the self-hosted files in `public/fonts/` instead, so it makes no request to Google. These fonts are licensed under the SIL Open Font License 1.1; the license texts are the `OFL-*.txt` files in the same directory. The original TTF sources are not kept in this repository. To regenerate the subsets, see "When the copy changes" above.

## License

All rights reserved; this website is not open source. See [LICENSE](LICENSE) for the exceptions (the fonts, and the 7-ZSTar program itself).
