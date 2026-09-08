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

`templates/index.html` is the app — all the markup, CSS and JS — with nine tokens in it.
`build.py` fills them: seven content blobs plus the two derived counts in the search
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

## The syllabus tab

The first tab **is** the syllabus, not a menu in front of it. It used to be eight cards
leading to a per-subject list leading to a modal, which meant the 1,723 subtopics — the
actual syllabus — could only be seen eight at a time, one topic at a time, 242 modals
deep. Now it is one page: groups open in place, topics open in place, and every subtopic
is its own tick target.

Two lenses over the same 242 topics, and this is the point of the tab rather than a
gimmick: **240 of the 242 carry more than one paper tag**, so `By subject` (how the
material is taught) and `By paper` (how the Commission sets it — Prelims 235, GS-I 69,
GS-II 82, GS-III 147, GS-IV 5, Essay 28) really are different shapes of one syllabus.
Anything that regroups topics must keep every topic: `tests/` checks the paper lens holds
exactly the topics tagged for each paper.

Things that will bite:

- **`state.open` and `state.openTopics` are Sets, and they are not persisted.** They are
  view state, not progress; `taracmd-v1` never sees them. Back collapses them before it
  leaves the tab, which is the middle rung of the `taracmdBack()` ladder.
- **Ticking re-renders, so it must not lose your place.** `refreshBehind()` restores the
  scroll position and any live search. Toggling a group goes through it for that reason;
  `render()` scrolls to the top and would throw you back up a 242-topic page.
- **Progress is two numbers, never one.** Topics finished and subtopics ticked say
  different things and a single percentage hides which you mean.
- The topic sheet still exists and still owns revision — `Open · mark revised` in an
  expanded topic. Reading moved into the page; revision did not.
- `Read it all` renders the whole syllabus flat with no controls, and is what `@media
  print` prints. The app is one file, so printing is a stylesheet rather than an export.

## Content files

| File | Holds |
|---|---|
| `subjects.json` | 8 subjects → 242 topics → 1,723 subtopics; each topic tagged with papers + weight |
| `pyq-papers.json` | official upsc.gov.in paper links per year — Prelims 22/24, Mains 54/60 |
| `answer-keys.json` | Prelims answer keys: links, marking scheme, dropped questions, set-wise letters |
| `quiz.json` | 35 practice questions, each tagged to a topic id |
| `toppers.json` | 102 published answer copies across 10 publishers |
| `daily.json` | daily current-affairs quiz sources: a URL pattern the page expands against the date |
| `optionals.json` | the Optional tab: Geography, Law and Agriculture, 22/22 papers each 2016–2026, plus curated copies |

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
| `daily` | daily quiz log, `YYYY-MM-DD -> {score,of,src}` — what the streak counts |

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

Seven functions, and nothing else crosses. Changing a name on either side breaks it
silently, because the page checks for the bridge before using it and falls back to
browser behaviour when it is absent.

| Direction | Name | Does |
|---|---|---|
| page → native | `AndroidHost.savedPath(url)` | non-null once this PDF is on disk, so the row can read "saved" |
| page → native | `AndroidHost.saveCopy(url)` | one URL to DownloadManager |
| native → page | `window.taracmdSaved()` | a download landed; re-render the Toppers tab |
| page → native | `AndroidHost.focusStart(mins)` | pin the screen and hold it awake for a focus session |
| page → native | `AndroidHost.focusState()` | `"locked"` or `"awake"` — what the OS actually granted, which the page trusts over `focusStart`'s return |
| page → native | `AndroidHost.focusStop()` | unpin, let the screen sleep again |
| native → page | `window.taracmdBack()` | hardware back. Closes sheet → refuses while a focus session runs → collapses the outline → returns to the Syllabus tab → returns `false` so the OS takes over |

### What the focus lock can and cannot do

`startLockTask()` from an ordinary app is **screen pinning**: Home and Recents stop
working and the page refuses Back. **Android always keeps one way out — holding Back and
Overview together — and no ordinary app may remove it.** That is deliberate on Android's
part and deliberate here: a phone that cannot be unlocked for ninety minutes is a phone
you cannot call an ambulance with. The tab says so rather than promising a cage.

For a lock with genuinely no way out the app has to be whitelisted by a **device owner**.
Same `startLockTask()` call; the provisioning is what upgrades it. On a factory-reset
device with no account added:

```bash
adb shell dpm set-device-owner com.taracmd.app/.AdminReceiver
```

That needs a `DeviceAdminReceiver` and a policy XML, neither of which exists here — it is
written down as the route, not as something already built.

Two things the page must keep honest, both easy to get wrong:

- `focusStart` posts `startLockTask` to the UI thread and cannot know whether it landed,
  so the mode shown comes from `focusState()` on the next render. **Never let the page
  claim a stronger lock than it has.**
- The pin does not survive the activity being recreated, but the session does — it lives
  in `localStorage`, because the app is pinned for an hour and the OS may reclaim it. On
  boot the page re-asks for the pin and reopens the Focus tab; otherwise the clock would
  run on with nothing actually holding the phone.

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

## Tests

`tests/` holds behaviour tests for the app itself, run by `node --test` against
**`web/taracmd.html`** — the built file, not the template, because that is what a phone
opens. jsdom is the only dependency.

```bash
npm --prefix tests ci      # once
npm --prefix tests test
```

They cover the parts where a silent wrong answer is worse than a crash: the runtime
exam-year filter, the widening revision-decay schedule, the union-not-replace merge that
restoring a backup depends on, `esc()`, and the exam clock. `content.yml` runs them on
every push.

Note the shape they had to be written to: **ticks are stored as numeric subtopic
indices**, not ids — `toggleSub` pushes `+dataset.i`. The first draft of these tests used
string ids, passed the length checks anyway, and only failed on the merge, where
`uniqSort`'s numeric comparator returns `NaN` for strings. The test was wrong, not the
app, but the shape is easy to get wrong twice.

## Open work, in order of leverage

1. **Weight bands do not discriminate.** 145 topics `high`, 96 `medium`, exactly 1 `low`.
   The stripes, the legend and the "High weight" filter are the app's central editorial
   claim and at 60% high they carry almost no signal. Needs an editorial pass through
   `subjects.json` — this is a judgment call about UPSC frequency, not a code change.
2. **Answer keys: 2022 GS-I is in, six papers to go.** Quiz → Score a paper works, for
   that one paper. Punch in a sheet, pick your Series, and it scores against the
   Commission's own letters on the Commission's own scheme.
   The other six are the work. `extract` cannot do them and never could: **every key
   the Commission publishes is a scan** — four pages, one per Series, a photograph of a
   printed grid, not one character of text in any of the 28 pages. It now says so
   instead of blaming its own regex.
   How 2022 GS-I was actually read, because the method is the reusable part:
   read off the scan by eye, then verified structurally. **UPSC builds the four Series
   by shuffling the same ten ten-question blocks**, so every block in Set A reappears
   intact in B, C and D. That makes each letter effectively read four times. All 301
   single-letter mutations of Set A break the property, so a misreading cannot survive
   it — and `tests/` now pins the property, so it guards the data permanently. The
   `dropped_count` printed on each page is a second, independent check.
   OCR also works and is proven, if a general reader is wanted: deskew (the scans sit up
   to 1.8° off square, which smears every rule and defeats projection), take the cell
   grid from the table's own printed rules rather than an assumed pitch (pitch drifts,
   and drift silently reads the wrong row near the bottom of a column), then read each
   cell with several tesseract modes and vote. On 2022 GS-I Set A that read 100 of 100
   and agreed with the eye on every one. What defeated it was **finding the table** on
   the other scans: they run 2,481×3,507 to 9,992×14,096 pixels, and run-length and
   projection heuristics both fail across that range. Morphological line extraction is
   the approach to try next, not more tuning of the current one.
   **Schema, worth knowing before adding a paper.** `X` is a valid key letter — it is
   the Commission's own mark for a dropped question — and it falls at a *different
   number in each Series*: 2022 GS-I dropped one, at 61 in A, 71 in B, 31 in C, 11 in D.
   The old per-paper `dropped` list could not express that and is gone; the page reads
   droppedness off the letters of the set you sat.
   Eleven papers still have no URL at all. `discover` will not help: checked 25 Aug 2026,
   the Commission's answer-key page lists only CDS-II and CAPF keys and no Civil Services
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
- Every exam year is inlined, including ones not sat yet; the **page** hides them, via
  `satOn()` next to `renderPYQ`. `build.py` deliberately does no date filtering — it did
  once, through a `SAT_BY` table, and that made its output depend on the day it ran and
  `content.yml`'s drift check fail on nothing. Do not move this back into the build.
- **No `--` inside an XML comment.** XML forbids it outright, and the res files are full
  of references to the page's CSS custom properties, whose names start with one. Writing
  `--accent` in a comment in `res/` fails `mergeDebugResources` with "The string `--` is
  not permitted within comments" — which is what broke every APK build until it was
  caught. Name the property without the dashes.
- **Adding an Optional subject is two edits and a fetch**, in this order: put the id in
  `OPTIONALS` in `tools/pyq-papers.py`, add the subject to `content/optionals.json` with
  `pyq: []`, then run `python tools/pyq-papers.py optionals`. Never hand-write the paper
  URLs — the tool exists to stop exactly that, and it fills only subjects already present
  in the JSON.
- **The Commission's label for a subject is not always the subject's name.** Civil
  Services (Main) 2023 lists "Agricultural Paper - I"; every other year 2016-2026 says
  "Agriculture". Matching the name exactly lost that one year *silently* — Agriculture
  simply had ten years instead of eleven, with nothing anywhere to say a year was
  missing. `OPT_LABEL` carries the variants. When a new optional comes up one year short,
  suspect the label before the archive.
- **The tab bar is a grid with a hard-coded column count, and it is now full.** Seven
  tabs is 53px each on a 375px phone and 46px on a 320px one, which is why the label
  shrinks below 360. Adding a button without raising `repeat(7,1fr)` silently wraps the
  last tab onto a second row — it does not overflow or clip, it just quietly becomes two
  rows. An eighth does not fit at any size the labels stay readable, so the next surface
  folds into an existing tab.
- **`.prim`'s theme overrides are `:root`-scoped**, so a bare `.custom` class on a `.prim`
  button loses to them and inherits the dark-on-dark ink meant for a filled accent
  button — an invisible label on a visible border. Match the specificity
  (`:root .prim.yours`) rather than reaching for `!important`.
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
