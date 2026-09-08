#!/usr/bin/env python3
"""Read a UPSC Prelims question paper into staged questions.

    python3 tools/pyq-ocr.py tools/.key-pdfs/QP-2022-gs1.pdf --year 2022 --code gs1

The Commission publishes its papers as scans — 48 pages of photographs with
not one character of text in them — so this is OCR, and OCR is a draft rather
than a transcript. What comes out is staged for review, never imported
straight into the bank.

Three things make it good enough to be worth reviewing:

  columns   the paper is two columns and Tesseract reads straight across
            them, interleaving question 41 with question 43 into nonsense.
            Cropping each column and reading it alone is the single change
            that turns unusable output into near-clean text.
  language  every question is printed twice, in Hindi and in English. The
            Devanagari pages come back as noise under an English model, so
            pages are kept or dropped on how much real English is in them.
  answers   are NOT read from the paper. The set is stamped in the page
            footer — "(21-A)" is page 21 of Series A — and the letters come
            from content/answer-keys.json, which was transcribed and checked
            against the Commission's own key. So the one thing OCR cannot be
            trusted with is the one thing it is not asked to do.

HOW GOOD IS IT, MEASURED ON CS(P)-2022 GS-I, ALL 48 PAGES

It locates 79 of the 100 questions and gets the Series right. The text is a
long way from usable, and the numbers are here so nobody has to rediscover
them:

    26 of 79   carry text bled in from the neighbouring column
    22 of 79   swallowed the page footer into an option
   164 options have a digit read as a letter — "1 and 2 only" comes back as
               "land 2 only", which for a paper this full of "which of the
               statements given above are correct" changes the answer
    21         questions not found at all

So this is a STARTING POINT, not a transcript, and the last of those defects
is the one that matters: an option that quietly says something different from
what was printed teaches the wrong thing, and it does it without looking
broken. Every question needs reading against the paper before it is imported.

What would have to improve before that stops being true: find the gutter by
pixel projection instead of assuming it sits at 52% of the width; crop the
footer off before OCR rather than filtering it afterwards; and put a
digit-versus-letter pass over the options, where the damage is concentrated.

Worth knowing before reaching for this at all: a TYPESET paper — anything a
coaching institute exports from Word — has a real text layer and needs none
of this. The intake folder exists for those. OCR is only for UPSC's own
papers, which are photographs, and it is the slow, error-prone path.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

Q_START = re.compile(r"^\s*(\d{1,3})\s*[.,]\s+(.*)$")
OPT = re.compile(r"^\s*\(\s*([a-dA-DqQ])\s*\)\s*(.*)$")
# "VGYH-U-FGT (21-A)" — page 21, Series A. The closing bracket is often the
# first thing OCR loses at the trimmed edge of a scan, and the dash comes back
# as a hyphen, an en dash or an em dash depending on the page, so require
# neither.
FOOTER_SET = re.compile(r"\(\s*\d{1,3}\s*[-–—]\s*([A-D]\b)")


def ocr(img, tmp: Path, psm: str = "4") -> str:
    img = img.resize((img.width * 3, img.height * 3))
    img.save(tmp)
    r = subprocess.run([TESS, str(tmp), "stdout", "--psm", psm],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout or ""


def englishness(t: str) -> float:
    """How much of this looks like English prose rather than mangled
    Devanagari. The Hindi half of the paper comes back as noise, and noise is
    mostly short non-words."""
    words = re.findall(r"[A-Za-z]+", t)
    if len(words) < 20:
        return 0.0
    real = [w for w in words if len(w) >= 4]
    return len(real) / len(words)


def columns(img):
    W, H = img.size
    # A little overlap, so a letter sitting on the gutter is not sliced away.
    yield img.crop((0, 0, int(W * 0.52), H))
    yield img.crop((int(W * 0.48), 0, W, H))


def parse(lines: list[str], total: int) -> list[dict]:
    """Numbered stems, then (a)-(d).

    The catch: a UPSC question is itself full of numbered lines. "Consider the
    following statements: 1. … 2. … 3. …" looks exactly like the start of
    questions 1, 2 and 3, and taking them as such both invents questions and
    swallows the real one they were inside. Nothing about a line distinguishes
    the two.

    What does distinguish them is the sequence. The paper is numbered 1 to
    100 in order, so only the number we are actually expecting next can start
    a question — anything else, at that point in the page, is a statement.
    """
    out, cur, opt = [], None, None
    expect = 1
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        m = Q_START.match(line)
        # a small forward window, so one question lost to a bad scan does not
        # derail every question after it
        if m and not (expect <= int(m.group(1)) <= min(expect + 3, total)):
            m = None
        if m and (cur is None or len(cur["options"]) >= 2):
            expect = int(m.group(1)) + 1
            if cur:
                out.append(cur)
            cur = {"n": int(m.group(1)), "q": m.group(2).strip(), "options": []}
            opt = None
            continue
        if cur is None:
            continue
        m = OPT.match(line)
        if m:
            letter = m.group(1).lower()
            letter = "d" if letter == "q" else letter        # "(dq)" happens
            cur["options"].append(m.group(2).strip())
            opt = len(cur["options"]) - 1
            continue
        # a continuation line belongs to whatever it followed
        if opt is not None:
            cur["options"][opt] += " " + line.strip()
        else:
            cur["q"] += " " + line.strip()
    if cur:
        out.append(cur)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--code", default="gs1")
    ap.add_argument("--set", dest="setname", help="override the set read from the footer")
    ap.add_argument("--pages", help="1-based range, e.g. 5-25, for a quick look")
    ap.add_argument("--out", type=Path, default=ROOT / "intake" / "staged-pyq.json")
    args = ap.parse_args()

    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("needs pypdf:  python -m pip install pypdf pillow")

    tmp = ROOT / "tools" / ".ocr-page.png"
    tmp.parent.mkdir(exist_ok=True)
    reader = PdfReader(str(args.pdf))
    lo, hi = 1, len(reader.pages)
    if args.pages:
        a, _, b = args.pages.partition("-")
        lo, hi = int(a), int(b or a)

    text, sets = [], []
    for i in range(lo - 1, min(hi, len(reader.pages))):
        page = reader.pages[i]
        im = next(iter(page.images), None)
        if im is None:
            continue
        img = im.image.convert("L")
        for col in columns(img):
            t = ocr(col, tmp)
            # Measured across the whole 2022 GS-I paper: the English columns
            # score 0.52 to 0.66 and the Hindi ones 0.19 to 0.38. The gap is
            # wide and the cut belongs in the middle of it — 0.55 sat inside
            # the English band and quietly dropped real pages.
            if englishness(t) < 0.45:
                continue
            found = FOOTER_SET.search(t)
            if found:
                sets.append(found.group(1))
            text.extend(t.splitlines())
        print(f"  page {i+1}/{hi}", end="\r", flush=True)
    print(" " * 30, end="\r")

    setname = args.setname or (max(set(sets), key=sets.count) if sets else None)
    if not setname:
        sys.exit("could not read the Series from any page footer; pass --set")

    keys = json.loads((ROOT / "content" / "answer-keys.json").read_text(encoding="utf-8"))
    year = next((y for y in keys["years"] if y["year"] == args.year), None)
    paper = next((p for p in (year or {}).get("papers", []) if p["code"] == args.code), None)
    letters = ((paper or {}).get("keys") or {}).get(setname)
    if not letters:
        sys.exit(f"no verified key for {args.year} {args.code} set {setname} — "
                 "the answers come from the key, not from the scan")

    qs, flagged = [], []
    for q in parse(text, len(letters)):
        n, why = q["n"], []
        if not 1 <= n <= len(letters):
            continue
        if len(q["options"]) != 4:
            why.append(f"{len(q['options'])} options")
        if letters[n - 1] == "X":
            why.append("the Commission dropped this one")
        if re.search(r"PM,|,,|\bug/m\b|[^\x00-\x7f]", q["q"] + " ".join(q["options"])):
            why.append("subscript or non-ascii lost in the scan")
        if len(q["q"]) < 20:
            why.append("stem looks truncated")

        item = {"n": n, "topic": "", "q": q["q"], "options": q["options"],
                "answer": "ABCD".find(letters[n - 1]) if letters[n - 1] != "X" else None,
                "paper": {"year": args.year, "code": args.code, "set": setname, "n": n}}
        if why:
            item["_review"] = why
            flagged.append(n)
        qs.append(item)

    qs.sort(key=lambda x: x["n"])
    seen, dedup = set(), []
    for q in qs:
        if q["n"] in seen:
            continue
        seen.add(q["n"])
        dedup.append(q)

    missing = [n for n in range(1, len(letters) + 1) if n not in seen]
    args.out.parent.mkdir(exist_ok=True)
    args.out.write_text(json.dumps(
        {"note": "OCR draft. Every question needs a topic, and every _review flag "
                 "needs a human before this is imported.",
         "paperSet": setname, "questions": dedup}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    print(f"set {setname}: {len(dedup)} of {len(letters)} questions read")
    print(f"  {len(flagged)} flagged for review: {flagged[:20]}{' …' if len(flagged) > 20 else ''}")
    print(f"  {len(missing)} not found: {missing[:20]}{' …' if len(missing) > 20 else ''}")
    print(f"\nwrote {args.out.relative_to(ROOT).as_posix()}")
    print("Nothing is imported yet. Topics are blank and must be filled in; the "
          "answers already come from the verified key rather than the scan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
