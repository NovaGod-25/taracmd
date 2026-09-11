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

# Which exam years to show is NOT decided here. Holding a year back at build
# time made this script's output depend on the day it ran, so the same content
# produced two different pages either side of a cutoff and content.yml's
# "was a generated target hand-edited?" check failed on nothing. It also froze
# a date into a page meant to be opened offline months later. The page filters
# on its own clock instead — see satOn() in templates/index.html.

# What the app's own PAPER_LBL map knows how to render.
PAPERS = {"prelims", "mains-gs1", "mains-gs2", "mains-gs3", "mains-gs4", "essay"}
WEIGHTS = {"high", "medium", "low"}
# "X" is the Commission's own mark for a question it dropped. It is a letter
# in the key like any other, and it falls at a DIFFERENT number in each Series
# — 2022 GS-I dropped one question, at 61 in Set A, 71 in B, 31 in C, 11 in D.
# That is why droppedness lives in the letters rather than in a per-paper list:
# a flat list cannot say "question 61, but only if you sat Set A".
SET_LETTERS = {"A", "B", "C", "D", "X"}

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
                fail(f"duplicate topic id {tid!r} - in {topics[tid]!r} and {sid!r}")
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
    # A CSAT passage is printed once above the items that share it, and stored
    # once: each of those questions carries the passage's id.
    passages = quiz.get("passages") or {}
    if not isinstance(passages, dict):
        fail("quiz `passages` must be a table of passage id -> text")
    used: set[str] = set()
    for q in quiz.get("questions", []):
        qid = q.get("id", "?")
        if qid in seen:
            fail(f"duplicate quiz question id {qid!r}")
        seen.add(qid)
        pid = q.get("passage")
        if pid is not None:
            if not isinstance(passages.get(pid), str) or not passages[pid].strip():
                fail(f"quiz question {qid!r} points at passage {pid!r}, which is not in the file")
            used.add(pid)

        if q.get("topic") not in topics:
            fail(f"quiz question {qid!r} points at unknown topic {q.get('topic')!r}")

        options = q.get("options") or []
        if len(options) < 2:
            fail(f"quiz question {qid!r} has {len(options)} options")
        if any(not isinstance(o, str) or not o.strip() for o in options):
            fail(f"quiz question {qid!r} has an empty option")
        if len(set(o.strip() for o in options if isinstance(o, str))) != len(options):
            fail(f"quiz question {qid!r} repeats an option, so two answers would be right")
        answer = q.get("answer")
        if not isinstance(answer, int) or not 0 <= answer < len(options):
            fail(f"quiz question {qid!r} has answer {answer!r}, outside its {len(options)} options")
        if not (q.get("q") or "").strip():
            fail(f"quiz question {qid!r} has no question text")

        # Where a question came from. UPSC's own papers carry `paper` and are
        # marked against the Commission's key; anything else — a coaching
        # institute's test series — carries `source`, and its answer is that
        # institute's claim rather than the Commission's. Keeping them apart
        # matters: a wrong answer from a test series is a normal event, and
        # nothing here should let one wear the Commission's authority.
        src = q.get("source")
        if src is not None:
            if q.get("paper"):
                fail(f"quiz question {qid!r} claims both an official paper and a source")
            for field in ("name",):
                if not (src.get(field) or "").strip():
                    fail(f"quiz question {qid!r} has a source with no {field!r}")

    for pid in passages:
        if pid not in used:
            fail(f"passage {pid!r} is not used by any question")

    # Institutes recycle questions, and the same question twice is a question
    # you have already answered wearing a different id.
    stems: dict[str, str] = {}
    for q in quiz.get("questions", []):
        stem = " ".join((q.get("q") or "").lower().split())
        if len(stem) < 25:
            continue
        # CSAT asks "the most logical inference from the passage" of passage
        # after passage; the same words over another passage are another question.
        if q.get("passage"):
            stem += " | " + " ".join((passages.get(q["passage"]) or "").lower().split())
        if stem in stems:
            fail(f"quiz questions {stems[stem]!r} and {q.get('id', '?')!r} ask the same thing")
        stems[stem] = q.get("id", "?")


def check_paper_tags(quiz, keys) -> None:
    """A question may say which paper cell it came from, and if it does, the
    Commission's own key gets to mark it.

    `paper: {year, code, set, n}` puts a typed question at question n of that
    Series, so Quiz -> Score a paper can show the real thing instead of a bare
    row of letters. The check that makes this worth having: the question's own
    `answer` must agree with the key letter at that cell. Typing a question
    against the wrong number, or mis-ordering its options, then fails the build
    rather than teaching you the wrong answer for a year.
    """
    marking = keys.get("marking", {})
    by_cell: dict[tuple, str] = {}

    for q in quiz.get("questions", []):
        tag = q.get("paper")
        if not tag:
            continue
        qid = q.get("id", "?")
        year = next((y for y in keys.get("years", []) if y.get("year") == tag.get("year")), None)
        if year is None:
            fail(f"question {qid!r} cites {tag.get('year')}, which has no answer key")
            continue
        paper = next((pp for pp in year["papers"] if pp.get("code") == tag.get("code")), None)
        if paper is None:
            fail(f"question {qid!r} cites {tag.get('year')} {tag.get('code')!r}, which is not a paper")
            continue

        letters = (paper.get("keys") or {}).get(tag.get("set"))
        if letters is None:
            fail(f"question {qid!r} cites set {tag.get('set')!r}, which has no letters yet")
            continue

        n = tag.get("n")
        total = marking.get(tag.get("code"), {}).get("questions", 0)
        if not isinstance(n, int) or not 1 <= n <= total:
            fail(f"question {qid!r} cites question {n!r}, outside 1-{total}")
            continue

        cell = (tag["year"], tag["code"], tag["set"], n)
        if cell in by_cell:
            fail(f"questions {by_cell[cell]!r} and {qid!r} both claim {cell}")
        by_cell[cell] = qid

        # A key shorter than the paper is check_keys' to report, as a short key.
        # Indexing past its end here used to crash the whole build with a
        # traceback before that message was ever printed -- so the one defect a
        # truncated key most needs to explain was the one it could not.
        if n > len(letters):
            fail(f"question {qid!r} cites {cell}, past the end of a {len(letters)}-letter key")
            continue
        want = letters[n - 1]
        if want == "X":
            fail(f"question {qid!r} sits on {cell}, which the Commission dropped")
            continue
        got = "ABCD"[q["answer"]] if isinstance(q.get("answer"), int) and 0 <= q["answer"] < 4 else "?"
        # 2021's CSAT accepted either of two letters for one question ("CD"),
        # and a question answering either one agrees with the Commission.
        if got not in want:
            fail(f"question {qid!r} answers {got} but the official key says {want} "
                 f"for {tag['year']} {tag['code']} set {tag['set']} q{n}")


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
                # A cell is one letter, X for dropped, or -- 2021's CSAT -- the
                # two letters the Commission accepts either of, written "CD".
                stray = sorted({c for c in letters if not (
                    c in SET_LETTERS or (1 < len(c) <= 4 and set(c) <= {"A", "B", "C", "D"}))})
                if stray:
                    fail(f"{y} {code} set {set_name} contains {stray}")

            # Each key page prints how many questions it dropped. That count is
            # transcribed separately, so it is an independent check on the
            # letters: if they disagree, one of the two was read wrong.
            want = paper.get("dropped_count")
            if want is not None:
                for set_name, letters in (paper.get("keys") or {}).items():
                    got = list(letters).count("X")
                    if got != want:
                        fail(f"{y} {code} set {set_name}: {got} question(s) marked X, "
                             f"but the paper says {want} were dropped")


def check_optionals(opts) -> None:
    """The Optional tab. Two papers per subject, and the answer log is keyed on
    `year-<subject id>-<code>`, so a duplicate subject id would merge two
    subjects' logged answers into one pile."""
    seen: set[str] = set()
    for sub in opts.get("subjects", []):
        sid = sub.get("id", "?")
        for field in ("id", "name", "short", "icon", "pyq", "copies"):
            if field not in sub:
                fail(f"optional {sid!r} has no {field!r}")
        if sid in seen:
            fail(f"duplicate optional subject id {sid!r}")
        seen.add(sid)

        years: set[int] = set()
        for year in sub.get("pyq") or []:
            y = year.get("year")
            if y in years:
                fail(f"optional {sid!r} lists {y} twice")
            years.add(y)
            codes = [p.get("code") for p in year.get("papers") or []]
            if codes != ["p1", "p2"]:
                fail(f"optional {sid!r} {y} has papers {codes}, expected ['p1', 'p2']")

        for copy in sub.get("copies") or []:
            for field in ("name", "year", "publisher", "url"):
                if field not in copy:
                    fail(f"optional {sid!r} copy {copy.get('name', '?')!r} has no {field!r}")

    if not seen:
        fail("optionals.json lists no subjects")


DAILY_FIELDS = re.compile(r"\{(yyyy|mm|dd|d|month)\}")


def check_daily(daily) -> None:
    """The daily quiz is reached by expanding a URL template against the date,
    so the template has to actually carry the date. A pattern missing {yyyy}
    would silently point at the same day forever."""
    srcs = daily.get("sources") or []
    if not srcs:
        fail("daily.json lists no sources")

    seen: set[str] = set()
    for src in srcs:
        sid = src.get("id", "?")
        for field in ("id", "name", "url", "index", "questions"):
            if field not in src:
                fail(f"daily source {sid!r} has no {field!r}")
        if sid in seen:
            fail(f"duplicate daily source id {sid!r}")
        seen.add(sid)

        url = src.get("url", "")
        fields = set(DAILY_FIELDS.findall(url))
        if not {"yyyy", "month"} <= fields and not {"yyyy", "mm"} <= fields:
            fail(f"daily source {sid!r} url has no date in it: {sorted(fields)}")
        for stray in re.findall(r"\{([a-z_]+)\}", url):
            if stray not in ("yyyy", "mm", "dd", "d", "month"):
                fail(f"daily source {sid!r} url uses unknown placeholder {{{stray}}}")

        for day in src.get("skips") or []:
            if not isinstance(day, int) or not 0 <= day <= 6:
                fail(f"daily source {sid!r} skips {day!r}; want 0-6, Sunday first")

        if not isinstance(src.get("questions"), int) or src["questions"] < 1:
            fail(f"daily source {sid!r} has questions={src.get('questions')!r}")


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
    print(f"TaraCmd build - {date.today().isoformat()}")

    subjects = load("subjects.json")
    pyq = load("pyq-papers.json")
    toppers = load("toppers.json")
    keys = load("answer-keys.json")
    quiz = load("quiz.json")
    opts = load("optionals.json")
    daily = load("daily.json")

    topics = check_subjects(subjects)
    check_quiz(quiz, topics)
    check_keys(keys)
    check_paper_tags(quiz, keys)
    check_optionals(opts)
    check_daily(daily)

    if problems:
        print(f"\n{len(problems)} problem(s) in content:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    n_topics = len(topics)
    n_subtopics = sum(len(t["subtopics"]) for s in subjects for t in s["topics"])
    print(f"  {len(subjects)} subjects, {n_topics} topics, {n_subtopics:,} subtopics")

    data = {"__SUBJECTS__": subjects, "__PYQ__": pyq, "__TOPPERS__": toppers,
            "__KEYS__": keys, "__QUIZ__": quiz, "__OPTIONALS__": opts,
            "__DAILY__": daily}

    values = {t: json.dumps(v, ensure_ascii=False, separators=(",", ":"))
              for t, v in data.items()}
    values["__N_TOPICS__"] = f"{n_topics:,}"
    values["__N_SUBTOPICS__"] = f"{n_subtopics:,}"

    template = TEMPLATE.read_text(encoding="utf-8")

    # An unsubstituted token kills the build, and this is the check that does
    # it: every token in the template must have a value here. Anything else —
    # a typo'd token, a new one added to the template and not wired up — lands
    # in `missing`.
    missing = {m.group(0) for m in TOKEN.finditer(template)} - values.keys()
    if missing:
        return fatal(f"template wants tokens nothing fills: {', '.join(sorted(missing))}")

    # One pass, so token-shaped text inside content is never rescanned. Do not
    # add a "did any token survive?" sweep over the result: the check above
    # already makes that impossible for template tokens, so the only thing such
    # a sweep can match is a __LIKE_THIS__ string that came out of the JSON —
    # harmless page text that would then fail the build for nothing.
    rendered = TOKEN.sub(lambda m: values[m.group(0)], template)

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
