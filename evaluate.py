"""evaluate.py — THE fixed evaluation. Demo version. Humans only.

This file is sacred by design (see program.md): the loop may never modify
it, and a diff that touches it is an automatic crash plus a lesson. For a
real project, replace `score()` with your own metric — a test pass rate, a
benchmark, a competition validation score — as long as it prints exactly
one float (higher = better) and validates its inputs honestly.

Demo: scores a toy training config. The optimum is interior on purpose
(learning_rate 0.03, batch_size 64, dropout 0.2, optimizer adam), so a loop
that only ever turns knobs one way cannot win by accident.

Usage:  python evaluate.py <workspace-dir>   (reads <workspace-dir>/config.json)
Exit:   0 and prints the metric; 2 if the workspace is invalid or empty (a crash the
        loop must learn from, not hide).
"""

import json
import math
import sys
from pathlib import Path

VALID_BATCHES = {8, 16, 32, 64, 128, 256}
VALID_OPTIMIZERS = {"adam", "sgd", "rmsprop"}


def validate(cfg: dict) -> str | None:
    """Return an error string, or None if the workspace is valid."""
    lr = cfg.get("learning_rate")
    if not isinstance(lr, (int, float)) or not (0 < lr <= 1):
        return f"learning_rate out of range (0, 1]: {lr!r}"
    if cfg.get("batch_size") not in VALID_BATCHES:
        return f"batch_size not one of {sorted(VALID_BATCHES)}: {cfg.get('batch_size')!r}"
    drop = cfg.get("dropout")
    if not isinstance(drop, (int, float)) or not (0 <= drop <= 0.9):
        return f"dropout out of range [0, 0.9]: {drop!r}"
    if cfg.get("optimizer") not in VALID_OPTIMIZERS:
        return f"optimizer not one of {sorted(VALID_OPTIMIZERS)}: {cfg.get('optimizer')!r}"
    return None


def score(cfg: dict) -> float:
    penalty = (
        (math.log10(cfg["learning_rate"]) - math.log10(0.03)) ** 2 * 0.50
        + ((cfg["batch_size"] - 64) / 64) ** 2 * 0.20
        + (cfg["dropout"] - 0.2) ** 2 * 0.80
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
