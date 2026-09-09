# TaraCmd — project context

An offline revision desk for the UPSC Civil Services Examination. One self-contained HTML
file, built from JSON, shipped as a web page and inside an Android WebView. Personal study
tool for one person, not a product.

This document is the orientation: what it is, what state it is in, what is decided and
should not be undone, and what is still open. `CLAUDE.md` is the working companion to it —
deeper, and closer to the code. Where the two disagree, `CLAUDE.md` is newer.

Repository: `github.com/NovaGod-25/taracmd` (private) · 31 commits · 63 tracked files.

---

## 1. What it is

```
content/*.json  ──►  build.py  ──►  web/taracmd.html            standalone, PWA
templates/                          web/artifact.html           embeddable fragment
  index.html                        android/…/assets/index.html what the APK ships
```

`templates/index.html` **is** the app — 2,575 lines of markup, CSS and JS with nine tokens
in it. `build.py` fills the tokens from `content/*.json`, validates as it goes, and writes
all three targets. There is **no runtime fetch for app content**: every byte is inlined at
build time. That single decision is why it works on a train with no signal, and most of
the other decisions follow from it.

Editing JSON and running `python build.py` is the whole content workflow. Never hand-edit
the three generated targets; CI fails if they drift.

### What it holds

| | |
|---|---|
| Syllabus | 8 subjects, 242 topics, 1,723 subtopics |
| Prelims papers | 12 years, 22/24 linked |
| Mains papers | 12 years, 54/60 linked |
| Optionals | Geography, Law, Agriculture — 11 years each, 22/22 papers |
| Answer keys | 18 paper slots, **2 filled** (2022 and 2023 GS-I, all four Series each) |
| Practice questions | 228 — 35 written here, 98 from a test series, 95 from UPSC 2023 GS-I |
| Toppers' copies | 102 across 10 publishers |

---

## 2. Decisions that should not be quietly reversed

**The app indexes, it does not mirror.** Question papers, answer keys and toppers'
booklets stay on upsc.gov.in and the publishers' own sites. The app links to them.
Bundling the scanned booklets was considered and rejected: it turns a personal study tool
into a redistribution problem. This is the principle that keeps deciding things.

**Everything is inlined at build time; nothing is fetched at runtime.** New content
arrives by rebuild, not over the air. The cost is a two-minute CI run before questions
appear; the gain is that the app never needs a network, a backend, or a host.

**`localStorage` key is `taracmd-v1` and never changes.** Changing it orphans every tick,
every logged answer and every scored paper. Every field added since is additive and
defaulted from `BLANK` on load.

**Provenance is enforced, not decorative.** A question carries `paper` (a real UPSC cell —
`build.py` refuses to ship one whose answer disagrees with the Commission's key) or
`source` (a coaching test series — its answer is that institute's claim). One or the
other, never both, and the app prints the difference on the question.

**Focus does not control the phone.** An earlier version pinned the screen with
`startLockTask()`. That was wrong twice: Android always leaves a way out of pinning, so
the promise could not be kept, and a study tool that fights the device is solving the
wrong problem. Nothing is blocked now — leaving the app voids the run.

**The page never claims a stronger guarantee than it has.** The lock says what it actually
got. The scorer says a key has not been loaded rather than showing an empty grid. An empty
tab that explains itself beats one that misleads.

---

## 3. Where it stands

### Working and verified

- **Syllabus tab** — the whole syllabus on one page, groups and topics opening in place,
  every subtopic its own tick target. Two lenses: *By subject* and *By paper* (Prelims
  235, GS-I 69, GS-II 82, GS-III 147, GS-IV 5, Essay 28). 240 of 242 topics serve more
  than one paper, which is what makes the second lens worth having. Plus a "Today" plan,
  subtopic search with matches marked, and a flat printable "read it all".
- **Papers tab** — Prelims / Mains / Optional as segments over the existing renderers.
- **Practice tab** — Daily current-affairs log, 35 practice questions, and *Score a paper*.
- **Score a paper works** for 2022 GS-I. A perfect Set A sheet scores 198.00 of 200, with
  the dropped question excluded. Where a question has been typed in, it is asked properly
  — stem, four options, reason — and untyped ones stay lettered cells in the same grid.
- **Focus tab** — a dial from 1 to 60 minutes. Leaving the app voids the run: clock to
  zero, streak to zero. Fourteen-day history of minutes focused.
- **Drawer** — Toppers, read-it-all, backup/restore, three-way theme.
- **49 tests** (`npm --prefix tests test`), run against the *built* page in a headless DOM.
- **CI green** on both workflows; APK installs over the previous one.

### Known gaps

- **The bank is no longer thin, but it is uneven.** 228 questions over 242 topics, and
  they cluster where the 2023 paper happened to go rather than where revision needs them.
- **16 of 18 answer-key slots are empty.** 2022 and 2023 GS-I are transcribed and
  structurally verified; the rest are scans nobody has read yet.
- **Weight bands do not discriminate** — 145 high, 96 medium, 1 low. The stripes and the
  "High weight" filter are the app's central editorial claim and at 60% high they carry
  almost no signal. Needs an editorial pass through `subjects.json`; it is judgement about
  UPSC frequency, not a code change. **This is the largest remaining weakness.**
- **A possible content mis-tag**: the paper lens puts a Geography drainage-patterns topic
  under Mains GS-II. The lens is faithful to the tags, so the tag is wrong — and the lens
  makes tagging errors visible for the first time, so there may be more.
- The Android wrapper is compile-verified but has never been run against a device by the
  tooling here.

---

## 4. Things that cost time to learn

**The keys and the papers are scans.** All seven published answer keys and the question
papers alike: 48 pages of 2022 GS-I, zero extractable characters. Every "just parse the
PDF" idea dies here.

**Every CI build was signed by a different key.** `assembleDebug` uses
`~/.android/debug.keystore`, which a fresh runner generates from scratch, and Android
refuses to update an app whose signing key changed — hence "uninstall first". There is one
committed key now (`android/app/taracmd-debug.p12`) and it must never be regenerated.

**`build.py` output must not depend on the day it runs.** It used to hold back exam years
whose exam had not been sat, so the same content produced different pages either side of a
cutoff and the drift check failed on nothing. The page filters at runtime instead.

**A dropped question sits at a different number in each Series** — 2022 GS-I dropped one,
at 61 in Set A, 71 in B, 31 in C, 11 in D. Droppedness is read off the letters (`X`) of
the set you sat, never from a per-paper list.

**The four Series are permutations of the same ten-question blocks.** That is what makes a
hand-read key trustworthy: every block in Set A reappears in B, C and D, so each letter is
effectively read four times. All 301 single-letter mutations of Set A break the property.
`tests/` pins it.

**targetSdk 35 means Android 15 draws edge-to-edge whether asked or not**, so the page sat
under the status bar and `env(safe-area-inset-*)` read zero. `MainActivity` pads the
WebView by the real insets.

**The tab bar grid count is not decorative.** `repeat(4,1fr)` with a fifth button silently
wraps onto a second row — no overflow, no clipping, just quietly two rows.

**A drag must not write to storage.** The focus dial called `save()` on every pointermove
— a full `JSON.stringify` of the whole store — and the arc had a 250ms transition, so it
eased *towards* the finger. Now: measure once, paint on a frame, write once on release.

---

## 5. Getting questions in

The bank takes two kinds of question and keeps them apart (§2, provenance).

**The pipeline.** Papers go in a Drive folder — *TaraCmd question intake*. One naming
rule: a paper and its key belong together when everything before the final `" - "` is
identical, with the suffix `paper`, `key`, `paper+key` or `explanations`. Reading a paper
is judgement — which of the 242 topics a question belongs to is not something a script
should guess — so that part is done by hand into a staged file under `intake/`.
`tools/quiz-import.py` does the mechanical rest; `tools/intake.py` runs every staged batch
and logs what it took, so re-running is free and a corrected batch is re-imported.

**A paper is usable if it has a text layer.** Institute papers are typeset and usually do.
UPSC's do not. `tools/pyq-ocr.py` exists for those and its limits are measured, not
guessed: on 2022 GS-I it locates 79 of 100 questions, but 26 carry text bled in from the
neighbouring column, 22 swallow the page footer, and **164 options have a digit read as a
letter** — `1 and 2 only` comes back as `land 2 only`. On a paper full of "which of the
statements given above are correct", that changes the answer without looking broken. It is
a draft for review, and nothing has been imported from it.

**Open decision.** A Vision IAS test paper (Test 15601) was read successfully — clean text
layer, 100 questions, 98 answers parsed. It was **not imported**, for two reasons worth
keeping in view: the paper carries an explicit "no reproduction, no storage in a retrieval
system" notice, and the copy is watermarked from a piracy aggregator 152 times. UPSC's own
papers are public documents of the Commission and carry no such problem. That choice is
the owner's and is still open.

---

## 6. Running it

```bash
python build.py                      # validate content, write all three targets
python tools/check-validation.py     # prove each validation actually fires (20 cases)
npm --prefix tests ci                # once
npm --prefix tests test              # 49 behaviour tests against the built page
perl tools/serve.pl 8787 --lan       # real http origin; --lan lets a phone reach it
```

Windows: the command is `python` or `py`, never `python3` — the python.org installer never
creates a `python3.exe`, so `python3` resolves to a WindowsApps stub that is not Python.

The APK is built by CI (`.github/workflows/android.yml`, also on demand from the Actions
tab) and installs over the previous one. `versionCode` follows `GITHUB_RUN_NUMBER`.

Remember to bump `CACHE` in `web/sw.js` before deploying the web build; the whole app is
one file, so a stale cache entry serves the old everything.

---

## 7. If you only fix one thing

The weight bands. 145 high / 96 medium / 1 low means the stripes, the legend, the "High
weight" filter and any ordering built on them are decoration. Everything else in the app
is honest about what it knows; this is the part that quietly is not.
