"""The proof run: the same 20 proposals on a deliberately noisy evaluation, kept by two laws.

    python tools/proof_run.py                 # headline seed + the seed sweep -> docs/proof/
    python tools/proof_run.py --check         # the release gate: re-run, compare to docs/proof/proof.json
    python tools/proof_run.py --seeds 1-5 --out /tmp/p

Workspace: examples/noisy-eval. evaluate.py scores a random 1,000 of 10,000 dev cases
per call (sigma about 0.014); holdout.py scores 5,000 other cases, all of them, and
the loop never sees it. Every role is the offline mock; its engineer applies the
entries of mock_script.json in order, so both modes get the same proposals in the
same order. Only the keep law differs:

  naive     keep anything that beats best (keep_threshold 0, noise_z 0, confirm_keep false)
  keeploop  the team.yaml as shipped: beat best + 2 sigma, then survive one confirm re-run

Same budget: the same number of cycles (--cycles, default 20). keeploop spends more
evaluation calls (baseline repeats and confirm re-runs); both counts are reported.

The noise is reproducible: KEEPLOOP_DEMO_SEED=<seed> makes the k-th evaluation of a
config draw the same sample in every run (see the example's evaluate.py). The
headline seed and the seed list are fixed in this file, before any run: the headline
is seed 1, the sweep is seeds 1-25. Nothing is picked after the fact.

Writes to --out: proof.json (every number), sweep.tsv (one row per seed and mode),
PROOF.md (the human summary), and for the headline seed <mode>/ with the run's real
files: results.tsv, hypotheses.jsonl, lessons.jsonl, best.json, holdout.json,
config.json (the final workspace) and stdout.txt (the run's own output, --narrate).
Stdlib only; runs the real run.py.
"""

import argparse
import csv
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "examples" / "noisy-eval"
sys.path.insert(0, str(REPO))
import scaffold  # noqa: E402

HEADLINE_SEED = 1
SWEEP_SEEDS = "1-25"
MODES = ("naive", "keeploop")
NAIVE = {"keep_threshold": "0.0", "noise_z": "0.0", "confirm_keep": "false"}
KEEPLOOP_SET: dict = {}  # --keeploop-set: a sensitivity run, never the headline


def example_module():
    """The example's evaluate.py as a module: its QUALITY table is the ground truth
    the simulation knows and the loop never sees."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("noisy_eval", EXAMPLE / "evaluate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def truth(rows: list[dict]) -> list[dict]:
    """Per cycle: the proposal, its TRUE effect on quality from the HEAD it was tried
    on, and the decision. Replays the keeps from the example's initial config.json."""
    ev = example_module()
    script = json.loads((EXAMPLE / "mock_script.json").read_text(encoding="utf-8"))
    cfg = json.loads((EXAMPLE / "config.json").read_text(encoding="utf-8"))
    out = []
    for r in rows:
        c = int(r["cycle"])
        if c < 1:
            continue
        entry = script[(c - 1) % len(script)]
        new = {**cfg, **entry["set"]}
        out.append({"cycle": c, "set": entry["set"], "status": r["status"],
                    "metric": float(r["metric"]) if r["metric"] else None,
                    "best_before": float(r["best_metric"]),
                    "true_effect": round(ev.quality(new) - ev.quality(cfg), 6)})
        if r["status"] == "keep":
            cfg = new
    return out


def seeds(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def set_loop(team: Path, values: dict) -> None:
    text = team.read_text(encoding="utf-8")
    for k, v in values.items():
        text, n = re.subn(rf"^(  {k}:).*$", rf"\g<1> {v}", text, flags=re.M)
        if n != 1:
            raise SystemExit(f"{team}: expected one `  {k}:` line under loop")
    team.write_text(text, encoding="utf-8")


def one(mode: str, seed: int, cycles: int, tmp: Path, keep_dir: Path | None) -> dict:
    dest = tmp / f"{mode}-{seed}"
    root, ws = scaffold.make_sandbox(EXAMPLE, dest, with_code=True, src=REPO)
    if mode == "naive":
        set_loop(root / "team.yaml", NAIVE)
    elif KEEPLOOP_SET:
        set_loop(root / "team.yaml", KEEPLOOP_SET)
    noise = dest / "noise.json"  # outside the project: evaluate.py's per-config draw counter
    env = {**os.environ, "KEEPLOOP_DEMO_SEED": str(seed), "KEEPLOOP_DEMO_STATE": str(noise),
           "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.run([sys.executable, str(root / "run.py"), "--mock", "--narrate",
                        "--iterations", str(cycles)], cwd=root, env=env,
                       capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise SystemExit(f"{mode} seed {seed}: run.py exit {p.returncode}\n{p.stdout}\n{p.stderr}")
    state = root / ".keeploop"
    with (state / "results.tsv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    best = json.loads((state / "best.json").read_text(encoding="utf-8"))
    hold = json.loads((state / "holdout.json").read_text(encoding="utf-8"))
    cyc = [r for r in rows if int(r["cycle"]) >= 1]
    kept = [int(r["cycle"]) for r in cyc if r["status"] == "keep"]
    script = json.loads((EXAMPLE / "mock_script.json").read_text(encoding="utf-8"))
    tr = truth(rows)
    out = {
        "mode": mode, "seed": seed, "experiments": len(cyc), "kept": len(kept),
        "kept_cycles": kept,
        "kept_changes": [script[(c - 1) % len(script)]["set"] for c in kept],
        "kept_no_true_gain": sum(x["status"] == "keep" and x["true_effect"] <= 0 for x in tr),
        "discarded_true_gain": sum(x["status"] != "keep" and x["true_effect"] > 0 for x in tr),
        "cycles": tr,
        "eval_calls": sum(json.loads(noise.read_text(encoding="utf-8")).values()),
        "sigma": round(best["sigma"], 6),
        "dev_baseline": round(hold["eval_baseline"], 6), "dev_final": round(best["metric"], 6),
        "holdout_baseline": round(hold["baseline"], 6), "holdout_final": round(hold["final"], 6),
    }
    out["holdout_gain"] = round(out["holdout_final"] - out["holdout_baseline"], 6)
    out["dev_gain"] = round(out["dev_final"] - out["dev_baseline"], 6)
    if keep_dir is not None:
        d = keep_dir / mode
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        for name in ("results.tsv", "hypotheses.jsonl", "lessons.jsonl", "best.json", "holdout.json"):
            if (state / name).exists():
                shutil.copy2(state / name, d / name)
        shutil.copy2(ws / "config.json", d / "config.json")
        (d / "stdout.txt").write_text(p.stdout.replace(str(dest), "<sandbox>"), encoding="utf-8")
    return out


def summarize(rows: list[dict], mode: str) -> dict:
    mine = [r for r in rows if r["mode"] == mode]
    hg = [r["holdout_gain"] for r in mine]
    return {"runs": len(mine),
            "kept_mean": round(statistics.fmean(r["kept"] for r in mine), 2),
            "holdout_gain_mean": round(statistics.fmean(hg), 6),
            "holdout_gain_median": round(statistics.median(hg), 6),
            "holdout_regressed_runs": sum(g < 0 for g in hg),
            "dev_overstates_holdout_mean": round(statistics.fmean(
                r["dev_gain"] - r["holdout_gain"] for r in mine), 6),
            "eval_calls_mean": round(statistics.fmean(r["eval_calls"] for r in mine), 2),
            "kept_no_true_gain_mean": round(statistics.fmean(r["kept_no_true_gain"] for r in mine), 2),
            "discarded_true_gain_mean": round(statistics.fmean(
                r["discarded_true_gain"] for r in mine), 2)}


def proof_md(head: dict, sweep: list[dict], summary: dict, cycles: int, seed_spec: str) -> str:
    n, k = head["naive"], head["keeploop"]
    by = {(r["seed"], r["mode"]): r for r in sweep}
    all_seeds = sorted({r["seed"] for r in sweep})
    diff = [by[s, "keeploop"]["holdout_gain"] - by[s, "naive"]["holdout_gain"] for s in all_seeds]
    wins, ties = sum(d > 0 for d in diff), sum(d == 0 for d in diff)
    sn, sk = summary["naive"], summary["keeploop"]

    def both(fmt, *keys):
        return " | ".join(fmt.format(*[r[x] for x in keys]) for r in (n, k))

    def kept(r):
        return ", ".join(f"cycle {x['cycle']} {json.dumps(x['set'])} ({x['true_effect']:+.3f})"
                         for x in r["cycles"] if x["status"] == "keep") or "none"
    return f"""# Proof run: naive keep vs the keeploop keep law

Generated by `python tools/proof_run.py`; do not edit by hand. Every number below is
in `proof.json` and `sweep.tsv`. The headline runs' own files are in `naive/` and
`keeploop/`: `results.tsv` is the ledger, `stdout.txt` the run's own output.

## Setup

`examples/noisy-eval`: `evaluate.py` scores a random 1,000 of 10,000 dev cases per call,
so the same config scores differently each time (sigma about 0.014). That sample size is
the one noise setting, chosen before any run. `holdout.py` scores 5,000 other cases, all
of them; no prompt or ledger row sees it.

Both modes run the same {cycles} proposals (`mock_script.json`, offline mock vendor) on the
same noise seeds, for the same number of cycles. Only the keep law differs:

- **naive**: keep anything that beats the best score (`keep_threshold 0`, `noise_z 0`,
  `confirm_keep false`), the way a plain keep-if-better loop does.
- **keeploop**: the example's `team.yaml` as shipped. Keep only above best + 2 sigma, with
  sigma measured from 3 baseline runs. Then the lower of the score and one confirm re-run
  must still clear that bar.

The simulation knows each proposal's true effect (the `QUALITY` table in `evaluate.py`;
the loop never sees it). So it can count the two ways a keep law can be wrong:

- keeping a change with no true gain;
- discarding a change with a true gain.

## Headline run (seed {HEADLINE_SEED}, fixed before running)

| | naive | keeploop |
|---|---|---|
| experiments run | {both("{}", "experiments")} |
| changes kept | {both("{}", "kept")} |
| kept with no true gain (true effect <= 0) | {both("{}", "kept_no_true_gain")} |
| discarded despite a true gain | {both("{}", "discarded_true_gain")} |
| evaluation calls | {both("{}", "eval_calls")} |
| dev score, baseline -> final (the loop's own best) | {both("{:.6f} -> {:.6f}", "dev_baseline", "dev_final")} |
| holdout, baseline -> final | {both("{:.6f} -> {:.6f}", "holdout_baseline", "holdout_final")} |
| holdout gain | {both("{:+.6f}", "holdout_gain")} |

Kept, with each change's true effect:

- naive: {kept(n)}.
- keeploop: {kept(k)}.

## Every seed ({seed_spec}: {len(all_seeds)} seeds, fixed before running)

| mean over seeds | naive | keeploop |
|---|---|---|
| changes kept | {sn["kept_mean"]} | {sk["kept_mean"]} |
| kept with no true gain | {sn["kept_no_true_gain_mean"]} | {sk["kept_no_true_gain_mean"]} |
| discarded despite a true gain | {sn["discarded_true_gain_mean"]} | {sk["discarded_true_gain_mean"]} |
| holdout gain (mean) | {sn["holdout_gain_mean"]:+.6f} | {sk["holdout_gain_mean"]:+.6f} |
| holdout gain (median) | {sn["holdout_gain_median"]:+.6f} | {sk["holdout_gain_median"]:+.6f} |
| runs whose holdout got worse | {sn["holdout_regressed_runs"]} of {sn["runs"]} | {sk["holdout_regressed_runs"]} of {sk["runs"]} |
| dev gain minus holdout gain (how far the loop's own score overstates) | {sn["dev_overstates_holdout_mean"]:+.6f} | {sk["dev_overstates_holdout_mean"]:+.6f} |
| evaluation calls | {sn["eval_calls_mean"]} | {sk["eval_calls_mean"]} |

Seed by seed, keeploop's holdout gain was higher than naive's on {wins} of
{len(all_seeds)} seeds, equal on {ties}, and lower on {len(all_seeds) - wins - ties}.
Per-seed rows are in `sweep.tsv`.

## Reproduce

    git clone https://github.com/johnha912/keeploop && cd keeploop
    python tools/proof_run.py --out /tmp/proof     # the same numbers and files
    python tools/proof_run.py --check              # the release gate: compares to proof.json

To run one by hand:

    kl init --example noisy-eval /tmp/ne && cd /tmp/ne/kl && kl begin && kl run --mock --narrate

Without `KEEPLOOP_DEMO_SEED` the noise is truly random, so the numbers differ from run
to run.
"""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seeds", default=SWEEP_SEEDS)
    ap.add_argument("--cycles", type=int, default=20)
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "proof")
    ap.add_argument("--keeploop-set", action="append", default=[], metavar="KEY=VALUE",
                    help="change one loop key in keeploop mode (a labelled sensitivity run)")
    ap.add_argument("--check", action="store_true",
                    help="re-run and fail if any number differs from <out>/proof.json")
    a = ap.parse_args(argv)
    KEEPLOOP_SET.update(kv.split("=", 1) for kv in a.keeploop_set)
    sweep, head = [], {}
    with tempfile.TemporaryDirectory(prefix="kl-proof-") as d:
        tmp = Path(d)
        work = tmp / "files" if a.check else a.out
        for seed in seeds(a.seeds):
            for mode in MODES:
                r = one(mode, seed, a.cycles, tmp, work if seed == HEADLINE_SEED else None)
                sweep.append(r)
                if seed == HEADLINE_SEED:
                    head[mode] = r
                print(f"seed {seed:>2} {mode:<8} kept {r['kept']:>2}  dev {r['dev_baseline']:.4f}"
                      f" -> {r['dev_final']:.4f}  holdout {r['holdout_baseline']:.4f} -> "
                      f"{r['holdout_final']:.4f} ({r['holdout_gain']:+.4f})", flush=True)
    summary = {m: summarize(sweep, m) for m in MODES}
    proof = {"headline_seed": HEADLINE_SEED, "seeds": a.seeds, "cycles": a.cycles,
             **({"keeploop_set": KEEPLOOP_SET} if KEEPLOOP_SET else {}),
             "headline": head, "summary": summary, "sweep": sweep}
    if a.check:
        want = json.loads((a.out / "proof.json").read_text(encoding="utf-8"))
        if want != proof:
            diff = [k for k in proof if proof[k] != want.get(k)]
            print(f"proof_run --check: FAIL, differs from {a.out / 'proof.json'} in {diff}")
            return 1
        print("proof_run --check: PASS, every number matches proof.json")
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "proof.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    keys = ["seed", "mode", "experiments", "kept", "kept_no_true_gain", "discarded_true_gain",
            "eval_calls", "sigma", "dev_baseline", "dev_final",
            "holdout_baseline", "holdout_final", "holdout_gain"]
    with (a.out / "sweep.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(keys)
        for r in sweep:
            w.writerow([r[k] for k in keys])
    if HEADLINE_SEED in seeds(a.seeds):
        (a.out / "PROOF.md").write_text(proof_md(head, sweep, summary, a.cycles, a.seeds),
                                        encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
