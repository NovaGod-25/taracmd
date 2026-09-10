#!/usr/bin/env python3
"""Check a hand-read UPSC answer key, and only then let it into the content.

    python tools/keycheck.py intake/key-2017-gs1.json
    python tools/keycheck.py intake/key-2017-gs1.json --write

Every answer key the Commission publishes is a photograph of a printed grid --
four pages, one per Series, no text layer in any of them. So the letters are
read off the page by eye, and the question is how you know you read them right.

You know because of how UPSC builds the four Series. **A, B, C and D are the
same blocks of questions in a different order.** Every block of Set A reappears
intact somewhere in B, C and D, which means each letter is effectively read four
times, from four different places on four different pages. Get one letter wrong
anywhere and its block matches nothing.

**The block size is not fixed, and assuming it is will reject a good key.**
2022 and 2023 shuffle ten blocks of ten; 2017 shuffles four blocks of
twenty-five, and its permutations are involutions -- B = A[2,1,4,3], C =
A[4,3,1,2], D = A[3,4,2,1]. So the size is discovered here, largest first,
because the bigger the block the more a misread has to survive to pass.

That the option order is untouched shows up independently: all four Series carry
the identical distribution of letters. If UPSC ever reorders options between
Series, that distribution breaks first and this whole method stops applying.

None of it is a heuristic. This tool tries every single-letter change to Set A --
400 of them -- and confirms all 400 break the property. So a key that passes
here cannot contain a single misread letter.

Three further checks, because the property alone would accept a key that is
internally consistent and still not the paper in front of you:

    dropped     the Commission prints "No. of Questions Dropped" on each page.
                An X must appear exactly that many times, in every Series.
    alphabet    only A-D and X. A stray letter is a slip of the hand.
    length      exactly as many letters as the paper had questions.

**A cell can accept two letters.** 2021's CSAT key prints "C or D" against one question
in each Series. Give it a placeholder letter and say what it stands for --
`"either": {"E": "CD"}` -- and the placeholder moves through the blocks like any
other letter, so it is checked four times too, and is written out as "CD".

The input is what you read, nothing more:

    {"year": 2017, "code": "gs1", "dropped": 1,
     "rows": {"A": ["ABBADDCADD", ...ten rows of ten...], "B": [...], ...}}

Ten rows of ten rather than one string of a hundred, because a transcription
you can lay beside the page is one you can check. (The page itself is usually
set as columns of fifteen or twenty; the rows here are for reading back.) --write puts it into content/answer-keys.json, and refuses to
overwrite a key that is already there.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETS = ("A", "B", "C", "D")
LETTERS = set("ABCDX")


def fail(msg: str) -> None:
    print(f"  REJECTED: {msg}")


def cover(v: str, A: str, budget: int = 200000):
    """Spell v out of runs of A, each letter of A used exactly once.

    Longest runs first, backing off when that strands the rest: a run can
    carry on a letter past the end of its passage by coincidence -- 2018's
    Series D takes question 11 along with 1-10 -- and taking it leaves the
    tail with nowhere to go. Bounded, so a misread key fails quickly rather
    than searching for ever."""
    n = len(A)
    used, out, left = [False] * n, [], [budget]

    def go(i):
        if i == n:
            return True
        left[0] -= 1
        if left[0] < 0:
            return False
        cands = []
        for j in range(n):
            L = 0
            while i + L < n and j + L < n and not used[j + L] and v[i + L] == A[j + L]:
                L += 1
            if L:
                cands.append((L, j))
        for L0, j in sorted(cands, reverse=True):
            for L in range(L0, 0, -1):
                for t in range(j, j + L):
                    used[t] = True
                out.append((j, L))
                if go(i + L):
                    return True
                out.pop()
                for t in range(j, j + L):
                    used[t] = False
        return False
    return out if go(0) else None


def runs_partition(keys: dict):
    """Set A cut wherever another Series' longest matching run starts or ends.

    For a paper whose blocks are not one size -- CSAT's are passages -- the
    blocks are read off the Series themselves: walk B, C and D, take the
    longest stretch of A each place matches, and every edge of every such
    stretch is a cut in A."""
    A = keys["A"]
    n = len(A)
    cuts = {0, n}
    for s in "BCD":
        got = cover(keys[s], A)
        if got is None:
            return None
        for j, L in got:
            cuts.update((j, j + L))
    c = sorted(cuts)
    # A run that happens to carry on a letter past the end of its passage
    # leaves a cut one letter off the true one, and a one-letter splinter
    # beside it. Two neighbouring blocks that stay together in every Series
    # are one passage, so merge them -- the smallest splinters first.
    merged = True
    while merged:
        merged = False
        order = sorted(range(1, len(c) - 1), key=lambda k: min(c[k] - c[k - 1], c[k + 1] - c[k]))
        for k in order:
            trial = c[:k] + c[k + 1:]
            parts = [A[trial[m]:trial[m + 1]] for m in range(len(trial) - 1)]
            if all(decomposes(keys[s], parts) for s in "BCD"):
                c, merged = trial, True
                break
    return [A[c[k]:c[k + 1]] for k in range(len(c) - 1)]


def decomposes(v: str, parts: list) -> bool:
    """Is v exactly these blocks, each used once, in some order?"""
    from collections import Counter

    def go(i, need):
        if i == len(v):
            return not +need
        for b in list(need):
            if need[b] and v.startswith(b, i):
                need[b] -= 1
                if go(i + len(b), need):
                    return True
                need[b] += 1
        return False
    return go(0, Counter(parts))


def uneven(keys: dict, n: int, counts: dict, drops: dict) -> tuple[bool, dict]:
    parts = runs_partition(keys)
    if not parts or not all(decomposes(keys[s], parts) for s in "BCD"):
        fail("the four Series are not permutations of one another, at any block "
             "size or as passages -- either a letter is misread, or this paper "
             "was not built the way every other one was")
        return False, {}
    lens = [len(p) for p in parts]
    # Blocks this short would match somewhere by chance, and then a misread
    # could hide inside one. Four is the least that still proves something.
    if min(lens) < 4:
        fail(f"the passages come out as blocks of {lens} -- too short to prove anything")
        return False, {}
    tried = survived = 0
    A = keys["A"]
    for i in range(n):
        for c in "ABCDX":
            if c == A[i]:
                continue
            tried += 1
            m = A[:i] + c + A[i + 1:]
            mparts, k = [], 0
            for L in lens:
                mparts.append(m[k:k + L]); k += L
            if all(decomposes(keys[s], mparts) for s in "BCD"):
                survived += 1
    if survived:
        fail(f"{survived} single-letter misreadings would have gone unnoticed")
        return False, {}
    where = ", ".join(f"{s} at {drops[s]}" for s in SETS) if counts["A"] else "none"
    print(f"  {n} letters a Series, {counts['A']} dropped ({where})")
    print(f"  built from {len(parts)} passages of {lens} questions, shuffled whole")
    print(f"  {tried} single-letter mutations of Set A tried, none survived")
    return True, keys


def check(year: int, code: str, rows: dict, dropped: int | None,
          either: dict | None = None) -> tuple[bool, dict]:
    ok = True
    keys = {}

    # GS-I is a hundred questions, CSAT (gs2) eighty -- ten rows of ten, or eight
    want = {"gs2": 8}.get(code, 10)
    for s in SETS:
        if s not in rows:
            fail(f"set {s} is missing"); return False, {}
        r = rows[s]
        if len(r) != want or any(len(x) != 10 for x in r):
            fail(f"set {s} is not {want} rows of ten: {[len(x) for x in r]}"); ok = False
        v = "".join(r)
        # a placeholder stands for a cell the Commission accepts two letters in
        bad = sorted(set(v) - LETTERS - set(either or {}))
        if bad:
            fail(f"set {s} has letters that are not A-D or X: {bad}"); ok = False
        keys[s] = v
    if not ok:
        return False, {}

    n = len(keys["A"])
    if any(len(v) != n for v in keys.values()):
        fail("the four Series are different lengths"); return False, {}

    # the Commission prints the count on every page
    drops = {s: [i + 1 for i, c in enumerate(v) if c == "X"] for s, v in keys.items()}
    counts = {s: len(d) for s, d in drops.items()}
    if len(set(counts.values())) != 1:
        fail(f"the Series disagree on how many questions were dropped: {counts}"); ok = False
    elif dropped is not None and counts["A"] != dropped:
        fail(f"the page says {dropped} dropped, the letters carry {counts['A']}"); ok = False

    # The property. The block size is NOT always ten: 2022 and 2023 shuffle
    # ten blocks of ten, 2017 shuffles four blocks of twenty-five. So find it
    # rather than assume it, and take the LARGEST that works — the bigger the
    # block, the more a misread has to survive to go unnoticed.
    from collections import Counter

    def blocks(v, b):
        return [v[i * b:(i + 1) * b] for i in range(len(v) // b)]

    def holds(b):
        want = Counter(blocks(keys["A"], b))
        return all(Counter(blocks(keys[s], b)) == want for s in "BCD")

    sizes = [b for b in range(n // 2, 4, -1) if n % b == 0 and holds(b)]
    if not sizes:
        # CSAT keeps a passage's questions together, so its blocks are
        # passages -- seven questions, thirteen, eight -- not a fixed size
        return uneven(keys, n, counts, drops)
    b = sizes[0]
    nb = n // b

    A = blocks(keys["A"], b)
    # Two blocks of Set A can be identical -- 2026 has two "DACBB" among its
    # twenty blocks of five -- and then index() names the first every time.
    # The check itself is a multiset comparison and is unaffected; only this
    # readout would mislead, so it says so rather than printing a permutation
    # that is not one.
    dupes = len(A) - len(set(A))
    perms = {}
    for s in "BCD":
        perms[s] = [A.index(x) + 1 for x in blocks(keys[s], b)]

    # and the reason to believe it
    tried = survived = 0
    want = Counter(A)
    for i in range(n):
        for c in "ABCDX":
            if c == keys["A"][i]:
                continue
            tried += 1
            m = keys["A"][:i] + c + keys["A"][i + 1:]
            got = Counter(blocks(m, b))
            if all(Counter(blocks(keys[s], b)) == got for s in "BCD"):
                survived += 1
    if survived:
        fail(f"{survived} single-letter misreadings would have gone unnoticed")
        return False, {}

    where = ", ".join(f"{s} at {drops[s]}" for s in SETS) if counts["A"] else "none"
    print(f"  {n} letters a Series, {counts['A']} dropped ({where})")
    print(f"  built from {nb} block(s) of {b}, shuffled")
    if dupes:
        print(f"  ({dupes} of Set A's blocks are repeats of another, so the "
              f"positions below name the first match, not a unique one)")
    for s in "BCD":
        rev = " — an exact reversal of A" if perms[s] == list(range(nb, 0, -1)) else ""
        print(f"  {s} = A blocks {perms[s]}{rev}")
    print(f"  {tried} single-letter mutations of Set A tried, none survived")
    return True, keys


def write(year: int, code: str, keys: dict, either: dict | None = None) -> int:
    p = ROOT / "content" / "answer-keys.json"
    raw = p.read_text(encoding="utf-8")
    data = json.loads(raw)
    y = next((y for y in data["years"] if y["year"] == year), None)
    if not y:
        sys.exit(f"content/answer-keys.json has no {year}; add the year first")
    paper = next((x for x in y.get("papers", []) if x["code"] == code), None)
    if not paper:
        sys.exit(f"{year} has no paper {code}")
    if paper.get("keys"):
        sys.exit(f"{year} {code} already has letters — delete them first if you mean to replace")
    paper["keys"] = {s: [(either or {}).get(c, c) for c in v] for s, v in keys.items()}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2)
                 + ("\n" if raw.endswith("\n") else ""), encoding="utf-8", newline="\n")
    print(f"  written into content/answer-keys.json")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("staged", type=Path, nargs="+")
    ap.add_argument("--write", action="store_true",
                    help="on success, put it into content/answer-keys.json")
    args = ap.parse_args()

    bad = 0
    for f in args.staged:
        d = json.loads(f.read_text(encoding="utf-8"))
        print(f"{d['year']} {d['code']}  ({f.name})")
        ok, keys = check(d["year"], d["code"], d["rows"], d.get("dropped"), d.get("either"))
        if not ok:
            bad += 1
        elif args.write:
            write(d["year"], d["code"], keys, d.get("either"))
        print()
    if bad:
        print(f"{bad} key(s) rejected — nothing written for those")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
