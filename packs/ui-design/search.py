"""search.py — search this pack's reference base (styles, palettes, fonts).

The data-driven half of the design pack, in the spirit of UI/UX skill
packs that ship a searchable knowledge base instead of vibes: the Engineer
queries it BEFORE inventing a style, and cites what it picked.

Ranking is a compact BM25 over each row's combined text (stdlib only).

Usage:
    python packs/ui-design/search.py "dark dashboard for fintech analytics"
    python packs/ui-design/search.py "warm editorial blog" --top 3
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bm25 import bm25_rank  # noqa: E402  (shared ranker, repo root)

DATA_DIR = Path(__file__).resolve().parent / "data"
FILES = {"style": "styles.csv", "palette": "palettes.csv", "font": "fonts.csv"}


def load_rows() -> list[dict]:
    rows = []
    for kind, filename in FILES.items():
        with (DATA_DIR / filename).open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                row["_kind"] = kind
                row["_text"] = " ".join(str(v) for v in row.values())
                rows.append(row)
    return rows


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # same bytes on any Windows codepage
    parser = argparse.ArgumentParser(description="search the ui-design reference base")
    parser.add_argument("query")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()
    results = [(s, r) for s, r in bm25_rank(args.query, load_rows()) if s > 0][:args.top]
    if not results:
        print("no matches — try broader terms (product type, mood, surface)")
        return 0
    for score, row in results:
        name = row.get("style") or row.get("name") or row.get("pairing")
        detail = row.get("description") or row.get("mood") or row.get("notes") or ""
        print(f"[{row['_kind']}] {name} (score {score:.2f}) — {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
