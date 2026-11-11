# 7-ZSTar website

Source of the 7-ZSTar website, <https://www.7zstar.com/>.

7-ZSTar itself lives in [7zStar/7-ZSTar](https://github.com/7zStar/7-ZSTar).

## Pages

Each language has its own address, so a shared link previews in that language and search engines index every one of them:

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
| `/ru/` | Russian |
| `/ko/` | Korean |
| `/it/` | Italian |
| `/pl/` | Polish |
| `/tr/` | Turkish |
| `/nl/` | Dutch |
| `/uk/` | Ukrainian |
| `/id/` | Indonesian |
| `/th/` | Thai |
| `/cs/` | Czech |
| `/hu/` | Hungarian |
| `/ro/` | Romanian |
| `/sv/` | Swedish |
| `/el/` | Greek |
| `/hi/` | Hindi |
| `/ar/` | Arabic (right to left) |
| `/fa/` | Persian (right to left) |
| `/he/` | Hebrew (right to left) |
| `/eo/` | Esperanto |
| `/` | Sends the visitor to one of the above: the language saved by the language menu, then the browser's language, then English. Without JavaScript it goes to `/en/`. |

The text and meta tags of every language page are already in that language in the raw HTML. Only the benchmark table, the bar chart and the file-format icons are drawn by the page's script.

## Layout

- `src/` - what you edit. `page.template.html` is the page with its text left empty, `i18n.json` holds the copy for every language (a language that is still a draft is listed in `draft-languages.json`), `root.template.html` is the page at `/`. `header-widths.json` (written by `tools/measure-header.py`) and `app-languages.json` (written by `tools/make-app-languages.py`) are generated but committed. `donate-address.txt` is the one place the donation address is written down, and `donate-qr.svg` is the QR made from it (committed, see `tools/make-donate-qr.py`).
- `public/` - the site. Committed: `icon.svg`, one share image per language (`og.png` for English, `og-<slug>.png` for the others, 1200×630), `robots.txt`, `fonts/` and `screenshots/`. Generated and not committed: `index.html`, one folder per language (`en/`, `zh-hant/`, ..., one for each address in the table above) and `sitemap.xml`. This is the only directory that gets published.
- `tools/` - helper scripts, not published, all run with `uv run`:
  - `build-pages.py` builds the generated files in `public/` from `src/` (standard library only, same input gives the same output).
  - `measure-header.py` measures, per language, the window widths at which the narrow header changes step and writes `src/header-widths.json` (headless Edge with a real classic scrollbar, needs a connection for the web fonts; `--check` only compares; `--verify DIR` looks at every step on the real pages with and without a scrollbar and writes screenshots and `report.md`). The file also stores a fingerprint of the nav labels and header CSS it was measured with, and `build-pages.py --strict` fails when it is out of date, so rerun the tool after changing either.
  - `make-app-languages.py` reads the language files of the 7-ZSTar source tree (`../src/Lang`, read only) and writes `src/app-languages.json`, the names listed in the "interface languages" section.
  - `merge-i18n-drafts.py` merges drafted copy (a folder with one `<lang>.json` per language, given as the first argument) into `src/i18n.json` and keeps the language on the draft list.
  - `make-og.py` renders `tools/og.html` into the share images, one per language (`uv run tools/make-og.py ru ko` renders only those), using the headline lines from `src/i18n.json`.
  - `subset-fonts.py` rebuilds the Simplified Chinese font subsets from the built `public/zh-hans/index.html`, and writes `public/fonts/zh-hans-chars.txt`, the characters the subsets really contain. `build-pages.py --strict` fails when the zh-Hans page uses a character that is not in that list.
  - `crop-screenshots.py` crops raw screenshots into `public/screenshots/<slug>/`.
  - `make-donate-qr.py` makes `src/donate-qr.svg` from `src/donate-address.txt`, then decodes the committed SVG and checks it equals the address character by character (`--check` only verifies). Rerun it if the address ever changes.
- `.github/workflows/pages.yml` - runs `build-pages.py --strict`, then deploys `public/` to GitHub Pages on every push to `main`.

## Build and preview locally

```
uv run tools/build-pages.py
uv run python -m http.server --directory public
```

A plain build only warns about a language that is not ready (draft copy, no screenshots or share image of its own, no measured header widths): such a page borrows the English screenshots and share image so it can be previewed. `--strict`, which the workflow uses, turns every one of those warnings into a failure, so a draft cannot be published.

Then open <http://localhost:8000/>. Preview through the local server: the language menu and the redirect at `/` need real addresses. (The images and fonts on a language page use relative paths, so opening `public/zh-hant/index.html` straight from disk shows the page, but the menu's links and the redirect do not work there.) Change the copy in `src/i18n.json` and the markup or script in `src/page.template.html`, then build again. Never edit the generated files in `public/`; the next build overwrites them.

## When the copy changes

The workflow only rebuilds the pages. The Simplified Chinese font subset and the share images are committed files, and CI does not regenerate them, so after changing the copy do this by hand, in this order, and commit the results:

1. `uv run tools/build-pages.py`
2. If the Simplified Chinese copy changed: `uv run tools/subset-fonts.py --src <dir> --html public/zh-hans/index.html --out public/fonts`. `<dir>` must hold `NotoSansSC[wght].ttf` and `Unbounded[wght].ttf`, the variable fonts from [google/fonts](https://github.com/google/fonts) (the versions are in the script's docstring; the raw files `https://github.com/google/fonts/raw/main/ofl/notosanssc/NotoSansSC[wght].ttf`, 17.8 MB, and `.../ofl/unbounded/Unbounded[wght].ttf`, 0.8 MB, were checked on 2026-11-09 and are exactly those versions; keep them in `fonts-src/`, which is git-ignored). Without this step, new characters fall back to a system font, and `--strict` stops the build.
3. If the headline copy changed (`hero.l1`, `onepass.h`, `speed.h2`): `uv run tools/make-og.py`, then look at every image. It needs Microsoft Edge installed locally. `tools/og.html` loads Noto Sans TC, Noto Sans JP, Noto Sans KR, the script families listed in `SCRIPT_FONTS` (`tools/build-pages.py`) and the full Unbounded (for accented letters) from Google Fonts, so it also needs a connection.

## Adding a language

The language menu, the `hreflang` links and the sitemap are all built from `PAGES` in `tools/build-pages.py`, so a new language shows up in all of them on every page once it has an entry there. For a language with the tag `xx`:

1. Add an entry to `PAGES`: `slug` (the address), `name` (the language in its own words, shown in the menu), `locale` and `og` (the share image's file name), plus `"dir": "rtl"` for a right-to-left language. The menu lists the languages in this order; it has one column below 520px, two from 520px and three from 760px by itself. Add `/public/<slug>/` to `.gitignore` too, since the generated pages are not committed.
2. Add an `xx` dictionary to `src/i18n.json` with every key of the `en` one. The build stops if a key is missing or extra.
3. The share image's file is the `og` entry you gave the page in step 1 (`tools/make-og.py` reads it from `PAGES`); give the language font rules for `.lines` in `tools/og.html` if the English ones do not suit it. If the three lines are longer than the space beside the icon, add an entry to `BREAKS` in the same script: the pieces of each line, which must join (with a space, or with `SEP` for a language written without spaces, like Japanese) to exactly the dictionary text. Run the script and look at the new image. Until `public/<og>` exists the page borrows the English share image and `--strict` fails; the build stops if the file is not 1200×630.
4. Nothing to do for `/`: `src/root.template.html` gets its address table, browser-language table (the first subtag, so `ru-RU` and `nl-BE` land) and fallback links from `PAGES`.
5. Fonts. Two cases:
   - The language's letters are not in Unbounded, Figtree and IBM Plex Mono (Greek, Thai, Devanagari, Arabic, Hebrew, ...): it needs a script family of its own. Add it to `SCRIPT_FONTS` in `tools/build-pages.py` (which also makes `google_fonts_url` load it and `measure-header.py` wait for it); in `src/page.template.html` add `html[lang="xx"]{--script:'Family'}` and put `[lang="xx"]` in the `html:is(...)` list under it, which gives the page its font stacks; in `tools/og.html` add the family's `<link>` and an `html[lang="xx"] .lines` rule. These three places are one table, and the build (`check_script_fonts`) and `make-og.py` (`check_og_fonts`) stop with a message when they disagree.
   - Otherwise (Latin Extended, or a script a family elsewhere in `google_fonts_url` already covers): add the language to the branch of `google_fonts_url(lang)` in `tools/build-pages.py` that picks the body and CJK families, and set `--font-display` and `--font-body` for `html[lang="xx"]` in `src/page.template.html` if it needs its own.
6. Check the rules that name languages, because a new language gets none of them by default:
   - In `src/page.template.html`, the `html[lang=...]` rules set letter spacing, line height and the English hero size.
   - Run `uv run tools/measure-header.py` and commit `src/header-widths.json`: it sets when the header shrinks. If the new language's header needs another order of steps than `default`, add it to `ORDERS` and `LANG_ORDER` in that tool; check the language at phone width.
   - In `tools/build-pages.py`, `image_alt` uses a full-width colon only for `zh-*` and `ja` (the others get `: `), and `fill_text` highlights the number in `speed.h2` only in the forms listed in `HIGHLIGHT_FORMS`: `10×`, `10 倍` (the space is optional), `10 lần`, `10배`, `10 ori`, `10 เท่า`, `10 مرات`, `10 برابر` and `פי 10`. A language that writes "10 times" another way needs its form added there, or the build warns.
   - In `tools/build-pages.py`, `HERO_PHRASES` has one table per language and sets where its hero lines may wrap. The phrases joined with a space must equal the dictionary text, or the build stops. `SPACELESS` lists the languages written without spaces (Japanese), whose phrases are joined with nothing.
   - In the page script of `src/page.template.html`, `NUM_STYLE` sets the decimal mark and the thousands separator of the benchmark table (without an entry the numbers print as `4.1` and `13,371`, and nothing warns you), and `MB` sets the file-size unit (`Mo` for French).
   - A right-to-left language (`"dir": "rtl"`) gets `<html dir="rtl">`, and the page mirrors by itself because the template uses logical properties (`margin-inline-*`, `inset-inline-*`, `text-align: start`, `border-inline-start`). Never write `left`/`right` for something that should mirror. What must not mirror (chart bars, table numbers, file names, the wordmark, the wallet address) is listed in the `RTL` block at the end of the template's CSS. The copy carries no U+200E / U+200F for Latin words in text elements: `isolate_ltr` in `tools/build-pages.py` wraps every run of Latin words (and dates like 2026-11) in `<bdi dir="ltr">` at build time. The values used outside text elements (title and meta, `aria-label`, `alt`, SVG `<text>`, the script's own strings) cannot be isolated by the layout and keep their marks. The share image is mirrored too (`html[dir="rtl"]` in `tools/og.html`).
   - In `src/page.template.html`, the `.dn-addr` font size is lowered for German and Vietnamese so the address stays on one line beside the copy button; check the new language at desktop width.
7. Add `public/screenshots/<slug>/main.png` and `menu.png` with `tools/crop-screenshots.py --new`. Windows and 7-ZSTar should both be in the new language, because the right-click menu shows the system's own text. The one exception is Esperanto: Windows 11 has no Esperanto language pack, so its screenshots are an English Windows with a 7-ZSTar in Esperanto, and the page says so in `a11y.shot_menu`. Until the files exist the page borrows the English ones and `--strict` fails.
8. Rebuild the font subset as in "When the copy changes": the new language's name now appears in the menu on the Simplified Chinese page too. Characters that Noto Sans SC does not have fall back to a system font on that page.

## Fonts

The English, Traditional Chinese, Japanese and the other Latin-script pages load their fonts from Google Fonts: Noto Sans JP on the Japanese page, Noto Sans TC on the others. The Vietnamese page loads Plus Jakarta Sans instead of Figtree, because Figtree has no Vietnamese letters; the Russian and Ukrainian pages load Onest, because Figtree has no Cyrillic; the Korean page loads Noto Sans KR (Unbounded, Figtree and IBM Plex Mono have no Hangul), the way the Japanese page loads Noto Sans JP. Czech, Hungarian, Romanian and Swedish need only Latin Extended letters (ő ű ă ș ț å), which Unbounded, Figtree and IBM Plex Mono all have. Thai, Greek, Hindi, Arabic, Persian and Hebrew have none of them in those three (checked against Google Fonts' unicode-range subsets on 2026-11-10), so those pages add one script family, listed in `SCRIPT_FONTS` in `tools/build-pages.py`: Noto Sans Thai, Noto Sans (Greek), Noto Sans Devanagari, Noto Sans Arabic, Vazirmatn (Persian) and Noto Sans Hebrew. The three original families stay first in the font stack, so Latin letters such as `7z` and `.tar` keep the site's look, and only the letters they lack fall to the script family. The Simplified Chinese page uses the self-hosted files in `public/fonts/` instead, so it makes no request to Google. These fonts are licensed under the SIL Open Font License 1.1; the license texts are the `OFL-*.txt` files in the same directory. The original TTF sources are not kept in this repository. To regenerate the subsets, see "When the copy changes" above.

## License

All rights reserved; this website is not open source. See [LICENSE](LICENSE) for the exceptions (the fonts, and the 7-ZSTar program itself).
