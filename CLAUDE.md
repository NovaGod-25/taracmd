# TaraCmd — working context

Offline revision desk for the UPSC Civil Services Examination. One self-contained HTML
document, built from JSON, shipped two ways: as a page you add to your home screen, and
inside an Android WebView wrapper.

Owner: Satyajit. Personal study tool, not a product.

## How it fits together

```
content/*.json  ─┐
                 ├─►  build.py  ──►  web/taracmd.html              (standalone, PWA)
templates/       ┘                   web/artifact.html             (fragment)
  index.html                         android/…/assets/index.html   (what the APK ships)
```

`templates/index.html` is the app — all the markup, CSS and JS — with eight tokens in it.
`build.py` fills them: six content blobs plus the two derived counts in the search
placeholder. There is **no runtime fetch for app content**; everything is inlined at build
time. Editing JSON then running `python3 build.py` is the whole content workflow.

`build.py` also validates: duplicate topic ids are fatal (progress is keyed on them),
quiz questions must point at real topic ids, answer-key arrays must match the question
count, and an unsubstituted token kills the build. It derives which exams have been sat
from today's date rather than pinning a year.

**All three targets are written by `build.py`.** Do not hand-edit
`android/app/src/main/assets/index.html` — it drifted a full rename behind the web build
once already and shipped an APK with dead branding and a different localStorage key.
`.github/workflows/content.yml` now fails the build if any generated target differs from
what `build.py` produces, which is the guard that was missing.

## Content files

| File | Holds |
|---|---|
| `subjects.json` | 8 subjects → 242 topics → 1,723 subtopics; each topic tagged with papers + weight |
| `pyq-papers.json` | official upsc.gov.in paper links per year — Prelims 22/24, Mains 54/60 |
| `answer-keys.json` | Prelims answer keys: links, marking scheme, dropped questions, set-wise letters |
| `quiz.json` | 35 practice questions, each tagged to a topic id |
| `toppers.json` | 102 published answer copies across 10 publishers |
| `optionals.json` | the Optional tab: Geography and Law, 22/22 papers each 2016–2026, plus curated copies |

## Decisions that should not be quietly reversed

**The app indexes, it does not mirror.** Question papers, answer-key PDFs and toppers'
answer booklets stay on upsc.gov.in and on the publishers' own sites. The app links to
them. This is not squeamishness — the scanned booklets are the coaching institutes'
material, and bundling them turns a personal study tool into a redistribution problem.

A bulk downloader for the topper entries was considered and rejected. Only 11 of the 102
are direct PDFs; the rest sit behind publisher pages, so "download everything" means a
scraper per site against ForumIAS, UnlockIAS, Vision, Vajiram, Insights, NEXT, GS SCORE,
theIAShub and the rest. What exists instead is a **per-copy Save button**: one tap, one
URL, handed to Android's DownloadManager, landing in the app's own folder. No crawler.

**`localStorage` key is `taracmd-v1`.** Changing it orphans everyone's progress, so it
never changes — every field added since is additive and defaulted from `BLANK` on load,
which means a store written by an older build still opens.

| Field | Holds |
|---|---|
| `done` | revision ticks, `topic id -> [subtopic indices]` |
| `theme` | `"dark"`, `"light"`, or null for system |
| `attempts` | OMR answer sheets, keyed `year-paper-set` |
| `revised` | revision history, `topic id -> [epoch ms]` — what the Due filter reads |
| `picks` | practice answers, `question id -> option index` |
| `writing` | Mains and Optional answer log, `year-code -> [{q,mins,words,score,of,note,on}]` |

There is no export bridge function: backup is a copyable blob in a sheet, plus a file
download on web only. That is deliberate — see the four-function contract below.

**The Android page is served over `https://appassets.androidplatform.net/`** via
`WebViewAssetLoader`, not `file:///android_asset/`. A `file://` page has an opaque
origin, which makes `localStorage` unreliable across WebView versions — and the revision
ticks live in `localStorage`. `APP_HOST` in `MainActivity.kt` is a host Google reserves
for this; it never resolves on the network.

**No publisher indexes its toppers' copies by optional subject.** Checked 7 Sep 2026
across Vision, GS SCORE, theIAShub and NEXT IAS: the listings are by rank and name, the
"geography optional" hits are meta-keywords and course menus, and the optional booklet
sits inside a topper's full set rather than being listed on its own. So `copies` in
`optionals.json` is curated by hand and starts empty — the tab links the publishers'
section pages instead. Filling it automatically would need a crawler per site across ten
sites, which is the thing already turned down above. Do not quietly build it.

**The tab bar is `repeat(6,1fr)`** — 63 px a column on a 375 px phone, labels at 9.5 px.
Measured: nothing clips, but a seventh tab would not fit. Fold new surfaces into an
existing tab, the way the Mains answer log went inside Mains.

**upsc.gov.in rate-limits hard.** It stopped answering entirely after roughly 45 requests
in one session. `tools/answer-keys.py` waits 4 seconds between requests on purpose. Any
new scraping should be designed to run locally and unhurried, never in CI.

## The JS ↔ native contract

Four functions, and nothing else crosses. Changing a name on either side breaks it
silently, because the page checks for the bridge before using it and falls back to
browser behaviour when it is absent.

| Direction | Name | Does |
|---|---|---|
| page → native | `AndroidHost.savedPath(url)` | non-null once this PDF is on disk, so the row can read "saved" |
| page → native | `AndroidHost.saveCopy(url)` | one URL to DownloadManager |
| native → page | `window.taracmdSaved()` | a download landed; re-render the Toppers tab |
| native → page | `window.taracmdBack()` | hardware back. Closes sheet → exits subject → returns to Subjects tab → returns `false` so the OS takes over |

## State of the work

The project tree was lost; only the built `taracmd.html` and this file survived. The tree
here was **reconstructed from that build on 25 Aug 2026** and verified byte-for-byte:
`tools/verify-roundtrip.pl` re-minifies `content/*.json`, substitutes the template, and
compares against the surviving page — it matches exactly, all 207,917 characters.

Recovered verbatim: all five content files, and every line of markup, CSS and JS.
Rewritten from this file's description rather than recovered: `build.py`, the whole
Android wrapper, `web/sw.js`, the manifest, the CI workflows and `tools/answer-keys.py`.

Of those, `build.py` has since been run: it reproduces all three committed targets
byte-for-byte, and `tools/check-validation.py` proves each of its checks actually fires.
The page itself was exercised in a browser on a real http origin — ticks persist under
`taracmd-v1`, `taracmdBack()` walks sheet → subject → tab, and ticking from search
results keeps the search.

**Still never executed, and the files to read sceptically: the whole Android wrapper**
(no SDK to hand), `web/sw.js` (registration is untested — the embedded browser had
service workers disabled, though the script parses and serves correctly) and
`tools/answer-keys.py` (its PDF parsing has never met a real key PDF).

Fixed in the session before the loss, all verified in a headless DOM and all present in
the recovered page:

- Android assets written by `build.py` (was shipping stale "UPSC Study Desk" branding
  and the old `upsc-study-desk-v1` storage key)
- Topic sheet closes four ways: × button, swipe the grip, Escape, Android hardware back
- Ticking a subtopic from search results no longer wipes the search (`refreshBehind()`)
- Theme persists to `localStorage`, icon flips moon↔sun, `theme-color` meta follows
- Raster launcher mipmaps for API 24–25 (only `anydpi-v26` existed; minSdk is 24) —
  regenerate with `perl tools/make-icons.pl`
- `restoreState` wired up, `startActivity` guarded against `ActivityNotFoundException`,
  `setAlgorithmicDarkeningAllowed(false)` replaces deprecated `setForceDark`
- PWA offline made real: `web/sw.js` + `web/manifest.webmanifest`, network-first
- Answer-key chips on the Prelims tab (7 official PDFs, 2021–2024, verified live)
- A Quiz tab: OMR self-scoring against the official key, plus an authored practice bank

Also gone with the tree, and not rebuilt: the four `taxonomy-*.json` files. They were
155 KB read by nothing, so their loss cost nothing and open item 3 is closed by default.

Added after the recovery, all exercised in a browser on a real http origin:

- **Revision decay.** A tick said you had read something once; it never said you still
  knew it nine months later. Completing a topic now dates it, and it falls due again at
  3, 7, 21, 60 then 120 days. A "Due" filter per subject, a cross-subject due list off
  the pace strip, and a footer in the topic sheet.
- **Practice answers persist.** They were in a plain `state` object, so a reload threw
  away every answer including the wrong ones. Adds a "Got wrong" queue.
- **Backup.** Copyable blob plus a file download on web. Import merges rather than
  replaces: ticks and dates unioned, local data wins.
- **The exam clock.** Days to the next exam, from the calendar rule at runtime — never
  baked in, since the page is meant to open offline months after it was built. The
  topics-a-day figure hides inside the last 30 days, where it is only an insult.
- **A Mains answer log** per paper: question, minutes, words, marks, and the sentence
  about what went wrong. Essay comes free on a 125/250 scale.

## Open work, in order of leverage

0. **`build.py`'s output depends on the date it runs.** `SAT_BY` decides at build
   time which exam years to inline, so the three generated targets change on their
   own when the calendar crosses a cutoff — no code involved. Seen live: a build on
   25 Aug and a build on 2 Sep differ, which makes `content.yml`'s "was a generated
   target hand-edited?" check fail for nothing. It also bakes the decision into a
   page meant to be opened offline months later, which is the exact argument the
   exam clock avoids by computing at runtime. The fix is to move the hold-back out
   of `build.py` and into the page: inline every year, let the page filter on
   `Date.now()`. That makes the build deterministic and the page honest.
1. **Weight bands do not discriminate.** 145 topics `high`, 96 `medium`, exactly 1 `low`.
   The stripes, the legend and the "High weight" filter are the app's central editorial
   claim and at 60% high they carry almost no signal. Needs an editorial pass through
   `subjects.json` — this is a judgment call about UPSC frequency, not a code change.
2. **Answer keys incomplete.** Every `keys` object is empty, so Quiz → Score a paper
   still says so rather than showing a grid. Seven papers do have URLs (2021–2024), and
   `python3 tools/answer-keys.py extract --dry-run` against those is the way in — it
   needs `pip install pypdf` and it downloads seven PDFs from upsc.gov.in, so run it
   locally and unhurried.
   `discover` will not help for the eleven missing URLs: checked 25 Aug 2026, the
   Commission's answer-key page lists only CDS-II and CAPF keys and no Civil Services
   Prelims at all. Those years are archived off it and need finding by hand.
3. **`gradle-wrapper.jar` is not committed** (binary). Open `android/` in Android Studio
   once, or run `gradle wrapper`, and `./gradlew` starts working. CI sidesteps this by
   installing Gradle directly.
4. Topic notes are not written — the sheet carries the subtopic checklist and the
   frequency read only. Notes slot into the same JSON.
5. `tools/answer-keys.py extract` parses the key PDFs by heuristic; UPSC has changed its
   own table layout between years. Always eyeball `--dry-run` before letting it write.

## Gotchas

- **Always link `www.upsc.gov.in`, never the bare `upsc.gov.in`.** They are separate
  certificates and the bare host's expired on 24 Aug 2026 while `www` runs to 2 November.
  The app's answer-key link and `tools/answer-keys.py` both used the bare host and both
  broke — the link with a certificate warning, the tool with
  `CERTIFICATE_VERIFY_FAILED`. Do not "fix" that by disabling verification.
- **Bump `CACHE` in `web/sw.js` on every deploy** or returning visitors get the cached
  old page.
- `assembleRelease` produces an **unsigned** APK that will not install. CI builds
  `assembleDebug`, signed with the debug key. A real release needs a keystore secret and
  a `signingConfigs` block.
- UPSC publishes answer keys for **Prelims only** — there has never been a Mains key, and
  the Mains tab correctly shows no key chips. Do not "fix" this.
- The page asks Google Fonts for IBM Plex, loaded non-blocking so it never delays first
  paint. Offline it falls back to the system font. The Devanagari family was removed —
  the content has zero Devanagari characters.
- Prelims 2026 papers exist (sat 25 May 2026); Mains 2026 does not until 1 September, and
  `build.py` holds it back automatically via `SAT_BY`. The entry is already in
  `pyq-papers.json` with null URLs, waiting for the date.
- The Android package is `com.taracmd.app`. Not `in.taracmd.*` — `in` is a Kotlin hard
  keyword and cannot be a package segment without backticks.
- **On Windows the command is `python` or `py`, not `python3`.** The python.org installer
  never creates a `python3.exe` — only the Microsoft Store build does. So `python3` keeps
  resolving to the WindowsApps stub, which is not Python and reports "Python was not
  found" however many times you install the real thing. Either use `py build.py`, or turn
  the alias off under Settings → Apps → Advanced app settings → App execution aliases.
  The `python3` in the commands below is written for CI, which runs on Ubuntu.

## Commands

```bash
python3 build.py                            # rebuild all three targets
python3 tools/check-validation.py           # prove build.py's validation still fires
python3 tools/pyq-papers.py discover        # fill in missing question-paper URLs
python3 tools/pyq-papers.py optionals       # rebuild the Optional tab paper lists
python3 tools/answer-keys.py discover       # find answer-key PDFs still missing
python3 tools/answer-keys.py extract --dry-run   # read Set A/B/C/D letters, print only
perl tools/make-icons.pl                    # regenerate the API 24–25 launcher rasters
cd android && ./gradlew assembleDebug       # local APK, needs Android SDK + wrapper
```

```bash
perl tools/serve.pl 8787                    # serve web/ on a real http origin
```

Needed because `localStorage` is disabled on a `file://` or `data:` page — the same
opaque-origin problem the Android build dodges with `appassets.androidplatform.net`. Open
`web/taracmd.html` straight off disk and the revision ticks silently do not persist.

One-off recovery tools, kept for provenance and not part of the build:

```bash
perl tools/extract-from-build.pl <taracmd.html>   # tree ← built page
perl tools/verify-roundtrip.pl <taracmd.html>     # prove the tree rebuilds that page
perl tools/verify-roundtrip.pl <taracmd.html> --emit   # write the targets without Python
```
