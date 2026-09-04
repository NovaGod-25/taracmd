#!/usr/bin/env python3
"""Fill in the question-paper URLs that are still null in pyq-papers.json.

    python3 tools/pyq-papers.py discover              # fetch, match, write
    python3 tools/pyq-papers.py discover --dry-run    # print only

RUN THIS LOCALLY, NEVER IN CI. Same reason as tools/answer-keys.py: upsc.gov.in
rate-limits hard and stops answering after roughly 45 requests in a session.

This one is cheap, though: two requests for the lot. The Commission publishes
every exam and every year across just two pages - the live one and the archive
- with no pagination at all, about 1,400 PDF links between them. Both are
cached under tools/.archive, so repeated runs cost nothing.

How the pages are shaped, since filenames alone will not do it. Across the years
the Commission has spelled the same paper CSP_2020_GS_Paper-1.pdf,
QP-CSP-18-GS-I-C.pdf, CSP-17-GS_PAPER-1-C.pdf and csp-p1.pdf. What is
consistent is the markup:

    <table>
      <caption>Civil Services (Preliminary) Examination, 2020</caption>
      ...
      <li>General Studies Paper-I<a href="....pdf"> (233 KB)</a></li>

So the caption gives the exam and the year, and each list item puts the paper's
own label immediately before its link. That is what this reads.
"""

from __future__ import annotations

import argparse
import html as H
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPERS_FILE = ROOT / "content" / "pyq-papers.json"
CACHE_DIR = ROOT / "tools" / ".archive"

# Two pages, and both are needed. The Commission keeps the last few sittings on
# the live page and moves older ones to the archive, with an overlap of a year
# or two. Same markup on each, so one parser reads both. Order matters only for
# the overlap, where the live page wins.
SOURCES = [
    ("current", "https://www.upsc.gov.in/examinations/previous-question-papers"),
    ("archive", "https://www.upsc.gov.in/examinations/previous-question-papers/archives"),
]

UA = "Mozilla/5.0 (compatible; TaraCmd/1.0; personal study tool)"
THROTTLE = 4.0

# Always www: the bare upsc.gov.in certificate expired on 24 Aug 2026 while
# www runs to 2 November. Do not "fix" a verify failure by turning off checks.
BASE = "https://www.upsc.gov.in"

CAPTION = re.compile(
    r"civil\s*services\s*\(\s*(preliminary|main)\s*\)\s*exam(?:ination)?\.?\s*,?\s*(\d{4})",
    re.IGNORECASE)

# "General Studies Paper - I", "...Paper-1", "...Paper II". Anchored, so the
# Mains optionals - "English Literature Paper - I" and the rest - do not match.
GS = re.compile(r"^general\s*studies\s*paper\s*[-–]?\s*(IV|III|II|I|[1-4])$", re.IGNORECASE)
ESSAY = re.compile(r"^essay$", re.IGNORECASE)

ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}


def strip_tags(s: str) -> str:
    return " ".join(H.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def label_to_code(label: str) -> str | None:
    if ESSAY.match(label):
        return "essay"
    m = GS.match(label)
    if not m:
        return None
    n = m.group(1).lower()
    return f"gs{ROMAN.get(n, n)}"


def get_page(name: str, url: str, refresh: bool) -> str | None:
    cache = CACHE_DIR / f"{name}.html"
    if cache.is_file() and not refresh:
        print(f"  {name}: cached {cache.stat().st_size:,} bytes")
        return cache.read_text("utf-8", "replace")

    time.sleep(THROTTLE)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        print(f"  {name}: ! {e.code}")
        return None
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  {name}: ! {e}")
        return None

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(raw)
    print(f"  {name}: fetched {len(raw):,} bytes")
    return raw.decode("utf-8", "replace")


def scrape(html: str) -> dict[tuple[str, int], dict[str, str]]:
    """-> {(kind, year): {code: url}} for General Studies and Essay only."""
    found: dict[tuple[str, int], dict[str, str]] = {}

    for table in re.findall(r"<table[^>]*>(.*?)</table>", html, re.S | re.I):
        cap = re.search(r"<caption[^>]*>(.*?)</caption>", table, re.S | re.I)
        if not cap:
            continue
        m = CAPTION.search(strip_tags(cap.group(1)))
        if not m:
            continue
        kind = "prelims" if m.group(1).lower() == "preliminary" else "mains"
        year = int(m.group(2))

        for li in re.findall(r"<li>(.*?)</li>", table, re.S | re.I):
            a = re.search(r'href="([^"]+\.pdf)"', li, re.I)
            if not a:
                continue
            # the label is whatever sits before the anchor
            code = label_to_code(strip_tags(re.sub(r"<a.*", "", li, flags=re.S)))
            if not code:
                continue
            url = a.group(1)
            if url.startswith("/"):
                url = BASE + url
            found.setdefault((kind, year), {}).setdefault(code, url)

    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover", help="fill in paper URLs that are still null")
    d.add_argument("--dry-run", action="store_true", help="print, do not write")
    d.add_argument("--refresh", action="store_true", help="refetch the archive page")
    args = ap.parse_args()

    with PAPERS_FILE.open(encoding="utf-8") as fh:
        papers = json.load(fh)

    gaps = [(k, y["year"], p["code"])
            for k, years in papers.items() for y in years
            for p in y["papers"] if not p.get("url")]
    if not gaps:
        print("every paper already has a URL")
        return 0
    print(f"{len(gaps)} paper(s) with no URL\n")

    found: dict[tuple[str, int], dict[str, str]] = {}
    for name, url in SOURCES:
        html = get_page(name, url, args.refresh)
        if html is None:
            continue
        for sitting, codes in scrape(html).items():
            # first source to offer a paper keeps it: live page before archive
            found.setdefault(sitting, {})
            for code, u in codes.items():
                found[sitting].setdefault(code, u)

    if not found:
        print("\ncould not read either page - try again later, unhurried")
        return 1
    print(f"\n  General Studies/Essay found for {len(found)} exam sitting(s)\n")

    filled = 0
    for kind, years in papers.items():
        for year in years:
            hit = found.get((kind, year["year"]))
            if not hit:
                continue
            for paper in year["papers"]:
                if paper.get("url") or paper["code"] not in hit:
                    continue
                paper["url"] = hit[paper["code"]]
                filled += 1
                print(f"  + {kind:8} {year['year']} {paper['code']:6} "
                      f"{paper['url'].rsplit('/', 1)[-1][:58]}")

    still = [(k, y, c) for k, y, c in gaps
             if not any(p.get("url") for yy in papers[k]
                        if yy["year"] == y for p in yy["papers"]
                        if p["code"] == c)]
    print(f"\nfilled {filled}, still missing {len(still)}")
    if still:
        by_kind: dict[str, list[str]] = {}
        for k, y, c in still:
            by_kind.setdefault(k, []).append(f"{y} {c}")
        for k, v in by_kind.items():
            print(f"  {k}: {', '.join(v)}")
        print("  - on neither page. Checked 4 Sep 2026: the Commission's own "
              "listings do not go back to 2015, and Mains 2016 has the four GS "
              "papers but no Essay. Nothing here can find those; they would "
              "have to come from somewhere that is not upsc.gov.in.")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0
    if filled:
        with PAPERS_FILE.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(papers, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"\nwrote content/pyq-papers.json")
        print("run `python3 build.py` to put the links on the tabs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
