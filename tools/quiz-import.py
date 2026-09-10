#!/usr/bin/env python3
"""Merge a batch of extracted questions into content/quiz.json.

    python3 tools/quiz-import.py staged.json --dry-run   # say what would happen
    python3 tools/quiz-import.py staged.json             # do it

Reading a paper is judgement — deciding which of the 242 topics a question
belongs to is not something a script should guess at. Everything AFTER that
judgement is mechanical, and mechanical work done by hand is where a bank of
questions quietly rots: an id that collides, an answer index off by one, the
same question imported twice from two test series that both lifted it.

So the staged file carries the judgement, and this carries the rest.

The staged file:

    {
      "source": {"name": "Vision IAS", "test": "PT Test 12", "year": 2026},
      "questions": [
        {"n": 1, "topic": "polity-basic-structure",
         "q": "...", "options": ["...", "...", "...", "..."],
         "answer": 1, "why": "..."}
      ]
    }

`source` names the test series the batch came from and is stamped on every
question in it. For genuine UPSC papers use `paper` on each question instead
— {year, code, set, n} — and build.py will mark the answers against the
Commission's own key. Nothing here may carry both.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUIZ = ROOT / "content" / "quiz.json"
SUBJECTS = ROOT / "content" / "subjects.json"


def load(path: Path):
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        sys.exit(f"missing: {path}")
    except json.JSONDecodeError as exc:
        sys.exit(f"{path.name} is not valid JSON: line {exc.lineno}, {exc.msg}")


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def stem_of(q: str) -> str:
    """A question's identity for the purpose of noticing it twice.

    Whitespace and case only. Nothing cleverer on purpose: a stemmer that
    decided two genuinely different questions were the same would silently
    drop one, and a false match is worse here than a missed one."""
    return " ".join((q or "").lower().split())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("staged", type=Path)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be imported, write nothing")
    args = ap.parse_args()

    batch = load(args.staged)
    quiz = load(QUIZ)
    subjects = load(SUBJECTS)

    topics = {t["id"] for s in subjects for t in s["topics"]}
    existing = quiz.setdefault("questions", [])
    have_ids = {q.get("id") for q in existing}
    have_stems = {stem_of(q.get("q")): q.get("id") for q in existing}

    src = batch.get("source") or {}
    if not (src.get("name") or "").strip() and not any(q.get("paper") for q in batch.get("questions", [])):
        sys.exit("the batch has no `source` and its questions cite no `paper`: "
                 "a question with no provenance cannot be shown honestly")

    prefix = "-".join(x for x in (slug(src.get("name")), slug(src.get("test")),
                                  str(src.get("year") or "")) if x)

    taken, skipped = [], []
    for i, q in enumerate(batch.get("questions", []), 1):
        n = q.get("n", i)
        # A question that cites a UPSC cell takes its id FROM that cell.
        # Without this a paper-provenance batch got no prefix at all and every
        # question became "q-7" -- which worked exactly once, for whichever
        # paper was imported first, and then collided with every paper after
        # it. The cell is already unique: year, paper, Series, number.
        pc = q.get("paper")
        if q.get("id"):
            qid = q["id"]
        elif pc:
            qid = f"csp{str(pc['year'])[2:]}-{pc['code']}-{str(pc['set']).lower()}-{pc['n']}"
        else:
            qid = f"{prefix}-{n}" if prefix else f"q-{n}"
        why = []

        if qid in have_ids:
            why.append(f"id {qid!r} already in the bank")
        if q.get("topic") not in topics:
            why.append(f"topic {q.get('topic')!r} is not one of the {len(topics)}")
        opts = q.get("options") or []
        if not 2 <= len(opts) <= 6:
            why.append(f"{len(opts)} options")
        elif any(not str(o).strip() for o in opts):
            why.append("an option is empty")
        elif len({str(o).strip() for o in opts}) != len(opts):
            why.append("two options are identical, so two answers would be right")
        a = q.get("answer")
        if not isinstance(a, int) or not 0 <= a < len(opts):
            why.append(f"answer {a!r} is outside the options")
        if not (q.get("q") or "").strip():
            why.append("no question text")
        st = stem_of(q.get("q"))
        if st and st in have_stems:
            why.append(f"already asked, as {have_stems[st]!r}")
        if q.get("paper") and src.get("name"):
            why.append("cites a UPSC paper and a test series at once")

        if why:
            skipped.append((qid, why))
            continue

        out = {"id": qid, "topic": q["topic"], "q": q["q"].strip(),
               "options": [str(o).strip() for o in opts], "answer": a}
        if (q.get("why") or "").strip():
            out["why"] = q["why"].strip()
        if q.get("paper"):
            out["paper"] = q["paper"]
        elif src.get("name"):
            out["source"] = {k: v for k, v in src.items() if v}

        taken.append(out)
        have_ids.add(qid)
        if st:
            have_stems[st] = qid

    print(f"{len(taken)} question(s) to import, {len(skipped)} skipped")
    for qid, why in skipped:
        print(f"  - {qid}: {'; '.join(why)}")

    if args.dry_run:
        print("\n--dry-run: content/quiz.json untouched")
        return 0
    if not taken:
        print("\nnothing to write")
        return 0

    existing.extend(taken)
    with QUIZ.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(quiz, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"\nwrote content/quiz.json — {len(existing)} question(s) in the bank")
    print("run `python build.py` next; it re-checks all of this and marks any "
          "UPSC-tagged answers against the Commission's key")
    return 0


if __name__ == "__main__":
    sys.exit(main())
