#!/usr/bin/env python3
"""Build TaraCmd from content/*.json into its three shipping targets.

    content/*.json  ──►  web/taracmd.html              standalone, PWA
                         web/artifact.html             fragment, embeddable
                         android/…/assets/index.html   what the APK ships

Nothing is fetched at runtime: every byte of content is inlined here, at build
time. Editing the JSON and running this script is the whole content workflow.

All three targets are written from the same template. Do not hand-edit any of
them — the Android copy drifted a full rename behind the web build once already
and shipped an APK with dead branding and a different localStorage key.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "templates" / "index.html"

TARGETS = {
    "web": ROOT / "web" / "taracmd.html",
    "artifact": ROOT / "web" / "artifact.html",
    "android": ROOT / "android" / "app" / "src" / "main" / "assets" / "index.html",
}

# An exam year is only shown once its exam has actually been sat, so the app
# never offers a year with nothing behind it. Prelims goes on the last Sunday
# of May (2025: the 26th, 2026: the 25th) and Mains opens on 1 September — and
# the Commission puts each paper up the same day it is sat, so the sitting date
# is also the publication date. The Prelims cutoff is the end of the month
# because the exact Sunday moves.
SAT_BY = {"prelims": (5, 31), "mains": (9, 1)}

# What the app's own PAPER_LBL map knows how to render.
PAPERS = {"prelims", "mains-gs1", "mains-gs2", "mains-gs3", "mains-gs4", "essay"}
WEIGHTS = {"high", "medium", "low"}
SET_LETTERS = {"A", "B", "C", "D"}

TOKEN = re.compile(r"__[A-Z0-9_]+__")

problems: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)


def load(name: str):
    path = ROOT / "content" / name
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        sys.exit(f"missing content file: content/{name}")
    except json.JSONDecodeError as exc:
        sys.exit(f"content/{name} is not valid JSON: line {exc.lineno}, {exc.msg}")


# ---------------------------------------------------------------- validation

def check_subjects(subjects) -> dict[str, str]:
    """Return {topic id: subject id}. Duplicate ids are fatal — progress is
    keyed on the topic id, so two topics sharing one would share their ticks."""
    seen_subjects: set[str] = set()
    topics: dict[str, str] = {}

    for s in subjects:
        for field in ("id", "name", "short", "icon", "topics"):
            if field not in s:
                fail(f"subject {s.get('id', '?')!r} has no {field!r}")
        sid = s.get("id", "?")
        if sid in seen_subjects:
            fail(f"duplicate subject id {sid!r}")
        seen_subjects.add(sid)

        for t in s.get("topics") or []:
            for field in ("id", "name", "weight", "papers", "subtopics"):
                if field not in t:
                    fail(f"topic {t.get('id', '?')!r} has no {field!r}")
            tid = t.get("id")
            if tid in topics:
                fail(f"duplicate topic id {tid!r} — in {topics[tid]!r} and {sid!r}")
            topics[tid] = sid

            if t.get("weight") not in WEIGHTS:
                fail(f"topic {tid!r} has weight {t.get('weight')!r}, not one of {sorted(WEIGHTS)}")
            for p in t.get("papers", []):
                if p not in PAPERS:
                    fail(f"topic {tid!r} is tagged for paper {p!r}, which the app cannot label")
            if not t.get("papers"):
                fail(f"topic {tid!r} is tagged for no paper at all")
            if not t.get("subtopics"):
                fail(f"topic {tid!r} has no subtopics")

    return topics


def check_quiz(quiz, topics: dict[str, str]) -> None:
    """Every question hangs off a real topic — the Revise link and the subject
    filter both resolve through it."""
    seen: set[str] = set()
    for q in quiz.get("questions", []):
        qid = q.get("id", "?")
        if qid in seen:
            fail(f"duplicate quiz question id {qid!r}")
        seen.add(qid)

        if q.get("topic") not in topics:
            fail(f"quiz question {qid!r} points at unknown topic {q.get('topic')!r}")

        options = q.get("options") or []
        if len(options) < 2:
            fail(f"quiz question {qid!r} has {len(options)} options")
        answer = q.get("answer")
        if not isinstance(answer, int) or not 0 <= answer < len(options):
            fail(f"quiz question {qid!r} has answer {answer!r}, outside its {len(options)} options")


def check_keys(keys) -> None:
    """A set's letters must be as long as the paper is, or the scorer silently
    marks the tail of the paper blank."""
    marking = keys.get("marking", {})
    for code, m in marking.items():
        for field in ("questions", "correct", "wrong", "total"):
            if field not in m:
                fail(f"marking scheme {code!r} is missing {field!r}")

    for year in keys.get("years", []):
        y = year.get("year", "?")
        for paper in year.get("papers", []):
            code = paper.get("code")
            if code not in marking:
                fail(f"{y} answer key names paper {code!r}, which has no marking scheme")
                continue
            expected = marking[code]["questions"]

            for set_name, letters in (paper.get("keys") or {}).items():
                if len(letters) != expected:
                    fail(
                        f"{y} {code} set {set_name}: {len(letters)} letters "
                        f"for a {expected}-question paper"
                    )
                stray = sorted(set(letters) - SET_LETTERS)
                if stray:
                    fail(f"{y} {code} set {set_name} contains {stray}")

            for q in paper.get("dropped") or []:
                if not 1 <= q <= expected:
                    fail(f"{y} {code}: dropped question {q} is outside 1–{expected}")


# ------------------------------------------------------------------- derived

def sat_years(pyq, today: date) -> dict:
    """Drop exam years whose exam has not been sat yet, so the app never shows
    a year with nothing behind it. Derived from today rather than pinned."""
    out = {}
    for kind, years in pyq.items():
        month, day = SAT_BY.get(kind, (12, 31))
        kept, held = [], []
        for y in years:
            (kept if date(y["year"], month, day) <= today else held).append(y)
        if held:
            years_held = ", ".join(str(y["year"]) for y in held)
            print(f"  {kind}: holding back {years_held} — not sat yet")
        out[kind] = kept
    return out


# ------------------------------------------------------------------- render

PWA_MARKER = re.compile(r"^<!--/?PWA-->\n", re.MULTILINE)
PWA_BLOCK = re.compile(r"^<!--PWA-->\n.*?^<!--/PWA-->\n", re.MULTILINE | re.DOTALL)


def keep_pwa(html: str) -> str:
    """Drop the markers, keep what they wrap."""
    return PWA_MARKER.sub("", html)


def strip_pwa(html: str) -> str:
    """Drop the manifest link and the service-worker registration along with
    the markers. Neither target that gets this has an sw.js beside it."""
    return PWA_MARKER.sub("", PWA_BLOCK.sub("", html))


def fragment(html: str) -> str:
    """The embeddable form: the stylesheet and the body, no document shell."""
    style = re.search(r"<style>.*?</style>", html, flags=re.DOTALL)
    body = re.search(r"<body>\n?(.*?)\n?</body>", html, flags=re.DOTALL)
    if not style or not body:
        sys.exit("template no longer has the <style>/<body> shape artifact.html needs")
    return style.group(0) + "\n" + body.group(1) + "\n"


def main() -> int:
    today = date.today()
    print(f"TaraCmd build — {today.isoformat()}")

    subjects = load("subjects.json")
    pyq = load("pyq-papers.json")
    toppers = load("toppers.json")
    keys = load("answer-keys.json")
    quiz = load("quiz.json")

    topics = check_subjects(subjects)
    check_quiz(quiz, topics)
    check_keys(keys)

    if problems:
        print(f"\n{len(problems)} problem(s) in content:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    n_topics = len(topics)
    n_subtopics = sum(len(t["subtopics"]) for s in subjects for t in s["topics"])
    print(f"  {len(subjects)} subjects, {n_topics} topics, {n_subtopics:,} subtopics")

    pyq = sat_years(pyq, today)

    data = {"__SUBJECTS__": subjects, "__PYQ__": pyq, "__TOPPERS__": toppers,
            "__KEYS__": keys, "__QUIZ__": quiz}

    values = {t: json.dumps(v, ensure_ascii=False, separators=(",", ":"))
              for t, v in data.items()}
    values["__N_TOPICS__"] = f"{n_topics:,}"
    values["__N_SUBTOPICS__"] = f"{n_subtopics:,}"

    template = TEMPLATE.read_text(encoding="utf-8")

    missing = {m.group(0) for m in TOKEN.finditer(template)} - values.keys()
    if missing:
        return fatal(f"template wants tokens nothing fills: {', '.join(sorted(missing))}")

    # Substituted in one pass, so a token appearing inside content is not rescanned.
    rendered = TOKEN.sub(lambda m: values[m.group(0)], template)

    left = TOKEN.findall(rendered)
    if left:
        return fatal(f"unsubstituted token(s) survived: {', '.join(sorted(set(left)))}")

    variants = {
        "web": keep_pwa(rendered),
        "android": strip_pwa(rendered),
        "artifact": fragment(strip_pwa(rendered)),
    }

    for name, path in TARGETS.items():
        body = variants[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        # Explicit open() rather than write_text(newline=...), which is 3.10+.
        # Newlines are pinned so a Windows checkout does not rewrite every
        # target with CRLF and make the CI drift check fail on nothing.
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        print(f"  wrote {path.relative_to(ROOT).as_posix()}  {len(body.encode('utf-8')):,} bytes")

    print("\nRemember to bump CACHE in web/sw.js before you deploy.")
    return 0


def fatal(msg: str) -> int:
    print(f"\n{msg}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
