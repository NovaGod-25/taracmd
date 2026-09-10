"""Tidy OCR'd question text: page furniture, the next question bleeding in, 3 read as 8.

    python tools/pyq-tidy.py            # report what it would change in content/quiz.json
    python tools/pyq-tidy.py --write    # change it

Only questions with a paper cell (the Commission's scans) are touched, and only
their words: the answer, the order of the options and every id stay as they are.
pyq-stage.py runs the same functions on everything it stages, so a year scanned
later comes in already clean, and refuses what problems() still finds wrong.

What the column crop leaves behind, and what is done about it:

  * The booklet code and page footer, "VGYH-U-FGT (3-", "BXC-U-FTHI/68A 13",
    "23 [ P.T.O." -- everything from there on is the page, not the question.
  * The next question, when an option ends a column: "2 and 3 only 99. Consider
    the following statements". Cut at the next question's own number.
  * "3" read as "8" in statement numbers. A statement-reference option cannot
    cite a statement the question does not have, so the 8 in "1 and 8 only" is
    a 3 unless the question really lists five, six and seven. The same misread
    in the stem's own list (1. 2. 8. 4.) is put back in order. A 3 read as two
    glyphs -- "38", "83", "B8", "S8", "3S8", "30", "80" -- is the same 3, and so
    is the "38" in an ordering "38-4-1-2" whose other three are 1, 2 and 4.
  * "1,2and3", "8only", "80nly", "land 3 only", "i,2and3", "2,.3and.5",
    "Both1land2" -- spacing, specks, and the 1 read as an l or an i. "and 2
    only" has lost its 1: nothing else can come before a 2, and "Both _ and 2"
    can only be "Both 1 and 2".
  * Roman lists (2025 numbers its statements I, II, III): "Il" is II, "Ill" is
    III, a lone "1" is I, and "I, II and II" -- a list never names a statement
    twice -- has lost the last I of its III.
  * Pipes, underscores, backslashes and stray quotes from table rules and specks.

What it does not do: guess. "1, Sand 4" could be a 3 or a 5, and a word
clipped by the column split ("Inc" for "India,") is not restored. Those are
reported by problems() and left for a person with the page in front of them.
"""
import importlib.util
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("scan", ROOT / "tools" / "pyq-scan.py")
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)

BOOKLET = r"[A-Z]{3,4}-[A-Z]-[A-Z]{3,4}\b"
BOOKLET_CUT = re.compile(rf"\s*{BOOKLET}.*$", re.S)
# "[ P.T.O." every way tesseract reads it -- "[ P:P.0:", "[-P:TO.", "{ PPO; {",
# "[:P2:0.", "EP-h20." -- and the bare "PTO." / "LPO." / "i P.F0;" at the very
# end. The bare forms want a space before and a stop after, so "(EPFO)" is safe.
PTO_CUT = re.compile(r"\s*(?:[\[{]\s*[-:]?\s*P\S{0,6}.*"
                     r"|(?<=\s)(?:[A-Za-z]\s+)?(?:L?P\.?\s*[TF]?\.?\s*[O0]|[A-Z]?P[-.:]\w?\d?[O0])[.;:]\W*)$",
                     re.S)
# What the crop leaves of a "( 5 - A )" footer at the end of an option: "(7-",
# "(2:", "(17". A closed "(1)" is never touched.
FOOT_END = re.compile(r"\s*\(\s*\d{1,3}\s*(?:[-\u2013:!.]\s*[A-D]?\s*\)?)?\s*$")
# ...and of the same footer read inside the column: " A)", "-~A)", " - A )".
# Needs a space or a dash before the letter so an option ending "Act)" is safe.
FOOT_SCRAP = re.compile(r"(?:\s+|[-~\u2013\u2014]+)\s*[A-D]\s*\)\s*$")
JUNK_TAIL = re.compile(r"(?:\s*[|~_*\u00b0;:\u00bb\u00ab\u00a7]+|\s+[.,\-'\u2018\u2019]+|\s+[=<>^]\S{0,3})+$")
JUNK_HEAD = re.compile(r"^(?:(?:[^\w\s(\u201c\u2018\"']|_)+\s*|['\u2018]\s+)+")
# In a stem, furniture sits in the middle when a question runs over a page.
STEM_FURNITURE = re.compile(
    rf"\s*(?:{BOOKLET}(?:/\w+)?(?:\s*\(\s*\d{{1,3}}\s*[-\u2013]\s*[A-D]\s*\))?"
    r"|\d{1,3}\s*\[\s*P\.?\s*T\.?\s*O\.?\s*\]?)")

REF = re.compile(r"(?:Only\s+)?\d(?:\s*,\s*\d)*(?:\s+and\s+\d)*(?:\s+only)?"
                 r"|Both\s+1\s+and\s+2|Neither\s+1\s+nor\s+2", re.I)
RN = r"(?:III|II|IV|I|V)"
ROMAN = re.compile(rf"{RN}(?:\s*,\s*{RN})*(?:\s+and\s+{RN})*(?:\s+only)?"
                   r"|Both\s+I\s+and\s+II|Neither\s+I\s+nor\s+II")
RVAL = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
ORDER = re.compile(r"\d+(?:\s*[-\u2013]\s*\d+)+")
# A 3 read as two glyphs, wherever a statement number stands.
GLYPH3 = re.compile(r"(?<![\dA-Za-z])(?:3S8|[3BS]8|[38]0|83)(?=\s|,|-|and|only|$)")
# A list marker in a stem: a lone digit and a full stop or comma, then a space.
MARK = re.compile(r"(?:(?<=\s)|^)([1-9])(?=\s*[.,]\s)")


def next_question(n: int) -> re.Pattern:
    """Where question n+1 starts, when it has run into the end of question n."""
    return re.compile(rf"(?:(?<=\s)|(?<=[\u2018'|.*]))\s*{n + 1}\s*[.,]{{1,2}}\s+(?=[A-Z\u2018\u201c'\"])")


def renumber(stem: str) -> str:
    """Put a statement list back in order where a 3 was read as an 8."""
    want = 1

    def fix(m):
        nonlocal want
        d = int(m.group(1))
        if d == want:
            want += 1
            return m.group(1)
        if d == 8 and want == 3:
            want = 4
            return "3"
        return m.group(1)
    return MARK.sub(fix, stem)


def listed(stem: str) -> set:
    return {int(d) for d in MARK.findall(renumber(" ".join(stem.split())))}


def tidy_stem(stem: str) -> str:
    t = " ".join(stem.split())
    t = STEM_FURNITURE.sub("", t)
    t = re.sub(r"(?<=\s)\|\s*\d{2,3}\s*\.?(?=\s)", "", t)      # the next column's "| 95."
    t = re.sub(r"(?<=\s)[|_]+(?=\s)", "", t)                    # rules and underscores
    t = re.sub(r"(?<=\s)[\u2018'](?=\s+\d\s*[.,]\s)", "", t)    # a speck before "1."
    t = re.sub(r"\s+[~|_]+[\s.,;:]*$", "", t)                   # "enjoined by ~ ."
    t = re.sub(r"\s+[;|]$", "", t)
    return renumber(" ".join(t.split()))


def spaced(t: str) -> str:
    """Space a statement reference the way the paper prints it."""
    t = re.sub(r"^Both\s*\S{0,2}?\s*and\s*2$", "Both 1 and 2", t)
    t = re.sub(r"^and\s+2\b", "1 and 2", t)                     # only a 1 comes before a 2
    t = re.sub(r"^[lLI|](?=\s*and\s*\d)", "1 ", t)              # "land 3 only"
    t = re.sub(r"^[iIl|](?=\s*,\s*\d)", "1", t)                 # "i,2and3"
    t = re.sub(r"(?<=\d)0nly\b", " only", t)                    # "80nly": an O read as 0
    if ORDER.fullmatch(t):
        return t
    m = re.match(r"(?:[\d\s,.\u00b0\-]|and(?![A-Za-z])|only(?![A-Za-z]))+", t)
    if not m or not re.search(r"\d", m.group(0)) or not re.search(r"and|only|,", m.group(0)):
        return t                                                # "65 million years", "2.5 per cent"
    head, rest = m.group(0), t[m.end():]
    head = re.sub(r"[.\u00b0\-]", " ", head)
    head = re.sub(r"(?<=\d)\s*and\s*(?=\d)", " and ", head)
    head = re.sub(r"(?<=\d)\s*only", " only", head)
    head = re.sub(r"\s*,\s*(?=\d)", ", ", head)
    return " ".join((head + " " + rest).split())


def _head(rx: re.Pattern, t: str):
    """The statement reference an option starts with, and what follows it --
    or None when the reference does not end cleanly ("38, 4", "1, 2ands")."""
    m = rx.match(t)
    if not m:
        return None
    rest = t[m.end():]
    if rest and not rest[0].isspace():
        return None
    if re.match(r"\s*[,&]", rest) or re.match(r"\s*\W*\s*(?:an|nor\b|or\b)", rest):
        return None                                             # the reference goes on
    return m.group(0), rest


def ref_head(t: str):
    return _head(REF, t)


def romans(options: list[str]) -> list[str]:
    """Statement I, II, III: "Il" is II, "Ill" is III, a lone "1" is I."""
    fix = [re.sub(r"\b(?:Ill|lll|IIl|lIl|IlI)\b", "III",
                  re.sub(r"\b(?:Il|lI|ll)\b", "II", o)) for o in options]
    fix = [re.sub(r"(?<![\d,])\b1\b(?=\s*(?:,|and|only))", "I", o) for o in fix]
    heads = [_head(ROMAN, o) for o in fix]
    if sum(1 for h in heads if h and not re.search(r"[A-Za-z]{3,}", h[1])) < 2:
        return options
    out = []
    for o, h in zip(fix, heads):
        o = h[0] if h else o
        nums = re.findall(RN, o) if h else []
        if len(nums) >= 2 and nums[-1] == nums[-2] == "II":
            k = o.rfind("II")
            cand = o[:k] + "III" + o[k + 2:]
            if cand not in fix and cand not in out:
                o = cand
        out.append(o)
    return out


def tail(o: str) -> str:
    for _ in range(4):
        o2 = JUNK_TAIL.sub("", o).strip()
        if o2.endswith("\u2018"):
            o2 = o2[:-1].rstrip()
        if o2.endswith("\u2019") and "\u2018" not in o2:
            o2 = o2[:-1].rstrip()
        if o2.endswith("'") and o2.count("'") % 2:
            o2 = o2[:-1].rstrip()
        if o2 == o:
            break
        o = o2
    return o


def _base(opt: str, n: int | None) -> tuple[str, bool]:
    t = " ".join(opt.split())
    before = len(t)
    if n is not None:
        m = next_question(n).search(t)
        if m and m.start() > 0:
            t = t[:m.start()]
    t = PTO_CUT.sub("", BOOKLET_CUT.sub("", t))
    cut = len(t) < before
    for _ in range(4):
        t2 = FOOT_SCRAP.sub("", FOOT_END.sub("", t))
        t2 = tail(JUNK_HEAD.sub("", t2.strip()))
        if t2 == t:
            break
        t = t2
    t = re.sub(r"\s[|~_\\]+(?=\s)", "", t)
    t = re.sub(r"(?<=[a-z])\s:\s(?=[a-z])", " ", t)             # "others : use"
    if "\u2018" in t and "\u2019" not in t:                     # a speck read as an opening quote
        t = re.sub(r"\u2018\s*", "", t)
    return " ".join(t.split()), cut


def tidy_options(stem: str, options: list[str], n: int | None = None) -> list[str]:
    found = listed(stem)
    eight_is_three = not ({5, 6, 7} <= found) and (not found or 3 in found)
    based = [_base(o, n) for o in options]
    texts = [spaced(t) for t, _ in based]
    heads = [ref_head(t) for t in texts]
    # a question whose options are statement numbers: two of them read cleanly
    is_ref = sum(1 for h in heads if h and not re.search(r"[A-Za-z]{3,}", h[1])) >= 2
    out = []
    for (raw, cut), t, h in zip(based, texts, heads):
        if is_ref and not h and eight_is_three:
            cand = spaced(GLYPH3.sub("3", raw))
            if ref_head(cand):
                t, h = cand, ref_head(cand)
        if ORDER.fullmatch(t):
            o = "-".join(re.findall(r"\d+", t))
            if eight_is_three and bad_order(o):
                for fix in (o.replace("8", "3"), GLYPH3.sub("3", o)):
                    if not bad_order(fix):
                        o = fix
                        break
        elif is_ref and h:
            o = h[0]
            if eight_is_three:
                o = o.replace("8", "3")
        else:
            o = t
            if cut:                                             # the page number left before "[ P.T.O."
                o = re.sub(r"\s+\d{1,3}(?:\s+[^\s\d]{1,4})?\s*$", "", o)
            if (len(o.split()) >= 4 and not re.search(r"\d", o[:-2])
                    and not re.search(r"\b(?:and|or|nor)\s+\S$", o)):
                o = re.sub(r"(?<=[a-z]{2})\s+(?:\d|[a-z])$", "", o)   # "to its members 5"
        out.append(tail(scan.repair_option(o)).strip())
    return romans(out)


def bad_order(opt: str) -> bool:
    """An ordering option that is not a permutation of 1..k is a misread."""
    if not ORDER.fullmatch(opt):
        return False
    d = re.findall(r"\d+", opt)
    return sorted(d) != [str(i) for i in range(1, len(d) + 1)]


def problems(stem: str, options: list[str]) -> list[str]:
    """What is still wrong after tidying -- staging refuses a question with any."""
    why = []
    is_ref = sum(bool(REF.fullmatch(o)) for o in options) >= 2
    is_roman = sum(bool(ROMAN.fullmatch(o)) for o in options) >= 2
    for o in options:
        if re.search(BOOKLET, o) or re.search(r"\[\s*P\W{0,2}T", o):
            why.append(f"page furniture in {o!r}")
        if bad_order(o):
            why.append(f"ordering {o!r} is not a permutation")
        if is_ref and re.search(r"\d", o):
            if any(int(x) > 9 for x in re.findall(r"\d+", o)):
                why.append(f"{o!r} cites a statement number past 9")
            elif not REF.fullmatch(o):
                why.append(f"{o!r} is not a statement reference")
            elif not re.match(r"(?:Both|Neither)", o):
                d = [int(x) for x in re.findall(r"\d", o)]
                if d != sorted(set(d)):
                    why.append(f"{o!r} does not list its statements in order")
        elif is_roman and re.search(r"\b[IVl1]{1,3}\b", o):
            if not ROMAN.fullmatch(o):
                why.append(f"{o!r} is not a statement reference")
            else:
                d = [RVAL[x] for x in re.findall(RN, o)]
                if d != sorted(set(d)):
                    why.append(f"{o!r} does not list its statements in order")
    if len(set(options)) != len(options) or any(not o for o in options):
        why.append("options not four distinct and non-empty")
    return why


def main() -> int:
    write = "--write" in sys.argv
    path = ROOT / "content" / "quiz.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    # what a person read off the page wins over anything a rule could do
    reads = json.loads((ROOT / "tools" / "pyq-page-reads.json").read_text(encoding="utf-8"))["options"]
    stems = opts = kept = 0
    left = []
    for q in doc["questions"]:
        p = q.get("paper")
        if not p:
            continue
        s = tidy_stem(q["q"])
        o = reads.get(q["id"]) or tidy_options(q["q"], q["options"], p.get("n"))
        if len(set(o)) != len(o) or any(not x for x in o):
            kept += 1
            print(f"  KEPT AS IS {q['id']}: tidying would leave {o}")
            o = q["options"]
        if s != q["q"]:
            stems += 1
            print(f"  {q['id']} stem\n      - {q['q']}\n      + {s}")
            q["q"] = s
        for i, (a, b) in enumerate(zip(q["options"], o)):
            if a != b:
                opts += 1
                print(f"  {q['id']} ({'abcd'[i]}) {a!r}\n{'':>{len(q['id']) + 8}}-> {b!r}")
        q["options"] = o
        why = problems(q["q"], o)
        if why:
            left.append((q["id"], why))
    print(f"\n{stems} stems and {opts} options {'changed' if write else 'would change'}; "
          f"{kept} questions left as they were")
    print(f"{len(left)} questions still need a person with the page:")
    for qid, why in left:
        print(f"  {qid}: {'; '.join(why)}")
    if write:
        with path.open("w", encoding="utf-8", newline="\n") as fh:   # as quiz-import writes it
            json.dump(doc, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
