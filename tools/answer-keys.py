#!/usr/bin/env python3
"""Find and read the Commission's own Prelims answer keys.

    python3 tools/answer-keys.py discover     # fill in URLs that are still null
    python3 tools/answer-keys.py extract      # read Set A/B/C/D letters off them
    python3 tools/answer-keys.py extract --dry-run   # print, do not write

RUN THIS LOCALLY, NEVER IN CI.

upsc.gov.in rate-limits hard - it stopped answering entirely after roughly 45
requests in one session, and once it stops it stays stopped for a while. Every
request here is separated by THROTTLE seconds on purpose. Do not lower it, do
not parallelise it, and do not put it on a schedule. There is nothing here that
needs to be fast; there are nine years of keys and they are published once.

Note the asymmetry the app depends on: UPSC publishes answer keys for Prelims
only. There has never been a Mains key. The Mains tab showing no key chips is
correct behaviour, not a gap to be filled.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYS_FILE = ROOT / "content" / "answer-keys.json"
CACHE = ROOT / "tools" / ".key-pdfs"      # downloaded once, reread for free

KEY_INDEX = "https://www.upsc.gov.in/examinations/answer-key"
UA = "Mozilla/5.0 (compatible; TaraCmd/1.0; personal study tool)"

THROTTLE = 4.0
_last = 0.0


def fetch(url: str, binary: bool = False):
    """One request, never sooner than THROTTLE seconds after the last."""
    global _last
    wait = THROTTLE - (time.monotonic() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()

    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        print(f"  ! {e.code} {url}")
        return None
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  ! {e} {url}")
        return None

    return raw if binary else raw.decode("utf-8", "replace")


def load_keys():
    with KEYS_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_keys(keys) -> None:
    """Written the way build.py's content files are: two-space, UTF-8 as-is."""
    with KEYS_FILE.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(keys, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ------------------------------------------------------------------ discover

LINK = re.compile(r'href="([^"]+\.pdf)"', re.IGNORECASE)

# What a Prelims key PDF's filename tends to look like, across the years the
# Commission has changed its own convention several times.
def looks_like_key(href: str, year: int, code: str) -> bool:
    name = href.rsplit("/", 1)[-1].lower()
    if "anskey" not in name and "answer" not in name:
        return False
    if str(year) not in name and str(year % 100) not in name:
        return False
    if "csp" not in name and "civilservicesp" not in name and "prelim" not in name:
        return False

    paper1 = ("paper-i", "paper_i", "paper%20i", "studies-i", "studies_i", "gs-i")
    paper2 = ("paper-ii", "paper_ii", "paper%20ii", "studies-ii", "studies_ii", "gs-ii")
    # -ii must be tested first: "paper-i" is a prefix of "paper-ii"
    if any(p in name for p in paper2):
        return code == "gs2"
    if any(p in name for p in paper1):
        return code == "gs1"
    return False


def discover(args) -> int:
    keys = load_keys()

    missing = [
        (y["year"], p["code"])
        for y in keys["years"] for p in y["papers"] if not p.get("url")
    ]
    if not missing:
        print("every paper already has a URL")
        return 0
    print(f"{len(missing)} paper(s) with no URL: "
          + ", ".join(f"{y} {c}" for y, c in missing))

    print(f"\nreading {KEY_INDEX}")
    page = fetch(KEY_INDEX)
    if page is None:
        print("could not read the answer-key index - try again later, unhurried")
        return 1

    hrefs = {h if h.startswith("http") else "https://www.upsc.gov.in" + h
             for h in LINK.findall(page)}
    print(f"  {len(hrefs)} pdf link(s) on the page")

    found = 0
    for year in keys["years"]:
        for paper in year["papers"]:
            if paper.get("url"):
                continue
            hit = next((h for h in sorted(hrefs)
                        if looks_like_key(h, year["year"], paper["code"])), None)
            if hit:
                paper["url"] = hit
                found += 1
                print(f"  + {year['year']} {paper['code']}  {hit}")

    if found:
        save_keys(keys)
        print(f"\nwrote {found} URL(s) into content/answer-keys.json")
        print("run `python3 build.py` to put the new chips on the Prelims tab")
    else:
        print("\nnothing matched. The Commission archives older keys off this "
              "page - those years may need finding by hand.")
    return 0


# ------------------------------------------------------------------- extract

def pdf_text(raw: bytes, name: str) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("extract needs pypdf:  python3 -m pip install pypdf")

    import io
    try:
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:
        print(f"  ! could not read {name}: {e}")
        return None


# A key PDF is a grid: question number, then one letter per set. The column
# order is given by a header row naming the sets. Layout has changed between
# years, so this is a heuristic - always eyeball --dry-run before writing.
ROW = re.compile(r"^\s*(\d{1,3})\s+([ABCD])(?:\s+([ABCD]))?(?:\s+([ABCD]))?(?:\s+([ABCD]))?\s*$")
HEADER = re.compile(r"\bSET\b[^\n]*?\bA\b", re.IGNORECASE)


def parse_key(text: str, questions: int):
    """→ ({set: [letters]}, note) or (None, why not)."""
    sets_in_header = None
    for line in text.splitlines():
        if HEADER.search(line):
            found = re.findall(r"\b([ABCD])\b", line.upper())
            if len(found) >= 2:
                sets_in_header = found
                break

    rows: dict[int, list[str]] = {}
    for line in text.splitlines():
        m = ROW.match(line)
        if not m:
            continue
        q = int(m.group(1))
        letters = [g for g in m.groups()[1:] if g]
        if 1 <= q <= questions:
            rows.setdefault(q, letters)

    if not rows:
        return None, "no question/letter rows recognised"

    width = max(len(v) for v in rows.values())
    names = sets_in_header if sets_in_header and len(sets_in_header) == width \
        else ["A", "B", "C", "D"][:width]

    out: dict[str, list[str]] = {}
    for i, set_name in enumerate(names):
        letters = []
        for q in range(1, questions + 1):
            row = rows.get(q, [])
            letters.append(row[i] if i < len(row) else None)
        if any(l is None for l in letters):
            gaps = [q for q in range(1, questions + 1) if letters[q - 1] is None]
            return None, (f"set {set_name} is short: {len(gaps)} question(s) "
                          f"unread, first at {gaps[0]}")
        out[set_name] = letters

    return out, f"{len(out)} set(s) x {questions}"


def extract(args) -> int:
    keys = load_keys()
    marking = keys["marking"]
    CACHE.mkdir(exist_ok=True)

    todo = [(y, p) for y in keys["years"] for p in y["papers"]
            if p.get("url") and not p.get("keys")]
    if not todo:
        print("nothing to extract: every paper with a URL already has letters")
        return 0

    print(f"{len(todo)} paper(s) to read\n")
    wrote = 0

    for year, paper in todo:
        tag = f"{year['year']} {paper['code']}"
        name = paper["url"].rsplit("/", 1)[-1]
        cached = CACHE / name

        if cached.is_file():
            raw = cached.read_bytes()
            print(f"{tag}  cached  {name}")
        else:
            print(f"{tag}  fetch   {name}")
            raw = fetch(paper["url"], binary=True)
            if raw is None:
                continue
            cached.write_bytes(raw)

        text = pdf_text(raw, name)
        if text is None:
            continue

        questions = marking[paper["code"]]["questions"]
        parsed, note = parse_key(text, questions)
        if parsed is None:
            print(f"          skip: {note}")
            continue

        print(f"          {note}: " + ", ".join(
            f"{s}={''.join(v[:6])}…" for s, v in parsed.items()))

        if not args.dry_run:
            paper["keys"] = parsed
            wrote += 1

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    if wrote:
        save_keys(keys)
        print(f"\nwrote letters for {wrote} paper(s)")
        print("run `python3 build.py`, then Quiz → Score a paper has a grid")
    else:
        print("\nnothing written")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("discover", help="fill in answer-key URLs that are still null")

    ex = sub.add_parser("extract", help="read Set A/B/C/D letters off the key PDFs")
    ex.add_argument("--dry-run", action="store_true",
                    help="print what was parsed without writing it")

    args = ap.parse_args()
    return {"discover": discover, "extract": extract}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
