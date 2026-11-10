"""quickstart.py - `kl quickstart` and `kl import-lite`: one command from nothing to a
project that `kl doctor` and `kl begin` can run. Stdlib only; init-time only (no
per-cycle cost).

    kl quickstart TEMPLATE [--workspace REPO] [DIR]
        TEMPLATE: tests | command | prompt | buildtime (the evaluate.py it writes)
        REPO: the git repo the loop may change (default: the current folder)
        DIR: the control folder (default: <repo>-keeploop beside it)

    kl import-lite LEDGER.md [DIR]
        Continue a keeploop-lite chat session in the CLI: the ledger's best version
        becomes the workspace, its scorecard and gates become evaluate.py (an LLM
        judge, repeats + median), its lessons go into program.md.

Existing files are never overwritten: a template that would replace your
evaluate.py is written next to it as evaluate.quickstart.py instead.
"""

import re
import subprocess
from pathlib import Path

import scaffold
from prepare import GIT_AUTHOR

HEADER = '''"""evaluate.py - {what} (written by `kl quickstart {name}`). Humans only.

The contract (docs/SPEC.md): print ONE float on stdout, higher is better; exit 2 for an
invalid workspace, any other non-zero exit for a crash. The loop never edits this file.
Edit the CAPITALISED settings below for your project, then run `kl doctor`: it runs
this file a few times and tells you how noisy it is before the loop trusts it.

Usage:  python evaluate.py <workspace-dir>
"""
'''

TEMPLATES = {
    "tests": ("the test suite's pass rate", '''
import re
import subprocess
import sys

TEST_CMD = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]  # or ["python", "-m", "unittest"]
TIMEOUT_S = 900


def pass_rate(out: str) -> float | None:
    """pytest's or unittest's summary -> passed / run, None if neither is found."""
    def n(rx):
        return sum(int(x) for x in re.findall(rx, out))
    if re.search(r"\\d+ (passed|failed|error)", out):  # pytest
        passed, bad = n(r"(\\d+) passed"), n(r"(\\d+) failed") + n(r"(\\d+) errors?")
        return passed / (passed + bad) if passed + bad else None
    if m := re.search(r"Ran (\\d+) tests?", out):  # unittest
        ran = int(m.group(1))
        bad = n(r"failures=(\\d+)") + n(r"errors=(\\d+)")
        return (ran - bad) / ran if ran else None
    return None


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python evaluate.py <workspace-dir>", file=sys.stderr)
        return 2
    try:
        p = subprocess.run(TEST_CMD, cwd=sys.argv[1], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"test command failed to run: {exc}", file=sys.stderr)
        return 1
    rate = pass_rate(p.stdout + p.stderr)
    if rate is None:
        print("no test summary found in the output: is TEST_CMD right?", file=sys.stderr)
        print((p.stdout + p.stderr)[-1500:], file=sys.stderr)
        return 1
    print(f"{rate:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''),
    "command": ("a number printed by any shell command", '''
import re
import statistics
import subprocess
import sys

CMD = ["python", "bench.py"]          # runs in the workspace; prints the number somewhere
NUMBER_RX = r"score[:=]\\s*([-+]?\\d+(?:\\.\\d+)?)"  # group 1 is the number
LOWER_IS_BETTER = False                # e.g. latency, bundle size: printed negated
REPEATS = 1                            # >1: the median of the repeats (kl doctor says if you need it)
TIMEOUT_S = 600


def one(ws: str) -> float:
    p = subprocess.run(CMD, cwd=ws, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=TIMEOUT_S)
    if p.returncode != 0:
        raise RuntimeError(f"command exited {p.returncode}: {(p.stderr or p.stdout)[-300:]}")
    m = re.search(NUMBER_RX, p.stdout + p.stderr)
    if not m:
        raise RuntimeError(f"NUMBER_RX matched nothing in: {(p.stdout + p.stderr)[-300:]}")
    return float(m.group(1))


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python evaluate.py <workspace-dir>", file=sys.stderr)
        return 2
    try:
        x = statistics.median(one(sys.argv[1]) for _ in range(max(1, REPEATS)))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"{-x if LOWER_IS_BETTER else x:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''),
    "prompt": ("a prompt's accuracy on a labelled set", '''
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases.jsonl"        # {"input": ..., "expected": ...} per line; outside the workspace
PROMPT = "prompt.md"                 # in the workspace: the file the loop improves
MODEL_CMD = ["claude", "-p"]         # reads the full prompt on stdin, prints the answer
MATCH = "exact"                      # "exact" (case-insensitive) or "contains"
WORKERS, TIMEOUT_S = 4, 120


def ask(system: str, case: dict) -> bool:
    p = subprocess.run(MODEL_CMD, input=f"{system}\\n\\n{case['input']}", capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S)
    if p.returncode != 0:
        raise RuntimeError(f"model command exited {p.returncode}: {p.stderr[-300:]}")
    got, want = p.stdout.strip().lower(), str(case["expected"]).strip().lower()
    return got == want if MATCH == "exact" else want in got


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python evaluate.py <workspace-dir>", file=sys.stderr)
        return 2
    prompt = Path(sys.argv[1]) / PROMPT
    if not prompt.is_file() or not prompt.read_text(encoding="utf-8").strip():
        print(f"invalid workspace: {PROMPT} is missing or empty", file=sys.stderr)
        return 2
    cases = [json.loads(x) for x in CASES.read_text(encoding="utf-8").splitlines() if x.strip()]
    system = prompt.read_text(encoding="utf-8")
    try:
        with ThreadPoolExecutor(WORKERS) as pool:
            hits = list(pool.map(lambda c: ask(system, c), cases))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"scoring failed: {exc}", file=sys.stderr)  # a crash, never a silent 0
        return 1
    print(f"{sum(hits) / len(hits):.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''),
    "buildtime": ("build (or bundle) time, faster is better", '''
import statistics
import subprocess
import sys
import time

BUILD_CMD = ["npm", "run", "build"]  # runs in the workspace
REPEATS = 5                          # timings are noisy: the median of the repeats
TIMEOUT_S = 1800


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python evaluate.py <workspace-dir>", file=sys.stderr)
        return 2
    times = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        try:
            p = subprocess.run(BUILD_CMD, cwd=sys.argv[1], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"build failed to run: {exc}", file=sys.stderr)
            return 1
        if p.returncode != 0:  # a broken build is a crash, never a fast build
            print(f"build failed: {(p.stderr or p.stdout)[-500:]}", file=sys.stderr)
            return 1
        times.append(time.perf_counter() - start)
    print(f"{-statistics.median(times):.6f}")  # negated seconds: higher is better
    print(f"build seconds: {[round(t, 3) for t in times]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''),
}

PROMPT_CASES = ('{"input": "Classify the sentiment: I love it", "expected": "positive"}\n'
                '{"input": "Classify the sentiment: It broke on day one", "expected": "negative"}\n')


def template_text(name: str) -> str:
    what, body = TEMPLATES[name]
    return HEADER.format(what=what, name=name) + body


def _git_top(path: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
        return Path(out).resolve()
    except (OSError, subprocess.CalledProcessError):
        return None


def _set_workspace(team: Path, rel: str) -> None:
    text = team.read_text(encoding="utf-8")
    text, n = re.subn(r"^workspace:.*$", f"workspace: {rel}", text, count=1, flags=re.M)
    if n != 1:
        raise SystemExit(f"refused: no `workspace:` line in {team}")
    team.write_text(text, encoding="utf-8")


def _rel(target: Path, start: Path) -> str:
    import os
    return Path(os.path.relpath(target, start)).as_posix()


def quickstart(name: str, workspace: Path | None, dest: Path | None, *, rewrite: bool,
               src: Path | None = None) -> list[str]:
    """Write a control folder for `workspace` with the template's evaluate.py.
    Returns the lines to print."""
    if name not in TEMPLATES:
        raise SystemExit(f"refused: unknown template {name!r}: one of {', '.join(TEMPLATES)}")
    ws = _git_top((workspace or Path.cwd()).resolve())
    if ws is None:
        raise SystemExit("refused: the workspace is not inside a git repository "
                         "(cd into your repo, or pass --workspace PATH)")
    dest = (dest or ws.parent / f"{ws.name}-keeploop").resolve()
    if dest == ws or dest in ws.parents or ws in dest.parents:
        raise SystemExit(f"refused: the control folder {dest} must be beside the repo {ws}, "
                         f"not inside it or above it (the loop resets the repo)")
    written, kept = scaffold.init(dest, rewrite=rewrite, src=src)
    out = [f"kl quickstart: wrote {len(written)} files in {dest}"]
    target = dest / ("evaluate.py" if "evaluate.py" in written else "evaluate.quickstart.py")
    target.write_text(template_text(name), encoding="utf-8")
    if target.name != "evaluate.py":
        out.append(f"warning: your evaluate.py was kept; the template is in {target.name}")
    if name == "prompt" and not (dest / "cases.jsonl").exists():
        (dest / "cases.jsonl").write_text(PROMPT_CASES, encoding="utf-8")
        out.append("wrote cases.jsonl (two sample cases: replace them with yours)")
    if "team.yaml" in written:
        _set_workspace(dest / "team.yaml", _rel(ws, dest))
        out.append(f"team.yaml: workspace: {_rel(ws, dest)}")
    else:
        out.append("warning: your team.yaml was kept: set its `workspace:` to the repo yourself")
    kl = "kl" if rewrite else "python kl.py"
    out += [f"next: edit the CAPITALISED settings at the top of {target.name}, then",
            f"  cd {dest}",
            f"  {kl} doctor          # runs evaluate.py a few times: is it noisy?",
            f"  {kl} begin           # baseline; then follow AGENTS.md"]
    return out


# --- keeploop-lite ledger -> CLI project ----------------------------------------

def parse_lite(text: str) -> dict:
    """A KEEPLOOP-LITE LEDGER block (lite/KEEPLOOP-LITE.md, section 7) -> its fields."""
    if "KEEPLOOP-LITE LEDGER" not in text:
        raise SystemExit("refused: no `KEEPLOOP-LITE LEDGER` block in that file")
    body = text.rsplit("KEEPLOOP-LITE LEDGER", 1)[1]  # the latest ledger in the file
    body = body.split("```", 1)[0] if "```" in body else body

    def field(name):
        m = re.search(rf"^{name}:\s*(.*)$", body, re.M)
        return m.group(1).strip() if m else ""
    sc = re.search(r"^Scorecard[^\n]*max\s*(\d+)[^\n]*\n((?:\d+\..*\n?)+)", body, re.M)
    if not sc:
        raise SystemExit("refused: the ledger has no numbered Scorecard")
    criteria = [re.sub(r"^\d+\.\s*", "", x).strip() for x in sc.group(2).strip().splitlines()]
    rows = re.findall(r"^\|\s*(\d+)\s*\|(.*?)\|(.*?)\|(.*?)\|\s*$", body, re.M)
    lessons_ = re.findall(r"^- (L\d+.*(?:\n  .*)*)", body.split("Lessons:", 1)[1], re.M) \
        if "Lessons:" in body else []
    best = body.split("Best version", 1)[1].split("\n", 1)[1].strip() if "Best version" in body else ""
    if not best:
        raise SystemExit("refused: the ledger has no `Best version` text")
    return {"artifact": field("Artifact"), "max": int(sc.group(1)), "criteria": criteria,
            "gates": field(r"Gates \(pass/fail\)"), "team": field("Team"),
            "rows": [tuple(x.strip() for x in r) for r in rows],
            "lessons": [" ".join(l.split()) for l in lessons_], "best": best + "\n"}


LITE_EVAL = '''"""evaluate.py - an LLM judge for the scorecard imported from a keeploop-lite session
(written by `kl import-lite`). Humans only.

Scores artifact.md in the workspace against the locked scorecard below, the way the
lite chat did: each criterion 0-10, total out of {max_total}. JUDGE_CMD reads the prompt
on stdin and prints the scores. A model judge is noisy: the score is the median of
REPEATS calls, and `kl doctor` measures what noise is left. The gates are checked here
in code where they can be (a word limit); a failed gate scores 0.

Usage:  python evaluate.py <workspace-dir>
"""

import re
import statistics
import subprocess
import sys
from pathlib import Path

ARTIFACT = "artifact.md"
CRITERIA = {criteria!r}
MAX_WORDS = {max_words!r}   # from the gates; None = no word limit
GATES = {gates!r}
JUDGE_CMD = ["claude", "-p"]
REPEATS, TIMEOUT_S = 3, 180


def judge(text: str) -> float:
    lines = "\\n".join(f"{{i}}. {{c}}" for i, c in enumerate(CRITERIA, 1))
    prompt = (f"Score this text against each criterion from 0 to 10. A 10 looks like the "
              f"description. Be strict and do not reward length.\\n\\nCriteria:\\n{{lines}}\\n\\n"
              f"Text:\\n<<<\\n{{text}}\\n>>>\\n\\nAnswer with exactly one line per criterion: "
              f"`<number>. <score>` and nothing else.")
    p = subprocess.run(JUDGE_CMD, input=prompt, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=TIMEOUT_S)
    if p.returncode != 0:
        raise RuntimeError(f"judge exited {{p.returncode}}: {{p.stderr[-300:]}}")
    scores = {{int(a): float(b) for a, b in re.findall(r"^\\s*(\\d+)\\.\\s*(\\d+(?:\\.\\d+)?)", p.stdout, re.M)}}
    if sorted(scores) != list(range(1, len(CRITERIA) + 1)):
        raise RuntimeError(f"judge reply not in the expected format: {{p.stdout[:200]!r}}")
    return sum(min(10.0, max(0.0, s)) for s in scores.values())


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python evaluate.py <workspace-dir>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1]) / ARTIFACT
    if not path.is_file() or not path.read_text(encoding="utf-8").strip():
        print(f"invalid workspace: {{ARTIFACT}} is missing or empty", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    if MAX_WORDS is not None and len(text.split()) >= MAX_WORDS:
        print(f"gate failed: {{len(text.split())}} words, the limit is under {{MAX_WORDS}}", file=sys.stderr)
        print("0.000000")
        return 0
    try:
        total = statistics.median(judge(text) for _ in range(REPEATS))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"scoring failed: {{exc}}", file=sys.stderr)
        return 1
    print(f"{{total:.6f}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def import_lite(ledger_file: Path, dest: Path, *, rewrite: bool, src: Path | None = None) -> list[str]:
    led = parse_lite(ledger_file.read_text(encoding="utf-8"))
    dest = dest.resolve()
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"refused: {dest} is not empty")
    root, ws = dest / "kl", dest / "artifact"
    written, _ = scaffold.init(root, rewrite=rewrite, src=src)
    ws.mkdir(parents=True)
    (ws / "artifact.md").write_text(led["best"], encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
    subprocess.run(["git", *GIT_AUTHOR, "commit", "-qm", "keeploop: best version from the lite session"],
                   cwd=ws, check=True)
    m = re.search(r"under (\d+) words", led["gates"], re.I)
    (root / "evaluate.py").write_text(LITE_EVAL.format(
        max_total=10 * len(led["criteria"]), criteria=led["criteria"],
        max_words=int(m.group(1)) if m else None, gates=led["gates"]), encoding="utf-8")
    _set_workspace(root / "team.yaml", "../artifact")
    team = root / "team.yaml"
    team.write_text(team.read_text(encoding="utf-8").replace(
        "pack: software", "pack: marketing-content", 1), encoding="utf-8")
    history = "\n".join(f"| {a} | {b} | {c} | {d} |" for a, b, c, d in led["rows"])
    (root / "program.md").write_text(f"""# program.md - the charter (imported from a keeploop-lite session, edit me, human)

## Mission

Improve `artifact.md` in the workspace: {led['artifact'] or 'the artifact from the lite session'}.
Measured ONLY by the score `evaluate.py` prints (the lite scorecard, judged by a model,
max {10 * len(led['criteria'])}). The lite session scored in a chat; those scores are history,
not a baseline: `kl begin` measures a new one with evaluate.py.

Scorecard (locked in the lite session):
{chr(10).join(f'{i}. {c}' for i, c in enumerate(led['criteria'], 1))}

Gates: {led['gates'] or 'none'}
Team in the lite session: {led['team'] or 'not recorded'}

## Hypotheses to test

Lessons the lite session learned, as claims to test first:

{chr(10).join(f'- {l}' for l in led['lessons']) or '- none recorded'}

## History from the lite session (not comparable with evaluate.py's scores)

| # | Change | Score | Verdict |
|---|---|---|---|
{history}

## The experiment contract

Read AGENTS.md: hypothesis card first, the metric decides, evaluate.py is sacred.
""", encoding="utf-8")
    kl = "kl" if rewrite else "python kl.py"
    return [f"kl import-lite: {len(led['criteria'])} criteria, {len(led['rows'])} ledger rows, "
            f"{len(led['lessons'])} lessons",
            f"workspace: {ws} (artifact.md = the lite session's best version, committed)",
            f"control folder: {root} (evaluate.py = a model judge of the locked scorecard)",
            f"next: cd {root} && {kl} doctor   (the judge is noisy: see how much) && {kl} begin"]
