#!/usr/bin/env python3
"""Check one OCR of a paper against a second, independent one.

    python tools/pyq-crosscheck.py --year 2019 intake/scan-2019-gs1.json \\
                                              intake/drishti-2019-gs1.json

OCR of a scan cannot verify itself. The answers are safe -- they come from the
Commission's key by number, and build.py checks them again -- but the question
TEXT and, worse, the NUMBERING rest on the reader having got the geometry right.
The tool that produced them says so, and refuses to vouch for a paper that did
not come out whole.

A second scan settles it. UPSC publishes one Series; Drishti publishes another
of the same paper. Two different printings, two different scans, two runs of
OCR that share no failure: where they agree, the text is right.

**The two Series are in different orders, and the answer key says exactly how.**
UPSC builds the Series by shuffling blocks of questions, so the permutation that
tools/keycheck.py already recovers is a lookup from one Series' numbering to
another's. That mapping is not guessed: the dropped question sits at a different
number in every Series, and it maps onto itself in every year checked, while
every mapped pair carries the same key letter.

So a match here corroborates three separate things at once -- that the question
text was read correctly, that it was given the right number, and that its
options are in the order the key expects.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def blocks(v: str, b: int) -> list[str]:
    return [v[i * b:(i + 1) * b] for i in range(len(v) // b)]


def mapper(keys: dict, src: str, dst: str = "A"):
    """A function from a number in Series `src` to the same question's number
    in Series `dst`."""
    K = {s: "".join(v) for s, v in keys.items()}
    n = len(K[dst])
    size = next((b for b in range(n // 2, 4, -1)
                 if n % b == 0
                 and all(Counter(blocks(K[s], b)) == Counter(blocks(K[dst], b)) for s in K)), None)
    if not size:
        return None, None
    base = blocks(K[dst], size)
    perm = [base.index(x) + 1 for x in blocks(K[src], size)]
    return (lambda m: (perm[(m - 1) // size] - 1) * size + (m - 1) % size + 1), size


NOISE = re.compile(r"[^a-z0-9 ]")


def norm(s: str) -> str:
    return " ".join(NOISE.sub(" ", s.lower()).split())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("a", type=Path, help="a staged scan")
    ap.add_argument("b", type=Path, help="a staged scan of the same paper, another Series")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--code", default="gs1")
    ap.add_argument("--agree", type=float, default=0.72,
                    help="similarity above which two readings count as the same question")
    args = ap.parse_args()

    keys = json.loads((ROOT / "content" / "answer-keys.json").read_text(encoding="utf-8"))
    year = next((y for y in keys["years"] if y["year"] == args.year), None)
    paper = next((p for p in (year or {}).get("papers", []) if p["code"] == args.code), None)
    if not paper or not paper.get("keys"):
        sys.exit(f"no verified key for {args.year} {args.code}; cross-checking needs one")

    da = json.loads(args.a.read_text(encoding="utf-8"))
    db = json.loads(args.b.read_text(encoding="utf-8"))
    sa, sb = da.get("paperSet"), db.get("paperSet")
    if not sa or not sb:
        sys.exit("both files must say which Series they are")
    if sa == sb:
        print(f"both are Series {sa} — the same order, so this compares like with like")

    to_a, size = mapper(paper["keys"], sb, sa)
    if not to_a:
        sys.exit("the four Series of this paper are not block permutations; cannot align them")

    A = {q["n"]: q for q in da["questions"]}
    B = {}
    for q in db["questions"]:
        B[to_a(q["n"])] = q

    both = sorted(set(A) & set(B))
    agree, differ, only_a, only_b = [], [], sorted(set(A) - set(B)), sorted(set(B) - set(A))
    for n in both:
        r = SequenceMatcher(None, norm(A[n]["q"])[:400], norm(B[n]["q"])[:400]).ratio()
        (agree if r >= args.agree else differ).append((n, round(r, 2)))

    print(f"{args.year} {args.code}: {args.a.name} is Series {sa}, {args.b.name} is Series {sb}")
    print(f"  aligned by the key's block permutation, blocks of {size}")
    print(f"  {len(A)} questions in one, {len(B)} in the other, {len(both)} in both")
    print(f"  {len(agree)} agree, {len(differ)} disagree")
    if only_a:
        print(f"  only in {sa}: {only_a[:20]}{' …' if len(only_a) > 20 else ''}")
    if only_b:
        print(f"  only in {sb} (these could fill gaps): {only_b[:20]}{' …' if len(only_b) > 20 else ''}")
    if differ:
        print("\n  disagreements, worst first:")
        for n, r in sorted(differ, key=lambda x: x[1])[:12]:
            print(f"    {n:3} ({r:.2f})")
            print(f"        {sa}: {' '.join(A[n]['q'].split())[:88]}")
            print(f"        {sb}: {' '.join(B[n]['q'].split())[:88]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
