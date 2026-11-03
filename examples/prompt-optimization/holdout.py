"""holdout.py - the hidden second evaluation (anti-Goodhart) for the prompt example. Humans only.

Same harness as evaluate.py, scored on holdout.jsonl: 100 tickets of the same 10
labels, disjoint from the dev set. holdout.jsonl sits next to this file at the
keeploop root, OUTSIDE the workspace. run.py scores the untouched baseline and
the final HEAD with it once each; no prompt, ledger row or lesson sees the
numbers. Limit: the fence stops writes outside the workspace, not reads, so a
vendor CLI could technically read this file.

Same contract as evaluate.py: one float on stdout, exit 2 on an invalid
workspace, exit 1 on a crash.

Usage:  python holdout.py <workspace-dir>
"""

import sys
from pathlib import Path

from evaluate import load_rows, report, score, validate  # same harness as the visible evaluation

HERE = Path(__file__).resolve().parent


def main() -> int:
    data = next((p for p in (HERE / "holdout.jsonl", HERE / "data" / "holdout.jsonl") if p.is_file()), None)
    if data is None:
        print("MISSING holdout.jsonl next to holdout.py", file=sys.stderr)
        return 2
    prompt, _, error = validate(Path(sys.argv[1]))  # prompt.md checks; the workspace dev set is not scored here
    if error and not error.startswith("data/"):
        print(f"INVALID WORKSPACE: {error}", file=sys.stderr)
        return 2
    try:
        acc, pairs = score(prompt, load_rows(data))
    except RuntimeError as exc:
        print(f"SCORING CRASHED: {exc}", file=sys.stderr)
        return 1
    report(pairs)
    print(f"{acc:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
