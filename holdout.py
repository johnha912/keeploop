"""holdout.py — the hidden second evaluation (anti-Goodhart). Demo version. Humans only.

run.py scores the untouched workspace with this once before cycle 1 and the
final HEAD once after the last cycle, and compares the gain with evaluate.py's.
No prompt, no ledger row and no lesson ever sees these numbers; a loop that
climbs evaluate.py but not this is overfitting the evaluation, and run.py
prints a WARNING. Same contract as evaluate.py: one float on stdout (higher =
better), exit 2 on an invalid workspace.

Demo: the same toy config scored against a slightly different optimum
(learning_rate 0.03, batch_size 64, dropout 0.25, optimizer adam).

Usage:  python holdout.py <workspace-dir>
"""

import json
import math
import sys
from pathlib import Path

from evaluate import validate  # same validation as the visible evaluation


def score(cfg: dict) -> float:
    penalty = (
        (math.log10(cfg["learning_rate"]) - math.log10(0.03)) ** 2 * 0.50
        + ((cfg["batch_size"] - 64) / 64) ** 2 * 0.20
        + (cfg["dropout"] - 0.25) ** 2 * 0.80
        + (0.0 if cfg["optimizer"] == "adam" else 0.05)
    )
    return max(0.0, min(1.0, 1.0 - penalty))


def main() -> int:
    path = Path(sys.argv[1]) / "config.json"
    if not path.exists():
        print(f"MISSING WORKSPACE FILE: {path}", file=sys.stderr)
        return 2
    cfg = json.loads(path.read_text(encoding="utf-8"))
    error = validate(cfg)
    if error:
        print(f"INVALID WORKSPACE: {error}", file=sys.stderr)
        return 2
    print(f"{score(cfg):.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
