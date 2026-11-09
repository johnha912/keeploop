"""holdout.py - the hidden evaluation for the noisy-eval example. Humans only.

The same pipeline quality as evaluate.py, scored on 5,000 held-out cases that the
dev set does not contain, ALL of them: no sampling, so no noise. run.py scores the
untouched workspace once before cycle 1 and the final HEAD once after the last
cycle; no prompt, ledger row or lesson ever sees these numbers.

Usage:  python holdout.py <workspace-dir>
"""

import sys
from pathlib import Path

from evaluate import difficulties, load, quality

HOLDOUT_CASES = 5_000


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python holdout.py <workspace-dir>", file=sys.stderr)
        return 2
    q = quality(load(Path(sys.argv[1])))
    cases = difficulties(HOLDOUT_CASES, "keeploop-noisy-eval-holdout")
    print(f"{sum(d < q for d in cases) / HOLDOUT_CASES:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
