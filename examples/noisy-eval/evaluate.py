"""evaluate.py - a deliberately NOISY evaluation: the proof-run demo. Humans only.

The workspace's config.json configures a toy question-answering pipeline. Each call
scores it on a RANDOM SAMPLE of 1,000 cases out of a 10,000-case dev set, the way a
sampled LLM eval or a flaky benchmark does: the same config scores a little
differently every time (sigma about 0.014 at accuracy 0.70). That noise is the
point of this example: a loop that keeps "any improvement over best" keeps noise.

How a case is scored (simulated, offline, stdlib only): the config has a true
quality q in [0, 1] (QUALITY below, an additive table the loop never sees); case
i has a fixed difficulty d_i in [0, 1); the pipeline solves it when d_i < q.
holdout.py scores the same q on 5,000 other cases, all of them, no sampling.

Reproducible noise: with KEEPLOOP_DEMO_SEED and KEEPLOOP_DEMO_STATE (a JSON file
outside the project) set, the k-th evaluation of a given config draws its sample
from Random("seed:config-hash:k"), so a run replays exactly (tools/proof_run.py
sets both). Without them the sample is truly random, like a real noisy eval.

Usage:  python evaluate.py <workspace-dir>        (reads <workspace-dir>/config.json)
Exit:   0 and prints the metric; 2 if the workspace is invalid.
"""

import hashlib
import json
import os
import random
import sys
from pathlib import Path

DEV_CASES, SAMPLE = 10_000, 1_000

BASE_QUALITY = 0.66
QUALITY = {  # knob -> value -> true effect on quality (hidden from the loop)
    "few_shot": {0: 0.0, 2: 0.035, 3: 0.05, 5: 0.058, 8: 0.05},
    "rerank": {False: 0.0, True: 0.045},
    "prompt_style": {"plain": 0.0, "checklist": 0.04, "persona": -0.012, "terse": -0.02},
    "temperature": {0.7: 0.0, 0.5: 0.002, 0.3: -0.004, 0.0: -0.01, 1.0: -0.015},
    "chunk_size": {512: 0.0, 384: -0.006, 256: -0.018, 768: -0.002, 1024: -0.01},
    "top_k": {5: 0.0, 3: -0.012, 8: -0.005, 10: -0.014},
    "retries": {1: 0.0, 2: 0.0, 3: -0.003},
    "max_tokens": {512: 0.0, 256: -0.025, 768: -0.001, 1024: -0.004},
}


def validate(cfg: dict) -> str | None:
    for knob, table in QUALITY.items():
        if knob not in cfg:
            return f"config.json is missing {knob}"
        v = cfg[knob]
        if not any(v == t and isinstance(v, bool) == isinstance(t, bool) for t in table):
            return f"{knob} must be one of {sorted(table, key=str)}: {v!r}"
    if extra := sorted(set(cfg) - set(QUALITY)):
        return f"unknown keys in config.json: {extra}"
    return None


def quality(cfg: dict) -> float:
    return BASE_QUALITY + sum(QUALITY[k][cfg[k]] for k in QUALITY)


def difficulties(n: int, seed: str) -> list[float]:
    rng = random.Random(seed)
    return [rng.random() for _ in range(n)]


def load(workspace: Path) -> dict:
    path = workspace / "config.json"
    if not path.is_file():
        raise SystemExit(print(f"invalid workspace: {path} not found", file=sys.stderr) or 2)
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(print(f"invalid workspace: config.json: {exc}", file=sys.stderr) or 2)
    if not isinstance(cfg, dict) or (err := validate(cfg)):
        raise SystemExit(print(f"invalid workspace: {err or 'not an object'}", file=sys.stderr) or 2)
    return cfg


def sample_rng(cfg: dict) -> random.Random:
    seed, state = os.environ.get("KEEPLOOP_DEMO_SEED"), os.environ.get("KEEPLOOP_DEMO_STATE")
    if not (seed and state):
        return random.Random(int.from_bytes(os.urandom(16), "big"))
    h = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]
    path = Path(state)
    seen = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    k = seen.get(h, 0)
    seen[h] = k + 1
    path.write_text(json.dumps(seen), encoding="utf-8")
    return random.Random(f"{seed}:{h}:{k}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python evaluate.py <workspace-dir>", file=sys.stderr)
        return 2
    cfg = load(Path(sys.argv[1]))
    q, cases = quality(cfg), difficulties(DEV_CASES, "keeploop-noisy-eval-dev")
    picked = sample_rng(cfg).sample(range(DEV_CASES), SAMPLE)
    print(f"{sum(cases[i] < q for i in picked) / SAMPLE:.6f}")
    print(f"scored a random {SAMPLE} of {DEV_CASES} dev cases", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
