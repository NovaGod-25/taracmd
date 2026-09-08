#!/usr/bin/env python3
"""Process every staged batch in one go, and remember what was already done.

    python3 tools/intake.py --dry-run     # say what would happen
    python3 tools/intake.py               # import, log, rebuild

The Drive folder holds papers. Reading one is judgement — which of the 242
topics a question belongs to is not something a script should guess at — so
each paper becomes a staged file under `intake/` by hand, and this takes it
from there for all of them at once.

Why a log rather than just importing whatever is in the folder: dropping five
papers in, processing three, then dropping two more is the normal case, and
re-importing the first three every time is how a bank ends up with the same
question three times under three ids. `tools/.intake-log.json` records what
has been taken, keyed by the batch's own id and the hash of its contents — so
re-running is free, and a batch you CORRECTED is noticed and re-imported
rather than skipped.

Nothing here fetches anything. The questions end up inlined in the built HTML
like every other byte of content, which is what lets the app work offline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTAKE = ROOT / "intake"
LOG = ROOT / "tools" / ".intake-log.json"
IMPORT = ROOT / "tools" / "quiz-import.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def batch_id(doc: dict, path: Path) -> str:
    src = doc.get("source") or {}
    parts = [str(src.get(k)) for k in ("name", "test", "year") if src.get(k)]
    return " · ".join(parts) if parts else path.stem


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="re-import batches already in the log")
    args = ap.parse_args()

    if not INTAKE.is_dir():
        sys.exit(f"no {INTAKE.relative_to(ROOT).as_posix()}/ — nothing staged to import")

    log = json.loads(LOG.read_text(encoding="utf-8")) if LOG.is_file() else {}
    staged = sorted(INTAKE.glob("*.json"))
    if not staged:
        print("nothing staged")
        return 0

    todo, already = [], []
    for path in staged:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"  ! {path.name}: not valid JSON, line {exc.lineno} — {exc.msg}")
            continue
        bid, d = batch_id(doc, path), digest(path)
        prev = log.get(bid)
        if prev and prev.get("digest") == d and not args.force:
            already.append(bid)
            continue
        todo.append((path, bid, d, prev is not None, len(doc.get("questions", []))))

    print(f"{len(staged)} staged, {len(todo)} to process, {len(already)} already done")
    for bid in already:
        print(f"  = {bid} (unchanged since it was imported)")
    for _, bid, _, seen, n in todo:
        print(f"  {'~' if seen else '+'} {bid} — {n} question(s){' (changed since last time)' if seen else ''}")

    if args.dry_run:
        print("\n--dry-run: nothing imported, nothing rebuilt")
        return 0
    if not todo:
        print("\nnothing new")
        return 0

    for path, bid, d, _, _ in todo:
        print(f"\n--- {bid} ---")
        r = subprocess.run([sys.executable, str(IMPORT), str(path)],
                           cwd=ROOT, capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        if r.returncode != 0:
            sys.stderr.write(r.stderr)
            print(f"\n{bid} failed; stopping so the log stays honest")
            return 1
        log[bid] = {"digest": d, "file": path.name}

    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nlogged {len(todo)} batch(es) in {LOG.relative_to(ROOT).as_posix()}")

    print("\n--- rebuilding ---")
    b = subprocess.run([sys.executable, str(ROOT / "build.py")], cwd=ROOT,
                       capture_output=True, text=True)
    sys.stdout.write(b.stdout)
    if b.returncode != 0:
        sys.stderr.write(b.stderr)
        print("\nthe build rejected the result — the questions are in "
              "content/quiz.json but the app was not rewritten")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
