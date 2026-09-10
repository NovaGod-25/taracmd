#!/usr/bin/env python3
"""Suggest a topic for each staged question, ranked, for a person to confirm.

    python tools/topic-suggest.py intake/scan-2022-gs1.json
    python tools/topic-suggest.py intake/scan-2022-gs1.json --apply

Every question needs one of the 242 topic ids, and that link is what puts a
question in front of you when the topic falls due. Deciding it is judgement,
and for one paper it is worth doing cold. For ten papers it is a thousand
decisions, and a thousand decisions made carelessly are worse than a hundred
made properly.

So this narrows rather than decides. It scores a question against the words the
syllabus itself uses -- 242 topic names and 1,723 subtopics -- and prints the
best three with their margin. Where the winner is clear the suggestion is
almost always right; where it is not, the question is marked `weak` and wants a
human eye.

**Why a wrong topic here is survivable, and a wrong answer would not be.** The
answers on these questions come from the Commission's own key and are checked
again by build.py. A mis-filed question surfaces while you are revising a
neighbouring topic; a mis-keyed one teaches you something false. Those are not
the same kind of mistake, and only the second is worth refusing to make.

Scoring is IDF-weighted overlap. Plain word counting hands everything to
whichever topic mentions "India" most; weighting a word by how FEW topics use
it means "Kulah-Daran", "probiotics" and "Arthashastra" decide the match, which
is what a reader would do too.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STOP = set("""a an the and or of in on at to for from by with as is are was were be been being
this that these those it its which who whom whose what when where how why not no nor but if
then than so such can could may might will would shall should must have has had do does did
following consider statements statement correct given above only both neither one two three
four all none about into over under between among during before after also more most other
india indian indias year years new using used use""".split())

WORD = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")


def words(s: str) -> list[str]:
    return [w.lower() for w in WORD.findall(s) if w.lower() not in STOP]


def build_index():
    data = json.loads((ROOT / "content" / "subjects.json").read_text(encoding="utf-8"))
    subs = data["subjects"] if isinstance(data, dict) else data
    docs = {}
    for s in subs:
        for t in s["topics"]:
            bag = Counter()
            # the topic's own name counts for more than any one subtopic: it is
            # the label a reader would match against first
            for w in words(t["name"]):
                bag[w] += 3
            for w in words(s.get("name", "")):
                bag[w] += 1
            for st in t.get("subtopics", []):
                for w in words(st):
                    bag[w] += 1
            docs[t["id"]] = bag
    df = Counter()
    for bag in docs.values():
        for w in bag:
            df[w] += 1
    n = len(docs)
    idf = {w: math.log(n / (1 + c)) for w, c in df.items()}
    return docs, idf


def rank(text: str, docs, idf, k: int = 3):
    q = Counter(words(text))
    if not q:
        return []
    scores = {}
    for tid, bag in docs.items():
        s = 0.0
        for w, c in q.items():
            if w in bag:
                s += min(c, 3) * math.log(1 + bag[w]) * max(0.0, idf.get(w, 0.0))
        if s > 0:
            scores[tid] = s
    return sorted(scores.items(), key=lambda kv: -kv[1])[:k]


# An institute that files its own question under "Polity" has already made the
# coarse call, and made it well; the scorer only has to choose among polity's
# thirty topics instead of all 242. "Current Affairs" says nothing about subject.
SUBJECT_OF = {"polity": "polity", "economics": "economics", "economy": "economics",
              "history": "history", "modern history": "history", "ancient history": "history",
              "medieval history": "history", "art and culture": "history", "geography": "geography",
              "environment": "environment", "ecology": "environment", "science": "scitech",
              "science and technology": "scitech", "international relations": "ir",
              "security": "security", "internal security": "security"}


def subject_of(q: dict, src: dict) -> str | None:
    test = re.search(r" - ([A-Za-z &]+) \(V", (src or {}).get("test", ""))
    for label in ((q.get("hint") or "").split(" / ")[0], test.group(1) if test else ""):
        s = SUBJECT_OF.get(label.strip().lower())
        if s:
            return s
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("staged", type=Path, nargs="+")
    ap.add_argument("--apply", action="store_true",
                    help="write the top suggestion into each question's topic field")
    ap.add_argument("--show", action="store_true", help="print every question's top three")
    args = ap.parse_args()

    docs, idf = build_index()
    valid = set(docs)

    for f in args.staged:
        d = json.loads(f.read_text(encoding="utf-8"))
        qs = d["questions"]
        weak, filled = [], 0
        for q in qs:
            # an institute's explanation names the topic in its first lines far
            # more plainly than the question does
            text = " ".join([q["q"], " ".join(q.get("options", [])), q.get("hint", ""),
                             q.get("why", "")[:400]])
            subj = subject_of(q, d.get("source"))
            pool = {t: b for t, b in docs.items() if t.startswith(subj + "-")} if subj else docs
            top = rank(text, pool, idf)
            if not top:
                q["_topics"] = []
                weak.append(q["n"])
                continue
            q["_topics"] = [{"id": t, "score": round(s, 2)} for t, s in top]
            # a suggestion is only as good as its lead over the runner-up
            lead = top[0][1] / top[1][1] if len(top) > 1 and top[1][1] else 9.9
            q["_lead"] = round(lead, 2)
            if top[0][1] < 8 or lead < 1.25:
                weak.append(q["n"])
            if args.apply:
                q["topic"] = top[0][0]
                filled += 1
            if args.show:
                print(f"  {q['n']:3} {' '.join(q['q'].split())[:58]:58} "
                      + " | ".join(f"{t}({s:.0f})" for t, s in top))

        assert all(q.get("topic", "") in valid or not q.get("topic") for q in qs)
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{f.name}: {len(qs)} questions, {filled} topics written, "
              f"{len(weak)} weak ({len(weak)*100//max(1,len(qs))}%) {weak[:18]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
