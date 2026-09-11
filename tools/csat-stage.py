#!/usr/bin/env python3
"""Stage a scanned CSAT paper: passages attached, every question read by a person.

    python tools/pyq-scan.py tools/.qp-pdfs/qp-2024-gs2.pdf --year 2024 --code gs2
    python tools/csat-stage.py 2024 draft          # intake/csat-2024-draft.txt, to read
    python tools/csat-stage.py 2024 page 21        # a page as a picture, to read against
    #   ...every question read; decisions written to intake/csat-2024-review.json
    python tools/csat-stage.py 2024 stage          # intake/upsc-2024-gs2-seta-add.json
    python tools/quiz-import.py intake/upsc-2024-gs2-seta-add.json --dry-run

CSAT differs from GS-I in three ways that matter here.

  passages   A passage is printed once, above the items that ask about it, under
             a "Directions for the following N (n) items" line. The parser sees it
             as spill-over at the end of the question before -- or, for the first,
             as preamble. It is cut out of there and stored once, and each of the
             N items after a Directions line points at the passage printed most
             recently above it. After the N items there is no passage.

  furniture  The parser drops short lines that repeat on over half the pages, to
             lose running heads. CSAT repeats real text that often: "Which of the
             assumptions given above", and half of every data-sufficiency option.
             So the raw OCR is parsed again here with that sweep off, and the
             booklet code and "P.T.O." are removed by pattern instead.

  arithmetic OCR cannot read an exponent, a decimal point set as a raised dot
             (3·5 comes back 3°5, 3:5 or 35) or the rupee sign (?, %, #, ¥, or a 1
             stuck to the number). A numeracy question typed wrong keeps the
             Commission's right answer and becomes unanswerable, which is worse
             than not having it. So every question is read against the page, the
             arithmetic is worked, and nothing is staged that the review file does
             not accept.

The review file has one entry per question number, and a number with no entry
is not staged:

    {"passages": {"csp24-gs2-a-p11": "...corrected passage text..."},
     "1":  {"topic": "csat-comprehension"},
     "9":  {"q": "...the stem as printed...", "options": ["..", "..", "..", ".."],
            "topic": "csat-numeracy"},
     "24": {"skip": "a letter sequence with blanks OCR cannot keep"}}

Answers are never taken from the page or from the review: they come from the
Commission's key by number, against the Series the booklet footer names.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRATCH = ROOT / "intake"


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pyq_text = _load("pyq_text", "pyq-text.py")

DIRECTIONS = re.compile(r"Directions?\s+for\s+the\s+following\s+(\d+)\s*\(?\s*[a-z]+\s*\)?\s*items?\s*[:;.]?",
                        re.IGNORECASE)
PASSAGE = re.compile(r"Passage\s*[—–\-−~_]+\s*[0-9IlO|]{1,2}\b\s*[:.]?", re.IGNORECASE)
# the booklet code and page number at the foot of the left column: "KSPC-B-GSPT/61A 3"
CODE = re.compile(r"\b[A-Z]{2,5}\s*[-–—]\s*[A-Z]\s*[-–—]\s*[A-Z]{2,5}\s*/\s*\d{1,3}\s*[A-D]\b(\s+\d{1,2}\b)?")
# "[P.T.O." in its OCR shapes, at the end of a line: "[PO.", "[PEO", "[ P:T-0.", "{ PTO:"
PTO_BRACKET = re.compile(r"\s*[\[{]\s*[-~]?\s*[A-Z0-9][A-Z0-9 .:;,\-]{0,8}\s*$")
PTO_BARE = re.compile(r"\s+[EU]?P+[TE]?[NA]?[O0Q][.:;!,]*\s*$")
SEP = re.compile(r"\n*=== page(?: (\d+))? ===\n*")
FIGURE = re.compile(r"\b(figure|figures|diagram|graph|chart|shown below|table|pie)\b", re.IGNORECASE)
ODD = re.compile(r"[°®«»¥#*¢~|@{}\[\]]|\?\s*\d|%\s*\d|\s_\s|\w_\s")
# the left-column footer in its other shape, "BXC-B-GYLI (3-", and what the
# right column keeps of "( 3 - A )" -- "A)", "-A)", "-~A)"
CODE2 = re.compile(r"\s*\b[A-Z]{3,5}\s*[-–—]\s*[A-Z]\s*[-–—]\s*[A-Z]{3,5}\b.{0,8}$")
SET_TAIL = re.compile(r"(?<!\()\s+[-~]*\s*[A-D]\)\s*\|?\s*$")


def _vocab() -> dict:
    """Every option a statement question can offer, generated rather than listed
    -- "2 and 4 only", "1, 3 and 5 only", "Both 1 and 2" -- keyed the way OCR is
    compared against it. A bare number is never in it, so a numeric answer is
    never snapped to anything."""
    import itertools
    words = {"Both 1 and 2", "Neither 1 nor 2", "Both I and II", "Neither I nor II",
             "Only one", "Only two", "Only three", "Only four", "All three", "All four",
             "None of the above", "All of the above"}
    for k in range(1, 6):
        for combo in itertools.combinations(range(1, 7), k):
            s = [str(c) for c in combo]
            body = s[0] if k == 1 else ", ".join(s[:-1]) + " and " + s[-1]
            words.add(body + " only")
            if k > 1:
                words.add(body)
    out = {}
    for w in words:
        key = _key(w)
        out[key] = None if key in out and out[key] != w else w
    return out


def _key(s: str) -> str:
    # OCR reads the digit 1 as l, i or I; apply the same to both sides
    return re.sub(r"[^a-z0-9]", "", s.lower()).translate(str.maketrans("li", "11"))


VOCAB = _vocab()


def snap(opt: str, statements: int) -> str:
    """"lonly" -> "1 only", "2and 8 only" -> "2 and 3 only" where the list has
    fewer than eight statements, "Bothland2" -> "Both 1 and 2". Prose and
    numbers pass through untouched: they match nothing in the vocabulary."""
    if len(opt) > 30:
        return opt
    k = _key(opt)
    if VOCAB.get(k):
        return VOCAB[k]
    if statements < 8 and "8" in k and VOCAB.get(k.replace("8", "3")):
        return VOCAB[k.replace("8", "3")]
    return opt


def clean_line(line: str) -> str | None:
    t = CODE.sub("", line).rstrip()
    t = CODE2.sub("", t)
    t = PTO_BRACKET.sub("", t)
    t = PTO_BARE.sub("", t)
    t = SET_TAIL.sub("", t)
    t = re.sub(r"\s+\\+\)?\s*$", "", t)
    s = t.strip()
    if not s or re.fullmatch(r"[\s\-~(|]*[A-D]\)[\s|]*", s):
        return None
    # A P.T.O. on a line of its own: short, and made of nothing but the letters
    # OCR turns it into. Anything looser takes real lines with it -- "P+R-T?"
    # and "9y(P) 8z." are both short and both carry a P.
    letters = re.sub(r"[^A-Za-z0-9]", "", s)
    if len(s) <= 10 and "P" in letters and set(letters) <= set("PTOQEUNA0"):
        return None
    return t


def raw_pages(year: int) -> list[tuple[int | None, str]]:
    raw = (SCRATCH / f"scan-{year}-gs2.txt").read_text(encoding="utf-8")
    parts = SEP.split(raw)
    # split keeps the captured page number between chunks
    if len(parts) == 1:
        return [(None, raw)]
    out, first = [], parts[0]
    if first.strip():
        out.append((None, first))
    for i in range(1, len(parts), 2):
        out.append((int(parts[i]) if parts[i] else None, parts[i + 1]))
    # A scan from before the page numbers were written down: the booklet prints
    # its own, in the footer -- "KSPC-B-GSPT/61A 13" or "( 13 - A )".
    fixed = []
    for pg, chunk in out:
        if pg is None:
            m = CODE.search(chunk)
            f = re.search(r"\(\s*(\d{1,2})\s*[-–—]\s*[A-D]\s*\)", chunk)
            pg = int(m.group(1)) if m and m.group(1) else int(f.group(1)) if f else None
        fixed.append((pg, chunk))
    return fixed


def clean_prose(t: str | None) -> str | None:
    if not t:
        return t
    t = CODE.sub(" ", t)
    t = re.sub(r"\s+[\[{]\s*P[\s.:;T\-]*[O0]\s*[.:;!,]*", " ", t)      # a P.T.O. mid-passage
    t = re.sub(r"(\w)_\s", r"\1 ", t)                                  # "a_ strategy"
    t = re.sub(r"\s_\s", " ", t)                                       # "Food and _ Agriculture"
    t = re.sub(r"\s+\|\s+", " ", t)                                    # a rule read as a pipe
    return " ".join(t.split())


def draft(year: int) -> dict:
    keys = json.loads((ROOT / "content" / "answer-keys.json").read_text(encoding="utf-8"))
    scan = json.loads((SCRATCH / f"scan-{year}-gs2.json").read_text(encoding="utf-8"))
    setname = scan["paperSet"]
    paper = next(p for y in keys["years"] if y["year"] == year for p in y["papers"] if p["code"] == "gs2")
    letters = paper["keys"][setname]
    total = keys["marking"]["gs2"]["questions"]

    pages = raw_pages(year)
    lines, line_page = [], []
    for pg, chunk in pages:
        for l in chunk.splitlines():
            c = clean_line(l)
            if c is not None:
                lines.append(c)
                line_page.append(pg)
    text = "\n".join(lines)
    qs = pyq_text.parse(text, total, len(pages), window=2, trust_sequence=True, drop_repeats=False)
    by_n = {}
    for q in qs:
        if 1 <= q["n"] <= total and q["n"] not in by_n:
            by_n[q["n"]] = q

    # which page each question starts on, for reading it against the picture
    starts = {}
    for idx, l in enumerate(lines):
        m = re.match(r"^\s*(\d{1,2})[.,]\s+(\S.{0,30})", l)
        if m and int(m.group(1)) in by_n and int(m.group(1)) not in starts:
            stem = by_n[int(m.group(1))]["q"]
            if stem.startswith(m.group(2)[:12].strip()):
                starts[int(m.group(1))] = line_page[idx]

    # the block above each question: cut out of the last option of the one before
    blocks = {}
    first_q = re.search(r"(?m)^\s*1[.,]\s+\S", text)
    if first_q:
        blocks[1] = text[:first_q.start()]
    for n in sorted(by_n):
        q = by_n[n]
        where = "options" if q["options"] else "q"
        s = q["options"][-1] if q["options"] else q["q"]
        m = min((x for x in (DIRECTIONS.search(s), PASSAGE.search(s)) if x), key=lambda x: x.start(), default=None)
        if m:
            blocks[n + 1] = s[m.start():]
            s = s[:m.start()].rstrip()
            if where == "options":
                q["options"][-1] = s
            else:
                q["q"] = s

    out, passages, remaining, current = [], {}, 0, None
    for n in range(1, total + 1):
        q = by_n.get(n)
        blk = blocks.get(n)
        if blk:
            d = DIRECTIONS.search(blk)
            ps = list(PASSAGE.finditer(blk))
            if d:
                remaining, current = int(d.group(1)), None
            if ps:
                pid = f"csp{str(year)[2:]}-gs2-{setname.lower()}-p{n}"
                passages[pid] = clean_prose(blk[ps[-1].end():])
                current = pid
            elif d:
                # Directions with no passage header: what follows is information
                # the items share -- a puzzle's facts -- and it is kept the same way.
                rest = clean_prose(blk[d.end():])
                if rest:
                    pid = f"csp{str(year)[2:]}-gs2-{setname.lower()}-p{n}"
                    passages[pid] = rest
                    current = pid
        if not q:
            if remaining > 0:
                remaining -= 1
            continue
        L = letters[n - 1]
        stem = " ".join(q["q"].split())
        # "1: Sustainable" and "1; Cover crops" are statement markers; "3: 5" is a ratio
        stem = re.sub(r"(?<=\s)([1-9])[:;]\s+(?=[A-Z])", r"\1. ", stem)
        nums = [int(x) for x in re.findall(r"(?:^|\s)([1-9])\.\s", stem)]
        item = {"n": n, "page": starts.get(n), "read": bool(q.get("read")),
                "answer": None if L == "X" or len(L) > 1 else "ABCD".index(L), "key": L,
                "q": stem, "options": [snap(" ".join(o.split()), max(nums, default=4)) for o in q["options"]]}
        if remaining > 0:
            item["passage"] = current
            remaining -= 1
        flags = []
        if len(item["options"]) != 4:
            flags.append(f"{len(item['options'])} options")
        if not item["read"]:
            flags.append("number inferred")
        if item["answer"] is None:
            flags.append("dropped" if L == "X" else f"key {L}")
        if FIGURE.search(item["q"]):
            flags.append("figure/table")
        if ODD.search(item["q"] + " " + " ".join(item["options"])):
            flags.append("odd characters")
        if "passage" not in item and re.search(r"\bpassage\b|\bauthor\b", item["q"], re.IGNORECASE):
            flags.append("mentions a passage but has none")
        if "passage" in item and not item["passage"]:
            flags.append("in a passage group with no passage found")
        item["flags"] = flags
        out.append(item)
    return {"year": year, "set": setname, "letters": letters, "passages": passages, "questions": out}


def write_draft(year: int) -> None:
    d = draft(year)
    (SCRATCH / f"csat-{year}-draft.json").write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n",
                                                     encoding="utf-8")
    lines = [f"CSAT {year}, Series {d['set']}: {len(d['questions'])} questions, {len(d['passages'])} passages", ""]
    for pid, t in d["passages"].items():
        lines += [f"=== {pid}", t, ""]
    for q in d["questions"]:
        lines.append(f"## {q['n']}  key {q['key']}  page {q['page']}  {q.get('passage') or ''}  {q['flags'] or ''}")
        lines.append("Q: " + q["q"])
        lines += [f"  ({L}) {o}" for L, o in zip("abcd", q["options"])]
    (SCRATCH / f"csat-{year}-draft.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    flagged = [q["n"] for q in d["questions"] if q["flags"]]
    print(f"{year}: {len(d['questions'])} questions, {len(d['passages'])} passages, "
          f"{len(flagged)} flagged -> intake/csat-{year}-draft.txt")


def page_png(year: int, page: int, box: str | None = None) -> None:
    from pypdf import PdfReader
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    scan = _load("pyq_scan", "pyq-scan.py")
    im = scan.page_image(PdfReader(str(ROOT / "tools" / ".qp-pdfs" / f"qp-{year}-gs2.pdf")).pages[page - 1], Image)
    if box:
        x0, y0, x1, y1 = (float(v) for v in box.split(","))
        im = im.crop((int(x0 * im.width), int(y0 * im.height), int(x1 * im.width), int(y1 * im.height)))
    else:
        im.thumbnail((1200, 1700))
    dest = SCRATCH / "look" / f"csat-{year}-p{page}{'-' + box.replace(',', '_') if box else ''}.png"
    dest.parent.mkdir(exist_ok=True)
    im.save(dest)
    print(dest)


def stage(year: int) -> int:
    d = draft(year)
    rv = json.loads((SCRATCH / f"csat-{year}-review.json").read_text(encoding="utf-8"))
    subs = json.loads((ROOT / "content" / "subjects.json").read_text(encoding="utf-8"))
    topics = {t["id"] for s in subs for t in s["topics"]}
    passages = {**d["passages"], **rv.get("passages", {})}
    out, used, skipped, unread, bad = [], set(), {}, [], []
    # A question the scan lost can still be added, typed from the page in full.
    have = {q["n"] for q in d["questions"]}
    for k, r in rv.items():
        if k.isdigit() and int(k) not in have and "q" in r:
            L = d["letters"][int(k) - 1]
            d["questions"].append({"n": int(k), "key": L, "q": r["q"], "options": r.get("options", []),
                                   "answer": None if L == "X" or len(L) > 1 else "ABCD".index(L)})
    d["questions"].sort(key=lambda x: x["n"])
    for q in d["questions"]:
        r = rv.get(str(q["n"]))
        if r is None:
            unread.append(q["n"])
            continue
        if "skip" in r:
            skipped[q["n"]] = r["skip"]
            continue
        stem, opts = r.get("q", q["q"]), r.get("options", q["options"])
        pid = r["passage"] if "passage" in r else q.get("passage")
        why = []
        if r.get("topic") not in topics:
            why.append(f"topic {r.get('topic')!r}")
        if q["answer"] is None:
            why.append(f"no single answer in the key ({q['key']})")
        if len(opts) != 4 or len({o.strip() for o in opts}) != 4 or any(not o.strip() for o in opts):
            why.append("options are not four distinct answers")
        if pid and not (passages.get(pid) or "").strip():
            why.append(f"passage {pid!r} is empty")
        if why:
            bad.append((q["n"], why))
            continue
        item = {"n": q["n"], "topic": r["topic"]}
        if pid:
            item["passage"] = pid
            used.add(pid)
        item.update({"q": stem, "options": opts, "answer": q["answer"],
                     "paper": {"year": year, "code": "gs2", "set": d["set"], "n": q["n"]}})
        out.append(item)
    if bad:
        for n, why in bad:
            print(f"  Q{n}: {'; '.join(why)}")
        return 1
    dest = SCRATCH / f"upsc-{year}-gs2-set{d['set'].lower()}-add.json"
    dest.write_text(json.dumps({
        "note": f"UPSC Civil Services Prelims {year}, CSAT Paper II, Series {d['set']}. OCR of the "
                "Commission's own scan, every question read against the page and every calculation "
                "worked. Answers are the Commission's own key.",
        "passages": {p: passages[p] for p in sorted(used)},
        "questions": out}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{year}: {len(out)} staged, {len(used)} passages -> {dest.name}")
    print(f"  skipped {len(skipped)}: " + "; ".join(f"Q{n} {w}" for n, w in skipped.items()))
    if unread:
        print(f"  NOT YET READ ({len(unread)}): {unread}")
    return 0


def main() -> int:
    year, mode = int(sys.argv[1]), sys.argv[2]
    if mode == "draft":
        write_draft(year)
        return 0
    if mode == "page":
        page_png(year, int(sys.argv[3]), sys.argv[4] if len(sys.argv) > 4 else None)
        return 0
    if mode == "stage":
        return stage(year)
    sys.exit(f"unknown mode {mode!r}")


if __name__ == "__main__":
    sys.exit(main())
