"""prepare.py — one-time setup for keeploop. Humans only; agents never edit this.

Run once after cloning:

    python prepare.py

Creates the `.keeploop/` state directory (ledger, lessons, guardrails,
best snapshot, scout memory) and the demo workspace: a git repository at
`.keeploop/workspace` holding config.json. The loop edits that repository
(or any git repo named by `workspace:` in team.yaml). Idempotent:
re-running never overwrites existing state.

All global constants live here (see docs/SPEC.md §3). `team.yaml` may
override the loop/budget subset; everything else is fixed by design,
the same way Karpathy's autoresearch fixes the training budget.
"""

import json
import subprocess
from pathlib import Path

__version__ = "0.1.0"  # the single source; pyproject reads it, see CHANGELOG.md

ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / ".keeploop"

CONFIG = {
    # Loop
    "max_iterations": 20,
    "keep_threshold": 0.0,          # minimum relative metric gain to keep
    "confirm_keep": True,           # re-run the evaluation once before a keep
    "engineer_repairs": 1,          # extra engineer calls for a repairable failure
    "repo_map_max_chars": 3000,     # size of the Analyst's repo map
    "max_diff_lines": 400,          # added+removed lines per diff (one idea)
    "max_consecutive_crashes": 3,
    "eval_timeout_s": 120,
    "noise_runs": 3,                # baseline evaluations; their pstdev is sigma
    "noise_z": 2.0,                 # a keep must beat best by noise_z * sigma
    "max_run_tokens": 2_000_000,    # estimated tokens per run; reached = stop
    "duplicate_jaccard": 0.8,       # card vs a rejected one: skip the Engineer
    "heavy_diff_lines": 100,        # a bigger diff is heavy: forced confirm, heavy_model
    "ledger_tail_for_prompt": 10,
    # Vendors / budgets
    "token_budget_per_role": 50_000,
    "vendor_timeout_s": 240,
    # Lessons
    "guardrail_max_chars": 4_000,
    "lesson_retire_after_days": 90,
    "lesson_effective_after": 10,   # clean ledger cycles before a lesson counts as effective
    "replay_on_keep": True,
    "recall_top_k": 8,              # more open lessons than this: inject only the k most relevant
    # Scout
    "scout_max_proposals": 3,
    "scout_min_relevance": 0.35,
}

# The demo workspace: parameters of a toy training run. For a real project,
# this is whatever surface the team is allowed to change (a config, a set of
# prompts, a workflow definition) — never evaluate.py itself.
INITIAL_WORKSPACE = {
    "learning_rate": 0.01,
    "batch_size": 32,
    "dropout": 0.1,
    "optimizer": "adam",
}


# C0/C1 controls, LRM/RLM and bidi overrides: stripped from any untrusted text
# (evaluation stderr, scout titles) before it can reach a prompt or the ledger.
CONTROL_RX = r"[\x00-\x1f\x7f-\x9f‎‏‪-‮⁦-⁩]"

GIT_AUTHOR =("-c", "user.name=keeploop", "-c", "user.email=keeploop@localhost")


HOOKS_DIR = STATE_DIR / "nohooks"  # setup() points this at the project's own


def git(repo, *args) -> str:
    """Run git in `repo`; return stdout, raise CalledProcessError on failure.

    Hooks and fsmonitor are disabled: an agent that can edit the workspace
    could otherwise plant .git/hooks or a core.fsmonitor command and get
    code execution through our own git calls.
    """
    return subprocess.run(["git", "-C", str(repo), "-c", f"core.hooksPath={HOOKS_DIR}",
                           "-c", "core.fsmonitor=false", *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          check=True).stdout


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def setup(root: Path = ROOT) -> Path:
    """Create state under `root`/.keeploop and return the state dir."""
    state = root / ".keeploop"
    state.mkdir(parents=True, exist_ok=True)
    global HOOKS_DIR
    HOOKS_DIR = state / "nohooks"
    HOOKS_DIR.mkdir(exist_ok=True)
    created = []
    if _write_if_missing(state / "results.tsv",
                         "cycle\tts\trole_vendors\tmetric\tbest_metric\tstatus"
                         "\ttokens\tlesson_id\tdescription\n"):
        created.append("results.tsv")
    if _write_if_missing(state / "lessons.jsonl", ""):
        created.append("lessons.jsonl")
    if _write_if_missing(state / "guardrails.md",
                         "# Guardrails\n\n"
                         "(generated from active lessons by lessons.py — "
                         "do not edit by hand)\n"):
        created.append("guardrails.md")
    ws = state / "workspace"
    if not ws.exists():
        ws.mkdir()
        (ws / "config.json").write_text(
            json.dumps(INITIAL_WORKSPACE, indent=2) + "\n", encoding="utf-8")
        git(ws, "init", "-q")
        git(ws, "add", "-A")
        git(ws, *GIT_AUTHOR, "commit", "-qm", "keeploop: initial workspace")
        created.append("workspace")
    if _write_if_missing(state / "best.json",
                         json.dumps({"metric": None, "rubric": None, "commit": None},
                                    indent=2) + "\n"):
        created.append("best.json")
    if _write_if_missing(state / "scout_seen.json", "{}\n"):
        created.append("scout_seen.json")
    if created:
        print(f"prepare: created {', '.join(created)} in {state}")
    else:
        print(f"prepare: {state} already initialized, nothing overwritten")
    return state


# --- minimal team.yaml loader ------------------------------------------------
# Stdlib-first is a design rule, so no PyYAML dependency. This parses the
# restricted subset used by team.yaml: two levels of `key: value` mappings,
# scalar values (str/int/float/bool/null), `#` comments. Anything fancier
# raises a clear error instead of guessing.

def _scalar(text: str):
    text = text.strip()
    if text in ("null", "~", ""):
        return None
    if text in ("true", "True"):
        return True
    if text in ("false", "False"):
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text.strip("'\"")


def load_team(path: Path) -> dict:
    return parse_team(path.read_text(encoding="utf-8"))


def parse_team(text: str) -> dict:
    """The restricted yaml subset above, from text (load_team reads the file)."""
    root: dict = {}
    section = None
    subsection = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        key, _, value = line.strip().partition(":")
        key = key.strip()
        if indent == 0:
            section = key
            subsection = None
            root[section] = {} if not value.strip() else _scalar(value)
        elif indent == 2 and section is not None:
            if value.strip():
                root[section][key] = _scalar(value)
            else:
                subsection = key
                root[section][key] = {}
        elif indent == 4 and section is not None and subsection is not None:
            root[section][subsection][key] = _scalar(value)
        else:
            raise ValueError(f"team.yaml: cannot parse line: {raw!r}")
    return root


if __name__ == "__main__":
    setup()
    print("prepare: done. Next: python run.py --mock --iterations 3")
