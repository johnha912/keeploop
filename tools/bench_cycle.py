"""Per-cycle cost of the headless loop on the offline mock demo: wall time and tokens.

    python tools/bench_cycle.py [--reps 7] [--cycles 6] [--json OUT]

Each rep builds a fresh demo project (`kl init` into a temp folder), then times
`run.py --mock --iterations 0` (baseline only) and `--iterations N` in that
order, each in a fresh project. Per-cycle wall time = (t_N - t_0) / N, so the
baseline evaluations and process start-up are not counted. Tokens per cycle =
the ledger's `tokens` column (the mock's estimate: prompt + reply characters / 4)
summed over the N cycles, divided by N. Prints the median over the reps and every rep.

The mock spends no real tokens; the estimate still moves when a prompt grows,
which is the regression it guards against. Used before and after a change: the
release budget is "no worse than 5% per cycle" unless the change is behind a
default-off flag.
"""

import argparse
import csv
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import scaffold  # noqa: E402


def one(iterations: int, tmp: Path, tag: str) -> tuple[float, list[int]]:
    proj = tmp / tag
    scaffold.init(proj, rewrite=False, src=REPO)
    start = time.perf_counter()
    p = subprocess.run([sys.executable, "-X", "utf8", str(REPO / "run.py"), "--root", str(proj),
                        "--mock", "--iterations", str(iterations)],
                       capture_output=True, text=True, encoding="utf-8")
    wall = time.perf_counter() - start
    if p.returncode != 0:
        raise SystemExit(f"run failed:\n{p.stdout}\n{p.stderr}")
    with (proj / ".keeploop" / "results.tsv").open(encoding="utf-8") as f:
        toks = [int(r["tokens"] or 0) for r in csv.DictReader(f, delimiter="\t")
                if int(r["cycle"]) >= 1]
    return wall, toks


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reps", type=int, default=7)
    ap.add_argument("--cycles", type=int, default=6)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    per_cycle, tokens = [], []
    with tempfile.TemporaryDirectory(prefix="kl-bench-") as d:
        tmp = Path(d)
        one(a.cycles, tmp, "warmup")  # file cache, imports
        for r in range(a.reps):
            t0, _ = one(0, tmp, f"r{r}-0")
            tn, toks = one(a.cycles, tmp, f"r{r}-n")
            per_cycle.append((tn - t0) / a.cycles)
            tokens.append(sum(toks) / max(1, len(toks)))
    out = {"reps": a.reps, "cycles": a.cycles,
           "wall_s_per_cycle_median": round(statistics.median(per_cycle), 4),
           "wall_s_per_cycle_all": [round(x, 4) for x in per_cycle],
           "tokens_per_cycle_median": round(statistics.median(tokens), 1)}
    print(json.dumps(out, indent=2))
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
