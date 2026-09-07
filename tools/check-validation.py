#!/usr/bin/env python3
"""Prove build.py's validation actually fires.

    python3 tools/check-validation.py

Each case copies content/, templates/ and build.py into a throwaway directory,
breaks exactly one thing, and asserts the build dies with a message that names
the real problem. The repo itself is never touched.

This exists because the validation is the part of build.py most likely to be
quietly wrong: it only runs when content is already broken, so a bug in it
hides until the day it was supposed to save you. It has already earned its
keep once — it caught a redundant post-substitution token sweep that could
only ever misfire on legitimate page text.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable

# A Windows console is cp1252, and build.py's messages are echoed back here
# verbatim. Without this, one non-ASCII character in a message crashes the
# whole run with UnicodeEncodeError instead of reporting a result.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def fresh(tmp: Path) -> Path:
    root = tmp / "repo"
    root.mkdir()
    shutil.copy(REPO / "build.py", root / "build.py")
    shutil.copytree(REPO / "content", root / "content")
    shutil.copytree(REPO / "templates", root / "templates")
    return root


def run(root: Path):
    # Force the child to speak UTF-8 down the pipe. Left to itself on Windows
    # it writes the locale encoding, and content/*.json legitimately contains
    # en-dashes ("Rajouri-Poonch-Kishtwar" is spelled with them), so an error
    # naming such a topic would come back as mojibake.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([PY, "build.py"], cwd=root, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    return p.returncode, (p.stdout + p.stderr)


def edit(root: Path, name: str, fn):
    path = root / "content" / name
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


CASES = []


def case(label, expect):
    """expect=None means the build must SUCCEED."""
    def deco(fn):
        CASES.append((label, expect, fn))
        return fn
    return deco


@case("baseline, untouched", None)
def _(root):
    pass


@case("duplicate topic id", "duplicate topic id")
def _(root):
    # Progress is keyed on the topic id, so two topics sharing one would
    # silently share their revision ticks.
    def m(d):
        d[1]["topics"][0]["id"] = d[0]["topics"][0]["id"]
    edit(root, "subjects.json", m)


@case("quiz points at unknown topic", "unknown topic")
def _(root):
    def m(d):
        d["questions"][0]["topic"] = "no-such-topic"
    edit(root, "quiz.json", m)


@case("answer-key array too short", "letters for a")
def _(root):
    # A short key means the scorer marks the tail of the paper blank.
    def m(d):
        d["years"][2]["papers"][0]["keys"] = {"A": ["A", "B", "C"]}
    edit(root, "answer-keys.json", m)


@case("stray letter in a key set", "contains")
def _(root):
    def m(d):
        n = d["marking"]["gs1"]["questions"]
        d["years"][2]["papers"][0]["keys"] = {"A": ["A"] * (n - 1) + ["E"]}
    edit(root, "answer-keys.json", m)


@case("quiz answer index out of range", "outside its")
def _(root):
    def m(d):
        d["questions"][0]["answer"] = 9
    edit(root, "quiz.json", m)


@case("paper the app cannot label", "cannot label")
def _(root):
    def m(d):
        d[0]["topics"][0]["papers"] = ["mains-gs9"]
    edit(root, "subjects.json", m)


@case("bad weight band", "not one of")
def _(root):
    def m(d):
        d[0]["topics"][0]["weight"] = "very high"
    edit(root, "subjects.json", m)


@case("template token nothing fills", "tokens nothing fills")
def _(root):
    p = root / "templates" / "index.html"
    p.write_text(
        p.read_text(encoding="utf-8").replace("<title>", "<!--__NOPE__--><title>"),
        encoding="utf-8")


@case("token-shaped text inside content is fine", None)
def _(root):
    # Must NOT fail: this is page text, not a token.
    def m(d):
        d[0]["topics"][0]["subtopics"][0] = "A subtopic mentioning __NOT_A_TOKEN__"
    edit(root, "subjects.json", m)


@case("duplicate optional subject id", "duplicate optional subject id")
def _(root):
    # The answer log is keyed year-<subject id>-<code>, so two subjects sharing
    # an id would pour their logged answers into one pile.
    def m(d):
        d["subjects"][1]["id"] = d["subjects"][0]["id"]
    edit(root, "optionals.json", m)


@case("optional year with wrong paper codes", "expected ['p1', 'p2']")
def _(root):
    def m(d):
        d["subjects"][0]["pyq"][0]["papers"] = [{"code": "gs1", "name": "x", "url": None}]
    edit(root, "optionals.json", m)


@case("optional year listed twice", "twice")
def _(root):
    def m(d):
        d["subjects"][0]["pyq"].append(dict(d["subjects"][0]["pyq"][0]))
    edit(root, "optionals.json", m)


@case("topper copy missing a field", "has no")
def _(root):
    def m(d):
        d["subjects"][0]["copies"] = [{"name": "Someone", "year": 2025}]
    edit(root, "optionals.json", m)


@case("daily url with no date in it", "no date in it")
def _(root):
    # A pattern without the date would point at the same day forever.
    def m(d):
        d["sources"][0]["url"] = "https://example.com/todays-quiz/"
    edit(root, "daily.json", m)


@case("daily url with unknown placeholder", "unknown placeholder")
def _(root):
    def m(d):
        d["sources"][0]["url"] = "https://example.com/{yyyy}/{mm}/{weekday}/q/"
    edit(root, "daily.json", m)


@case("daily skips out of range", "want 0-6")
def _(root):
    def m(d):
        d["sources"][0]["skips"] = [7]
    edit(root, "daily.json", m)


@case("malformed JSON", "not valid JSON")
def _(root):
    (root / "content" / "quiz.json").write_text('{"questions": [', encoding="utf-8")


@case("missing content file", "missing content file")
def _(root):
    (root / "content" / "toppers.json").unlink()


def main() -> int:
    ok = bad = 0
    for label, expect, mutate in CASES:
        with tempfile.TemporaryDirectory() as td:
            root = fresh(Path(td))
            mutate(root)
            code, out = run(root)

            if expect is None:
                passed = code == 0
                detail = "exit 0" if passed else f"exit {code}, expected success"
            else:
                passed = code != 0 and expect in out
                line = next((l.strip() for l in out.splitlines() if expect in l), "")
                detail = f"exit {code}: {line[:80]}" if passed \
                    else f"exit {code}, expected {expect!r}"

            print(f"  {'ok  ' if passed else 'FAIL'} {label:42} {detail}")
            ok, bad = (ok + 1, bad) if passed else (ok, bad + 1)

    print(f"\n{ok} passed, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
