#!/usr/bin/env python3
"""Read a SCANNED UPSC question paper into staged questions, with OCR.

    python tools/pyq-scan.py tools/.qp-pdfs/qp-2022-gs1.pdf --year 2022 --code gs1

tools/pyq-text.py handles a paper with a text layer and should always be tried
first -- it is exact, and UPSC's own 2023 GS-I turns out to have one. Every
other year from 2016 to 2026 is a photograph: 48 pages, zero characters.

An earlier attempt at this (tools/pyq-ocr.py) located 79 questions of 100 and
left 26 carrying text bled in from the neighbouring column. That was not a
limit of OCR. The pages are clean printed English at about 150 dpi, and
tesseract reads them very nearly perfectly. What was wrong was the geometry:
the columns were split at a fixed 0.52 of the width.

**The page prints a rule between its two columns.** Find that and the split is
exact on every page, whatever the scan's margins do. On 2022 it sits at 0.486,
not 0.52, and that four per cent is the whole difference between bleeding and
not.

Finding it is the subtle part: NOT the column carrying the most ink, which on
three pages of 2022 is a column of text and puts the split at 0.64. A rule is
the longest UNBROKEN vertical run of ink -- text is many short runs, a rule is
one long one. Then take the median across the booklet, because a booklet is
printed to one layout and a page that disagrees has a faint rule rather than a
different design.

Three other things the format gives you for free:

  the Series   is printed in the page footer, "( 3 - A )". No need to be told
               which Series the booklet is, and getting it wrong would line the
               questions up against the wrong answer key.
  the language pages alternate English and Hindi. Hindi comes back from an
               English-only tesseract as plausible-looking latin noise, so
               pages are kept on whether they contain real English function
               words, not on their page number.
  the options  of a statement-reference question come from a tiny fixed
               vocabulary -- "1 and 2 only", "Both 1 and 2", "All three". OCR's
               one persistent error here is reading "1 and" as "land", and
               against a closed vocabulary that is repairable rather than
               merely detectable.

Answers are never taken from the paper. They come from content/answer-keys.json
by number against the Series the footer names, so a question is staged only
once the Commission's own letter for it is known.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# the parser is the same one the typeset reader uses -- numbering, options and
# page furniture do not change just because the words arrived through a camera
_spec = importlib.util.spec_from_file_location("pyq_text", Path(__file__).with_name("pyq-text.py"))
pyq_text = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pyq_text)

# Two footer formats. 2022 prints "( 3 - A )". 2019, 2021 and 2025 print a
# booklet code instead -- "BXC-U-FTHI/68A", "LVPK-O-PSO/56A" -- where the
# Series is the letter closing it. Reading the wrong one would line every
# question up against the wrong answer key, so both are looked for.
FOOTER_SET = re.compile(r"\(\s*\d+\s*[-–—]\s*([A-D])\s*\)"
                        r"|/\s*\d{1,3}\s*([A-D])")
# a page of English says these constantly; Hindi read as English says them never
ENGLISH = re.compile(r"\b(the|following|which|statements|consider|reference|correct|above)\b",
                     re.IGNORECASE)


def ocr(img, psm: int = 6) -> str:
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "c.png"
        img.save(f)
        r = subprocess.run([TESS, str(f), "stdout", "--psm", str(psm)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.stdout or ""


def rule_x(gray) -> int:
    """Where the printed rule between the two columns is.

    Not the column with the most ink -- a column of text can carry more ink
    than a hairline rule, and on three pages of 2022 it did, putting the split
    at 0.64 and interleaving both columns into nonsense. A rule is the longest
    UNBROKEN vertical run: text is many short runs, a rule is one long one.
    That finds the same 0.48-0.49 on every page of the paper, including the
    ones the ink test got wrong."""
    import numpy as np
    a = np.asarray(gray) < 160
    h, w = a.shape
    lo, hi = int(0.30 * w), int(0.70 * w)
    best_x, best = lo, 0
    for x in range(lo, hi):
        cur = run = 0
        for v in a[:, x]:
            cur = cur + 1 if v else 0
            if cur > run:
                run = cur
        if run > best:
            best, best_x = run, x
    return best_x if best > 0.06 * h else -1


def page_image(pg, Image):
    """The page as one image.

    2016, 2017 and 2018 do not store a page as a picture: they store it as four
    or five horizontal STRIPS of identical width, stacked. Taking the largest
    image -- which is what this did -- reads a fifth of the page and throws the
    rest away, and those three years produced nothing at all. Stitch them back
    in the order the content stream lists them, which for a scan is top to
    bottom."""
    ims = [x.image for x in pg.images]
    if not ims:
        return None
    if len(ims) == 1:
        return ims[0].convert("L")
    w = max(i.width for i in ims)
    # strips of one page share a width; anything else is a logo or a stamp
    strips = [i for i in ims if abs(i.width - w) <= 2]
    if len(strips) < 2:
        return max(ims, key=lambda z: z.width * z.height).convert("L")
    out = Image.new("L", (w, sum(i.height for i in strips)), 255)
    y = 0
    for i in strips:
        out.paste(i.convert("L"), (0, y))
        y += i.height
    return out


def gutter_x(gray) -> int:
    """Where the columns part when nothing is printed between them.

    2021 and 2025 separate their columns with white space and no rule at all,
    so rule_x correctly finds nothing and the page would be read as one block
    with both columns interleaved into nonsense. The gutter is the answer: the
    widest run of nearly empty columns in the middle third, and its centre is
    the split. It is less sharp than a printed rule -- a rule is exact -- so it
    is the fallback, never the first choice."""
    import numpy as np
    a = np.asarray(gray) < 160
    h, w = a.shape
    ink = a.sum(axis=0)
    lo, hi = int(0.32 * w), int(0.68 * w)
    quiet = ink[lo:hi] <= max(2, 0.004 * h)
    best = run = start = best_start = 0
    for i, q in enumerate(quiet):
        if q:
            if run == 0:
                start = i
            run += 1
            if run > best:
                best, best_start = run, start
        else:
            run = 0
    if best < 0.01 * w:
        return -1
    return lo + best_start + best // 2


def split_x(gray) -> int:
    """The printed rule if there is one, the white gutter if there is not."""
    x = rule_x(gray)
    return x if x > 0 else gutter_x(gray)


# what a statement-reference option can say, and nothing else
VOCAB = [
    "1 only", "2 only", "3 only", "4 only",
    "1 and 2 only", "1 and 3 only", "1 and 4 only", "2 and 3 only",
    "2 and 4 only", "3 and 4 only",
    "1, 2 and 3", "1, 2 and 4", "1, 3 and 4", "2, 3 and 4",
    "1, 2 and 3 only", "1, 2 and 4 only", "1, 3 and 4 only", "2, 3 and 4 only",
    "1, 2, 3 and 4", "1, 2 and 3 and 4",
    "Both 1 and 2", "Neither 1 nor 2",
    "Only one", "Only two", "Only three", "Only four",
    "All three", "All four", "None",
    "None of the above", "All of the above",
]
VNORM = {re.sub(r"[^a-z0-9]", "", v.lower()): v for v in VOCAB}
# the one error OCR makes here over and over: "1 and" set tight becomes "land"
GLUED = re.compile(r"\b[lJI]and\b")


# What is left of the booklet footer once the column crop has cut it in half:
# "VGYH-U-FGT (19", "-A)", and the stray rules tesseract sees as pipes.
TAIL_JUNK = re.compile(r"(\s*\|)+\s*$|\s*[A-Z]{3,}[-A-Z0-9]*\s*\(?\s*\d*\s*$"
                       r"|\s*[-–—]\s*[A-D]\s*\)\s*$")


def repair_option(s: str) -> str:
    """Snap a short statement-reference option onto the vocabulary it must
    have come from. Long prose options are left completely alone -- there is
    nothing to snap them to, and guessing at prose would be inventing."""
    t = " ".join(s.split())
    for _ in range(3):
        t2 = TAIL_JUNK.sub("", t).strip()
        if t2 == t:
            break
        t = t2
    if len(t) > 26:
        return t
    t2 = GLUED.sub("1 and", t)
    k = re.sub(r"[^a-z0-9]", "", t2.lower())
    if k in VNORM:
        return VNORM[k]
    # one more pass for digits read as letters, but only inside a short option
    k2 = k.translate(str.maketrans("lioszb", "110528"))
    for kk, v in VNORM.items():
        if kk.translate(str.maketrans("lioszb", "110528")) == k2:
            return v
    return t2


# A bracket holding one or two characters, at least one of them a lowercase
# a/b/c/d or the "@" that tesseract likes to make of an "a". Three characters
# or more is prose -- "(RBI)", "(NEER)" -- and is left alone.
#
# The brackets themselves are not reliably round. 2019's scan gives "(b}",
# "{c})" and "fc)" -- a curly close, a curly open, an "f" for a "(" -- and
# with a round-only pattern thirty-nine of its questions came out with three
# options instead of four. So both ends accept the shapes OCR confuses them
# with; what still has to be there is a letter that could be an option.
# Q_START is anchored without MULTILINE because the parser feeds it one line
# at a time; searching a multi-line chunk with it silently never matches.
QLINE = re.compile(r"(?m)^\s*\d{1,3}[.,]\s+\S")
MARKER = re.compile(r"[({\[f|]\s*[a-z@]{0,1}[abcd@][a-z]{0,1}\s*[)}\]|]")


def fix_markers(text: str) -> str:
    """Relabel the option markers by position rather than by what they look like.

    Tesseract mangles them constantly: (@) for (a), (ec) and (co) for (c), (ad)
    and (dq) for (d). Half of them merge two options into one and the question
    comes out with three. The mangled glyph does not say which letter it was --
    "ad" turns up where (d) belongs and "ec" where (c) does -- so reading the
    shape is hopeless. Position is not: options run a, b, c, d, in order.

    **The counter resets at every question start, and that is the whole safety
    of it.** Cycling across a page instead looked fine and was much worse than
    useless: question 59 lost its (a) entirely, so the three markers left were
    relabelled a, b, c, and every question after it on that page was shifted
    too. Options in the wrong order means the Commission's letter points at the
    wrong text -- a silently wrong answer, which is the one outcome worth more
    trouble than a missing question. Confined to its own question, a lost
    marker leaves that question with three options, and three options is a flag
    that keeps it out of the bank."""
    out, i, n = [], 0, 0
    for m in MARKER.finditer(text):
        chunk = text[i:m.start()]
        # a question start between two markers means a new question's options
        if QLINE.search(chunk):
            n = 0
        out.append(chunk)
        out.append("(" + "abcd"[n % 4] + ") ")
        n += 1
        i = m.end()
    out.append(text[i:])
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--code", default="gs1")
    ap.add_argument("--set", dest="setname")
    ap.add_argument("--pages", help="limit to a page range like 1-12, for a quick look")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    try:
        from pypdf import PdfReader
        from PIL import Image
    except ImportError:
        sys.exit("needs pypdf and pillow:  python -m pip install pypdf pillow")
    Image.MAX_IMAGE_PIXELS = None

    pages = PdfReader(str(args.pdf)).pages
    lo, hi = 1, len(pages)
    if args.pages:
        a, _, b = args.pages.partition("-")
        lo, hi = int(a), int(b or a)

    # Pass one: where is the rule on each page? A booklet is printed to one
    # layout, so the median settles it, and a page that disagrees is a page
    # whose rule came out faint rather than a page built differently.
    print("  finding the column rule...", flush=True)
    imgs, xs = {}, []
    for i, pg in enumerate(pages, 1):
        if not (lo <= i <= hi):
            continue
        im = page_image(pg, Image)
        if im is None:
            continue
        imgs[i] = im
        x = split_x(im)
        if x > 0:
            xs.append(x / im.width)
    if not xs:
        sys.exit("no column rule found on any page")
    xs.sort()
    frac = xs[len(xs) // 2]
    print(f"  rule sits at {frac:.3f} of the width (median of {len(xs)} pages)", flush=True)

    chunks, seen_sets, kept, skipped = [], Counter(), 0, 0
    for i, im in imgs.items():
        own = split_x(im)
        x = own if own > 0 and abs(own / im.width - frac) < 0.02 else int(frac * im.width)
        parts = ([im.crop((0, 0, x - 6, im.height)), im.crop((x + 6, 0, im.width, im.height))]
                 if x > 0 else [im])
        text = chr(10).join(ocr(p) for p in parts)
        # The footer runs the full width UNDER the rule, so the column crops
        # cut it in half and the Series went missing the moment the geometry
        # got good. Read the last strip of the page separately for it.
        # the bottom tenth, and upscaled: the footer is small type and at this
        # scan's ~150 dpi tesseract reads it as noise until it is enlarged
        strip = im.crop((0, int(im.height * 0.90), im.width, im.height))
        foot = ocr(strip.resize((strip.width * 3, strip.height * 3), Image.LANCZOS), 6)
        hits = len(ENGLISH.findall(text))
        numbered = len(re.findall("(?m)" + r"^\s*\d{1,3}\.\s+\S", text))
        # English alone is not enough, and neither is numbering: the back
        # cover is a page of numbered English instructions and would walk
        # into the middle of the paper. A question page always offers options.
        opts = len(re.findall(r"\([a-d]\)", text))
        if hits < 4 or numbered < 2 or opts < 2:
            skipped += 1
            continue
        kept += 1
        for g in FOOTER_SET.findall(text + foot):
            s = next((x for x in g if x), None) if isinstance(g, tuple) else g
            if not s:
                continue
            seen_sets[s] += 1
        chunks.append(fix_markers(text))
        print(f"  page {i:3}: {len(text):5} chars, {hits:3} english words"
              f"{'' if x > 0 else '  (no rule found — read whole)'}", flush=True)

    if not chunks:
        sys.exit("no English pages found — is this the right booklet?")

    setname = args.setname or (seen_sets.most_common(1)[0][0] if seen_sets else None)
    if not setname:
        sys.exit("could not read the Series off any page footer; pass --set")

    keys = json.loads((ROOT / "content" / "answer-keys.json").read_text(encoding="utf-8"))
    year = next((y for y in keys["years"] if y["year"] == args.year), None)
    paper = next((p for p in (year or {}).get("papers", []) if p["code"] == args.code), None)
    letters = ((paper or {}).get("keys") or {}).get(setname)
    total = (keys.get("marking", {}).get(args.code, {}) or {}).get("questions", 100)

    qs, flagged = [], []
    for q in pyq_text.parse("\n".join(chunks), total, len(chunks), window=2, trust_sequence=True):
        if not 1 <= q["n"] <= total:
            continue
        opts = [repair_option(o) for o in q["options"]]
        why = []
        if len(opts) != 4:
            why.append(f"{len(opts)} options")
        if len(q["q"]) < 25:
            why.append("stem looks truncated")
        if any(not o.strip() for o in opts):
            why.append("an option came out empty")
        if len(set(opts)) != len(opts):
            why.append("two options came out identical")
        if not q.get("read"):
            why.append("number inferred from position, not read off the page")
        item = {"n": q["n"], "topic": "", "q": q["q"], "options": opts,
                "read": bool(q.get("read")),
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

    # The gate. Numbers are assigned by POSITION, so the numbering is only
    # trustworthy if the paper came out whole: exactly `total` questions,
    # 1 to `total`, no gaps. A gap means everything after it may be shifted by
    # one, and a shifted number pulls the wrong letter out of the answer key --
    # a silently wrong answer, which is worse than no question at all.
    whole = len(dedup) == total and not missing

    out = args.out or (ROOT / "intake" / f"scan-{args.year}-{args.code}.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(
        {"note": f"OCR of a scanned paper, Series {setname}. Every stem needs a human read "
                 f"before import; the answers are the Commission's own.",
         "paperSet": setname, "questions": dedup}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    print(f"\nSeries {setname} (from the footer on {sum(seen_sets.values())} pages)")
    print(f"  {kept} English pages read, {skipped} skipped as Hindi or blank")
    print(f"  {len(dedup)} of {total} questions parsed")
    read_ok = sum(1 for q in dedup if q.get("read"))
    print(f"  {read_ok} of {len(dedup)} had their printed number actually read")
    print(f"  {len(flagged)} flagged: {flagged[:24]}{' …' if len(flagged) > 24 else ''}")
    print(f"  {len(missing)} missing: {missing[:24]}{' …' if len(missing) > 24 else ''}")
    print(f"  answers: {'from the verified key' if letters else 'NONE — no key for this Series'}")
    if whole:
        print("  numbering: whole paper, 1 to " + str(total) + " with no gaps")
    else:
        print("  numbering: NOT TRUSTWORTHY — the paper did not come out whole, so")
        print("             positions after a gap may be shifted and would pull the")
        print("             wrong letter from the key. Do not import without a read.")
    print(f"\nwrote {out.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
