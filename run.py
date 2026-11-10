"""run.py — the loop. The one file that runs the team.

One cycle (docs/SPEC.md §2):

    propose (Analyst) -> duplicate precheck -> implement (Engineer edits the
    workspace repo) -> QC gates (protected paths, secrets, diff size, tier)
    -> evaluate (fixed) -> audit (Auditor + rubric in ONE call, only if the
    metric beats the bar) -> confirm (skipped when sigma is 0 and the change
    is light) -> incident replay -> keep (git commit)
    or discard (git reset) -> ledger row (always) -> lesson (on a mistake)

The workspace is a git repository (`workspace:` in team.yaml). Every cycle
ends with a reset + clean of it, so a discard leaves nothing behind. The
loop is profession-agnostic: the domain lives in `evaluate.py` (the metric),
`program.md` (the charter) and the active pack in `packs/`.

The evaluation is sacred: it lives outside the workspace, and every call that
runs code the loop does not trust (vendors, evaluation, holdout, lesson
checks) is fenced by a sha256 fingerprint of everything outside the workspace
plus a check of the workspace's git control state. Any change stops the run
(exit 2) and nothing is kept.

An optional holdout.py is a second, hidden evaluation: scored on the untouched
baseline and the final HEAD only, never shown to any prompt, to warn when the
keeps overfit evaluate.py.

Usage:
    python run.py [--mock] [--iterations N] [--root PATH]

--mock routes every role to the deterministic MockVendor (offline demo). A
mock_script.json next to team.yaml (a list of JSON patches for config.json)
replaces the mock engineer's built-in script: the noisy-eval example uses it so
every run sees the same proposals. --narrate prints each step of a cycle (card,
diff, score against the keep bar, decision); off by default.

Speed levers, team.yaml `loop:`, all off by default (the keep law never changes):
fused (the Engineer writes the card and builds it in one call), auto_cards (an
untested program.md hypothesis is the card, no call), confirm_skip_z (no re-run for
a light gain far beyond the noise), eval_stderr_handle, and `profile: fast`
(prepare.PROFILES: fused, auto_cards and smaller prompt caps).
"""

import argparse
import fnmatch
import hashlib
import json
import math
import os
import re
import shlex
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import codemap
import ledger
import lessons
import packs
import rubric as rubric_mod
import vendors
from prepare import (CONFIG, CONTROL_RX, GIT_AUTHOR, PROFILES, __version__, git, load_team,
                     setup)
from vendors import FUSED_MARK, safe_env

ROLES = ("analyst", "engineer", "auditor")
PHASE = {"analyst": "a", "engineer": "e", "auditor": "q"}  # keys of the timing line

SECRET_PATTERNS = {kind: re.compile(rx) for kind, rx in {
    "AWS access key": r"AKIA[0-9A-Z]{16}",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "GitHub token": r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}",
    "OpenAI/Anthropic key": r"sk-[A-Za-z0-9_-]{20,}",
    "Google API key": r"AIza[0-9A-Za-z_-]{35}",
    "Slack token": r"xox[abprs]-[A-Za-z0-9-]{10,}",
}.items()}
# Matched case-insensitively on the file name, on every OS.
SECRET_FILES = (".env", ".env.*", "*.env", ".npmrc", ".pypirc", ".netrc", "*.pem",
                "*.key", "*.p12", "*.pfx", "id_rsa", "id_dsa", "id_ecdsa",
                "id_ed25519", "credentials*.json")

# Lessons the loop records itself: (what, root cause, guardrail). Fixed
# guardrail text per class, so a repeat is a retrigger, not a duplicate.
L_NO_CARD = ("Analyst gave no pre-registered card",
             "The reply lacked HYPOTHESIS, CHANGE, REJECT IF or MISSING",
             "No card, no cycle: answer in the labelled format; never fill gaps "
             "with fluent text.")
L_NO_CHANGE = ("Engineer made no change",
               "The card was not turned into a file edit",
               "The Engineer must edit files in the workspace; an empty diff is a failure.")
L_MEASURE_EDIT = ("Measurement card edited files",
                  "The card said MEASUREMENT: yes (no diff expected) but the workspace changed",
                  "A measurement card is tested by measuring only: never edit files for it; "
                  "drop the label if the card needs a change.")
L_TAMPER = ("Agent-run code changed files outside the workspace or hid a change from git",
            "Nothing but the fingerprint fence stops code with write access",
            "Change files only inside the workspace; evaluation, charter, config "
            "and state are off-limits.")
L_PROTECTED = ("Change touched a protected path",
               "The engineer edited a path listed under protect in team.yaml",
               "Never touch protected paths; they are fixed by the humans.")
L_SECRET = ("Change contained a secret",
            "An agent wrote a credential or a secret file into the workspace",
            "Never write secrets, keys or .env files into the workspace.")
L_SIZE = ("Diff was too large",
          "The change bundled more than one idea",
          "One idea per diff: keep each change small enough to review.")
L_VAGUE = ("Card's REJECT IF was not falsifiable",
           "REJECT IF named no comparison, threshold or metric",
           "REJECT IF must be checkable: a number with <, >, below or above, or the "
           "metric itself (e.g. 'metric below 0.85' or 'metric does not beat the best').")
L_SLOP = ("Change added a banned slop pattern",
          "The diff added text the pack bans (leftover markers, stock filler)",
          "Never add text the pack's slop list bans; finish or remove it before the change.")
L_AUDIT = ("Audit rejected an improving change",
           "Change did not satisfy the audit checklist",
           "An improving metric never overrides a failed audit; fix the cause "
           "and re-propose.")


class Tampered(Exception):
    def __init__(self, role: str, files: list[str]):
        super().__init__(f"{role} broke the fence: " + ", ".join(files[:5]))
        self.files = files


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


CARD_LABEL = re.compile(
    r"^[ \t>*#-]*(HYPOTHESIS|ALTERNATIVES|CHANGE|EXPECT|REJECT IF|MISSING|DIFFERENT|TIER|MEASUREMENT)"
    r"[ \t]*\**[ \t]*:[ \t]*\**", re.I | re.M)
NO_QUESTION = ("", "none", "n/a", "-")
# Manifests, lockfiles, CI and migrations: a change here is heavy whatever its size.
DEFAULT_HEAVY = ("requirements*.txt, pyproject.toml, setup.py, package.json, *.lock, "
                 "go.mod, Cargo.toml, Dockerfile, migrations/*, .github/*")


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def jaccard(a: str, b: str) -> float:
    x, y = words(a), words(b)
    return len(x & y) / len(x | y) if x | y else 0.0


def is_heavy(files: list[str], heavy: list[str]) -> bool:
    """Any changed path (or its file name, so nested manifests count) matches."""
    return any(is_protected(f, heavy) or is_protected(Path(f).name, heavy) for f in files)


def parse_card(text: str) -> dict | None:
    """Labelled card -> {hypothesis, alternatives, change, expect, reject_if,
    missing, different}; None unless HYPOTHESIS, CHANGE, REJECT IF and MISSING
    are all there. DIFFERENT (what is new about a re-proposed card) and TIER
    (`heavy` when the card declares a heavy change) and MEASUREMENT (`yes`: tested by
    measurement alone, no diff expected) are optional."""
    hits = list(CARD_LABEL.finditer(text))
    card = {}
    for m, nxt in zip(hits, hits[1:] + [None]):
        value = " ".join(text[m.end():nxt.start() if nxt else len(text)].split())
        card.setdefault(m.group(1).lower().replace(" ", "_"), value.strip(" *"))
    if not all(card.get(k) for k in ("hypothesis", "change", "reject_if", "missing")):
        return None
    return {k: card.get(k, "") for k in
            ("hypothesis", "alternatives", "change", "expect", "reject_if", "missing",
             "different", "tier", "measurement")}


def is_measurement(parsed: dict | None) -> bool:
    return bool(parsed) and parsed.get("measurement", "").strip().lower().startswith(("yes", "true"))


_COMPARE = re.compile(r"<=|>=|<|>|\b(below|above|under|over|at least|at most|fewer|more)\b", re.I)


def falsifiable(reject_if: str) -> bool:
    """REJECT IF must say how the result can refute the card: the metric itself,
    or a number together with a comparison."""
    return bool(re.search(r"\bmetric\b", reject_if, re.I)
                or (re.search(r"\d", reject_if) and _COMPARE.search(reject_if)))


def declared_heavy(parsed: dict, heavy_globs: list[str]) -> bool:
    """A card is heavy when it says `TIER: heavy` or its CHANGE names a file the heavy
    globs match. The tier `kl check` / the gates find after the edit stays authoritative."""
    words_ = [w.strip("`'\".,;:()[]") for w in parsed.get("change", "").replace("\\", "/").split()]
    return (parsed.get("tier", "").strip().lower().startswith("heavy")
            or any(w and is_heavy([w], heavy_globs) for w in words_))


def card_block(text: str) -> str:
    """The labelled card inside a fused Engineer reply: from the first label to the
    first blank line after the last one, so a closing remark ("done, edited x") never
    runs into MISSING. Text with no label is returned as is (parse_card refuses it)."""
    hits = list(CARD_LABEL.finditer(text))
    if not hits:
        return text.strip()
    end = re.search(r"\n[ \t]*\n", text[hits[-1].end():])
    return text[hits[0].start():hits[-1].end() + end.start() if end else len(text)].strip()


CARD_LINES = (
    "HYPOTHESIS: what we believe and why\n"
    "ALTERNATIVES: at least one competing explanation, and why this card "
    "discriminates between them\n"
    "CHANGE: the smallest change\n"
    "EXPECT: the expected effect on the metric\n"
    "REJECT IF: the result that rejects the hypothesis\n"
    "MISSING: the information that would change this decision, or none\n"
    "DIFFERENT: only when re-proposing something under 'Already tested': what "
    "is new this time (a card without it that repeats a tested hypothesis is "
    "dropped without a run)\n"
    "TIER: heavy - only when the change touches manifests, lockfiles, CI, "
    "migrations or is large; a critic then reviews the card first")
ANALYST_ASK = (
    "You are the Analyst. The workspace is the current directory: read "
    "it, change nothing. Think of competing hypotheses, then pick the one "
    "the smallest change can tell apart from the others. Answer ONLY in "
    "these labelled lines, fixed before anything is run:\n" + CARD_LINES)


def fused_ask(protect: list[str]) -> str:
    """loop.fused: the Analyst's job and the Engineer's in one call. The reply is the card;
    the loop parses and fixes it before the evaluation runs, as for an Analyst card."""
    return (f"{FUSED_MARK} The workspace is the current directory. Think of competing "
            "hypotheses, pick the one the smallest change can tell apart from the others, "
            "then implement exactly that change by editing files in the current directory, "
            f"nothing else. Protected paths (never touch): {', '.join(protect) or '(none)'}. "
            "Run the project's own tests/eval yourself if you can before finishing. The "
            "loop fixes your card before it runs the evaluation. Reply ONLY with these "
            "labelled lines, nothing before or after them:\n" + CARD_LINES)


AUTO_CHANGE = "the smallest change that tests it"


def auto_card(line: str, heavy_globs: list[str]) -> str:
    """loop.auto_cards: the card for a human hypothesis from program.md, built without an
    Analyst call. Pre-registered and falsifiable like any card (REJECT IF names the metric).
    TIER: heavy when the line itself names a heavy file, so the critic round still runs."""
    line = " ".join(line.split())
    return ("HYPOTHESIS: " + line + "\n"
            "ALTERNATIVES: none written (card built from program.md without an analyst call)\n"
            f"CHANGE: {AUTO_CHANGE}\n"
            "EXPECT: the metric rises\n"
            "REJECT IF: the metric does not beat the keep bar\n"
            "MISSING: none"
            + ("\nTIER: heavy" if declared_heavy({"change": line}, heavy_globs) else ""))


def critic_prompt(card: str, standards: str) -> str:
    return (f"Card:\n{card}\n\n{standards}\n\nYou are the Critic. This card is heavy; you "
            "read it before anything is built and change nothing. Attack it. Answer ONLY in "
            "these labelled lines:\nOBJECTIONS: how the change could fail or mislead\n"
            "STRONGEST ALTERNATIVE: the best competing explanation the card missed\n"
            "REJECT-IF CHECK: is REJECT IF too easy to pass? what would a stricter one be\n"
            "VERDICT: proceed or revise")


def wants_revision(critique: str) -> bool:
    return bool(re.search(r"VERDICT\W*revise", critique, re.I))


def slop_hits(diff: str, rules: list) -> list[str]:
    """`name (reason)` per pack slop rule matching a line the diff ADDS."""
    added = "\n".join(l[1:] for l in diff.splitlines()
                      if l.startswith("+") and not l.startswith("+++"))
    return [f"{name} ({reason})" for name, rx, reason in rules if rx.search(added)]


def read_hypotheses(state: Path) -> list[dict]:
    path = state / "hypotheses.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


REJECTED = ("rejected", "inconclusive", "refuted")  # verdicts that mean "examined, not repeated"


def already_tested(rows: list[dict]) -> str:
    """Last 20 rejected/inconclusive/refuted hypotheses, newest first, capped at 2000 chars."""
    out, used = [], 0
    for r in [r for r in rows if r["verdict"] in REJECTED][-20:][::-1]:
        line = f"- cycle {r['cycle']} [{r['verdict']}]: {r['hypothesis']}"
        if used + len(line) > 2000:
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def human_hypotheses(program: Path, rows: list[dict]) -> list[str]:
    """Bullets under '## Hypotheses to test' that no registry row contains yet."""
    if not program.exists():
        return []
    sec = re.search(r"^## Hypotheses to test\s*(.*?)(?=^## |\Z)",
                    program.read_text(encoding="utf-8"), re.S | re.M)
    bullets = re.findall(r"^[-*]\s+(.+)$", sec.group(1), re.M) if sec else []
    done = " ".join(" ".join(r["hypothesis"].split()).lower() for r in rows)
    return [b for b in bullets if " ".join(b.split()).lower() not in done]


def ask_human(state: Path, cycle: int, missing: str) -> None:
    """Append a MISSING value to questions.md (deduped). Never sent to a vendor."""
    if missing.strip(" .").lower() in NO_QUESTION:
        return
    path = state / "questions.md"
    old = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if any(l.endswith(") " + missing) for l in old):
        return
    with path.open("a", encoding="utf-8") as f:
        f.write(f"- (cycle {cycle}) {missing}\n")


def approved(text: str) -> bool:
    """True only if the verdict STARTS with APPROVED ("NOT APPROVED" is a no)."""
    return text.strip().lstrip("*#> \t").upper().startswith("APPROVED")


def _sha(p: Path) -> str:
    try:
        return "link:" + os.readlink(p) if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return "unreadable"


def _hash_tree(top: Path, out: dict, label: str, skip=()) -> None:
    """out[label + relpath] = sha256 of every file under top (symlinks by target)."""
    for d, dirs, files in os.walk(top):
        dirs[:] = [x for x in dirs if Path(d, x) not in skip]
        for n in files + [x for x in dirs if Path(d, x).is_symlink()]:
            out[label + Path(d, n).relative_to(top).as_posix()] = _sha(Path(d, n))


def git_dirs(workspace: Path) -> tuple[Path, Path]:
    """(git dir, common git dir) of the workspace, as `git rev-parse --git-dir` and
    `--git-common-dir` give them, read from git's own pointer files instead of running
    git (whose config is what the fence guards). A plain repo: both are <workspace>/.git.
    A worktree: <workspace>/.git is a file `gitdir: PATH`, and PATH/commondir names the
    main repository's .git, where the config, hooks and info that git runs from live."""
    dot = workspace / ".git"
    if not dot.is_file():
        return dot, dot
    try:
        line = dot.read_text(encoding="utf-8").strip()
    except OSError:
        return dot, dot
    if not line.startswith("gitdir:"):
        return dot, dot
    gitdir = (workspace / line[len("gitdir:"):].strip()).resolve()
    try:
        common = (gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()).resolve()
    except OSError:
        common = gitdir
    return gitdir, common


def fingerprint(root: Path, workspace: Path) -> dict:
    """{relpath: sha256} of everything an agent must not touch: all of root
    (.git, __pycache__, .venv and the state dir included) except the workspace
    and root .git/objects, plus the workspace's git config, info/ and hooks/
    (config can make our own git calls run commands). Content, never size+mtime.
    For a worktree they are read where git reads them: the main repository's .git
    (config, hooks, info) and the worktree's own git dir (config.worktree)."""
    out = {}
    _hash_tree(root, out, "", {workspace, root / ".git" / "objects"})
    gitdir, common = git_dirs(workspace)
    label = "<workspace>/.git/" if common == workspace / ".git" else "<git-common>/"
    for sub in ("info", "hooks"):
        _hash_tree(common / sub, out, f"{label}{sub}/")
    out[f"{label}config"] = _sha(common / "config")
    for d, lab in {(gitdir, "<workspace>/.git/" if gitdir == workspace / ".git" else "<git-dir>/"),
                   (common, label)}:
        if (d / "config.worktree").exists():
            out[f"{lab}config.worktree"] = _sha(d / "config.worktree")
    return out


def fence_files(root: Path, workspace: Path) -> dict:
    """What kl's fence.json seals: fingerprint() minus what the loop itself writes
    (.keeploop/), bytecode, and the root .git churn that `git status` causes
    (config/hooks/info stay covered)."""
    keep_git = (".git/config", ".git/hooks/", ".git/info/")
    return {k: v for k, v in fingerprint(root, workspace).items()
            if not k.startswith(".keeploop/") and "__pycache__/" not in k
            and (not k.startswith(".git/") or k.startswith(keep_git))}


def index_flags(workspace: Path) -> list[str]:
    """Paths the index hides from `git status`: skip-worktree (S) or
    assume-unchanged (lowercase tag)."""
    out = git(workspace, "-c", "core.quotepath=off", "ls-files", "-v", "-z")
    return [e[2:] for e in out.split("\0") if e and (e[0] == "S" or e[0].islower())]


def parse_protect(raw: str, key: str = "protect") -> list[str]:
    """`protect:` (or `heavy:`) -> normalised, casefolded fnmatch patterns.
    ValueError on an absolute path or `..` (it could never mean 'inside the workspace')."""
    out = []
    for p in raw.split(","):
        p = p.strip().replace("\\", "/")
        while p.startswith("./"):
            p = p[2:]
        if p.startswith("/") or re.match(r"[A-Za-z]:", p) or ".." in p.split("/"):
            raise ValueError(f"{key}: {p!r} must be a relative path inside the "
                             f"workspace (no absolute path, no '..')")
        if p.rstrip("/"):
            out.append(p.rstrip("/").casefold())
    return out


def is_protected(path: str, protect: list[str]) -> bool:
    """True if the path, or a folder above it, matches a pattern (fnmatch, any case)."""
    parts = path.casefold().split("/")
    return any(fnmatch.fnmatchcase("/".join(parts[:i]), p)
               for i in range(1, len(parts) + 1) for p in protect)


def protected_dirty(workspace: Path, protect: list[str]) -> list[str]:
    """Protected files whose working-tree bytes differ from HEAD. Ignores the
    index, so skip-worktree / assume-unchanged cannot hide an edit."""
    out = []
    for entry in git(workspace, "ls-tree", "-r", "-z", "HEAD").split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        mode, kind, sha = meta.split()
        if kind != "blob" or not is_protected(path, protect):
            continue
        try:  # git's blob id of the bytes; LF form too, for autocrlf checkouts
            p = workspace / path
            data = os.readlink(p).encode() if mode == "120000" else p.read_bytes()
        except OSError:
            out.append(path)
            continue
        algo = "sha256" if len(sha) == 64 else "sha1"
        if sha not in {hashlib.new(algo, b"blob %d\0" % len(d) + d).hexdigest()
                       for d in (data, data.replace(b"\r\n", b"\n"))}:
            out.append(path)
    return out


def scan_secrets(workspace: Path, files: list[str]) -> list[tuple[str, str]]:
    """(kind, file) per hit in file names and in the CONTENT of every file in
    the change (working-tree bytes, binary included). Never the value."""
    hits = {("secret file name", f) for f in files
            if any(fnmatch.fnmatchcase(Path(f).name.casefold(), g) for g in SECRET_FILES)}
    for f in files:
        p = workspace / f
        if p.is_symlink() or not p.is_file():  # deleted, or never follow a link out
            continue
        text = p.read_bytes().decode("utf-8", errors="ignore")
        # the NUL-free copy catches UTF-16 text and NUL-padded secrets
        hits |= {(kind, f) for kind, rx in SECRET_PATTERNS.items()
                 if rx.search(text) or rx.search(text.replace("\0", ""))}
    return sorted(hits)


def diff_size(workspace: Path) -> int:
    """Added+removed lines of the staged change. Files git will not count
    (binary, `-diff` attribute) cost ceil(bytes/80), so they cannot dodge the cap."""
    size = 0
    for rec in git(workspace, "diff", "--no-ext-diff", "--no-textconv", "--cached",
                   "--no-renames", "--numstat", "-z").split("\0"):
        if not rec:
            continue
        added, deleted, path = rec.split("\t", 2)
        if added.isdigit():
            size += int(added) + int(deleted)
        else:
            try:
                size += -(-(workspace / path).lstat().st_size // 80)
            except OSError:
                pass  # deleted
    return size


def keep_bar(best: float, keep_threshold: float, noise_z: float, sigma: float) -> float:
    """A candidate must exceed this: best plus the larger of the relative
    threshold and noise_z measured standard deviations."""
    return best + max(abs(best) * keep_threshold, noise_z * sigma)


def ceiling_warning(best: float, bar: float, metric_max) -> str | None:
    """A warning when no score can beat the keep bar (a keep needs metric > bar): the
    bar is at or above the top of the metric's scale (loop.metric_max). Without
    metric_max, a best of exactly 1.0 gets a hint, since 0..1 is the commonest scale."""
    if metric_max is not None:
        if bar >= float(metric_max):
            return (f"warning: baseline at ceiling: keep-bar {bar:.6f} is not below the metric's "
                    f"maximum {float(metric_max):.6f}, so every cycle will be discarded. A human "
                    f"must give the score headroom (a stricter evaluate.py) and take a new baseline")
        return None
    if best == 1.0:
        return (f"note: best is 1.000000 and keep-bar {bar:.6f}; if 1.0 is the top of your "
                f"metric, nothing can be kept. Set `metric_max: 1.0` under `loop:` in "
                f"team.yaml to check this")
    return None


def brake(best: float, loop_cfg: dict, rows: list[dict]) -> str | None:
    """Why the loop must stop asking for work (None = carry on). Two human-set
    brakes against doing more than was asked: loop.target (the score that is good
    enough) and loop.stall_cycles (that many cycles in a row without a keep). Both
    are off by default; only a human changes them (team.yaml is fenced)."""
    target = loop_cfg.get("target")
    if target is not None and best >= float(target):
        return (f"target reached: best {best:.6f} >= target {float(target):.6f} (loop.target). "
                f"The job is done: report, do not start another cycle. Only a human raises the target")
    limit = int(loop_cfg.get("stall_cycles") or 0)
    if limit > 0:
        streak = 0
        for row in reversed([r for r in rows if int(r["cycle"]) >= 1]):
            if row["status"] == "keep":
                break
            streak += 1
        if streak >= limit:
            return (f"stalled: {streak} cycles in a row without a keep (loop.stall_cycles {limit}). "
                    f"Stop and report; a human decides what changes next")
    return None


LAST_STDERR = [""]  # evaluate.py's stderr from its last run in this process; never holdout.py's


def save_scorer_notes(state: Path, commit: str) -> None:
    """Pin the last evaluate.py stderr to the best commit (after a baseline or a keep):
    control characters stripped (newlines and tabs kept), secrets redacted, then cut."""
    text = re.sub(r"(?![\n\t])" + CONTROL_RX, "", LAST_STDERR[0])
    for kind, rx in SECRET_PATTERNS.items():
        text = rx.sub(f"[{kind} redacted]", text)
    _write_json(state / "scorer_notes.json", {"commit": commit, "stderr": text.strip()[:65536]})


def scorer_notes(state: Path, best: dict, cap: int, handle: bool = False) -> str:
    """The saved scorer stderr for the current best, capped; "" when off or stale.
    handle (loop.eval_stderr_handle): a cut excerpt ends with the path of the file
    that holds all of it, so the agent reads the rest only if it needs it."""
    path = state / "scorer_notes.json"
    if cap <= 0 or not path.exists():
        return ""
    saved = _read_json(path)
    if saved.get("commit") != best.get("commit"):
        return ""
    text = str(saved.get("stderr", ""))
    if handle and len(text) > cap:
        return (f"{text[:cap]}\n[cut at {cap} of {len(text)} chars; all of it: "
                f"{path.resolve()} (JSON, key \"stderr\")]")
    return text[:cap]


def evaluate_workspace(root: Path, workspace: Path, script: str = "evaluate.py",
                       timeout: int | None = None,
                       eval_cmd: str | None = None) -> tuple[float | None, str]:
    """Run a fixed scorer (evaluate.py, or holdout.py) on the workspace.
    Returns (metric, error); the error text is stripped of control characters.
    run() calls this inside guard(); no secrets in its environment, and no
    .pyc written next to the scorer (that would trip the fence).
    `eval_cmd` (team.yaml, callers pass the merged value) replaces evaluate.py only:
    shlex-split argv, no shell, cwd = workspace; holdout.py is never replaced."""
    timeout = timeout or CONFIG["eval_timeout_s"]  # callers pass the project's merged value
    argv, cwd = [sys.executable, str(root / script), str(workspace)], None
    if eval_cmd and script == "evaluate.py":
        try:
            argv, cwd = shlex.split(str(eval_cmd)), workspace
        except ValueError as exc:
            return None, f"eval_cmd is not parseable: {exc}"
        if not argv:
            return None, "eval_cmd is empty"
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=cwd,
            env={**safe_env(), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"})
    except subprocess.TimeoutExpired:
        return None, f"evaluation timed out after {timeout}s"
    except OSError as exc:  # eval_cmd names a program that cannot start
        return None, re.sub(CONTROL_RX, " ", f"eval_cmd could not start: {exc}")
    if script == "evaluate.py":
        LAST_STDERR[0] = proc.stderr
    if proc.returncode != 0:
        err = (proc.stderr.strip().splitlines() or ["evaluation crashed"])[-1]
        return None, re.sub(CONTROL_RX, " ", err)
    try:
        return float(proc.stdout.strip().splitlines()[-1]), ""
    except (ValueError, IndexError):
        return None, f"evaluation printed no metric: {proc.stdout[:80]!r}"


def repo_map(workspace: Path, max_chars: int, cache: Path | None = None) -> str:
    """Tracked files plus top-level def/class names, capped (codemap.py, cached)."""
    return codemap.render(codemap.build(workspace, cache), max_chars)


def _revert(workspace: Path, to: str = "HEAD") -> None:
    """Drop everything uncommitted (ignored files like .env stay)."""
    git(workspace, "reset", "-q", "--hard", to)
    git(workspace, "clean", "-qfd")


def guarded(root: Path, workspace: Path, role, fn):
    """Run fn; raise Tampered if anything outside the workspace changed or the
    index now hides a path from git. Wraps every call that runs code we do not
    trust: vendors, evaluation, holdout, lesson replay (run.py and kl.py)."""
    before = fingerprint(root, workspace)
    try:
        return fn()
    finally:
        after = fingerprint(root, workspace)
        changed = sorted(k for k in before.keys() | after.keys()
                         if before.get(k) != after.get(k))
        if not changed:  # git config is intact, so our own git call is as safe as before
            changed = [f"<index> {p}" for p in index_flags(workspace)]
        if changed:
            raise Tampered(role, changed)


def project_config(root: Path) -> dict:
    """team.yaml -> the settings every entry point needs. ValueError on a bad
    protect/heavy pattern."""
    team = load_team(root / "team.yaml") if (root / "team.yaml").exists() else {}
    protect = parse_protect(str(team.get("protect") or ""))
    raw = team["heavy"] if "heavy" in team else DEFAULT_HEAVY  # `heavy:` alone = size only
    loop = {k: v for k, v in team.get("loop", {}).items() if k in CONFIG}
    if loop.get("profile") is not None and loop["profile"] not in PROFILES:
        raise ValueError(f"loop.profile: unknown profile {loop['profile']!r} "
                         f"(known: {', '.join(PROFILES)})")
    return {
        "team": team, "protect": protect,
        "heavy_globs": parse_protect(str(raw or ""), "heavy"),
        # defaults < the profile's preset < the keys written under loop:
        "loop_cfg": {**CONFIG, **PROFILES.get(loop.get("profile"), {}), **loop},
        "workspace": (root / str(team.get("workspace") or ".keeploop/workspace")).resolve()}


def workspace_error(root: Path, workspace: Path) -> str | None:
    """Why the workspace cannot be used (None = fine)."""
    if workspace == root or workspace in root.parents:
        return (f"workspace {workspace} must be a folder inside or beside the "
                f"project, not the project itself or a parent of it")
    try:
        top = git(workspace, "rev-parse", "--show-toplevel").strip()
        is_repo = os.path.samefile(top, workspace)
    except (OSError, subprocess.CalledProcessError):
        is_repo = False
    if not is_repo:
        return (f"workspace {workspace} is not a git repository (run prepare.py "
                f"or `git init` it)")
    if git(workspace, "status", "--porcelain").strip():
        return (f"workspace {workspace} has uncommitted changes: commit or stash "
                f"first; the loop resets discarded work")
    return None


def qc_gates(workspace: Path, base: str, protect: list[str], heavy_globs: list[str],
             loop_cfg: dict, slop: list = ()) -> tuple[list[str], str, bool, tuple | None]:
    """Stage the change against `base`, then run the deterministic gates:
    protected paths, secrets, diff size, tier. Returns (changed, diff, heavy,
    fail); fail is (status, note, lesson) or None."""
    git(workspace, "reset", "-q", "--soft", base)  # an agent commit is still a change
    git(workspace, "add", "-A")
    changed = [f for f in git(workspace, "diff", "--cached", "--name-only",
                              "--no-renames", "-z").split("\0") if f]
    # --text: the Auditor is never shown "Binary files differ" or a -diff blind spot
    diff = git(workspace, "diff", "--text", "--no-ext-diff", "--no-textconv", "--cached")
    if not changed:
        return changed, diff, False, None
    hit = sorted({f for f in changed if is_protected(f, protect)}
                 | set(protected_dirty(workspace, protect) if protect else ()))
    if hit:
        return changed, diff, False, (
            "crash", f"gate: protected path touched: {', '.join(hit[:3])}", L_PROTECTED)
    secrets = scan_secrets(workspace, changed)
    if secrets:
        return changed, diff, False, ("crash", "gate: secret blocked: " + ", ".join(
            f"{kind} in {f or '?'}" for kind, f in secrets[:3]), L_SECRET)
    if hits := slop_hits(diff, slop):
        return changed, diff, False, ("crash", "gate: slop: " + "; ".join(hits[:3]), L_SLOP)
    size = diff_size(workspace)
    if size > loop_cfg["max_diff_lines"]:
        return changed, diff, False, (
            "discard", f"gate: diff of {size} lines exceeds {loop_cfg['max_diff_lines']}",
            L_SIZE)
    return changed, diff, size > loop_cfg["heavy_diff_lines"] or is_heavy(
        changed, heavy_globs), None


def eval_crash_lesson(error: str) -> tuple[str, str, str]:
    return (f"Evaluation crashed: {error}",
            "The change left the valid region and nothing the engineer ran caught it first",
            "Run the project's own eval before finishing; an invalid change is a crash "
            "with a lesson, never a silent skip.")


def duplicate_of(parsed: dict, rows: list[dict], threshold: float) -> int | None:
    """Cycle of the rejected/inconclusive hypothesis this card repeats (a card
    that says what is DIFFERENT is never a duplicate), else None."""
    if parsed["different"].strip(" .").lower() not in NO_QUESTION:
        return None
    twin = max(((jaccard(parsed["hypothesis"], r["hypothesis"]), r["cycle"])
                for r in rows if r["verdict"] in REJECTED),
               default=(0.0, 0))
    return twin[1] if twin[0] >= threshold else None


def audit_prompt(card: str, diff: str, metric: float, best: float, standards: str,
                 criteria: list[dict] | None, specialists: str, heavy: bool) -> str:
    """The one audit call: verdict, rubric scores and (heavy changes only) the
    pack's specialist checklists."""
    return (
        f"Card:\n{card}\n\nDiff (capped at 8000 chars):\n{diff[:8000]}\n\n"
        f"Metric: {metric:.6f} (best so far: {best:.6f})\n\n"
        f"{standards}\n\nYou are the Auditor. Checklist: (0) the diff tests the "
        "stated HYPOTHESIS and the CHANGE; flag a change that would pass the "
        "metric without testing it; (1) scope: the diff "
        "implements the card and nothing else; (2) no evaluation gaming: no "
        "hard-coded expected outputs, no special-casing tests or the metric; "
        "(3) guardrails respected; (4) security: no secrets, no new network "
        "calls or exfiltration, no disabled checks; (5) craft per the "
        "standards. Reply with APPROVED or CHANGES REQUESTED as the first "
        "words, then one line per failed checklist item."
        + (f"\n\n{specialists}" if heavy and specialists else "")
        + (f"\n\n{rubric_mod.ask_text(criteria)}" if criteria else ""))


def needs_confirm(heavy: bool, loop_cfg: dict, sigma: float) -> bool:
    """A deterministic metric (sigma 0) needs no re-run for a light change."""
    return heavy or (loop_cfg["confirm_keep"] and sigma > 0)


def _chi2_cdf(x: float, k: int) -> float:
    """P(X <= x) for X ~ chi-square with k degrees of freedom (regularized lower
    incomplete gamma, power series; exact enough for the small x a lower quantile needs)."""
    if x <= 0:
        return 0.0
    a, h = k / 2, x / 2
    term = total = 1.0 / a
    n = 0
    while term > total * 1e-15 and n < 10_000:
        n += 1
        term *= h / (a + n)
        total += term
    return min(1.0, math.exp(a * math.log(h) - h - math.lgamma(a)) * total)


def sigma_upper(sigma: float, runs: int, alpha: float = 0.05) -> float:
    """One-sided (1 - alpha) upper confidence bound on the true sigma, given `sigma`, the
    pstdev of `runs` baseline scores: runs * sigma^2 / true^2 ~ chi-square(runs - 1).
    Fewer than 2 runs measure no spread at all: infinite."""
    if runs < 2:
        return math.inf
    lo, hi = 0.0, float(runs)
    while _chi2_cdf(hi, runs - 1) < alpha:
        hi *= 2
    for _ in range(100):  # bisection for the alpha quantile
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _chi2_cdf(mid, runs - 1) < alpha else (lo, mid)
    return sigma * math.sqrt(runs / hi)


def confirm_skippable(metric: float, best: float, sigma: float, heavy: bool,
                      loop_cfg: dict) -> bool:
    """loop.confirm_skip_z (0 = off): a light change whose first score beats best by at
    least confirm_skip_z times the 95% upper bound on sigma keeps without the re-run.

    The false-keep argument. Take a change with no true effect. Without the skip it is
    kept only if the first score AND the re-run clear the bar. With it, it can also be
    kept on the first score alone, when that score lands >= z * upper(sigma) over best.
    So the extra false-keep probability is at most P(skip | no effect), and the skip only
    removes a re-run that would have passed or failed. P(skip | no effect) is small even
    when sigma is badly underestimated, because the bound grows with the doubt:
    upper(sigma) = sigma * 5.41 at 3 runs, 2.65 at 5, 1.73 at 10, 1.41 at 20 (chi-square,
    95%). Simulated on this exact law (normal noise, best = mean of the baseline runs,
    noise_z 2, z 4, 200,000 changes per row):
        noise_runs 3:  P(skip | no effect) 0.22%; false keeps 4.93% -> 5.03%
        noise_runs 5:  P(skip | no effect) 0.04%; false keeps 1.87% -> 1.90%
        noise_runs 10: P(skip | no effect) 0.003%; false keeps 0.58% -> 0.58%
    (every difference is within the simulation's own noise). Using sigma itself instead
    of the bound is NOT safe: sigma is the pstdev of a few runs and often far too small
    (3 runs: P(estimate < half the truth) = 1 - exp(-3/8) = 0.31), and the same simulation
    then gives 4.9% -> 7.8% false keeps at 3 runs, 0.57% -> 0.78% at 10.

    What the argument does not cover: noise that is not roughly normal (one wild outlier
    is exactly what a re-run catches), and drift between runs. Hence off by default and
    not in `profile: fast`, which is about AI calls, not evaluations. Never for a heavy
    change (its re-run is forced for reasons other than noise), sigma 0 (no re-run anyway)
    or confirm_skip_z <= noise_z (it would skip every confirm). noise_runs must be the
    count that measured best's sigma: change it only with a new baseline. A skipped keep
    records the single score as best (no min of two): if anything, a higher bar later."""
    z = float(loop_cfg.get("confirm_skip_z") or 0)
    if z <= 0 or heavy or sigma <= 0 or z <= loop_cfg["noise_z"]:
        return False
    return metric - best >= z * sigma_upper(sigma, int(loop_cfg["noise_runs"]))


def take_baseline(state: Path, loop_cfg: dict, evaluate, has_holdout: bool,
                  role_vendors: str, best: dict, workspace: Path) -> tuple[str, str]:
    """Score the untouched workspace noise_runs times, record best.json (+ the
    hidden holdout baseline) and ledger row 0. Returns (summary, error)."""
    runs = []
    n_runs = max(1, int(loop_cfg["noise_runs"]))
    for _ in range(n_runs):  # repeats measure the noise (baseline only, never per cycle)
        metric, error = evaluate()
        if metric is None:
            return "", f"baseline evaluation failed: {error}"
        runs.append(metric)
    metric, sigma = statistics.fmean(runs), statistics.pstdev(runs)
    if has_holdout:
        held, error = evaluate("holdout.py")
        if held is None:
            return "", f"baseline holdout failed: {error}"
        _write_json(state / "holdout.json", {"baseline": held, "eval_baseline": metric})
    best.update(metric=metric, sigma=sigma, noise_runs=n_runs,
                commit=git(workspace, "rev-parse", "HEAD").strip())
    _write_json(state / "best.json", best)
    save_scorer_notes(state, best["commit"])
    ledger.append_row(state, {
        "cycle": 0, "ts": _now(), "role_vendors": role_vendors,
        "metric": f"{metric:.6f}", "best_metric": f"{metric:.6f}",
        "status": "keep", "tokens": 0, "lesson_id": "",
        "description": "baseline: untouched workspace"
                       + ("; WARNING sigma not measured (noise_runs 1): the keep bar is the best"
                          if n_runs < 2 else "")})
    return (f"baseline metric = {metric:.6f}  sigma = {sigma:.6f} ({len(runs)} runs)"
            + ("  holdout baseline recorded" if has_holdout else "")
            + ("\n" + UNMEASURED if n_runs < 2 else "")), ""


# loop.noise_runs below 2 measures no noise: said loudly at the baseline, by kl level and
# kl doctor, and in the ledger's baseline row, never silently
UNMEASURED = ("WARNING: sigma is NOT measured (loop.noise_runs is 1): the keep bar is the best "
              "itself, so with a noisy evaluate.py a lucky run is kept as a gain. Set "
              "loop.noise_runs: 3 or more, or check with `kl doctor` that the score does not move.")


def commit_keep(workspace: Path, state: Path, best: dict, n: int, card1: str,
                metric: float, rubric_score: float | None) -> None:
    git(workspace, *GIT_AUTHOR, "commit", "-q", "-m", f"keeploop cycle {n}: {card1[:60]}")
    best.update(metric=metric, commit=git(workspace, "rev-parse", "HEAD").strip(),
                rubric=rubric_score if rubric_score is not None else best.get("rubric"))
    _write_json(state / "best.json", best)
    save_scorer_notes(state, best["commit"])


def rubric_regressed(score: float | None, best: dict) -> bool:
    return (score is not None and best.get("rubric") is not None
            and score < best["rubric"] - rubric_mod.REGRESSION_TOLERANCE)


def record_hypothesis(state: Path, n: int, parsed: dict, verdict: str,
                      metric: float | None, best_before: float,
                      confirm_metric: float | None = None) -> None:
    """The confirm re-run's score, when there is one, is kept here, untruncated."""
    confirm = {"confirm_metric": confirm_metric} if confirm_metric is not None else {}
    with (state / "hypotheses.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "cycle": n, "ts": _now(), "hypothesis": parsed["hypothesis"][:300],
            "change": parsed.get("change", "")[:300],
            "alternatives": parsed.get("alternatives", "")[:300],
            "reject_if": parsed["reject_if"][:200], "verdict": verdict,
            "metric": metric, "best_before": best_before, **confirm}) + "\n")


def unconfirmed_note(metric2: float | None, error: str = "") -> str:
    return ("unconfirmed: re-run " + (f"{metric2:.6f} below the bar" if metric2 is not None
                                      else f"failed: {error[:80]}"))


def verdict_of(status: str, metric: float | None, bar_before: float,
               refuted: bool = False) -> str:
    """`refuted` = examined and rejected on evidence without an eval; a crash never is."""
    return ("supported" if status == "keep"
            else "refuted" if refuted and status != "crash"
            else "untested" if status == "crash" or metric is None
            else "inconclusive" if metric > bar_before else "rejected")


def mock_script(root: Path) -> list[dict] | None:
    """mock_script.json: [{"hypothesis": str, "set": {...}}, ...], else None (built-in)."""
    path = root / "mock_script.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not (isinstance(data, list) and data and all(
            isinstance(x, dict) and isinstance(x.get("hypothesis"), str) and x["hypothesis"].strip()
            and "\n" not in x["hypothesis"] and isinstance(x.get("set"), dict) and x["set"]
            for x in data)):
        raise ValueError(f'{path.name}: must be a non-empty list of '
                         f'{{"hypothesis": "one line", "set": {{...}}}} objects')
    return data


def eval_cache_key(root: Path, workspace: Path, eval_cmd: str | None) -> str:
    """Exactly what the evaluation sees: the workspace's files (git tree of everything,
    staged) plus evaluate.py and eval_cmd. Same key = same inputs."""
    git(workspace, "add", "-A")
    tree = git(workspace, "write-tree").strip()
    scorer = hashlib.sha256((root / "evaluate.py").read_bytes()).hexdigest() \
        if (root / "evaluate.py").exists() else ""
    return hashlib.sha256(f"{tree}\0{scorer}\0{eval_cmd or ''}".encode()).hexdigest()


def diff_lines(diff: str, limit: int = 4) -> list[str]:
    """The changed lines of a diff (no headers), for --narrate."""
    out = [ln for ln in diff.splitlines()
           if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    return out[:limit] + ([f"... {len(out) - limit} more"] if len(out) > limit else [])


def run(root: Path, *, mock: bool, iterations: int | None = None,
        narrate: bool = False) -> int:
    root = root.resolve()
    state = setup(root)
    try:
        cfg = project_config(root)
        script = mock_script(root) if mock else None
    except ValueError as exc:
        print(f"run: {exc}")
        return 1
    team, loop_cfg, workspace = cfg["team"], cfg["loop_cfg"], cfg["workspace"]
    protect, heavy_globs = cfg["protect"], cfg["heavy_globs"]
    roles_cfg = team.get("roles", {})
    if iterations is None:
        iterations = loop_cfg["max_iterations"]

    # Preflight: refuse early, with a clear message ---------------------------
    if problem := workspace_error(root, workspace):
        print(f"run: {problem}")
        return 1
    def build(role, model):
        """FallbackVendor for a role; `vendor: a, b` is an ordered fallback list.
        `model` applies to every CLI in the list, so name one only for single-vendor roles."""
        spec = "mock" if mock else str(roles_cfg.get(role, {}).get("vendor", "mock"))
        names = [n.strip() for n in spec.split(",") if n.strip()]
        try:
            extra = {"custom": team["vendors"]} if isinstance(team.get("vendors"), dict) else {}
            members = [v for v in (vendors.get_vendor(
                n, timeout_s=loop_cfg["vendor_timeout_s"], model=model, **extra)
                for n in names) if v.available()]
        except vendors.VendorUnavailable as exc:
            print(f"run: {role}: {exc}")
            return None
        for m in members:
            if script and getattr(m, "is_mock", False):
                m.script = script
        if not members:
            print(f"run: {role}: none of {names} is available (CLI not installed?)")
        return vendors.FallbackVendor(members) if members else None

    try:  # every model name is checked, whichever vendor serves the role
        for cfg in roles_cfg.values():
            for key in ("model", "heavy_model"):
                vendors.check_model(cfg.get(key) if isinstance(cfg, dict) else None)
    except vendors.VendorUnavailable as exc:
        print(f"run: {exc}")
        return 1
    vendor_objs = {}
    for role in ROLES:
        vendor_objs[role] = build(role, roles_cfg.get(role, {}).get("model"))
        if vendor_objs[role] is None:
            return 1
    # Only the Auditor's tier is known after the work is done; its heavy_model
    # serves heavy changes. (A heavy_model on another role is not used.)
    heavy_model = roles_cfg.get("auditor", {}).get("heavy_model")
    heavy_auditor = build("auditor", heavy_model) if heavy_model else None
    if heavy_model and heavy_auditor is None:
        return 1

    def served() -> dict:
        """Role -> vendor that actually answered (first member before any call)."""
        return {r: v.served or v.members[0].name for r, v in vendor_objs.items()}

    gl = lessons.global_cfg(team)
    pack = packs.load_pack(root, team.get("pack", "software"))
    charter = ""
    if (root / "program.md").exists():
        charter = (root / "program.md").read_text(encoding="utf-8")
    taste = (pack or {}).get("taste", "")
    active_rubric = rubric_mod.load_rubric(pack["rubric_path"]) if pack else None
    specialists = packs.specialists_text(pack)
    slop = packs.slop_rules(pack)
    tokens = [0]
    notes: list[str] = []
    parsed: dict = {}  # this cycle's parsed card, empty if none
    forced: dict = {}  # per-cycle flags: "verdict" decided early ("duplicate"), "audited"
    timing = dict.fromkeys("aevq", 0.0)  # seconds this cycle: analyst, engineer, eval, audit
    phase_totals = dict.fromkeys("aevq", 0.0)

    def guard(role, fn):
        return guarded(root, workspace, role, fn)

    def halt(exc: Tampered) -> int:
        # blocks any later re-seal of fence.json until a human runs `kl begin --accept-changes`
        (state / "tampered.txt").write_text("\n".join(exc.files) + "\n", encoding="utf-8")
        print("run: STOPPED, the fence was broken:\n  " + "\n  ".join(exc.files[:20])
              + "\nThe workspace is left as is: inspect its .git/config and index "
                "before running git there.")
        return 2

    sub = dict.fromkeys("cu", 0.0)  # critic (inside audit) and confirm (inside eval) seconds

    def timed(phase, fn, part=None):
        start = time.monotonic()
        try:
            return fn()
        finally:
            timing[phase] += time.monotonic() - start
            if part:
                sub[part] += time.monotonic() - start

    def evaluate(script="evaluate.py", part=None):
        key = None
        if (loop_cfg["eval_cache"] and script == "evaluate.py" and best.get("metric") is not None
                and not best.get("sigma")):  # never for a noisy evaluation
            key = eval_cache_key(root, workspace, team.get("eval_cmd"))
            if (hit := cache.get(key)) is not None:
                notes.append("eval: cached (same files, same evaluate.py)")
                return hit, ""
        metric, error = timed("v", lambda: guard(
            "evaluate", lambda: evaluate_workspace(
                root, workspace, script, loop_cfg["eval_timeout_s"],
                eval_cmd=team.get("eval_cmd"))), part)
        if key and metric is not None:
            cache[key] = metric
            _write_json(state / "eval_cache.json", cache)
        return metric, error

    def call(role, prompt, heavy=False, part=None):
        v = heavy_auditor if heavy and role == "auditor" and heavy_auditor else vendor_objs[role]
        res = timed(PHASE[role], lambda: guard(role, lambda: v.complete(
            prompt, role=role, cwd=workspace,
            max_tokens=roles_cfg.get(role, {}).get(
                "token_budget", loop_cfg["token_budget_per_role"]))), part)
        vendor_objs[role].served = v.served  # the ledger names who answered
        tokens[0] += res.tokens
        return res

    # kl's fence.json: refreshed at the end only if it held at the start (no fence is not
    # clean after a halt: tampered.txt) and nothing outside the workspace changed since,
    # so a headless run never launders a tamper
    fence_path = state / "fence.json"
    sealed = _read_json(fence_path) if fence_path.exists() else None
    start_files = fence_files(root, workspace)
    fence_ok = not (state / "tampered.txt").exists() and not index_flags(workspace) and (
        sealed is None or (sealed.get("files") == start_files
                           and sealed.get("best_sha") == _sha(state / "best.json")))
    best = _read_json(state / "best.json")
    cache = (_read_json(state / "eval_cache.json")
             if loop_cfg["eval_cache"] and (state / "eval_cache.json").exists() else {})
    hold_path = state / "holdout.json"  # never read into a prompt or the ledger
    has_holdout = (root / "holdout.py").exists()
    try:
        if best.get("metric") is None:  # baseline: score the untouched workspace
            summary, error = take_baseline(
                state, loop_cfg, evaluate, has_holdout,
                ",".join(f"{r}={n}" for r, n in served().items()), best, workspace)
            if error:
                print(f"run: {error}")
                return 1
            print(f"run: {summary}")
    except Tampered as exc:
        return halt(exc)
    sigma = best.get("sigma") or 0.0

    def bar(b):
        return keep_bar(b, loop_cfg["keep_threshold"], loop_cfg["noise_z"], sigma)

    def say(step: str, text: str) -> None:  # --narrate only
        if narrate:
            print(f"  {step:<9} {text}", flush=True)

    def bar_text(b: float) -> str:
        z, th = loop_cfg["noise_z"], loop_cfg["keep_threshold"]
        if bar(b) == b:
            return f"bar {b:.6f} = best (no noise margin)"
        rule = (f"best + {z:g}σ, σ {sigma:.6f}" if z * sigma >= abs(b) * th
                else f"best + {th:g} x best")
        return f"bar {bar(b):.6f} = {rule}"

    if warn := ceiling_warning(best["metric"], bar(best["metric"]), loop_cfg["metric_max"]):
        print(f"run: {warn}")

    def cycle(n: int, base: str) -> tuple[str, float | None, str]:
        def learn(what, cause, rule):
            return lessons.record(state, what=what, root_cause=cause,
                                  guardrail=rule, trigger_cycle=n, cfg=loop_cfg)["id"]

        guardrails = lessons.guardrails_text(
            state, ledger.tail_text(state, 3) + " " + " ".join(human_hypotheses(
                root / "program.md", read_hypotheses(state))[:3]), loop_cfg["recall_top_k"],
            loop_cfg)
        standards = f"{guardrails}\n\nCraft standards:\n{taste}"

        # 1. PROPOSE ------------------------------------------------------
        rows = read_hypotheses(state)
        tested = already_tested(rows)
        human = human_hypotheses(root / "program.md", rows)

        def context() -> str:  # what the card writer reads (Analyst, or the fused Engineer)
            diag = scorer_notes(state, best, loop_cfg["eval_stderr_max_chars"],
                                loop_cfg["eval_stderr_handle"])
            return (
                f"{charter}\n\n{standards}\n\nRepo map:\n"
                f"{repo_map(workspace, loop_cfg['repo_map_max_chars'], state / 'map.json')}\n\nRecent ledger:\n"
                f"{ledger.tail_text(state, loop_cfg['ledger_tail_for_prompt'])}\n\n"
                + (f"Scorer diagnostics for the current best (evaluate.py stderr, capped):\n{diag}\n\n"
                   if diag else "")
                + (f"Already tested (do not re-propose without saying what is "
                   f"different):\n{tested}\n\n" if tested else "")
                + ("Human hypotheses (test the first one not yet in the registry "
                   "before proposing your own):\n"
                   + "\n".join(f"- {h}" for h in human[:5]) + "\n\n" if human else ""))

        # Who writes the card. Default: the Analyst (read-only, workspace reverted after).
        # loop.auto_cards: the next untested human hypothesis is the card, no call at all
        # (one that would not fit the registry's 300 chars is left to the Analyst, or it
        # would never count as tested). loop.fused: the Engineer writes the card and builds
        # it in the same call; the edit stays (`built`) and is gated and evaluated only
        # after the card has been parsed, checked and fixed, exactly as an Analyst's card.
        built, source = False, ""
        auto = [h for h in human if len(" ".join(h.split())) <= 300]
        if loop_cfg["auto_cards"] and auto:
            card, source = auto_card(auto[0], heavy_globs), "program.md"
        elif loop_cfg["fused"]:
            card = card_block(call("engineer", context() + fused_ask(protect)).text)
            built, source = True, "engineer (fused)"
        else:
            card = call("analyst", context() + ANALYST_ASK).text.strip()
            _revert(workspace, base)  # the analyst only reads
        parsed.update(parse_card(card) or {})
        if not parsed:
            notes.append("analyst card is not in the labelled format")
            return "crash", None, learn(*L_NO_CARD)
        if not falsifiable(parsed["reject_if"]):
            notes.append("card: REJECT IF is not falsifiable")
            return "crash", None, learn(*L_VAGUE)
        ask_human(state, n, parsed["missing"])
        guardrails = lessons.guardrails_text(state, card, loop_cfg["recall_top_k"], loop_cfg)  # card-relevant
        if gl["enabled"]:  # opt-in: capped lessons from other projects
            guardrails += lessons.global_text(card, gl)
        standards = f"{guardrails}\n\nCraft standards:\n{taste}"
        card1 = " ".join(parsed["hypothesis"].split())
        notes.append("card: " + card1[:90])
        if source:
            notes.append(f"card by {source}")
        say("card" if source else "analyst", "HYPOTHESIS: " + card1[:90])

        # 1b. DUPLICATE PRECHECK: no Engineer call for a repeat of a tested hypothesis
        if (twin := duplicate_of(parsed, rows, loop_cfg["duplicate_jaccard"])) is not None:
            notes.append(f"duplicate of cycle {twin}")
            if built:  # the cycle's end resets the workspace to base: never evaluated
                notes.append("fused edit dropped before evaluation")
            say("DISCARD", f"repeats the rejected card of cycle {twin}: "
                + ("edit dropped, not evaluated" if built else "no engineer call"))
            forced["verdict"] = "duplicate"
            return "discard", None, ""

        # 1c. CHALLENGE (heavy cards only, max one round): the auditor's vendor
        #     critiques the card, the analyst may revise once. Light cards: no calls.
        if declared_heavy(parsed, heavy_globs):
            critique = call("auditor", critic_prompt(card, standards), heavy=True,
                            part="c").text
            notes.append("critic: " + ("revise" if wants_revision(critique) else "proceed"))
            if wants_revision(critique):
                reply = call("analyst", (
                    f"Card:\n{card}\n\nA critic reviewed it:\n{critique[:3000]}\n\nRevise the "
                    "card ONCE in the same labelled lines, or keep it by answering "
                    "'KEEP: <your reason>'. The metric decides in the end, not this debate."
                )).text.strip()
                _revert(workspace, base)
                built = False  # a fused edit went with the revert: the Engineer builds anew
                new = parse_card(reply)
                if new and falsifiable(new["reject_if"]):
                    card, new["different"] = reply, new["different"] or parsed["different"]
                    parsed.clear()
                    parsed.update(new)
                    card1 = " ".join(parsed["hypothesis"].split())
                    notes.append("card revised after critique")
                else:
                    notes.append("card kept: " + " ".join(reply.split())[:60])

        # 2. IMPLEMENT (+ QC gates, evaluation, bounded repair) -----------
        eng_prompt = (
            f"Experiment card:\n{card}\n\n{standards}\n\nProtected paths (never "
            f"touch): {', '.join(protect) or '(none)'}\n\nYou are the Engineer. "
            "Implement exactly the card by editing files in the current "
            "directory, nothing else. Run the project's own tests/eval yourself "
            "if you can before finishing.")
        first, problem, lesson, heavy = None, "", L_NO_CHANGE, False
        for attempt in range(loop_cfg["engineer_repairs"] + 1):
            if attempt or not built:  # a fused call already made the first attempt
                call("engineer", eng_prompt if not attempt else (
                    f"{eng_prompt}\n\nYour last attempt failed: {problem}. The "
                    "workspace still holds your change; fix it."))
            changed, diff, heavy, fail = qc_gates(workspace, base, protect, heavy_globs,
                                                  loop_cfg, slop)
            if fail:
                notes.append(fail[1])
                return fail[0], None, learn(*fail[2])
            if not changed:
                problem, lesson = "no files were changed", L_NO_CHANGE
            else:
                metric, error = evaluate()  # 3. EVALUATE
                if metric is not None:
                    break
                problem, lesson = error, eval_crash_lesson(error)
            if first is None:
                first = lesson
        else:
            notes.append(f"engineer failed: {problem}")
            return "crash", None, learn(*lesson)
        lesson_id = ""
        if first:  # repaired: the original mistake still gets its lesson
            notes.append(f"repaired after: {first[0][:60]}")
            lesson_id = learn(*first)

        notes.append("tier: " + ("heavy" if heavy else "light"))
        for ln in diff_lines(diff):
            say("engineer", ln)

        # 4. DECIDE on the metric alone first: a candidate that cannot be kept
        #    costs no Auditor call
        def beats(m):
            return m > bar(best["metric"])

        b = best["metric"]
        say("evaluate", f"{metric:.6f}   best {b:.6f}   {bar_text(b)}")
        if not beats(metric):
            say("DISCARD", (f"+{metric - b:.6f} over best, inside the noise band -> git reset"
                            if metric > b else "not above best -> git reset"))
            return "discard", metric, lesson_id

        # 5. AUDIT: one call gives the verdict and, when a pack has a rubric, the scores
        res = call("auditor", audit_prompt(
            card, diff, metric, best["metric"], standards, active_rubric, specialists,
            heavy),
            heavy=heavy)
        forced["audited"] = True
        audit_ok = approved(res.text)
        say("audit", " ".join(res.text.split())[:70])
        notes.append("audit: " + " ".join(res.text.split())[:60])
        rubric_score = rubric_mod.reply_score(
            vendor_objs["auditor"], active_rubric, res.text)
        if rubric_score is not None:
            notes.append(f"rubric: {rubric_score:.0f}")

        # 6. DECIDE -------------------------------------------------------
        if not audit_ok:
            return "discard", metric, learn(*L_AUDIT)
        if rubric_regressed(rubric_score, best):
            notes.append(f"rubric regressed from {best['rubric']:.0f}")
            return "discard", metric, lesson_id
        if needs_confirm(heavy, loop_cfg, sigma) and confirm_skippable(
                metric, best["metric"], sigma, heavy, loop_cfg):
            notes.append(f"confirm skipped: +{(metric - best['metric']) / sigma:.1f} sigma")
            say("confirm", f"skipped: {metric:.6f} is over {loop_cfg['confirm_skip_z']:g} x the "
                f"upper bound of sigma above best")
        elif needs_confirm(heavy, loop_cfg, sigma):
            metric2, error = evaluate(part="u")
            forced["confirm_metric"] = metric2
            if metric2 is None or not beats(min(metric, metric2)):
                notes.insert(1, unconfirmed_note(metric2, error))  # early: the ledger cuts at 240
                say("confirm", (f"re-run {metric2:.6f}: below the bar" if metric2 is not None
                                else f"re-run failed: {error[:60]}"))
                say("DISCARD", "the gain did not survive a second measurement -> git reset")
                return "discard", metric, lesson_id
            metric = min(metric, metric2)
            say("confirm", f"re-run {metric2:.6f}: the lower score {metric:.6f} still clears the bar")
        failures = (guard("replay", lambda: lessons.replay(state, workspace, loop_cfg))
                    if loop_cfg["replay_on_keep"] else [])
        if failures:
            for lid, _ in failures:
                lessons.retrigger(state, lid)
            notes.append("replay failed: " + "; ".join(f"{i}: {m}" for i, m in failures))
            return "discard", metric, failures[0][0]

        commit_keep(workspace, state, best, n, card1, metric, rubric_score)
        say("KEEP", f"{metric:.6f} clears the bar -> git commit {best['commit'][:7]}")
        return "keep", metric, lesson_id

    consecutive_crashes = 0
    totals = {"keep": 0, "discard": 0, "crash": 0, "tokens": 0, "lessons": 0}
    stop = 0
    for n in range(1, iterations + 1):
        if why := brake(best["metric"], loop_cfg, ledger.read_rows(state)):
            print(f"run: stopping — {why}")
            break
        if narrate:
            print(f"\ncycle {n}", flush=True)
        notes.clear()
        parsed.clear()
        forced.clear()
        timing.update(dict.fromkeys("aevq", 0.0))
        sub.update(dict.fromkeys("cu", 0.0))
        best_before = best["metric"]
        tokens[0] = 0
        for v in vendor_objs.values():
            v.served = None
        status, metric, lesson_id = "crash", None, ""
        base = git(workspace, "rev-parse", "HEAD").strip()
        try:
            status, metric, lesson_id = cycle(n, base)
        except vendors.VendorUnavailable as exc:  # infrastructure, not a mistake
            status = "crash"
            notes.append(f"vendor unavailable: {exc}")
        except subprocess.CalledProcessError as exc:
            status = "crash"
            notes.append(f"command failed: {(exc.stderr or str(exc)).strip()[-120:]}")
        except Tampered as exc:
            status, stop = "crash", 2
            notes.insert(0, str(exc))  # first: the ledger cuts the description at 240 chars
            lesson_id = lessons.record(
                state, what=L_TAMPER[0], root_cause=L_TAMPER[1], guardrail=L_TAMPER[2],
                trigger_cycle=n, cfg=loop_cfg)["id"]
            halt(exc)
        finally:  # a keep moved HEAD on purpose; anything else goes back to base
            if not stop:  # never run git in a repo whose config may be poisoned
                _revert(workspace, best["commit"] if status == "keep" else base)
        if parsed:  # the pre-registered hypothesis gets its verdict
            verdict = forced.get("verdict") or verdict_of(
                status, metric, bar(best_before))
            notes.insert(min(1, len(notes)), f"verdict: {verdict}")
            record_hypothesis(state, n, parsed, verdict, metric, best_before,
                              confirm_metric=forced.get("confirm_metric"))
        consecutive_crashes = consecutive_crashes + 1 if status == "crash" else 0
        totals[status] += 1
        totals["tokens"] += tokens[0]
        totals["lessons"] += bool(lesson_id)
        description = " | ".join(" ".join(x.split()) for x in notes)
        names = served()
        suffix = (" | audit: fresh-context (same vendor)"
                  if forced.get("audited") and names["auditor"] == names["engineer"] else "")
        ledger.append_row(state, {
            "cycle": n, "ts": _now(),
            "role_vendors": ",".join(f"{r}={v}" for r, v in names.items()),
            "metric": f"{metric:.6f}" if metric is not None else "",
            "best_metric": f"{best['metric']:.6f}",
            "status": status, "tokens": tokens[0], "lesson_id": lesson_id,
            "description": description[:240 - len(suffix)] + suffix})
        with (state / "timing.jsonl").open("a", encoding="utf-8") as f:  # kl report / kl slow
            f.write(json.dumps({"cycle": n, **{name: round(sec, 2) for name, sec in (
                ("analyst", timing["a"]), ("critic", sub["c"]), ("engineer", timing["e"]),
                ("eval", timing["v"] - sub["u"]), ("confirm", sub["u"]),
                ("audit", timing["q"] - sub["c"]))}}) + "\n")
        for k, v in timing.items():
            phase_totals[k] += v
        print(f"cycle {n}: {status}  metric={metric}  best={best['metric']:.6f}"
              f"  tokens={tokens[0]}" + (f"  lesson={lesson_id}" if lesson_id else "")
              + "  time " + " ".join(f"{k}={v:.0f}s" for k, v in timing.items()))
        if stop:
            return stop
        if consecutive_crashes >= loop_cfg["max_consecutive_crashes"]:
            print(f"run: stopping — {consecutive_crashes} consecutive crashes "
                  f"(limit {loop_cfg['max_consecutive_crashes']})")
            break
        if totals["tokens"] >= loop_cfg["max_run_tokens"]:  # checked after the cycle: it finishes
            print(f"run: budget reached ({totals['tokens']} of "
                  f"{loop_cfg['max_run_tokens']} estimated tokens)")
            break

    if has_holdout and hold_path.exists():  # the final HEAD, scored once
        try:
            held, error = evaluate("holdout.py")
        except Tampered as exc:
            return halt(exc)
        if held is None:
            print(f"run: final holdout failed: {error}")
        else:
            h = {**_read_json(hold_path), "final": held, "eval_final": best["metric"]}
            _write_json(hold_path, h)
            gain, eval_gain = held - h["baseline"], best["metric"] - h["eval_baseline"]
            print(f"holdout: {h['baseline']:.6f} -> {held:.6f} ({gain:+.6f}); "
                  f"evaluation: {h['eval_baseline']:.6f} -> {best['metric']:.6f} "
                  f"({eval_gain:+.6f})")
            if gain < 0 or (eval_gain > 0 and gain < eval_gain / 2):
                print("WARNING: the holdout gain is below the evaluation gain: the keeps "
                      "may be overfitting the evaluation. Review them before trusting "
                      "the metric.")

    print(f"\nrun complete: {totals['keep']} keeps, {totals['discard']} discards, "
          f"{totals['crash']} crashes, {totals['lessons']} lessons, "
          f"{totals['tokens']} tokens. Best metric: {best['metric']:.6f}")
    print("time: " + ", ".join(f"{name} {phase_totals[k]:.0f}s" for k, name in (
        ("a", "analyst"), ("e", "engineer"), ("v", "eval"), ("q", "audit"))))
    standing = lessons.review(state, loop_cfg)
    for l in standing:  # a lesson that recurs with no check: ask a human, once
        if l["standing"] == "ineffective":
            ask_human(state, n if iterations else 0,
                      f"{l['id']} keeps recurring and its text did not stop it: "
                      f"{lessons.hint(l['id'])}")
    if standing:
        print("lessons: " + ", ".join(
            f"{sum(l['standing'] == s for l in standing)} {s}"
            for s in ("enforced", "ineffective", "effective", "provisional")))
    print(f"ledger: {state / 'results.tsv'}")
    qs = state / "questions.md"
    if qs.exists() and (open_q := len(qs.read_text(encoding="utf-8").splitlines())):
        print(f"{open_q} open questions in {qs}")
    if fence_ok and fence_files(root, workspace) == start_files and not index_flags(workspace):
        _write_json(fence_path, {"files": start_files, "best_sha": _sha(state / "best.json")})
    else:
        print(f"run: {fence_path} left as it was: something outside the workspace changed "
              "outside kl; a human must inspect it, then run `kl begin --accept-changes`")
    return 0


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    """`python run.py`, or `kl run` (root = the project kl resolved)."""
    parser = argparse.ArgumentParser(prog="kl run" if root else None, description="keeploop loop")
    parser.add_argument("--version", action="version", version=f"keeploop {__version__}")
    parser.add_argument("--mock", action="store_true",
                        help="route every role to the mock vendor (offline demo)")
    parser.add_argument("--iterations", type=int, default=None,
                        help="default: loop.max_iterations from team.yaml")
    parser.add_argument("--root", type=Path, default=root or Path(__file__).resolve().parent)
    parser.add_argument("--narrate", action="store_true",
                        help="print each step of a cycle: card, diff, score vs the keep bar, decision")
    args = parser.parse_args(argv)
    return run(args.root, mock=args.mock, iterations=args.iterations, narrate=args.narrate)


if __name__ == "__main__":
    raise SystemExit(main())
