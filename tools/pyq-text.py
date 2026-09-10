#!/usr/bin/env python3
"""Read a TYPESET question paper into staged questions. No OCR.

    python3 tools/pyq-text.py tools/.key-pdfs/drishti-2023-gs1.pdf --year 2023 --code gs1

The Commission publishes its own papers as photographs, so tools/pyq-ocr.py
exists and is a draft-maker at best. But a paper that somebody has typeset —
Drishti's 2023 GS-I is one, 51,508 characters of real text where every other
year on the same page is a scan — needs none of that. The text is already
there, exact, with no column bleed and no digit read as a letter.

So: always check for a text layer before reaching for OCR. Of the fourteen
years Drishti publishes, exactly one is typeset, and that one is worth more
than the other thirteen put together.

Three things need care, and all three were found by reading the output rather
than by reasoning about the format:

  numbering   a question is "12." at the start of a line, and so is the second
              statement inside question 11. Nothing about the line tells them
              apart. Two rules together do: only the number the paper is up to
              may start a question, and only once the question being built has
              reached its options.
  options     "(a) Andhra (b) Gandhara" is one line carrying two options; a
              long option wraps onto the next line with no marker at all; the
              space after the marker is not always there ("(c)The Charter
              Act"); and sometimes the opening bracket is missing entirely.
              The last of those is repaired before splitting, not by loosening
              the split -- a split loose enough to take a bare "b)" also takes
              the one inside "Article 39(b)".
  furniture   the advertising panel down the side of every page is emitted
              inline, so it lands BETWEEN option (b) and option (c) wherever a
              page breaks. See furniture(): it is found, not named.

Measured on Drishti's 2023 GS-I, which is the only typeset paper available:

    questions parsed        99 of 100
    flagged for review       0
    missing                  1   -- question 29 is absent from the source
                                    itself: the text runs 28 straight to 30

Compare tools/pyq-ocr.py on a scan of the same size: 79 located, 27 usable
without a look. A text layer is worth more than any amount of OCR tuning.

Answers are NOT taken from the paper: it does not carry them. They come from
content/answer-keys.json, matched by number against the Series the paper says
it is — so a question is only staged once the Commission's own letter for it
is known.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The separator after a question number is a full stop on the page, but OCR
# gives a comma often enough to lose a whole question -- 2022 renders "4."
# as "4," and it vanished. Statements are numbered the same way; what tells
# them apart is `started`, never the punctuation.
Q_START = re.compile(r"^\s*(\d{1,3})[.,]\s+(.*)$")
OPT_SPLIT = re.compile(r"\(([a-d])\)\s*")
# Sometimes the opening bracket is lost in the typesetting and an option is
# printed "b) Only two". Put the bracket back before splitting rather than
# loosening the split itself: a split that accepts a bare "b)" also accepts
# the one inside "Article 39(b)", and the trailing \s* the real markers need
# (options are not always spaced: "(c)The Charter Act") makes that worse.
# The lookbehind is what keeps "39(b)" and "(a)" out of it.
LOST_BRACKET = re.compile(r"(?<![A-Za-z0-9(])([a-d])\)(?=\s)")
SET_HINT = re.compile(r"\bSet\s*[-–]?\s*([A-D])\b", re.IGNORECASE)
# "VGYH-U-FGT (3-A)" and "VGYH-U-FGT (11-A)" are the same footer and not the
# same line, so furniture() -- which matches repeats exactly -- never drops
# them, and one lands inside the last option of a question on every page.
FOOTER = re.compile(r"\(\s*\d{1,3}\s*[-–—]\s*[A-D]\s*\)")
NOISE = re.compile(r"^\s*(general studies|upsc civil services|paper[- ]?i+|\d{1,3})\s*$", re.IGNORECASE)


def furniture(lines: list[str], pages: int) -> set[str]:
    """The lines that are page furniture rather than paper.

    Whoever typeset this one ran an advertising panel down every page, and
    pypdf emits it inline — so it lands in the MIDDLE of a question, between
    option (b) and option (c), wherever a page happens to break. Stripping
    from the first advert to the end of the question therefore takes the last
    two options with it, which is worse than leaving it in.

    So find it instead of naming it: a line that repeats on over half the
    pages and is short is a header, a footer or a banner. The two guards are
    what keep real paper out of it — "(a) Only one (b) Only two" repeats 36
    times in a paper like this, and every genuine repeated line is either an
    option or a long one."""
    from collections import Counter
    seen = Counter(l for l in lines if l)
    return {l for l, n in seen.items()
            if n > pages / 2 and len(l) <= 40
            and not OPT_SPLIT.search(l) and not Q_START.match(l)}

def split_options(chunk: str) -> list[str]:
    """Pull "(a) X (b) Y" apart, keeping what follows each marker.

    The paper sets short options two to a line and long ones one to a line,
    and a wrapped option carries no marker at all — so the split is on the
    markers themselves and everything between two of them belongs to the
    first."""
    parts = OPT_SPLIT.split(chunk)
    if len(parts) < 3:
        return []
    out, i = [], 1
    while i + 1 < len(parts) + 1 and i < len(parts):
        letter, text = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        out.append((letter, " ".join(text.split())))
        i += 2
    return [t for _, t in out]


def parse(text: str, total: int, pages: int = 1, window: int = 3,
          trust_sequence: bool = False) -> list[dict]:
    lines = [l.rstrip() for l in text.splitlines()]
    junk = furniture([l.strip() for l in lines], pages)
    out, cur, expect, buf = [], None, 1, []

    def flush():
        """Close the question being built: everything after the first option
        marker is options, everything before it is the stem."""
        if not cur:
            return
        blob = LOST_BRACKET.sub(lambda m: "(" + m.group(1) + ")", " ".join(buf))
        cut = blob.find("(a)")
        cur["q"] = " ".join(blob[:cut].split()) if cut > 0 else " ".join(blob.split())
        cur["options"] = split_options(blob[cut:]) if cut >= 0 else []
        out.append(cur)

    for raw in lines:
        line = raw.strip()
        if not line or line in junk or NOISE.match(line) or FOOTER.search(line):
            continue
        m = Q_START.match(raw)
        # Only the number the paper is up to may start a question, AND only
        # once the question being built has reached its options. Statements
        # come before the options and the next question comes after them, so
        # "3." inside question 2 is a statement — without this, question 2
        # loses its options and question 3 swallows both.
        started = cur is None or "(a)" in " ".join(buf)
        # `window` is how far ahead a question number may jump and still be
        # believed. Three is right for exact text. OCR needs more: a page it
        # cannot read is a hole of four or five questions, and too tight a
        # window means the paper never resyncs and everything after the hole
        # is lost. The guard against a statement being read as a question is
        # `started`, not this number.
        #
        # `trust_sequence` is for OCR, and it is the difference between 74 of
        # 100 and nearly all of them. Tesseract misreads the question NUMBERS
        # more often than the words -- on 2022 it gave 38 for 33, 84 for 34,
        # 386 for 36, 80 for 30, 88 for 38. Where a line is a question start
        # and the number is unreadable, its position in the paper is better
        # evidence than the glyph, so the number becomes the one the paper is
        # up to. What keeps a statement from being taken as a question is
        # `started` -- the question being built must already have reached its
        # options -- and that does not depend on reading any digit correctly.
        if m and started:
            got = int(m.group(1))
            take = (got if expect <= got <= min(expect + window, total)
                    else expect if trust_sequence and expect <= total
                    else None)
            if take is not None:
                flush()
                cur = {"n": take}
                buf = [m.group(2)]
                expect = take + 1
                continue
        if cur is not None:
            buf.append(line)
    flush()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--code", default="gs1")
    ap.add_argument("--set", dest="setname")
    ap.add_argument("--out", type=Path, default=ROOT / "intake" / "staged-pyq-text.json")
    args = ap.parse_args()

    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("needs pypdf:  python -m pip install pypdf")

    pages = PdfReader(str(args.pdf)).pages
    npages = len(pages)
    text = "\n".join((p.extract_text() or "") for p in pages)
    if len(text.strip()) < 5000:
        sys.exit(f"{args.pdf.name} has no usable text layer — this is a scan, "
                 "so it needs tools/pyq-ocr.py and a great deal more care")

    setname = args.setname
    if not setname:
        hit = SET_HINT.search(text)
        setname = hit.group(1).upper() if hit else None
    if not setname:
        sys.exit("could not tell which Series this paper is; pass --set")

    keys = json.loads((ROOT / "content" / "answer-keys.json").read_text(encoding="utf-8"))
    year = next((y for y in keys["years"] if y["year"] == args.year), None)
    paper = next((p for p in (year or {}).get("papers", []) if p["code"] == args.code), None)
    letters = ((paper or {}).get("keys") or {}).get(setname)
    total = (keys.get("marking", {}).get(args.code, {}) or {}).get("questions", 100)

    qs, flagged = [], []
    for q in parse(text, total, npages):
        why = []
        if not 1 <= q["n"] <= total:
            continue
        if len(q["options"]) != 4:
            why.append(f"{len(q['options'])} options")
        if len(q["q"]) < 20:
            why.append("stem looks truncated")
        if any(not o.strip() for o in q["options"]):
            why.append("an option came out empty")
        item = {"n": q["n"], "topic": "", "q": q["q"], "options": q["options"],
                "paper": {"year": args.year, "code": args.code, "set": setname, "n": q["n"]}}
        if letters:
            L = letters[q["n"] - 1]
            item["answer"] = None if L == "X" else "ABCD".find(L)
            if L == "X":
                why.append("the Commission dropped this one")
        if why:
            item["_review"] = why
            flagged.append(q["n"])
        qs.append(item)

    seen, dedup = set(), []
    for q in sorted(qs, key=lambda x: x["n"]):
        if q["n"] not in seen:
            seen.add(q["n"]); dedup.append(q)
    missing = [n for n in range(1, total + 1) if n not in seen]

    args.out.parent.mkdir(exist_ok=True)
    note = ("Parsed from a typeset PDF — no OCR. Every question still needs a topic."
            if letters else
            "Parsed from a typeset PDF — no OCR. NO ANSWERS: there is no verified key for "
            f"{args.year} {args.code} set {setname} in content/answer-keys.json yet, so these "
            "cannot be imported until one is transcribed.")
    args.out.write_text(json.dumps({"note": note, "paperSet": setname, "questions": dedup},
                                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"set {setname}: {len(dedup)} of {total} questions parsed")
    print(f"  {len(flagged)} flagged: {flagged[:20]}{' …' if len(flagged) > 20 else ''}")
    print(f"  {len(missing)} missing: {missing[:20]}{' …' if len(missing) > 20 else ''}")
    print(f"  answers: {'from the verified key' if letters else 'NONE — key not transcribed yet'}")
    print(f"\nwrote {args.out.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
