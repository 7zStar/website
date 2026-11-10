#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright==1.55.0"]
# ///
"""Measure where the narrow header of every language page changes step, and write src/header-widths.json.

The header shrinks in five steps as the window narrows (what each does: tools/build-pages.py, near
WIDTH_KEYS, and the "@media" blocks of src/page.template.html):

    w_short     the language button shows its short name
    w_narrow    the third link (source) is dropped and the wordmark gets smaller
    w_icons     the download and screenshot links become icons
    w_wordmark  the wordmark is hidden
    w_globe     the language button keeps only the globe

Each number is the widest window, in media-query px, at which that step applies (the step is on when the
window is at most that wide). The ORDER in which the steps happen is a design decision per language (English
links are long, so English drops the third link first and swaps the links for icons early; Chinese links are
short, so Chinese hides the wordmark first and switches to icons last). It is the table ORDERS below, one
order per kind of language; the tool measures the numbers for that order:

  1. Build the language page with impossible sentinel widths (9001..9005) in its five media queries, then
     switch each step on or off from script by rewriting those queries (so the page's own CSS is what is
     measured, and nothing is copied).
  2. The browser is Edge with its REAL classic scrollbar (15px; headless mode normally hides it), because
     media queries count the scrollbar and the page's padding changes at a media-query width (480px), so
     the layout width and the query width are not a fixed 15px apart in every window. The page is also made
     2px narrower than that (html margin), which is what Firefox's 17px scrollbar does: every number holds
     in both. (A phone's overlay scrollbar takes no room, which only makes the header roomier.)
  3. fits(state set, W): in a W px wide window the header is one row, nothing wraps inside it, no item is
     squeezed below its own width (the language button must not shrink), no item overlaps its neighbour,
     and the last item ends inside the page padding.
  4. min_width(state set): the smallest W (300..1100) from which fits() stays true all the way up. Binary
     search, then every width up to 100px above the answer is checked, because "fits" is not monotonic
     (below 480px the padding shrinks from 24px to 18px, so a header can fit at 480px and not at 483px).
  5. Walk the order. A step's number is that smallest W of the steps before it, minus 1. A step that does
     not make the header narrower is a PROBLEM (the order is wrong for that language): the tool prints it,
     writes nothing and exits 1. The one exception is a step that comes after the header already fits at
     300px, the lowest width tested; it is kept (its number is then 299, so it never applies) and noted.

Greedy order (at each step the one that makes the header narrowest) is printed as a suggestion with
--explain; it is not what the site uses, because it would hide the wordmark before shortening the button.

The file also records, per language, a fingerprint of what the numbers depend on (nav labels, language
button text, header CSS and font rules, font files; build-pages.py header_inputs). `build-pages.py --strict`
fails when it no longer matches, so numbers measured before a label or the CSS changed cannot ship.

Fonts matter (Unbounded, Figtree, Noto Sans, ...): the pages load them from Google Fonts, so this needs an
internet connection, and the tool refuses to measure with fallback fonts. It uses the locally installed
Edge, like tools/make-og.py, and opens one headless window at a time.

Usage: uv run tools/measure-header.py                 measure all languages and write src/header-widths.json
       uv run tools/measure-header.py --check         measure, compare with the file, change nothing (exit 1 if different)
       uv run tools/measure-header.py --lang en ja    only these languages (merged into the file)
       uv run tools/measure-header.py --explain       also print the smallest width of the steps tried
       uv run tools/measure-header.py --verify DIR    check the file on the real pages, in two rounds (with a classic
                                                      scrollbar, and without): for every step the window N px wide
                                                      (step on) and N+1 px wide (step off), a screenshot of each, and
                                                      DIR/report.md. Exit 1 if any check fails.
"""
import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "header-widths.json"
KEYS = ("w_short", "w_narrow", "w_icons", "w_wordmark", "w_globe")  # also the tie-break order
SENTINEL = {k: 9001 + i for i, k in enumerate(KEYS)}
# A step that only makes sense once another one is on: the icon rule also hits the third link, which has no
# icon and is hidden by w_narrow first; the globe-only button hides the short name that w_short shows.
REQUIRES = {"w_icons": "w_narrow", "w_globe": "w_short"}
SCROLLBAR = 15       # what Edge's classic scrollbar takes from the window
FIREFOX_EXTRA = 2    # Firefox's is 17px: measure with the page this much narrower still

# The order in which the five steps switch on, per kind of language. Orders the site shipped with until
# 2026-11-09 (the hand-written table this tool replaced); "default" is also what every new language starts with.
ORDERS = {
    "default": ["w_narrow", "w_short", "w_icons", "w_wordmark", "w_globe"],       # en, de, fr, es, pt-BR and the batch-1 languages
    "zh": ["w_narrow", "w_short", "w_wordmark", "w_globe", "w_icons"],            # short links stay text, icons last
    "short-first": ["w_short", "w_narrow", "w_icons", "w_wordmark", "w_globe"],    # vi, eo, ja: the language button shortens first
}
LANG_ORDER = {"zh-Hant": "zh", "zh-Hans": "zh", "vi": "short-first", "eo": "short-first", "ja": "short-first"}
MEDIA_RULES = 6  # w_narrow owns two media queries, the other four one each
LOWEST, HIGHEST = 300, 1100  # below 300 the header wraps on purpose (page.template.html: min-width:300px)

spec = importlib.util.spec_from_file_location("build_pages", ROOT / "tools" / "build-pages.py")
build_pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_pages)

# Page-side helpers. setSteps(list of keys) switches the five steps on exactly as listed; setExtra(px) makes
# the page that much narrower (a wider scrollbar) without touching the media-query width.
SETUP = """
(sentinel) => {
  const byWidth = {}; for (const [k, v] of Object.entries(sentinel)) byWidth[v] = k;
  window.__rules = [];
  for (const sheet of document.styleSheets) {
    let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
    for (const rule of rules) {
      if (!(rule instanceof CSSMediaRule)) continue;
      const m = rule.media.mediaText.match(/max-width:\\s*(\\d+)px/);
      if (m && byWidth[m[1]]) window.__rules.push({ rule, key: byWidth[m[1]], text: rule.media.mediaText });
    }
  }
  /* No item may be squeezed below its own width: the language button would otherwise shrink (its name is
     cut short with an ellipsis) and the header would look like it fits long after the design says it does */
  const st = document.createElement('style');
  st.textContent = '.top .wrap > *, .tools > * { flex-shrink: 0 !important; }';
  document.head.appendChild(st);
  window.setSteps = (on) => {
    for (const r of window.__rules)
      r.rule.media.mediaText = r.text.replace(/\\(max-width:\\s*\\d+px\\)/, on.includes(r.key) ? '(min-width: 0px)' : '(max-width: 0px)');
  };
  return window.__rules.length;
}
"""

EXTRA = """
(px) => {
  let st = document.getElementById('x-extra');
  if (!st) { st = document.createElement('style'); st.id = 'x-extra'; document.head.appendChild(st); }
  st.textContent = px ? 'html { margin-right: ' + px + 'px; }' : '';
}
"""

LOOK = """
  const look = () => {
    const wrap = document.querySelector('.top .wrap');
    const cw = document.documentElement.clientWidth;
    const kids = [...wrap.children];
    const rects = kids.map(k => k.getBoundingClientRect());
    const pad = parseFloat(getComputedStyle(wrap).paddingRight);
    const why = [];
    if (new Set(rects.map(r => Math.round(r.top))).size > 1) why.push('wrapped');
    for (let i = 0; i + 1 < rects.length; i++) if (rects[i].right > rects[i + 1].left + 0.5) why.push('overlap');
    if (rects[rects.length - 1].right > wrap.getBoundingClientRect().right - pad + 0.5) why.push('overflow');
    for (const k of kids) if (k.scrollWidth > k.clientWidth + 1) why.push('clipped ' + k.className);
    const links = [...document.querySelectorAll('.nav a')].filter(a => getComputedStyle(a).display !== 'none');
    if (new Set(links.map(a => Math.round(a.getBoundingClientRect().top))).size > 1) why.push('nav wrapped');
    if (document.documentElement.scrollWidth > cw) why.push('page scrolls sideways');
    return why.join(',');
  };
"""

FITS = """
async () => {""" + LOOK + """
  let result = look();
  /* A letter the header shows for the first time (the short language name, say) makes the browser fetch one more
     slice of a web font; measure again once everything has arrived, or the numbers would depend on timing */
  while (document.fonts.status === 'loading') { await document.fonts.ready; result = look(); }
  return result;
}
"""

# What the header looks like in the real page (real widths, no script-switched steps). The five flags say which
# steps the page's own media queries have switched on at this window width.
STATE = """
() => {""" + LOOK + """
  const shown = (sel) => { const e = document.querySelector(sel); return !!e && getComputedStyle(e).display !== 'none'; };
  const flags = {
    w_short: getComputedStyle(document.querySelector('.lang-name')).position === 'absolute',  /* the full name is clipped away; the short word itself is hidden again by w_globe */
    w_narrow: !shown('.nav a:not(.nav-dl):not(.nav-shots)'),
    w_icons: shown('.nav-ico'),
    w_wordmark: !shown('.brand .wordmark'),
    w_globe: !shown('.lang-caret'),
  };
  const lang = document.querySelector('.tools .lang');
  const real = lang.getBoundingClientRect().width;
  const st = document.createElement('style');
  st.textContent = '.top .wrap > *, .tools > * { flex-shrink: 0 !important; }';
  document.head.appendChild(st);
  const natural = lang.getBoundingClientRect().width;
  const why = look();
  st.remove();
  return { flags, why, squeezed: real < natural - 0.5 };
}
"""


class Measurer:
    def __init__(self, page, lang: str):
        self.page, self.lang, self.cache, self.probes = page, lang, {}, 0

    def fits(self, on: tuple, width: int) -> bool:
        self.probes += 1
        return self.why(on, width) == ""

    def why(self, on: tuple, width: int) -> str:
        self.page.set_viewport_size({"width": width, "height": 900})
        self.page.evaluate("(on) => setSteps(on)", list(on))
        return self.page.evaluate(FITS)

    def min_width(self, on: tuple) -> int:
        key = tuple(sorted(on))
        if key in self.cache:
            return self.cache[key]
        if self.fits(key, LOWEST):
            result = LOWEST
        else:
            if not self.fits(key, HIGHEST):
                raise SystemExit(f"[{self.lang}] header does not fit even at {HIGHEST}px with steps {key}: {self.why(key, HIGHEST)}")
            lo, hi = LOWEST, HIGHEST  # fits(lo) is False, fits(hi) is True
            while hi - lo > 1:
                mid = (lo + hi) // 2
                lo, hi = (lo, mid) if self.fits(key, mid) else (mid, hi)
            result = hi
            # "Fits" is not monotonic in the window width (see the docstring, step 4): the step must already
            # be on at the widest window where the header fails, so move the answer past every failure within
            # 100px; then spot-check farther up.
            for width in range(result + 1, result + 101):
                if not self.fits(key, width):
                    result = width + 1
            for extra in (1, 2, 5, 10, 20, 40, 80):
                if not self.fits(key, result + extra):
                    raise SystemExit(f"[{self.lang}] header fit is not monotonic with steps {key}: fits at {result}, "
                                     f"not at {result + extra} ({self.why(key, result + extra)})")
        self.cache[key] = result
        return result

    def walk(self, steps: list[str]) -> tuple[list[int], list[str], list[str]]:
        """(smallest window the steps before each step fit in, problems, notes) for the steps switched on in this order"""
        on: tuple = ()
        floors, problems, notes = [], [], []
        for step in steps:
            need = REQUIRES.get(step)
            if need and need not in on:
                raise SystemExit(f"[{self.lang}] order {steps}: {step} needs {need} before it")
            before = self.min_width(on)
            floors.append(before)
            after = self.min_width(on + (step,))
            if after > before or (after == before and before > LOWEST):
                problems.append(f"{step} does not make the header narrower ({before}px before, {after}px after)")
            elif before == LOWEST:
                notes.append(f"{step} is not needed: the header already fits at {LOWEST}px without it (its number is {LOWEST - 1}, "
                             "so it never applies)")
            on += (step,)
        return floors, problems, notes

    def greedy(self) -> list[str]:
        on: tuple = ()
        while len(on) < len(KEYS):
            options = {k: self.min_width(on + (k,)) for k in KEYS if k not in on and REQUIRES.get(k, k) in on + (k,)}
            on += (min(options, key=lambda k: (options[k], KEYS.index(k))),)
        return list(on)


def page_folder(lang: str) -> Path:
    folder = ROOT / "public" / f"_measure-{build_pages.PAGES[lang]['slug']}"
    folder.mkdir(exist_ok=True)
    return folder


def measure(browser, lang: str, template: str, i18n: dict, want_greedy: bool) -> tuple[dict, dict, dict]:
    folder = page_folder(lang)
    try:
        html = build_pages.build_page(template, i18n, lang, widths=SENTINEL)
        (folder / "index.html").write_text(html, encoding="utf-8", newline="\n")
        page = browser.new_page(viewport={"width": 1000, "height": 900})
        try:
            page.goto((folder / "index.html").as_uri(), wait_until="load")
            found = page.evaluate(SETUP, SENTINEL)
            if found < MEDIA_RULES:
                raise SystemExit(f"[{lang}] found {found} of the {MEDIA_RULES} step media queries in the page; did the template change?")
            wait_for_fonts(page, lang, sentinel=True)
            page.evaluate(EXTRA, FIREFOX_EXTRA)
            prewarm(page)
            bar = page.evaluate("window.innerWidth - document.documentElement.clientWidth")
            if bar != SCROLLBAR:
                raise SystemExit(f"[{lang}] the browser's scrollbar takes {bar}px, expected {SCROLLBAR}: the page must be "
                                 "taller than the window and the scrollbars must not be hidden")
            m = Measurer(page, lang)
            kind = LANG_ORDER.get(lang, "default")
            steps = ORDERS[kind]
            floors, problems, notes = m.walk(steps)
            numbers = {step: floor - 1 for step, floor in zip(steps, floors)}
            details = {"order": steps, "kind": kind, "narrowest_window_before_each_step": floors,
                       "narrowest_window_with_all_steps": m.min_width(tuple(KEYS))}
            return {k: numbers[k] for k in KEYS}, details, {"problems": problems, "notes": notes, "probes": m.probes,
                                                           "greedy": m.greedy() if want_greedy else None}
        finally:
            page.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def verify(browser, scrollbar: bool, lang: str, template: str, i18n: dict, widths: dict, out: Path) -> list[dict]:
    """Open the real page of `lang` (the widths in src/header-widths.json, nothing forced from script) and, for
    each of the five steps, look at the window N px wide (the step is on) and N+1 px wide (it is off): the header
    must be one row without overflow, the language button must not be squeezed, and the five steps must be on or
    off exactly as the numbers say. With a classic scrollbar the N+1 window is also looked at 2px narrower
    (Firefox's 17px scrollbar). A screenshot of the top 80px of each window is saved."""
    folder = page_folder(lang)
    rows = []
    try:
        html = build_pages.build_page(template, i18n, lang, widths=widths)
        (folder / "index.html").write_text(html, encoding="utf-8", newline="\n")
        page = browser.new_page(viewport={"width": 1000, "height": 900})
        try:
            page.goto((folder / "index.html").as_uri(), wait_until="load")
            wait_for_fonts(page, lang)
            tests = []
            for key in KEYS:
                tests.append((key, widths[key], True, 0))
                tests.append((key, widths[key] + 1, False, 0))
                if scrollbar:
                    tests.append((key, widths[key] + 1, False, FIREFOX_EXTRA))
            for key, width, expect_on, extra in tests:
                if width < LOWEST:
                    continue  # the step never applies at 300px or more; only its "off" side is looked at
                page.evaluate(EXTRA, extra)
                page.set_viewport_size({"width": width, "height": 900})
                page.wait_for_timeout(150)
                page.evaluate("document.fonts.ready")
                state = page.evaluate(STATE)
                wrong = [k for k in KEYS if state["flags"][k] != (width <= widths[k])]
                problems = []
                if state["why"]:
                    problems.append(state["why"])
                if state["squeezed"]:
                    problems.append("language button squeezed")
                if wrong:
                    problems.append("steps in the wrong state: " + ",".join(wrong))
                if state["flags"][key] != expect_on:
                    problems.append(key + " should be " + ("on" if expect_on else "off"))
                tag = "-ff17" if extra else ""
                image = out / lang / f"{key}-{width}{tag}.png"
                image.parent.mkdir(parents=True, exist_ok=True)
                if not extra:
                    page.screenshot(path=image, clip={"x": 0, "y": 0, "width": width, "height": 80})
                rows.append({"key": key, "width": width, "on": expect_on, "extra": extra, "ok": not problems,
                             "problems": problems, "image": f"{lang}/{image.name}" if not extra else ""})
        finally:
            page.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return rows


def write_report(out: Path, widths: dict, results: dict, drafts: dict, notes: dict) -> int:
    """results[mode][lang] = rows. Returns how many checks failed."""
    lines = ["# Header breakpoints, checked in headless Edge", "",
             "Each language, each of the five header steps, at the step's number N (the step is on) and at N+1 (it is off).",
             "A check is OK when the header is one row, nothing overflows, wraps or is clipped, the language button is not "
             "squeezed, and all five steps are on or off exactly as `src/header-widths.json` says.", "",
             "- **scrollbar** round: Edge with its real classic scrollbar (15px), like a desktop browser. It also looks at "
             "N+1 with the page 2px narrower, which is what Firefox's 17px scrollbar does (`N+1 ff17`, no screenshot).",
             "- **no scrollbar** round: the same pages with the scrollbar hidden, like a phone or a Mac with overlay scrollbars.",
             "- Screenshots are the top 80px of the window, named `<round>/<lang>/<step>-<width>.png`.", ""]
    bad = 0
    head = ["| language | " + " | ".join(KEYS) + " | scrollbar | no scrollbar |", "|---|" + "---|" * (len(KEYS) + 2)]
    detail = []
    for lang in widths:
        cells = []
        for mode in ("scrollbar", "noscrollbar"):
            rows = results[mode][lang]
            failed = [r for r in rows if not r["ok"]]
            bad += len(failed)
            cells.append(f"{len(rows) - len(failed)}/{len(rows)} OK" if not failed else f"**{len(failed)} of {len(rows)} FAILED**")
        head.append(f"| {lang}{' (draft)' if lang in drafts else ''} | " + " | ".join(str(widths[lang][k]) for k in KEYS)
                    + f" | {cells[0]} | {cells[1]} |")
        detail.append(f"### {lang}" + (" (draft copy: measure again once the final copy is in)" if lang in drafts else ""))
        for note in notes.get(lang, []):
            detail.append(f"- note: {note}")
        for mode in ("scrollbar", "noscrollbar"):
            detail.append(f"- {mode}")
            detail.append("")
            detail.append("| step | window | step should be | result |")
            detail.append("|---|---|---|---|")
            for r in results[mode][lang]:
                shot = f" ([png]({mode}/{r['image']}))" if r["image"] else ""
                label = f"{r['width']}{' (ff17)' if r['extra'] else ''}"
                detail.append(f"| {r['key']} | {label} | {'on' if r['on'] else 'off'} | "
                              + ("OK" if r["ok"] else "FAILED: " + "; ".join(r["problems"])) + shot + " |")
            detail.append("")
    total = sum(len(rows) for mode in results.values() for rows in mode.values())
    lines += head + ["", "Languages marked (draft) use placeholder or first-draft copy for their navigation labels, so their numbers "
                         "must be measured again when the final copy is in.", "",
                     f"Checks made: {total}, failed: {bad}.", ""] + detail
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return bad


def prewarm(page) -> None:
    """Show every step combination once, so that every web font slice the header can need is fetched
    before the numbers are taken."""
    for mask in range(1 << len(KEYS)):
        on = [k for i, k in enumerate(KEYS) if mask >> i & 1]
        for width in (320, 520, 760, 1000):
            page.set_viewport_size({"width": width, "height": 900})
            page.evaluate("(on) => setSteps(on)", on)
            page.evaluate(FITS)
    page.evaluate("document.fonts.ready")


def wait_for_fonts(page, lang: str, sentinel: bool = False) -> None:
    """Wait until the body font and Unbounded are loaded from Google Fonts. document.fonts.check() would
    say yes while the stylesheet has not even arrived, so look for loaded FontFace objects instead.
    Google answers a request now and then too slowly in a long run, so the page is reloaded once before the
    tool gives up (it never goes on with fallback fonts). sentinel: the page was set up by SETUP, redo that."""
    body = page.evaluate("getComputedStyle(document.body).fontFamily.split(',')[0].trim().replace(/['\\\"]/g, '')")
    # zh-Hans loads its fonts from public/fonts/zh-hans.css instead of Google
    wanted = ["Noto Sans SC"] if lang == "zh-Hans" else ["Unbounded", body]
    for attempt in (1, 2):
        try:
            page.wait_for_function(
                """(wanted) => wanted.every(w => [...document.fonts].some(f => f.family.replace(/['"]/g, '') === w && f.status === 'loaded'))""",
                arg=wanted, timeout=30000)
            break
        except PlaywrightTimeoutError:
            if attempt == 2:
                raise SystemExit(f"[{lang}] the fonts {wanted} did not load in 30s, twice (no internet?); measuring with "
                                 "fallback fonts would give wrong numbers") from None
            try:
                page.reload(wait_until="load")
                if sentinel:
                    found = page.evaluate(SETUP, SENTINEL)
                    if found < MEDIA_RULES:
                        raise SystemExit(f"[{lang}] after reloading the page only {found} of the {MEDIA_RULES} step media "
                                         "queries were found")
            except PlaywrightError as error:
                raise SystemExit(f"[{lang}] reloading the page after the slow fonts failed: {error}") from None
    page.evaluate("document.fonts.ready")


def launch(p, scrollbar: bool):
    """Edge, headless. Headless hides scrollbars by default; asking for them back gives the real 15px one."""
    return p.chromium.launch(channel="msedge", headless=True,
                             ignore_default_args=["--hide-scrollbars"] if scrollbar else None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="compare with src/header-widths.json, write nothing")
    parser.add_argument("--lang", nargs="*", help="only these languages (default: all in PAGES)")
    parser.add_argument("--explain", action="store_true", help="print the smallest width of every step tried")
    parser.add_argument("--verify", type=Path, metavar="DIR",
                        help="do not measure: check src/header-widths.json on the real pages at N and N+1 of every step, "
                             "with and without a classic scrollbar; save screenshots and report.md in DIR (exit 1 if any check fails)")
    args = parser.parse_args()
    langs = args.lang or list(build_pages.PAGES)
    for lang in langs:
        if lang not in build_pages.PAGES:
            raise SystemExit(f"unknown language {lang}; PAGES has {list(build_pages.PAGES)}")
    i18n = json.loads((ROOT / "src" / "i18n.json").read_text(encoding="utf-8"))
    build_pages.APP_LANGS.update(build_pages.load_app_languages())
    template = (ROOT / "src" / "page.template.html").read_text(encoding="utf-8")
    if args.verify:
        table = {lang: row for lang, row in build_pages.load_header_widths().items() if lang in langs}
        missing = [lang for lang in langs if lang not in table]
        if missing:
            raise SystemExit(f"src/header-widths.json has no numbers for {missing}; run tools/measure-header.py first")
        drafts = build_pages.draft_languages(i18n)
        stored = json.loads(OUT.read_text(encoding="utf-8")).get("_measured", {})
        notes = {lang: stored.get(lang, {}).get("notes", []) for lang in table}
        results = {"scrollbar": {}, "noscrollbar": {}}
        with sync_playwright() as p:
            for mode in results:
                browser = launch(p, mode == "scrollbar")
                try:
                    for lang in table:
                        rows = verify(browser, mode == "scrollbar", lang, template, i18n, table[lang], args.verify / mode)
                        results[mode][lang] = rows
                        failed = [r for r in rows if not r["ok"]]
                        shown = f"all {len(rows)} OK" if not failed else "; ".join(
                            f"{r['key']}@{r['width']}{'(ff17)' if r['extra'] else ''} {r['problems']}" for r in failed)
                        print(f"{mode:11} {lang:8} {shown}", flush=True)
                finally:
                    browser.close()
        bad = write_report(args.verify, table, results, drafts, notes)
        print("wrote", args.verify / "report.md", f"({bad} failed)")
        return 1 if bad else 0
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() else {}
    result = {k: v for k, v in old.items() if not k.startswith("_")}
    details_all = dict(old.get("_measured", {}))
    inputs = dict(old.get("_inputs", {}))
    hard_problems = False
    with sync_playwright() as p:
        browser = launch(p, True)
        try:
            for lang in langs:
                numbers, details, extra = measure(browser, lang, template, i18n, args.explain)
                details["notes"] = extra["notes"]
                result[lang], details_all[lang] = numbers, details
                inputs[lang] = build_pages.header_inputs(lang, i18n[lang], template)
                print(f"{lang:8} " + "  ".join(f"{k}={numbers[k]}" for k in KEYS) + f"   order ({details['kind']}): "
                      + " > ".join(details["order"]) + f"   ({extra['probes']} probes)", flush=True)
                for note in extra["notes"]:
                    print(f"           note: {note}")
                for problem in extra["problems"]:
                    print(f"           PROBLEM: {problem}")
                    hard_problems = True
                if args.explain:
                    print(f"           smallest window before each step: {details['narrowest_window_before_each_step']}, "
                          f"with every step: {details['narrowest_window_with_all_steps']}; greedy order would be "
                          + " > ".join(extra["greedy"]))
        finally:
            browser.close()
    if hard_problems:
        print("PROBLEMS found: src/header-widths.json was NOT written; fix the order in ORDERS or the header CSS.")
        return 1
    ordered = {lang: result[lang] for lang in build_pages.PAGES if lang in result}
    data = {"_note": "Written by tools/measure-header.py (headless Edge with a real scrollbar, fonts from Google Fonts); do not edit "
                     "by hand. Each w_ number is the widest window, in media-query px, at which that header step applies. "
                     "_measured gives the order of the steps and the smallest window each step before it fits in; _inputs is "
                     "a fingerprint of the labels, CSS and fonts the numbers were measured with (build-pages.py --strict "
                     "fails when it no longer matches).",
            **ordered,
            "_measured": {lang: details_all[lang] for lang in build_pages.PAGES if lang in details_all},
            "_inputs": {lang: inputs[lang] for lang in build_pages.PAGES if lang in inputs}}
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        same = all(old.get(lang) == data.get(lang) and old.get("_inputs", {}).get(lang) == data["_inputs"].get(lang) for lang in langs)
        print("src/header-widths.json " + ("matches the measurement" if same else "DIFFERS from the measurement"))
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print("wrote", OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
