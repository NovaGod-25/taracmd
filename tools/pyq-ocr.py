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

                            first cut    now
    questions located          79         79   of 100
    footer swallowed           22          0
    digit read as a letter    164         20
    text bled in from the
      neighbouring column      26         26   ← not fixed
    usable without a look       ~0         27

Two of the three defects are gone. The footer is cropped before OCR rather
than filtered after, so it can no longer be read as a continuation of whatever
option ended last. And "land 2 only" is "1 and 2 only" again — that one
mattered most, because an option saying something different from what was
printed teaches the wrong answer without ever looking broken.

THE COLUMN BLEED IS NOT FIXED, and the honest reason is that four attempts at
measuring the gutter all failed: widest quiet run, run nearest the ink
midpoint, leftmost run, median across pages. The trap is that the widest gap
in the middle of these pages is usually the hanging indent INSIDE a column —
between "43." and its text — not the gap between columns. Cutting there sliced
the question number off every right-column question and the yield fell from 79
to 9. So the fixed split with its overlap stays: it costs bleed, which is
visible and flagged, rather than silently losing a third of the paper.
Fixing it properly needs real layout analysis, not a fifth projection
heuristic.

What the flags are worth: 27 of the 79 come through unflagged, and an
independent audit of those found nothing wrong with any of them. The rest
carry a reason. The most useful check turned out to be the paper marking its
own homework — an option citing statement 38 when the stem lists five is a
digit that came from the other side of the gutter.

Still a draft. 27 questions you could read and import; 52 to fix by hand; 21
the reader never found.

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


FOOTER = re.compile(r"VGYH|www\.|©|upscpdf|^\s*\d{1,3}\s*$", re.IGNORECASE)


def columns(img, foot=0.955, left=0.52, right=0.48):
    """The two columns, with the footer band cut off first.

    The split is a fixed fraction with a deliberate overlap, and that is a
    retreat. Measuring the gutter was tried four ways — widest quiet run,
    the run nearest the ink midpoint, the leftmost run, the median across
    pages — and none was stable, because the widest gap in the middle of
    these pages is often the hanging indent INSIDE a column, between "43."
    and its text, rather than the gap between the columns. Cutting there
    sliced the question number off every right-column question and the yield
    collapsed from 79 questions to 9.

    So the overlap stays. It costs some text bleeding in from the neighbour,
    which is visible and flagged, rather than silently losing a third of the
    paper. Getting this right needs proper layout analysis, not another
    projection heuristic.

    The footer crop is not a retreat: the running footer sat below the text
    and was read as a continuation of whichever option ended last, so it
    landed inside an answer. Cutting it before OCR is cheaper and safer than
    recognising it afterwards.
    """
    W, H = img.size
    bottom = int(H * foot)
    yield img.crop((0, 0, int(W * left), bottom))
    yield img.crop((int(W * right), 0, W, bottom))


# An option on this paper is nearly always a reference to the numbered
# statements in the stem: "1 only", "2 and 3 only", "1, 2 and 3", "Both 1 and
# 2", "Neither 1 nor 2", "Only two". In that shape a lone "1" is the character
# tesseract most often loses — it comes back as "l", and "1 and" collapses into
# the word "land", which reads as English and so survives every spellcheck.
# 164 of the option defects on CS(P)-2022 GS-I were this one thing.
COUNTING = re.compile(r"^only (one|two|three|four)$|^all four$|^none$", re.IGNORECASE)
KEYWORDS = re.compile(r"\b(only|both|neither|and|nor|or|land)\b", re.IGNORECASE)


def repair_option(text: str) -> str:
    """Put back the digits tesseract turned into letters.

    Only inside options that are pure references to statement numbers. A
    factual option — "Article 368", "Ministry of Home Affairs", "forest land
    system" — is left completely alone, because there an "l" may well belong
    and "land" is a word.

    Note the order: the test for "is this a reference to statement numbers"
    strips `land` as a keyword rather than rewriting it first. Rewriting first
    would turn every legitimate "land" in the paper into "1 and".
    """
    t = " ".join(text.split())
    if COUNTING.match(t):
        return t

    # Split runs like "2and" before stripping keywords: there is no word
    # boundary between a digit and a letter, so \band\b never sees the "and"
    # in "2and 3 only" and the whole option would look like prose.
    spaced = re.sub(r"(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)", " ", t)
    probe = KEYWORDS.sub(" ", spaced).replace(",", " ").strip()
    if not probe or not all(re.fullmatch(r"[\dlI]+", tok) for tok in probe.split()):
        return t

    # From here on work on the spaced form: "1,2and3" has no word boundaries
    # for the rules below to catch, and by this point the option is known to be
    # nothing but statement numbers and joining words, so spacing it is safe.
    t = spaced
    t = re.sub(r"\bland\b", "1 and", t, flags=re.IGNORECASE)
    t = re.sub(r"(?<![A-Za-z])[lI](?![A-Za-z])", "1", t)
    t = re.sub(r"(\d)(and|only|nor|or)\b", r"\1 \2", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(and|nor|or|both|neither)(\d)", r"\1 \2", t, flags=re.IGNORECASE)
    return " ".join(t.split())


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
            cur["options"].append(repair_option(m.group(2).strip()))
            opt = len(cur["options"]) - 1
            continue
        if FOOTER.search(line) and len(line.strip()) < 40:
            continue                                        # running footer, not content
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

    pages = list(range(lo - 1, min(hi, len(reader.pages))))
    text, sets = [], []
    for i in pages:
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
        if re.search(r"PM,|,,|\bug/m\b", q["q"] + " ".join(q["options"])):
            why.append("subscript lost in the scan")

        # An option that references a statement the stem does not have is the
        # signature of text bled in from the neighbouring column: "1 and 3
        # only" comes back as "1 and 83 only" because a digit from the other
        # side of the gutter landed in it. The stem numbers its own statements,
        # so the paper checks itself here.
        stmts = [int(x) for x in re.findall(r"(?<![\d.])(\d{1,2})\.\s", q["q"])]
        # A statement list never runs past about five on this paper, and where
        # the stem sets them out inline the pattern above finds none at all —
        # so the floor matters as much as the measurement. Anything above it is
        # a digit that came from somewhere else.
        top = max(stmts + [5])
        refs = [int(x) for o in q["options"] for x in re.findall(r"\d+", o)]
        stray = sorted({x for x in refs if x > top})
        if stray:
            why.append(f"option cites {stray}, above the {top} statements in the stem")
        if re.search(r"\|", q["q"] + " ".join(q["options"])):
            why.append("text bled in from the other column")
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
