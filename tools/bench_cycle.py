"""Per-cycle cost of the headless loop on the offline mock demo: wall time, tokens, calls.

    python tools/bench_cycle.py [--reps 7] [--cycles 6] [--json OUT]
    python tools/bench_cycle.py --latency analyst=2,engineer=4,auditor=2 --profile fast --reps 2
    python tools/bench_cycle.py --set fused=true --set auto_cards=true
    python tools/bench_cycle.py --example noisy-eval --seed 1 --cycles 20 --reps 1

Each rep builds a fresh demo project (`kl init` into a temp folder), then times
`run.py --mock --iterations 0` (baseline only) and `--iterations N` in that
order, each in a fresh project. Per-cycle wall time = (t_N - t_0) / N, so the
baseline evaluations and process start-up are not counted. Tokens per cycle =
the ledger's `tokens` column (the mock's estimate: prompt + reply characters / 4)
summed over the N cycles, divided by N. Calls per cycle = the mock's own call log
(KEEPLOOP_MOCK_LOG) by role over the N cycles, divided by N; a fused call (the
Engineer writing the card too) is counted under engineer. Prints the median over
the reps and every rep.

--latency SPEC makes every mock call sleep (KEEPLOOP_MOCK_LATENCY, e.g.
"analyst=2,engineer=4,auditor=2" seconds; a bare number covers the other roles), so
the wall time shows what fewer calls save with a real vendor. --profile NAME and
--set KEY=VALUE write `profile:` / loop keys into the project's team.yaml.
--example NAME benchmarks examples/NAME's sandbox instead of the demo (with --seed,
the noisy-eval example replays its noise, as tools/proof_run.py does); `decisions`
is then the last rep's keep/discard/crash per cycle (K/D/C).

The mock spends no real tokens; the estimate still moves when a prompt grows,
which is the regression it guards against. Used before and after a change: the
release budget is "no worse than 5% per cycle" unless the change is behind a
default-off flag.
"""

import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import scaffold  # noqa: E402

ROLES = ("analyst", "engineer", "auditor")
OPTS = argparse.Namespace(latency="", loop={}, example="", seed=None)


def set_loop(team: Path, values: dict) -> None:
    """Write each loop key into team.yaml: replace its line, or add it under `loop:`."""
    text = team.read_text(encoding="utf-8")
    for k, v in values.items():
        text, n = re.subn(rf"^  {re.escape(k)}:.*$", f"  {k}: {v}", text, flags=re.M)
        if not n:
            text, n = re.subn(r"^loop:[ \t]*\n", f"loop:\n  {k}: {v}\n", text, count=1, flags=re.M)
        if not n:
            raise SystemExit(f"{team}: no loop: section to put {k} in")
    team.write_text(text, encoding="utf-8")


def one(iterations: int, tmp: Path, tag: str) -> tuple[float, list[int], Counter, str]:
    proj = tmp / tag
    env = {**os.environ, "KEEPLOOP_MOCK_LOG": str(tmp / f"{tag}.calls.jsonl")}
    env.pop("KEEPLOOP_MOCK_LATENCY", None)
    if OPTS.latency:
        env["KEEPLOOP_MOCK_LATENCY"] = OPTS.latency
    if OPTS.example:
        root, _ = scaffold.make_sandbox(REPO / "examples" / OPTS.example, proj,
                                        with_code=True, src=REPO)
        argv = [str(root / "run.py")]
        if OPTS.seed is not None:
            env.update(KEEPLOOP_DEMO_SEED=str(OPTS.seed),
                       KEEPLOOP_DEMO_STATE=str(tmp / f"{tag}.noise.json"))
    else:
        root = proj
        scaffold.init(proj, rewrite=False, src=REPO)
        argv = [str(REPO / "run.py"), "--root", str(proj)]
    if OPTS.loop:
        set_loop(root / "team.yaml", OPTS.loop)
    start = time.perf_counter()
    p = subprocess.run([sys.executable, "-X", "utf8", *argv, "--mock", "--iterations",
                        str(iterations)], capture_output=True, text=True, encoding="utf-8",
                       cwd=root, env=env)
    wall = time.perf_counter() - start
    if p.returncode != 0:
        raise SystemExit(f"run failed:\n{p.stdout}\n{p.stderr}")
    with (root / ".keeploop" / "results.tsv").open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f, delimiter="\t") if int(r["cycle"]) >= 1]
    log = tmp / f"{tag}.calls.jsonl"
    calls = Counter(json.loads(l)["role"] for l in
                    (log.read_text(encoding="utf-8").splitlines() if log.exists() else []) if l)
    return (wall, [int(r["tokens"] or 0) for r in rows], calls,
            "".join(r["status"][0].upper() for r in rows))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reps", type=int, default=7)
    ap.add_argument("--cycles", type=int, default=6)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--latency", default="", metavar="SPEC",
                    help='mock sleep per call, e.g. "analyst=2,engineer=4,auditor=2" (seconds)')
    ap.add_argument("--profile", default="", metavar="NAME", help="loop.profile for the project")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="a loop key for the project's team.yaml (repeatable)")
    ap.add_argument("--example", default="", metavar="NAME", help="examples/NAME instead of the demo")
    ap.add_argument("--seed", type=int, help="KEEPLOOP_DEMO_SEED for the example's noise")
    a = ap.parse_args(argv)
    OPTS.latency, OPTS.example, OPTS.seed = a.latency, a.example, a.seed
    OPTS.loop = {**({"profile": a.profile} if a.profile else {}),
                 **dict(kv.split("=", 1) for kv in a.set)}
    per_cycle, tokens, calls, decisions = [], [], {r: [] for r in ROLES}, ""
    with tempfile.TemporaryDirectory(prefix="kl-bench-") as d:
        tmp = Path(d)
        if not a.latency:
            one(a.cycles, tmp, "warmup")  # file cache, imports (sleeps would add nothing)
        for r in range(a.reps):
            t0, _, _, _ = one(0, tmp, f"r{r}-0")
            tn, toks, n_calls, decisions = one(a.cycles, tmp, f"r{r}-n")
            per_cycle.append((tn - t0) / a.cycles)
            tokens.append(sum(toks) / max(1, len(toks)))
            for role in ROLES:
                calls[role].append(n_calls[role] / a.cycles)
    out = {"reps": a.reps, "cycles": a.cycles,
           **({"example": a.example, "seed": a.seed} if a.example else {}),
           **({"latency": a.latency} if a.latency else {}),
           **({"loop": OPTS.loop} if OPTS.loop else {}),
           "wall_s_per_cycle_median": round(statistics.median(per_cycle), 4),
           "wall_s_per_cycle_all": [round(x, 4) for x in per_cycle],
           "tokens_per_cycle_median": round(statistics.median(tokens), 1),
           "calls_per_cycle_median": {r: round(statistics.median(v), 3) for r, v in calls.items()},
           **({"decisions": decisions} if a.example else {})}
    print(json.dumps(out, indent=2))
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
