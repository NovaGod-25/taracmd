# TaraCmd

An offline revision desk for the UPSC Civil Services Examination: 8 subjects, 242 topics,
1,723 subtopics, the official question papers, the Commission's own answer keys, an OMR
self-scorer, and an index of published toppers' answer copies.

One self-contained HTML file. No backend, no accounts, no analytics. Revision progress is
stored in `localStorage` on the device and goes nowhere else.

Personal study tool, not a product.

## What it indexes, and what it doesn't host

Question papers, answer keys and toppers' booklets stay where they were published — on
upsc.gov.in and on the publishers' own sites. Every link in the app opens the source.
Nothing is mirrored or re-uploaded. Inside the Android build a single tapped copy can be
saved to the app's own folder for offline reading; nothing is fetched unless asked for.

## Build

Needs Python 3.7+ on PATH. Content lives in `content/*.json`; the app itself lives in
`templates/index.html`.

```bash
python3 build.py
```

That validates the content and writes all three targets:

| Target | What it is |
|---|---|
| `web/taracmd.html` | standalone page, installable as a PWA |
| `web/artifact.html` | the same app as an embeddable fragment |
| `android/app/src/main/assets/index.html` | what the APK ships |

Never hand-edit those three — `build.py` owns them, and CI fails if they drift.

For the APK, open `android/` in Android Studio, or:

```bash
cd android && ./gradlew assembleDebug
```

`assembleRelease` produces an unsigned APK that will not install; a real release needs a
keystore. CI builds and uploads a debug APK on demand from the Actions tab.

## Working on it

Read [CLAUDE.md](CLAUDE.md) first. It carries the architecture, the decisions that should
not be quietly reversed, the JS ↔ native contract, the open work and the gotchas.
