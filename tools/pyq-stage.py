"""Stage one scanned year for import: corroborated questions only, topics by hand.

    python tools/pyq-scan.py tools/.qp-pdfs/qp-2024-gs1.pdf --year 2024 --code gs1
    python tools/pyq-stage.py 2024 intake/topics-2024-gs1.json
    python tools/quiz-import.py intake/upsc-2024-gs1-seta-add.json --dry-run

The rule, in order, and every question failing it is counted rather than lost
silently: its printed number was READ off the page, not inferred from position;
the Commission did not drop it; tidied (tools/pyq-tidy.py), its four options
are distinct and problems() finds nothing still wrong with them; and a topic for
it was assigned by a person in the topics file. Questions already in the bank
are skipped, so a year can be re-scanned and staged again and only what is new
comes through.
"""
import importlib.util
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("tidy", ROOT / "tools" / "pyq-tidy.py")
tidy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tidy)


def main() -> int:
    year = int(sys.argv[1])
    topics = {int(k): v for k, v in json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")).items()}
    subs = json.loads((ROOT / "content" / "subjects.json").read_text(encoding="utf-8"))
    subs = subs["subjects"] if isinstance(subs, dict) else subs
    valid = {t["id"] for s in subs for t in s["topics"]}
    bad = {n: t for n, t in topics.items() if t not in valid}
    if bad:
        sys.exit(f"topic ids that do not exist: {bad}")

    src = json.loads((ROOT / "intake" / f"scan-{year}-gs1.json").read_text(encoding="utf-8"))
    have = json.loads((ROOT / "content" / "quiz.json").read_text(encoding="utf-8"))["questions"]
    already = {q["paper"]["n"] for q in have
               if q.get("paper", {}).get("year") == year and q["paper"].get("code") == "gs1"}

    out, left, refused = [], Counter(), []
    for q in src["questions"]:
        n = q["n"]
        if n in already:
            left["already in the bank"] += 1; continue
        if not q.get("read"):
            left["number not read off the page"] += 1; continue
        if q.get("answer") is None:
            left["dropped by the Commission"] += 1; continue
        stem = tidy.tidy_stem(q["q"])
        opts = tidy.tidy_options(q["q"], q["options"], n)
        why = tidy.problems(stem, opts)
        if len(opts) != 4 or why:
            left["options unusable"] += 1
            if n in topics:
                refused.append((n, why or [f"{len(opts)} options"]))
            continue
        if n not in topics:
            left["no confident topic"] += 1; continue
        out.append({"n": n, "topic": topics[n], "q": stem,
                    "options": opts, "answer": q["answer"], "paper": q["paper"]})

    dest = ROOT / "intake" / f"upsc-{year}-gs1-set{src['paperSet'].lower()}-add.json"
    dest.write_text(json.dumps({
        "note": f"UPSC Civil Services Prelims {year}, GS Paper I, Series {src['paperSet']}. OCR "
                "of the Commission's own scan; only questions whose printed number was READ off "
                "the page. Answers are the Commission's own key.",
        "questions": out}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{year}: {len(out)} staged -> {dest.name}; left out: {dict(left)}")
    for n, why in refused:
        print(f"  Q{n} has a topic but was refused: {'; '.join(why)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
