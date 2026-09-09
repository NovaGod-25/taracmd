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

**Three lenses, and Map is the one it opens on.** Map draws all 242 topics as one square
each, grouped by subject — the whole of what the Commission examines on a screen and a
half, which a scrolling outline can never be. Colour there is progress, never weight:
where you have and have not been is a fact, and weight is an editorial claim that at the
moment barely discriminates. Tap a square for the topic, a subject's name to drop into
the outline at that subject.

`By subject` and `By paper` are the other two, and they are the point of the tab rather
than a gimmick: **240 of the 242 carry more than one paper tag**, so how the material is
taught and how the Commission sets it (Prelims 235, GS-I 69, GS-II 82, GS-III 147, GS-IV
5, Essay 28) really are different shapes of one syllabus. Anything that regroups topics
must keep every topic: `tests/` checks the paper lens holds exactly the topics tagged for
each paper, and that the map draws every topic exactly once.

**The map view suppresses the dashboard cards on purpose.** The tab is called Syllabus and
it used to open on three stacked cards — Today, the exam clock, the counts strip — with
the syllabus itself below the fold. In the map the exam clock folds into the map's own
header line and Today moves below the picture. There is a test that the pace card is not
drawn in map view, because the temptation to put it back is real.

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

## Navigation

Five tabs and a drawer, after the bar reached seven and stopped having a shape.

```
Syllabus   Papers      Practice    Focus   Shelf     ☰ drawer
├ Map      ├ Prelims   ├ Daily                       ├ Toppers' copies
├ Subject  ├ Mains     └ Papers                      ├ Read the whole syllabus
└ Paper    └ Optional                                ├ Back up or restore
                                                     └ Theme
```

Prelims, Mains and Optional were three of the seven tabs and **one idea** — the
Commission's question papers — and Prelims and Mains already shared `renderPYQ`. They are
segments now, in the same control the syllabus lens and the practice modes already use.

Things that will bite:

- **`renderPapers` reassigns `view`.** The three paper renderers all write to `view` and
  none takes a target, so it points `view` at a panel below the segment and puts it back
  in a `finally`. That is why `view` is `let` and not `const`. If it ever failed to put it
  back, every later render would draw into the wrong element — there is a test for
  exactly that.
- **The drawer is button-opened, never edge-swiped.** On Android 10+ a swipe in from
  either edge is the system Back gesture; an app cannot reliably take that edge, and
  trying makes Back unreliable, which is worse than having no gesture.
- **The back ladder gained a rung and the drawer goes first**, because it is the topmost
  thing on screen: drawer → sheet → read view → collapse the outline → Syllabus tab → OS.
- **Toppers lights no tab**, because it is reached from the drawer. `markTab` clears the
  bar rather than leaving the previous tab lit and claiming you are somewhere you are not.
- **The grid's column count must equal the number of tabs.** It is `repeat(5,1fr)` now —
  75px a column on a 375px phone, which is roomier than the six that fitted before the
  drawer existed. A button more than there are columns does not overflow or clip: it
  silently wraps onto a second row, which is the kind of bug you only ever see on a
  phone. `tests/` reads the column count out of the stylesheet and compares it with the
  number of `.tab` buttons, so the two cannot drift apart again.
- **Anything rare still goes in the drawer rather than the bar.** Shelf earned a tab
  because it is somewhere you go on purpose and often; Toppers did not.

## The shelf

Somewhere to keep your own documents, and the whole feature is about *where* they are
kept rather than that they are listed.

**Every directory the app owns is deleted when the app is** — `filesDir` and
`getExternalFilesDir()` both, and so is anything written through MediaStore once the
app's ownership of it goes. So the app does not choose the location. The owner picks a
folder through `ACTION_OPEN_DOCUMENT_TREE`, Android hands over a persistable grant, and
the files are then ordinary files in ordinary storage: visible in the phone's own Files
app, and untouched by uninstalling TaraCmd.

**What an uninstall takes is the grant, not the files.** That is Android's design and not
something to route around — `MANAGE_EXTERNAL_STORAGE` would survive it and is a
Play-restricted permission wildly out of proportion to a shelf. Pointing at the same
folder again after a reinstall costs one tap and brings the whole shelf back, and the
page says exactly that rather than implying the app is holding anything.

Things that will bite:

- **The remembered URI string is not a permission.** After an uninstall, or if the user
  revokes it in Settings, the row in `persistedUriPermissions` is gone and reading
  through the URI throws. `shelf()` checks the grant is actually held and returns null
  otherwise, which is what makes the page fall back to "pick a folder" instead of showing
  an empty shelf that should not be empty.
- **`registerForActivityResult` must run before the activity is STARTED**, which is why
  both launchers sit at the top of `onCreate` rather than beside the bridge methods that
  use them.
- **Deleting removes the file.** The shelf *is* the folder — there is no copy to remove
  instead — so the page confirms first and says so in the confirmation.
- **A filename is not a trusted author.** It comes off the phone's filesystem and goes
  through `innerHTML`; it is escaped, and there is a test that a filename cannot become
  markup.

## The question palette

Green, red and grey, which is the colour language of every exam hall and worth copying
exactly. Answered is green, **seen-but-not-answered is red**, not visited is grey, and
the question the Commission dropped is struck through and out of the total.

The middle state is the one that earns its keep: without it a question you skipped and
one you have never reached look identical, and the palette stops being able to tell you
where the work is. It needs `store.seen`, written once the first time a number is shown —
not on every render, which would put a full `JSON.stringify` of the store behind every
tap of the palette. Answered beats seen, so coming back to a question and answering it
turns it green rather than leaving it looking like a failure.

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

## Feeding question papers in

The bank takes questions from two kinds of source and keeps them apart, because they do
not carry the same authority.

| Field | Means | Answer is |
|---|---|---|
| `paper: {year, code, set, n}` | a real UPSC paper | the **Commission's**, and `build.py` refuses to ship a question whose answer disagrees with the official key |
| `source: {name, test, year}` | a coaching institute's test series | **that institute's claim**, which is a different thing and is labelled as such on the question |

A question may carry one or the other, never both. Every question also needs a `topic`
that resolves to one of the 242 ids — that link is what puts a question in front of you
when the topic falls due, and a question with no topic is just trivia.

`build.py` also rejects an empty option, two identical options in one question (both
would be right), a missing stem, and two questions asking the same thing in different
words — institutes recycle heavily, and the same question twice is one you have already
answered wearing a new id.

**What a paper needs before it can be converted:**

1. **A text layer.** This is the whole game. Institute papers are usually typeset and do
   carry text. UPSC's own PDFs do not — both the question papers and the answer keys are
   photographs of paper, and 2021 Prelims read through Drive comes back as 43 empty pages,
   exactly as `pypdf` reads it locally. A scan needs OCR before anything can be done with it.
2. **The answer key.** Without it there is no `answer`, and a guessed answer is worse than
   no question at all.
3. Explanations, where the institute gives them. They become `why`, which is the part that
   teaches.

**The pipeline.** Papers go in a Drive folder — *TaraCmd question intake*. One naming
rule: a paper and a key belong together when **everything before the final `" - "` is
identical**, and the suffix is one of `paper`, `key`, `paper+key`, `explanations`. The
front part is free-form and becomes the label on every question, so it should be
findable a year later — `Vision IAS - PT Test 12 - 2026` rather than `test 3 new`.
Different sets and different sections go in as separate pairs.

Batches are staged under `intake/` (gitignored, along with `tools/.intake-log.json`);
what ships is `content/quiz.json`. `tools/intake.py` processes every staged batch at
once and **logs what it took, keyed by the batch's contents** — so dropping five papers,
processing three, then dropping two more does not re-import the first three, while a
batch you *corrected* is noticed and re-imported, taking only what changed. Re-asking is
therefore free, which is the property that makes this safe to run on a whim. Reading a
paper is judgement, and deciding which of the 242 topics a question belongs to is not
something a script should guess at, so that part is done by hand into a staged file:

```json
{ "source": {"name": "Vision IAS", "test": "PT Test 12", "year": 2026},
  "questions": [{"n": 1, "topic": "polity-basic-structure", "q": "…",
                 "options": ["…","…","…","…"], "answer": 1, "why": "…"}] }
```

Everything after the judgement is mechanical, and mechanical work done by hand is where a
question bank quietly rots — a colliding id, an answer index off by one, the same question
imported twice from two test series that both lifted it. `tools/quiz-import.py` does that
part: it mints ids from the source, checks the topic resolves, rejects empty or repeated
options and out-of-range answers, refuses a question already in the bank under another id,
and stamps the provenance. `--dry-run` says what it would do. `build.py` then re-checks all
of it independently.

**What cannot be carried:** anything that is not text. Map questions, diagrams, and
image-based match-the-following have nowhere to live in this format — the app is one HTML
file and an inlined image is weight on every page load. Those get skipped rather than
mangled.

## Typing a past question in

Quiz → Score a paper used to be a bare grid of letters: you marked A/B/C/D against a
paper open in another app, which is an answer sheet, not practice. A question can now
carry the paper cell it came from, and where one has been typed the scorer **asks it
properly** — stem, four options, and the reason once you answer. Untyped questions stay
as lettered cells in the same grid, so a paper fills in as it is typed rather than
switching mode.

Add one to `content/quiz.json`:

```json
{
  "id": "csp22-gs1-a-2",
  "topic": "polity-basic-structure",
  "paper": { "year": 2022, "code": "gs1", "set": "A", "n": 2 },
  "q": "…the question, as printed…",
  "options": ["…", "…", "…", "…"],
  "answer": 1,
  "why": "…why that one, and why the near-miss is not…"
}
```

`paper` is optional; without it a question is ordinary practice. With it, **the
Commission's own key marks your typing**: `build.py` fails if `answer` disagrees with the
key letter at that cell, if two questions claim one cell, if the number is out of range,
or if the cell is one the Commission dropped. Typing a question against the wrong number
or mis-ordering its options is caught by the build rather than teaching you a wrong
answer for a year.

Order matters — options must be in the order the paper prints them, because the key is a
letter, not a value. And the sets are shuffled against each other, so a question typed
for Set A cannot be reused for Set B: it is a different number there, with the options in
a different order.

**2023 GS-I is typed in — 95 of its 100 questions — and it came from somebody else's
typesetting, not from UPSC.** The Commission's own PDF is 48 pages of photographs as
always. What made this paper possible is that Drishti publishes a *typeset* copy of it:
51,508 characters of real text, where every one of the other thirteen years on the same
page is a scan of 0. `tools/pyq-text.py` reads that, and reads it far better than OCR
ever read a scan — 99 of 100 questions parsed, 0 flagged. So **always check for a text
layer before reaching for OCR**, including on somebody else's copy of a paper UPSC
publishes as an image.

The answers are still the Commission's own: `pyq-text.py` refuses to invent one, and takes
each from `content/answer-keys.json` by number against the Series the paper says it is.

Five of the hundred are not in the bank, and each for a reason worth keeping:

| | |
|---|---|
| 29 | absent from the source itself — Drishti's text runs 28 straight to 30 |
| 14 | the Commission dropped it, so there is no answer to mark you against |
| 55, 56, 64 | sports awards, the Chess Olympiad and the Flag Code: **nothing in the 242 topics covers them.** A forced topic is worse than a missing question — it puts a question in front of you while you are revising something else |

### A paper stops being an answer sheet once its questions are in

A UPSC paper used to open as the OMR grid whatever was in the bank. Now the folder looks
at what has been typed for the Series you are on: if there are questions it is **sat**,
one at a time, with the numbers nobody has typed yet still in the palette as four blank
lettered cells. The grid is still there, behind a link, for when the paper is open on
paper in front of you.

Two things about this that are easy to get wrong:

- **The sheet is stored per Series, not per paper** — `2023-gs1-B`, which is the key the
  scorer has always used. The folder used to read `upsc-2023-gs1`, an id nothing was ever
  written to, so a UPSC paper reported none answered however much of it you had filled
  in. `paperId()` is now the single place that decides.
- **The letters have to follow the Series selector.** Switching Series changes the
  answers *and* moves the dropped question — 2023 dropped one, at 34 in A but 94 in D —
  so `p.letters` is reassigned alongside `p.set`. Changing one without the other marks
  your sheet against a paper you did not sit.

A dropped question is struck through in the palette rather than removed, so the paper
still counts to a hundred and question 62 is still at 62; it is not asked, not scorable,
and excluded from the total, which is what the Commission's own "taken for Scoring 99"
means.

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
| `seen` | which questions have been looked at, keyed like `attempts` — what makes "not answered" a state distinct from "not visited" |

There is no export bridge function: backup is a copyable blob in a sheet, plus a file
download on web only. That is deliberate — see the bridge contract below.

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

**upsc.gov.in rate-limits hard.** It stopped answering entirely after roughly 45 requests
in one session. `tools/answer-keys.py` waits 4 seconds between requests on purpose. Any
new scraping should be designed to run locally and unhurried, never in CI.

## The JS ↔ native contract

Thirteen functions, and nothing else crosses. Changing a name on either side breaks it
silently, because the page checks for the bridge before using it and falls back to
browser behaviour when it is absent.

| Direction | Name | Does |
|---|---|---|
| page → native | `AndroidHost.savedPath(url)` | non-null once this PDF is on disk, so the row can read "saved" |
| page → native | `AndroidHost.saveCopy(url)` | one URL to DownloadManager |
| native → page | `window.taracmdSaved()` | a download landed; re-render the Toppers tab |
| page → native | `AndroidHost.appVersion()` | the installed versionName, which only the APK knows |
| page → native | `AndroidHost.focusAwake(on)` | hold the screen awake for a focus run, and let it sleep after |
| native → page | `window.taracmdBack()` | hardware back. Closes sheet → collapses the outline → returns to the Syllabus tab → returns `false` so the OS takes over |
| native → page | `window.taracmdInterrupted()` | `onPause` — the app has been left, so a focus run is void |
| page → native | `AndroidHost.docsFolder()` | the shelf folder's name, or null while none is picked |
| page → native | `AndroidHost.docsPick()` | choose or change that folder |
| page → native | `AndroidHost.docsAdd()` | pick documents and copy them onto the shelf |
| page → native | `AndroidHost.docsList()` | JSON of what is on it — id, name, size, mime, date |
| page → native | `AndroidHost.docsOpen(id)` | hand one to whatever the phone reads it with |
| page → native | `AndroidHost.docsRemove(id)` | delete it — the file, not a listing of it |
| native → page | `window.taracmdDocs()` | the shelf changed (folder picked, files added); re-render |

### Focus does not control the phone

It used to try. An earlier version called `startLockTask()` to pin the screen, and that
was wrong twice over: Android always leaves a way out of ordinary pinning, so the promise
could not be kept, and a study tool that fights the device is solving the wrong problem
anyway. What breaks a study hour is the reflex — the idle unlock, the glance at a
notification — and that cannot be engineered away. It can only be counted.

So nothing is blocked. The rule is that **leaving the app voids the run**: the clock stops,
the dial returns to zero, and the streak of clean runs goes back to zero with it. The only
thing at stake is whether the run counts, which is the point — a number you cannot fake is
worth more than a cage you can escape.

- **`onPause` is the interruption**, and it is the right hook because it hears every way of
  leaving: Home, Recents, a call, the screen locking, another app taking focus. The page
  also listens for `visibilitychange` and `pagehide`, which is what catches it on the web.
- **In-app navigation is not an interruption.** Reading the syllabus during a focus hour is
  the activity, not a distraction from it. Nothing about the tab bar or the back button
  changes while a run is going.
- The run lives in `localStorage`, so a reload resumes it rather than losing it — and the
  app reopens on the Focus tab when it finds one.
- The dial is 1 to 60 minutes, one tick per minute, so the angle round the face **is** the
  number of minutes and it needs no legend.

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
2. **Answer keys: 2022 and 2023 GS-I are in, five papers to go.** 2023 was read the same
   way as 2022 and holds the same guarantee — see the block-permutation note below; Set C
   turned out to be an exact reversal of Set A, block for block, and all 400 single-letter
   mutations of Set A break the property. Punch in a sheet, pick your Series, and it
   scores against the Commission's own letters on the Commission's own scheme — and for
   2023, where the questions are typed in, it asks them instead of taking letters.
   The other five are the work. `extract` cannot do them and never could: **every key
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
- **The tab bar is a grid with a hard-coded column count.** Raise `repeat(N,1fr)` in
  lockstep with the number of buttons or the last tab silently wraps onto a second row —
  no overflow, no clipping, just quietly two rows. Seven was 53px a column and the labels
  had to shrink below 360px; five is 75px and comfortable. There is a test.
- **`.prim`'s theme overrides are `:root`-scoped**, so a bare `.custom` class on a `.prim`
  button loses to them and inherits the dark-on-dark ink meant for a filled accent
  button — an invisible label on a visible border. Match the specificity
  (`:root .prim.yours`) rather than reaching for `!important`.
- **The signing key is committed, and must never be regenerated.** `assembleDebug`
  otherwise signs with `~/.android/debug.keystore`, which a fresh CI runner creates from
  scratch every run — three consecutive builds were signed by three different keys, and
  **Android refuses to update an app whose signing key changed.** That is what made every
  new APK demand an uninstall first, taking every tick, logged answer and scored paper
  with it. `android/app/taracmd-debug.p12` is exempted in `.gitignore` and marked
  `binary` in `.gitattributes` on purpose: `text=auto` normalising a keystore would
  corrupt it silently. It is a debug key and it is in the tree deliberately, because it
  has to be identical on every machine and every runner. A release key for Play would be
  a different key, kept out of the tree.
  To check two APKs will update over each other, compare their signers rather than
  guessing — the public key sits in the v2 signing block, after the magic
  `APK Sig Block 42` near the end of the file.
- **The app cannot check for its own updates**, and should not pretend to. The repository
  is private, so a version check needs a token, and a token shipped inside an APK is a
  token given away. The drawer shows what `AndroidHost.appVersion()` reports and opens
  the build page instead, where you are already signed in.
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
