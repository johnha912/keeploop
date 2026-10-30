"""ledger.py — the append-only results ledger (.keeploop/results.tsv).

Borrowed directly from Karpathy's autoresearch: one TSV row per experiment,
never edited, never deleted. Corrections are new rows. Anyone — human or
agent — can audit the team's entire history from this one file.
"""

import csv
from pathlib import Path

FIELDS = ["cycle", "ts", "role_vendors", "metric", "best_metric",
          "status", "tokens", "lesson_id", "description"]

STATUSES = ("keep", "discard", "crash")


def append_row(state_dir: Path, row: dict) -> None:
    """Append one cycle row. `status` must be keep/discard/crash."""
    if row.get("status") not in STATUSES:
        raise ValueError(f"invalid ledger status: {row.get('status')!r}")
    path = state_dir / "results.tsv"
    is_new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t")
        if is_new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in FIELDS})


def read_rows(state_dir: Path) -> list[dict]:
    path = state_dir / "results.tsv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def tail_text(state_dir: Path, n: int) -> str:
    """Last n rows as plain text — what the Analyst sees in its prompt."""
    rows = read_rows(state_dir)[-n:]
    if not rows:
        return "(ledger is empty — this is the first cycle)"
    lines = ["\t".join(FIELDS)]
    for r in rows:
        lines.append("\t".join(str(r.get(k, "")) for k in FIELDS))
    return "\n".join(lines)
