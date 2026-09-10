#!/usr/bin/env python3
"""Turn an institute's test -- question PDF and solution PDF -- into a staged batch.

    python tools/test-parse.py intake/tests/forumias-411203     # one test: finds -qp and -sol
    python tools/test-parse.py --all                            # every pair in intake/tests/

Writes intake/<stem>.json in the shape tools/quiz-import.py takes. `topic` is
left empty for a person to fill (tools/topic-suggest.py narrows it); `hint`
carries the institute's own subject/topic label where the solution prints one.
A solution saved as `<stem>-sol.txt` (Drive's own text export) is preferred to
the PDF: one Vision solution stores a letter per line, and pypdf reads it back
with every line-wrap glued shut ("economyand").

Three layouts, told apart by what the pages print rather than by file name:

  ForumIAS    "Q.12) ... a) ... d) ..."     solution "Q.12) Ans) c Exp) ..."
  Vision IAS  "12. ... (a) ... (d) ..."     solution "Q 12. C ..."
  Vajiram     "12. ... (a) ... (d) ..."     solution "Q12. Answer: c Explanation: ..."
                                            and an answer-key table

**The answer is the institute's claim, and it is checked against itself.** Each
solution states the letter at least twice -- ForumIAS as "Ans) c" and "Option c
is the correct answer", Vision as "Q 12. C" and "Hence option (c)", Vajiram in
its key table, above the explanation and again at its end. Where they disagree
the question is left out: one of them is a typo, and which is not for us to
guess.

**Counted, not silently lost:** a question whose four options did not come
apart cleanly, one that leans on a map or figure the bank cannot carry, one
with no answer, and one whose answer its own solution contradicts.

Vision and Vajiram number their statements "1." exactly as they number their
questions, and Vajiram's pages come out of the PDF with their columns in the
wrong order (question 10, then 18). So a number starts a question only if it
has not been used yet AND the question before it has already shown all four
options -- statement 2 of question 7 can never qualify, whatever order the
text arrives in.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = ROOT / "intake" / "tests"
YEAR = 2027
WHY_CAP = 1200

FURNITURE = re.compile("|".join([
    r"https?://upscpdf\.com/?",
    r"PTS\s*2027\s*\|\s*(?:Solution\s*\|\s*)?Test\s*Code\s*:\s*[\d ]+\|?",
    r"Forum Learning Centre\s*:.*?helpdesk@forumias\.academy",
    r"AbxK",                                   # a watermark, often glued to the footer before it
    r"(?:Page\s*\d+\s*)?Shared\s+Freely\s+(?:in\s+UPSC\s+test\s+series\s+zone|By)",
    r"\\?\[\s*\d{1,3}\s*\\?\]",
    r"\b\d{1,3}\s+www\s*\.?\s*visionias\s*\.?\s*in\s*©\s*Vision\s*IAS",
    r"www\s*\.?\s*visionias\s*\.?\s*in",
    r"(?:Copyright\s*)?©\s*(?:by\s*)?(?:Vision\s*IAS)?(?:\s*All\s+rights\s+(?:are\s+)?reserved.{0,300}?Vision\s*IAS\.?)?",
    r"\d{0,3}\s*VISION\s?IAS(?![a-z])",
    r"V\s?AJIRAM\s*&\s*RA\s?VI",
    r"\d{0,3}\s*PowerUp\s+Prelims\s+Test\s+Series\s*[–-]\s*\d{4}\s*GS\s*Test\s*[–-]\s*[\d ]+[–-]\s*[A-Za-z &]+?\(\s*V[\d ]+\)",
    r"Prelims\s+Test\s+Series\s*[–-]\s*\d{4}\s*(?:GS\s*Test\s*[–-]\s*[\d ]+[–-]\s*)?[A-Za-z &]+?\(\s*V[\d ]+\)",
    r"Answer\s+Key\s*&\s*Detailed\s+Answer\s+Explanations",
    r"PowerUp\s*GS\s*Test\s*-?\s*\d+\s*-?\s*Answer\s*Key\s*\(V\d+\)",
    r"Space\s+for\s+Rough\s+Work",
]), re.S | re.I)
KEY_CELLS = re.compile(r"(?:Answer\s+Key\s*)?(?:\s*\d{1,3}\s*\.\s*\([a-d]\)){5,}")

OPT_FORUM = re.compile(r"(?<![\w(])([a-d])\)\s")
OPT_PAREN = re.compile(r"\(([a-d])\)\s?")
FIGURE = re.compile(r"\b(?:map|figure|diagram|graph|image|picture|shown below|following sketch)\b", re.I)


def pages_of(path: pathlib.Path) -> list[str]:
    if path.suffix == ".txt":
        t = path.read_text(encoding="utf-8")
        # Drive's text export escapes markdown: "1\." "\[5\]"
        return [re.sub(r"\\([\[\]\.\-_*()#|])", r"\1", t)]
    from pypdf import PdfReader
    return [(p.extract_text() or "") for p in PdfReader(str(path)).pages]


def flatten(t: str) -> str:
    """One line of text. Some PDFs store every word -- or every letter -- as its
    own fragment, and there a line break is not always a gap between words."""
    lines = t.split("\n")
    one = sum(1 for ln in lines if len(ln) == 1) / max(1, len(lines))
    tiny = sum(1 for ln in lines if len(ln.strip()) <= 2) / max(1, len(lines))
    if one > 0.6:
        # a letter per line: the spaces are lines of their own
        t = t.replace("\n", "")
    elif tiny > 0.25:
        # a word in fragments (Vajiram): "fr" + "om" joins, but "2" + "2." must
        # not -- only a break between two lowercase letters is inside a word
        t = re.sub(r"(?<=[a-z])\n(?=[a-z])", "", t)
    return " ".join(t.split())


def text_of(path: pathlib.Path, from_options: bool) -> tuple[str, str]:
    """(clean text, raw head) -- the head keeps the page headers that name the test."""
    pages = pages_of(path)
    head = flatten("\n".join(pages[:2]))
    if from_options:
        # the booklet's own instructions are numbered 1., 2. ... too: start at
        # the first page that offers an option
        for i, p in enumerate(pages):
            if re.search(r"\(\s*a\s*\)|(?<![\w(])a\)\s", p):
                pages = pages[i:]
                break
    t = flatten("\n".join(pages))
    return " ".join(FURNITURE.sub(" ", t).split()), head


def split_options(body: str, rx: re.Pattern):
    """Stem and four options: the LAST a) that has b), c), d) after it, in order."""
    marks = [(m.start(), m.end(), m.group(1)) for m in rx.finditer(body)]
    for ia in range(len(marks) - 1, -1, -1):
        if marks[ia][2] != "a":
            continue
        seq, want = [marks[ia]], "bcd"
        for mk in marks[ia + 1:]:
            if want and mk[2] == want[0]:
                seq.append(mk)
                want = want[1:]
        if not want:
            opts = [body[seq[k][1]:seq[k + 1][0]] for k in range(3)] + [body[seq[3][1]:]]
            return body[:seq[0][0]], [" ".join(o.split()) for o in opts]
    return None


def latin(s: str) -> float:
    letters = re.findall(r"[^\W\d_]", s)
    return sum(c.isascii() for c in letters) / max(1, len(letters))


def questions_forum(t: str) -> dict[int, str]:
    parts = re.split(r"Q\.\s*(\d{1,3})\s*\)", t)
    out = {}
    for i in range(1, len(parts) - 1, 2):
        n, body = int(parts[i]), parts[i + 1]
        # a bilingual booklet prints every question twice; keep the English one
        if n not in out or latin(body) > latin(out[n]):
            out[n] = body
    return out


def questions_numbered(t: str) -> dict[int, str]:
    starts, used, last = [], set(), None
    for m in re.finditer(r"(?:(?<=\s)|^)(\d{1,3})\s*\.\s+", t):
        n = int(m.group(1))
        if n in used or not 1 <= n <= 150:
            continue
        if last is not None and split_options(t[last.end():m.start()], OPT_PAREN) is None:
            continue
        starts.append(m)
        used.add(n)
        last = m
    return {int(m.group(1)): t[m.end():(starts[i + 1].start() if i + 1 < len(starts) else len(t))]
            for i, m in enumerate(starts)}


def said_in_text(body: str):
    ms = re.findall(r"option\s*\(?\s*([a-d])\s*\)?\s*is\s*(?:the\s*)?correct", body, re.I)
    return ms[-1].lower() if ms else None


def answers_forum(t: str) -> dict[int, tuple]:
    out = {}
    parts = re.split(r"Q\.\s*(\d{1,3})\s*\)\s*Ans\s*\)\s*([a-dA-D])\b", t)
    for i in range(1, len(parts) - 2, 3):
        body = re.sub(r"^\s*Exp\s*\)\s*", "", parts[i + 2])
        h = re.search(r"Subject\s*:?\)\s*(.*?)\s*Topic\s*:?\)\s*(.*?)\s*(?:Subtopic|$)", body)
        hint = " / ".join(x.strip(" :)") for x in h.groups() if x.strip(" :)")) if h else ""
        out[int(parts[i])] = (parts[i + 1].lower(), [said_in_text(body[:300])], body, hint)
    return out


def answers_vision(t: str) -> dict[int, tuple]:
    out = {}
    parts = re.split(r"Q\s*(\d{1,3})\s*\.\s*([A-D])(?![a-z])", t)
    for i in range(1, len(parts) - 2, 3):
        n, body = int(parts[i]), parts[i + 2]
        if n not in out:                          # an explanation quoting "Q 5. A" elsewhere
            out[n] = (parts[i + 1].lower(), [said_in_text(body)], body, "")
    return out


def answers_vajiram(t: str, subject: str) -> dict[int, tuple]:
    key = {int(n): a for n, a in re.findall(r"(?<![\d.])(\d{1,3})\s*\.\s*\(([a-d])\)", t)}
    out = {}
    parts = re.split(r"Q\s*(\d{1,3})\s*\.?\s*Answer\s*:\s*\(?([a-dA-D])\)?", t)
    for i in range(1, len(parts) - 2, 3):
        n = int(parts[i])
        body = re.sub(r"^\s*Explanation\s*:\s*", "", parts[i + 2])
        out[n] = (parts[i + 1].lower(), [key.get(n), said_in_text(body)], body, subject)
    for n, a in key.items():                       # in the key but no explanation block
        out.setdefault(n, (a, [], "", subject))
    return out


def why_of(body: str) -> str:
    b = KEY_CELLS.sub(" ", body)
    b = re.split(r"\bSources?\s*:?\)|\bSources?\s*:|\bSubject\s*:?\)|Knowledge\s*Base\s*:", b)[0]
    b = re.sub(r"^\s*Option\s*\(?[a-d]\)?\s*is\s*(?:the\s*)?correct\s*answer\s*\.?", "", b, flags=re.I)
    b = re.sub(r"\s*(?:Hence|Therefore),?\s*option\s*\(\s*[a-d]\s*\)\s*is\s*(?:the\s*)?correct\s*answer\s*\.?",
               " ", b, flags=re.I)
    b = " ".join(b.split())
    if len(b) > WHY_CAP:
        cut = b.rfind(". ", 0, WHY_CAP)
        b = b[:cut + 1 if cut > WHY_CAP // 2 else WHY_CAP].rstrip() + " \u2026"
    return b


def lay_out(stem: str) -> str:
    """Statements on their own lines, as the paper prints them."""
    s = " ".join(stem.split())
    s = re.sub(r"\s*(?<![\w.])((?:[1-9]|1[0-9])\.|(?:I{1,3}|IV|V|VI)\.)\s+(?=\S)",
               lambda m: "\n" + m.group(1) + " ", s)
    s = re.sub(r"\s+(?=(?:Which (?:of|one of) the|Select the|How many|Code\s*:))", "\n", s)
    return s.strip()


def source_of(stem: str, qhead: str, shead: str) -> dict:
    kind, code = stem.split("-", 1)[0], stem.split("-")[1]
    if kind == "forumias":
        k = int(code[-2:])
        test = f"Level 2 Test {k - 10:02d}" if k > 10 else f"Test {k:02d}"
        return {"name": "ForumIAS", "test": f"Prelims Test Series {YEAR}, {test} ({code})", "year": YEAR}
    if kind == "vajiram":
        both = qhead + " " + shead
        m = re.search(r"GS\s*Test\s*[–-]\s*0?\s*(\d+)\s*[–-]\s*([A-Za-z &]+?)\s*\(\s*V", both)
        n = int(m.group(1)) if m else int(code[-2:])
        subj = m.group(2).strip() if m else ""
        if not subj:
            s = re.search(r"\b(Polity|Economics|Geography|History|Environment|Science)\b", both)
            subj = s.group(1) if s else ""
        return {"name": "Vajiram & Ravi",
                "test": f"PowerUp Prelims Test Series {YEAR}, GS Test {n:02d}{' - ' + subj if subj else ''} ({code})",
                "year": YEAR}
    n = int(re.search(r"t(\d+)", stem).group(1))
    m = re.search(r"TEST\s*[–-]\s*(\d{5})", shead) or re.search(r"\b(156\d\d)\b", qhead + " " + shead)
    tc = m.group(1) if m else f"156{n:02d}"
    return {"name": "Vision IAS", "test": f"Prelims Test Series {YEAR}, Test {n:02d} ({tc})", "year": YEAR}


def parse(stem: str) -> dict:
    qp = TESTS / f"{stem}-qp.pdf"
    sol = next((p for p in (TESTS / f"{stem}-sol.txt", TESTS / f"{stem}-sol.pdf") if p.exists()), None)
    kind = stem.split("-", 1)[0]
    qtext, qhead = text_of(qp, from_options=(kind != "forumias"))
    stext, shead = text_of(sol, from_options=False) if sol else ("", "")
    src = source_of(stem, qhead, shead)
    if kind == "forumias":
        bodies, rx = questions_forum(qtext), OPT_FORUM
        keys = answers_forum(stext)
    else:
        bodies, rx = questions_numbered(qtext), OPT_PAREN
        subj = re.search(r"-\s*([A-Za-z &]+) \(V", src["test"])
        keys = answers_vajiram(stext, subj.group(1).strip() if subj else "") if kind == "vajiram" \
            else answers_vision(stext)

    out, left = [], Counter()
    for n in sorted(bodies):
        sp = split_options(bodies[n], rx)
        if not sp:
            left["options did not come apart"] += 1
            continue
        q, opts = sp
        if not q.strip() or any(not o for o in opts) or len(set(opts)) != 4 or max(map(len, opts)) > 300:
            left["options did not come apart"] += 1
            continue
        if FIGURE.search(q):
            left["leans on a map or figure"] += 1
            continue
        if n not in keys:
            left["no answer in the solution"] += 1
            continue
        a, also, body, hint = keys[n]
        if any(x and x != a for x in also):
            left["solution contradicts itself"] += 1
            continue
        item = {"n": n, "topic": "", "q": lay_out(q), "options": opts, "answer": "abcd".index(a)}
        w = why_of(body)
        if w:
            item["why"] = w
        if hint:
            item["hint"] = hint
        out.append(item)
    return {"source": src, "questions": out, "_left": dict(left), "_seen": len(bodies)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stems", nargs="*")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    stems = sorted({p.name.rsplit("-", 1)[0] for p in TESTS.glob("*-qp.pdf")}) if args.all \
        else [pathlib.Path(s).name for s in args.stems]
    for stem in stems:
        d = parse(stem)
        left, seen = d.pop("_left"), d.pop("_seen")
        dest = ROOT / "intake" / f"{stem}.json"
        dest.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{stem:22} {len(d['questions']):3} staged of {seen:3} found | {d['source']['test']} | left out: {left}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
