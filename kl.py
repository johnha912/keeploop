"""kl.py - deterministic tools for the AI you already use (Claude Code, Codex,
Gemini CLI, Cursor, Copilot, ...). keeploop is not an AI: your AI is the CEO and
reads AGENTS.md; kl only measures, gates, records and refuses. Stdlib only, and
every command except `kl audit --vendor` runs with no AI CLI installed.

    python kl.py begin                  baseline, noise, fence snapshot
    python kl.py next                   fast path: compact brief + card skeleton
    python kl.py try [CARD]             fast path: card + check + eval + keep/discard
    python kl.py handoff [--audit|--critic]  one packet for a chat AI with no repo access
    python kl.py apply REPLY            write a chat AI's reply files, then the `try` flow
    python kl.py status                 what the CEO reads each cycle
    python kl.py card FILE|-            validate + register a hypothesis card
    python kl.py check                  deterministic gates on the workspace diff
    python kl.py eval                   fenced evaluate.py vs the keep bar
    python kl.py audit --vendor NAME    optional cross-vendor audit (prints verdict)
    python kl.py keep                   re-runs everything; commits only if proven
    python kl.py discard                reset to best, ledger + verdict
    python kl.py lesson ...             add | check | review | list  (lessons.py)
    python kl.py scout [...]            trend scout (scout.py)
    python kl.py debate ID --critic|--reply FILE   one bounded critic round (heavy cards)
    python kl.py slow                   the user says it is slow: bottleneck + levers + lesson cmds
    python kl.py report                 run facts from the ledger (paste verbatim)
    python kl.py recall QUERY           did we try or learn this already? (BM25 over memory)
    python kl.py map [--query NAME]     cached code index: defs, importers, related memory
    python kl.py cite FILE              opt-in network: dead links, missing quotes
    python kl.py staff [--apply]        staffing proposal from the ledger
    python kl.py pack new NAME          scaffold a profession pack
    python kl.py init [DIR]             write keeploop's editable files into DIR (pip: kl init)
    python kl.py init --example NAME DEST   build a worked example's sandbox
    python kl.py run [--mock] [...]     the headless loop (same as python run.py)

HONEST LIMIT: in interactive mode the user's AI has the same file rights as kl.
The fence snapshot and the best.json seal in .keeploop/ are TAMPER-EVIDENT (a
changed evaluate.py, charter, team.yaml or best.json is detected and refused),
not tamper-proof: an agent that rewrites the snapshot too is not stopped. Use
the headless run.py, or an OS-level sandbox, when that matters.

Exit codes: 0 ok, 1 refused (reason printed), 2 fence broken; `try` and `apply`
also 3 (waiting for a critic or auditor verdict, the cycle stays open; the next
command is printed) and 4 (discarded).
"""

import sys

sys.dont_write_bytecode = True  # a .pyc written under the project would trip the fence

import argparse
import contextlib
import fnmatch
import hashlib
import html
import io
import json
import math
import re
import statistics
import time
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import codemap
import ledger
import lessons
import packs
import report
import quickstart
import rubric as rubric_mod
import run as R
import scaffold
import scout
import vendors
from prepare import ROOT, load_team, setup


class Refuse(Exception):
    pass


class BadVerdict(Refuse):
    """The audit verdict is for another diff: audit again (`kl try` keeps the cycle open)."""


def kl() -> str:
    """How the user types this tool: `kl` when pip-installed, else `python kl.py`."""
    # PureWindowsPath splits on both / and \ on every OS (Path does not on POSIX);
    # Windows launchers report kl.EXE, so the name is compared case-insensitively
    name = PureWindowsPath(sys.argv[0]).name.lower()
    return "kl" if name in ("kl", "kl.exe") or scaffold.BUNDLE.is_dir() else "python kl.py"


# --- context and state ------------------------------------------------------

def load(root: Path) -> SimpleNamespace:
    root = root.resolve()
    with contextlib.redirect_stdout(io.StringIO()):
        state = setup(root)
    try:
        cfg = R.project_config(root)
    except ValueError as exc:
        raise Refuse(str(exc))
    c = SimpleNamespace(root=root, state=state, **cfg)
    c.roles = c.team.get("roles") if isinstance(c.team.get("roles"), dict) else {}
    c.pack = packs.load_pack(root, c.team.get("pack", "software"))
    c.criteria = rubric_mod.load_rubric(c.pack["rubric_path"]) if c.pack else None
    return c


def _sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def _json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _snap(c) -> dict:
    return R.fence_files(c.root, c.workspace)


def _write_fence(c) -> None:
    R._write_json(c.state / "fence.json", {"files": _snap(c),
                                           "best_sha": _sha_file(c.state / "best.json")})


def _reseal(c) -> None:
    f = _json(c.state / "fence.json", None)
    if f is not None:
        f["best_sha"] = _sha_file(c.state / "best.json")
        R._write_json(c.state / "fence.json", f)


def _fence_check(c) -> None:
    """Refuse (exit 2) when anything outside the workspace changed since `kl begin`."""
    f = _json(c.state / "fence.json", None)
    if f is None:
        raise Refuse(f"no fence snapshot: run `{kl()} begin` first")
    now = _snap(c)
    changed = sorted(k for k in f["files"].keys() | now.keys() if f["files"].get(k) != now.get(k))
    changed += [f"<index> {p}" for p in R.index_flags(c.workspace)]
    if changed:
        raise R.Tampered("kl", changed)


def _best(c) -> dict:
    best = R._read_json(c.state / "best.json")
    if best.get("metric") is None:
        raise Refuse(f"no baseline yet: run `{kl()} begin`")
    f = _json(c.state / "fence.json", None)
    if f is None or f.get("best_sha") != _sha_file(c.state / "best.json"):
        raise Refuse("best.json changed outside kl (or no fence): a human must inspect it "
                     f"and run `{kl()} begin --accept-changes`")
    return best


def _cycle(c) -> dict:
    return _json(c.state / "cycle.json", {})


def _put(c, **kw) -> dict:
    cy = {**_cycle(c), **kw}
    R._write_json(c.state / "cycle.json", cy)
    return cy


def _clear(c) -> None:
    (c.state / "cycle.json").unlink(missing_ok=True)


def _timed(c, key, fn):
    """Run fn and add its seconds to the open cycle's `key` (feeds timing.jsonl)."""
    start = time.monotonic()
    try:
        return fn()
    finally:
        _put(c, **{key: _cycle(c).get(key, 0.0) + time.monotonic() - start})


def _log_time(c, n) -> None:
    """One timing.jsonl row per finished cycle. `agent` is wall time from the card
    to the verdict minus kl's own measured phases: analyst, engineer and any waiting."""
    cy = _cycle(c)
    t = {k: round(cy.get(f"{k}_s", 0.0), 2) for k in ("critic", "eval", "confirm", "audit")}
    wall = time.time() - cy["t0"] if "t0" in cy else sum(t.values())
    t["agent"] = round(max(0.0, wall - sum(t.values())), 2)
    with (c.state / "timing.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"cycle": n, **t}) + "\n")


PHASES = ("analyst", "critic", "engineer", "eval", "confirm", "audit", "agent")


def _timings(c) -> list[dict]:
    path = c.state / "timing.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if path.exists() else []


def _total(row: dict) -> float:
    return sum(float(row.get(k, 0)) for k in PHASES)


def _phase_sums(rows: list[dict]) -> dict:
    sums = {k: sum(float(r.get(k, 0)) for r in rows) for k in PHASES}
    return {k: v for k, v in sums.items() if v > 0}


def _next_cycle(c) -> int:
    return max((int(r["cycle"]) for r in ledger.read_rows(c.state)), default=0) + 1


def _row(c, n, status, metric, lesson_id, desc, tokens=0, best=None) -> None:
    best = best or R._read_json(c.state / "best.json")
    ledger.append_row(c.state, {
        "cycle": n, "ts": R._now(), "role_vendors": "interactive",
        "metric": f"{metric:.6f}" if metric is not None else "",
        "best_metric": f"{best['metric']:.6f}", "status": status, "tokens": tokens,
        "lesson_id": lesson_id, "description": " ".join(desc.split())[:240]})


def _learn(c, lesson, n) -> str:
    return lessons.record(c.state, what=lesson[0], root_cause=lesson[1],
                          guardrail=lesson[2], trigger_cycle=n, cfg=c.loop_cfg)["id"]


def _evaluate(c, script="evaluate.py"):
    return R.guarded(c.root, c.workspace, "evaluate",
                     lambda: R.evaluate_workspace(c.root, c.workspace, script,
                                                  c.loop_cfg["eval_timeout_s"],
                                                  eval_cmd=c.team.get("eval_cmd")))


def _gates(c, best, parsed=None):
    changed, diff, heavy, fail = R.qc_gates(c.workspace, best["commit"], c.protect,
                                            c.heavy_globs, c.loop_cfg, packs.slop_rules(c.pack))
    if R.is_measurement(parsed):  # tested by measurement alone: an empty diff is the point
        if changed:
            fail = ("crash", "measurement card must not edit files", R.L_MEASURE_EDIT)
        return changed, diff, heavy, fail
    if not changed and not fail:
        fail = ("crash", "no files were changed", R.L_NO_CHANGE)
    return changed, diff, heavy, fail


def _bar(c, best) -> float:
    return R.keep_bar(best["metric"], c.loop_cfg["keep_threshold"], c.loop_cfg["noise_z"],
                      best.get("sigma") or 0.0)


def _dirty(c) -> bool:
    return bool(R.git(c.workspace, "status", "--porcelain").strip())


def _stop_on_fail(c, fail) -> None:
    _put(c, fail=list(fail))
    raise Refuse(fail[1])


# --- commands ---------------------------------------------------------------

def cmd_begin(c, a) -> int:
    if problem := R.workspace_error(c.root, c.workspace):
        raise Refuse(problem)
    mark = c.state / "tampered.txt"  # left by a run.py that stopped on a broken fence
    if mark.exists() and not a.accept_changes:
        raise Refuse(f"the last run.py stopped on a broken fence ({mark}): a human must "
                     f"inspect it, then run `{kl()} begin --accept-changes`")
    fence = _json(c.state / "fence.json", None)
    if fence and not a.accept_changes:
        _fence_check(c)  # a resumed session must not launder an earlier change
        if fence.get("best_sha") != _sha_file(c.state / "best.json"):
            raise Refuse("best.json changed outside kl; inspect it, then --accept-changes")
    best = R._read_json(c.state / "best.json")
    if best.get("metric") is None:
        summary, error = R.take_baseline(
            c.state, c.loop_cfg, lambda script="evaluate.py": _evaluate(c, script), (c.root / "holdout.py").exists(),
            "interactive", best, c.workspace)
        if error:
            raise Refuse(error)
        print("kl: " + summary)
    _write_fence(c)
    mark.unlink(missing_ok=True)
    print(status_text(c))
    return 0


def status_text(c) -> str:
    best = R._read_json(c.state / "best.json")
    if best.get("metric") is None:
        return f"not started: run `{kl()} begin`"
    rows = ledger.read_rows(c.state)
    cyc = [r for r in rows if int(r["cycle"]) >= 1]
    count = lambda s: sum(r["status"] == s for r in cyc)  # noqa: E731
    hyps = R.read_hypotheses(c.state)
    out = [f"best {best['metric']:.6f}  sigma {best.get('sigma') or 0:.6f}  keep-bar "
           f"{_bar(c, best):.6f}  | cycles {len(cyc)} (keep {count('keep')}, discard "
           f"{count('discard')}, crash {count('crash')})",
           f"workspace: {c.workspace}"]
    if warn := R.ceiling_warning(best["metric"], _bar(c, best), c.loop_cfg["metric_max"]):
        out.append(warn)
    if why := R.brake(best["metric"], c.loop_cfg, ledger.read_rows(c.state)):
        out.append(f"STOP: {why}")
    cy = _cycle(c)
    out.append(f"pending card: {cy['n']}  {cy['parsed']['hypothesis'][:80]}" if "card" in cy
               else "pending card: none")
    open_l = [l for l in lessons.review(c.state, c.loop_cfg) if l["standing"] in ("provisional", "ineffective")]
    out.append("open lessons: " + ("none" if not open_l else ""))
    out += [f"  {l['id']} [{l['standing']}] {l['guardrail'][:140]}" for l in open_l[:8]]
    qs = c.state / "questions.md"
    ql = qs.read_text(encoding="utf-8").splitlines() if qs.exists() else []
    out.append(f"open questions: {len(ql)}" + (" (ask the human)" if ql else ""))
    out += [f"  {q[:140]}" for q in ql[:3]]
    tested = R.already_tested(hyps).splitlines()[:3]
    if tested:
        out.append("recently rejected (do not repeat):")
        out += [f"  {t[:150]}" for t in tested]
    nxt = R.human_hypotheses(c.root / "program.md", hyps)
    out.append("next hypothesis to test: " + (nxt[0] if nxt else "none listed; propose your own"))
    return "\n".join(out)


def cmd_status(c, a) -> int:
    print(status_text(c))
    return 0


def _vet(c, parsed, n, best, log=True) -> None:
    """Falsifiable REJECT IF, MISSING -> questions.md, duplicate check: for `kl card`
    and for a card revised in `kl debate --reply` (log=False: no ledger row, the
    cycle is already open)."""
    if not R.falsifiable(parsed["reject_if"]):
        lid = ""
        if log:
            lid = _learn(c, R.L_VAGUE, n)
            _row(c, n, "crash", None, lid, "card: REJECT IF is not falsifiable", best=best)
        raise Refuse("REJECT IF must be checkable: name the metric, or a number with "
                     f"< > below or above (e.g. 'metric below 0.85')" + (f"; logged as {lid}" if lid else ""))
    R.ask_human(c.state, n, parsed["missing"])
    twin = R.duplicate_of(parsed, R.read_hypotheses(c.state), c.loop_cfg["duplicate_jaccard"])
    if twin is not None:
        if log:
            R.record_hypothesis(c.state, n, parsed, "duplicate", None, best["metric"])
            _row(c, n, "discard", None, "", f"card: {parsed['hypothesis'][:90]} | duplicate of "
                 f"cycle {twin} | verdict: duplicate", best=best)
        raise Refuse(f"duplicate of cycle {twin}: add a DIFFERENT: line saying what is new, "
                     "or propose another hypothesis")


def _register(c, text: str, edited: bool = False) -> int:
    """`kl card`'s rules: one open card, the brakes, the labelled format, the vet.
    `edited`: `kl try` registers the card after the edit, so the workspace may be
    dirty; the card is still fixed before the evaluation runs."""
    best = _best(c)
    if "card" in _cycle(c):
        raise Refuse(f"card {_cycle(c)['n']} is still open: `kl keep` or `kl discard` it first")
    if not edited and _dirty(c):
        raise Refuse(f"workspace has uncommitted changes: run `{kl()} discard` first")
    if why := R.brake(best["metric"], c.loop_cfg, ledger.read_rows(c.state)):
        raise Refuse(f"{why}. Report with `{kl()} report`")
    n = _next_cycle(c)
    parsed = R.parse_card(text)
    if not parsed:
        lid = _learn(c, R.L_NO_CARD, n)
        _row(c, n, "crash", None, lid, "card is not in the labelled format", best=best)
        raise Refuse("card needs HYPOTHESIS, CHANGE, REJECT IF and MISSING (label: text); "
                     f"logged as {lid}")
    _vet(c, parsed, n, best)
    t0 = time.time()
    if edited:  # the cycle began at `kl next`, before the edit: keep `kl slow` honest
        mark = _json(c.state / "next.json", {}).get("t0")
        t0 = mark if isinstance(mark, (int, float)) and 0 <= t0 - mark < 86400 else t0
    (c.state / "next.json").unlink(missing_ok=True)
    _put(c, n=n, card=text, parsed=parsed, fail=None, metric=None, t0=t0)
    print(f"card {n} registered")
    return n


def cmd_card(c, a) -> int:
    text = sys.stdin.read() if a.file == "-" else Path(a.file).read_text(encoding="utf-8")
    n = _register(c, text)
    parsed = _cycle(c)["parsed"]
    if R.declared_heavy(parsed, c.heavy_globs):
        print(f"heavy card: run the critic (fresh context) on it, then "
              f"`{kl()} debate {n} --critic FILE` (one round, see AGENTS.md)")
    return 0


def cmd_debate(c, a) -> int:
    """One bounded challenge round per card: one critique, one reply. Append-only."""
    cy = _cycle(c)
    if "card" not in cy or cy["n"] != a.card_id:
        raise Refuse(f"card {a.card_id} is not the open card")
    src = a.critic or a.reply
    text = Path(src).read_text(encoding="utf-8").strip()
    path = c.state / "debate" / f"{a.card_id}.md"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if a.critic:
        if "## Critique" in old:
            raise Refuse("this card already has its critique: one round only")
        if not re.search(r"VERDICT\W*(proceed|revise)", text, re.I):
            raise Refuse("a critique ends with `VERDICT: proceed` or `VERDICT: revise`")
        note = "critique recorded" + ("; the analyst may revise once or reply with a reason"
                                     if R.wants_revision(text) else "")
        section = f"## Critique\n{text}\n"
        _put(c, critic_s=round(time.time() - cy.get("t0", time.time()), 2))  # card -> critique
    else:
        if "## Critique" not in old:
            raise Refuse("no critique recorded yet")
        if "## Reply" in old:
            raise Refuse("this card already has its reply: one round only")
        new = R.parse_card(text)
        if new:
            _vet(c, new, a.card_id, _best(c), log=False)
            _put(c, card=text, parsed=new)
        note = ("reply recorded; " + ("card revised" if new else "card kept")
                + ". The CEO decides now; the metric still has the last word.")
        section = f"## Reply\n{text}\n"
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as f:  # append-only
        f.write(section + "\n")
    print(note)
    return 0


def cmd_check(c, a) -> int:
    best = _best(c)
    cy = _cycle(c)
    if "card" not in cy:
        print(f"FAIL no open card: run `{kl()} card FILE` first")
        return 1
    _fence_check(c)
    changed, diff, heavy, fail = _gates(c, best, cy["parsed"])
    if fail:
        _put(c, fail=list(fail))
        print(f"FAIL {fail[1]}")
        return 1
    _put(c, fail=None, gate={"heavy": heavy, "diff": _tag(diff)})  # read by `kl try`
    if R.is_measurement(cy["parsed"]):
        print("PASS measurement card, no diff expected")
        return 0
    print(f"PASS tier={'heavy' if heavy else 'light'} files={len(changed)} "
          f"lines={R.diff_size(c.workspace)} diff={_tag(diff)}")
    return 0


def cmd_eval(c, a) -> int:
    best = _best(c)
    _fence_check(c)
    cy = _cycle(c)
    if "card" in cy and (fail := _gates(c, best, cy["parsed"])[3]):  # the gates `kl keep` runs
        _put(c, fail=list(fail))
        print(f"FAIL {fail[1]} (no evaluation run): fix it and `{kl()} check` again, or `{kl()} discard`")
        return 1
    metric, error = _timed(c, "eval_s", lambda: _evaluate(c))
    if metric is None:
        _put(c, fail=["crash", f"evaluation crashed: {error}", list(R.eval_crash_lesson(error))])
        print(f"FAIL evaluation crashed: {error}")
        return 1
    _put(c, metric=metric)
    bar = _bar(c, best)
    print(f"metric {metric:.6f}  keep-bar {bar:.6f}  best {best['metric']:.6f}  -> "
          + ("beats the bar" if metric > bar else "does not beat the bar (noise or worse)"))
    return 0


def _tag(diff: str) -> str:
    return hashlib.sha256(diff.encode()).hexdigest()[:12]


def _standards(c) -> str:
    return (f"{lessons.guardrails_text(c.state, cfg=c.loop_cfg)}\n\nCraft standards:\n"
            f"{(c.pack or {}).get('taste', '')}")


def _audit_prompt(c, cy, best, diff, heavy, metric) -> str:
    """The one audit prompt, for `kl audit --vendor` and `kl handoff --audit`."""
    return R.audit_prompt(cy["card"], diff, metric, best["metric"], _standards(c),
                          c.criteria, packs.specialists_text(c.pack), heavy)


def cmd_audit(c, a) -> int:
    best = _best(c)
    cy = _cycle(c)
    if "card" not in cy:
        raise Refuse("no registered card: `kl card` first")
    if R.is_measurement(cy["parsed"]):
        raise Refuse(f"measurement card: no diff to audit; `{kl()} discard --reason \"<evidence>\"`")
    _fence_check(c)
    changed, diff, heavy, fail = _gates(c, best)
    if fail:
        _stop_on_fail(c, fail)
    metric = cy.get("metric")
    if metric is None:
        metric, error = _evaluate(c)
        if metric is None:
            raise Refuse(f"evaluation crashed: {error}")
    extra = {"custom": c.team["vendors"]} if isinstance(c.team.get("vendors"), dict) else {}
    try:
        v = vendors.get_vendor(a.vendor, timeout_s=c.loop_cfg["vendor_timeout_s"], model=a.model, **extra)
        if not v.available():
            raise vendors.VendorUnavailable(f"{a.vendor} is not installed")
        prompt = _audit_prompt(c, cy, best, diff, heavy, metric)
        res = _timed(c, "audit_s", lambda: R.guarded(c.root, c.workspace, "auditor", lambda: v.complete(
            prompt, role="auditor", cwd=c.workspace,
            max_tokens=c.roles.get("auditor", {}).get("token_budget", c.loop_cfg["token_budget_per_role"]))))
    except vendors.VendorUnavailable as exc:
        raise Refuse(f"audit: {exc}")
    if _tag(_gates(c, best)[1]) != _tag(diff):
        raise Refuse("the auditor changed the workspace; verdict discarded")
    print(f"{res.text.strip()}\n\nDIFF: {_tag(diff)}")
    return 0


def cmd_keep(c, a) -> int:
    best = _best(c)
    cy = _cycle(c)
    if "card" not in cy:
        raise Refuse("no registered card: no card, no cycle (`kl card`)")
    if a.card is not None and a.card != cy["n"]:
        raise Refuse(f"open card is {cy['n']}, not {a.card}")
    n, parsed = cy["n"], cy["parsed"]
    if R.is_measurement(parsed):
        raise Refuse("measurement card: nothing to keep; `kl discard` it (verdict refuted)")
    _put(c, unconfirmed=None, confirm_metric=None)  # an earlier attempt's re-run is not this one's
    _fence_check(c)
    changed, diff, heavy, fail = _gates(c, best)
    if fail:
        _stop_on_fail(c, fail)
    if (heavy or R.declared_heavy(parsed, c.heavy_globs)) and "## Critique" not in (
            (c.state / "debate" / f"{n}.md").read_text(encoding="utf-8")
            if (c.state / "debate" / f"{n}.md").exists() else ""):
        print("kl: warning: heavy card kept without a recorded critique (kl debate); "
              "not blocking, the metric and the audit still decide")
    pre = getattr(a, "evaluated", None)  # `kl try`: (diff id, metric) it measured a moment ago
    if pre and pre[0] == _tag(diff):
        metric = pre[1]
    else:
        metric, error = _timed(c, "eval_s", lambda: _evaluate(c))
        if metric is None:
            _stop_on_fail(c, ("crash", f"evaluation crashed: {error}", R.eval_crash_lesson(error)))
    bar = _bar(c, best)
    _put(c, metric=metric)
    if not metric > bar:
        raise Refuse(f"metric {metric:.6f} does not beat the keep bar {bar:.6f} "
                     f"(best {best['metric']:.6f}, sigma {best.get('sigma') or 0:.6f})")
    rscore = None
    if a.audit_verdict:
        text = Path(a.audit_verdict).read_text(encoding="utf-8")
        m = re.search(r"DIFF:\s*([0-9a-f]{12})", text)
        if not m or m.group(1) != _tag(diff):
            raise BadVerdict("audit verdict is missing its `DIFF: <id>` line (printed by `kl check`) "
                         "or is for a different diff: audit again")
        if not R.approved(text):
            _stop_on_fail(c, ("discard", "audit: " + " ".join(text.split())[:80], R.L_AUDIT))
        rscore = rubric_mod.reply_score(vendors.Vendor(), c.criteria, text)
        if R.rubric_regressed(rscore, best):
            raise Refuse(f"rubric regressed from {best['rubric']:.0f} to {rscore:.0f}")
    elif heavy:
        raise Refuse("heavy change: needs --audit-verdict FILE (an APPROVED audit of this diff)")
    metric2 = None
    if R.needs_confirm(heavy, c.loop_cfg, best.get("sigma") or 0.0):
        metric2, error = _timed(c, "confirm_s", lambda: _evaluate(c))
        if metric2 is None or not metric2 > bar:
            _put(c, unconfirmed=R.unconfirmed_note(metric2, error), confirm_metric=metric2)
            raise Refuse("unconfirmed: the re-run " + (f"failed: {error}" if metric2 is None
                                                       else f"gave {metric2:.6f}, below the bar"))
        metric = min(metric, metric2)
    if c.loop_cfg["replay_on_keep"]:
        failures = R.guarded(c.root, c.workspace, "replay",
                             lambda: lessons.replay(c.state, c.workspace, c.loop_cfg))
        if failures:
            for lid, _ in failures:
                lessons.retrigger(c.state, lid)
            raise Refuse("lesson replay failed: " + "; ".join(f"{i}: {m}" for i, m in failures))
    card1 = " ".join(parsed["hypothesis"].split())
    before = best["metric"]  # commit_keep updates `best` in place
    R.commit_keep(c.workspace, c.state, best, n, card1, metric, rscore)
    _reseal(c)
    R.record_hypothesis(c.state, n, parsed, "supported", metric, before, confirm_metric=metric2)
    _log_time(c, n)
    _row(c, n, "keep", metric, "", f"card: {card1[:90]} | verdict: supported | tier: "
         f"{'heavy' if heavy else 'light'}", a.tokens, best)
    _clear(c)
    print(f"KEPT cycle {n}: metric {metric:.6f} (bar {bar:.6f}); best is now {best['metric']:.6f}")
    return 0


def cmd_discard(c, a) -> int:
    best = _best(c)
    if a.refuted and not a.reason.strip():
        raise Refuse("--refuted needs --reason \"<the evidence>\"")
    _fence_check(c)  # never run git in a workspace whose config may be poisoned
    cy = _cycle(c)
    if a.refuted and (cy.get("fail") or ["discard"])[0] == "crash":
        raise Refuse("a crash is not evidence: discard it without --refuted")
    R._revert(c.workspace, best["commit"])
    fail = cy.get("fail")
    if "card" not in cy and not fail:
        _clear(c)
        print("workspace reset to best (no open card, nothing logged)")
        return 0
    n = cy.get("n") or _next_cycle(c)
    status = fail[0] if fail else "discard"
    lid = _learn(c, tuple(fail[2]), n) if fail else ""
    metric = cy.get("metric")
    notes = [f"card: {cy['parsed']['hypothesis'][:90]}"] if "card" in cy else []
    notes += ([cy["unconfirmed"]] if cy.get("unconfirmed") else []) + ([fail[1]] if fail else []) \
        + ([f"discard: {a.reason}"] if a.reason else [])
    if "card" in cy:
        verdict = R.verdict_of(status, metric, _bar(c, best),
                               a.refuted or R.is_measurement(cy["parsed"]))
        notes.insert(1, f"verdict: {verdict}")
        R.record_hypothesis(c.state, n, cy["parsed"], verdict, metric, best["metric"],
                            confirm_metric=cy.get("confirm_metric"))
    _log_time(c, n)
    _row(c, n, status, metric, lid, " | ".join(notes), a.tokens, best)
    _clear(c)
    print(f"discarded cycle {n} ({status}); workspace back at best {best['metric']:.6f}"
          + (f"; lesson {lid}" if lid else ""))
    return 0


def report_text(c) -> str:
    """Facts only, straight from the ledger, hypotheses and lessons. Paste verbatim."""
    rows = ledger.read_rows(c.state)
    cyc = [r for r in rows if int(r["cycle"]) >= 1]
    count = lambda s: sum(r["status"] == s for r in cyc)  # noqa: E731
    best = R._read_json(c.state / "best.json")
    base = next((r for r in rows if int(r["cycle"]) == 0), None)
    hyps = R.read_hypotheses(c.state)
    verdicts = {v: sum(h["verdict"] == v for h in hyps) for v in sorted({h["verdict"] for h in hyps})}
    out = ["keeploop report (from .keeploop/, not from memory)",
           f"cycles: {len(cyc)}  keeps: {count('keep')}  discards: {count('discard')}  "
           f"crashes: {count('crash')}",
           "baseline: " + (base["metric"] if base else "none") + "  best: "
           + (f"{best['metric']:.6f}" if best.get("metric") is not None else "none")]
    if base and best.get("metric") is not None:
        out.append(f"gain over baseline: {best['metric'] - float(base['metric']):+.6f}")
    hold = _json(c.state / "holdout.json", None)
    if hold and "final" in hold:
        out.append(f"holdout: {hold['baseline']:.6f} -> {hold['final']:.6f} "
                   f"({hold['final'] - hold['baseline']:+.6f})")
    elif hold:
        out.append("holdout: baseline recorded, final not scored yet (headless run.py scores it)")
    out.append("hypotheses: " + (", ".join(f"{k} {v}" for k, v in verdicts.items()) or "none"))
    out.append("lessons: " + (", ".join(f"{sum(l['standing'] == s for l in rv)} {s}" for s in
                                         ("enforced", "ineffective", "effective", "provisional")
                                         if any(l["standing"] == s for l in rv))
                              if (rv := lessons.review(c.state, c.loop_cfg)) else "none"))
    qs = c.state / "questions.md"
    out.append(f"open questions: {len(qs.read_text(encoding='utf-8').splitlines()) if qs.exists() else 0}")
    out.append(f"tokens recorded: {sum(int(r['tokens'] or 0) for r in cyc)}")
    rows_t = _timings(c)
    if rows_t:
        sums = _phase_sums(rows_t)
        whole = sum(sums.values()) or 1.0
        top = max(sums, key=sums.get)
        out.append("time per phase: " + ", ".join(f"{k} {v:.0f}s" for k, v in sums.items())
                   + f"  | slowest: {top} ({sums[top] / whole:.0%})  | last cycle: "
                   f"{_total(rows_t[-1]):.0f}s")
        budget = c.team.get("cycle_time_budget_s")
        if isinstance(budget, (int, float)):
            over = [str(r["cycle"]) for r in rows_t if _total(r) > budget]
            out.append(f"cycles over the {budget:g}s budget: " + (", ".join(over) or "none"))
    return "\n".join(out)


def cmd_report(c, a) -> int:
    print(report_text(c))
    if a.html or a.svg:  # the shareable chart: ledger only, no model call
        run = report.read_run(c.state)
        title = f"keeploop run: {c.root.name}"
        z = float(c.loop_cfg["noise_z"])
        print("summary: " + report.summary(run))
        if a.html:
            Path(a.html).write_text(report.html_page(run, z, title), encoding="utf-8")
            print(f"wrote {a.html}")
        if a.svg:
            Path(a.svg).write_text(report.chart_svg(run, z, title, auto_dark=True), encoding="utf-8")
            print(f"wrote {a.svg}")
    if a.assert_cycle_under is not None:  # the attachable lesson check
        rows_t = _timings(c)
        if rows_t and _total(rows_t[-1]) > a.assert_cycle_under:
            print(f"FAIL: last cycle took {_total(rows_t[-1]):.0f}s, over {a.assert_cycle_under:g}s")
            return 1
    return 0


LEVERS = {  # phase -> (lever, share of that phase it can save, risk)
    "analyst": ("faster or smaller model for the analyst (`kl staff --goal speed`)", "30-50%",
                "weaker cards, more discards"),
    "critic": ("declare TIER: heavy only for real manifest/CI/migration changes", "all of it on light cards",
               "a risky change skips its challenge round"),
    "engineer": ("faster or smaller model for the engineer (`kl staff --goal speed`)", "30-50%",
                 "more crashes and repairs"),
    "eval": ("make evaluate.py itself faster (subset, cache): the human owns it; lower "
             "`loop.eval_timeout_s` only caps the worst case", "depends on evaluate.py",
             "a smaller subset can hide regressions"),
    "confirm": ("skip the confirm re-run: automatic for light changes when sigma is 0; if sigma "
                "is above 0 the re-run is what protects against noise", "up to 100% of confirm",
                "a noisy metric lets a lucky run through"),
    "audit": ("light tier for more paths (narrow `heavy:` globs in team.yaml), or a faster "
              "auditor model", "up to 100% on light changes", "less independent review"),
    "agent": ("agent time (thinking, editing, waiting): a faster model for the slowest role, "
              "smaller cards (one idea per diff)", "20-40%", "less careful work"),
}


def cmd_slow(c, a) -> int:
    rows_t = _timings(c)
    if not rows_t:
        print("no timing recorded yet: finish a cycle (kl keep / kl discard), then run kl slow")
        return 0
    sums = _phase_sums(rows_t)
    whole = sum(sums.values())
    top = max(sums, key=sums.get)
    avg = whole / len(rows_t)
    print(f"{len(rows_t)} cycles, {avg:.0f}s each on average. Bottleneck: {top} "
          f"({sums[top]:.0f}s, {sums[top] / whole:.0%} of all time).")
    print("Phases: " + ", ".join(f"{k} {v / whole:.0%}" for k, v in sorted(
        sums.items(), key=lambda kv: -kv[1])))
    print("Levers, biggest first (estimates; nothing is applied by kl slow):")
    order = [top] + [k for k in sums if k != top]
    for k in order[:3]:
        lever, saves, risk = LEVERS[k]
        print(f"- {k}: {lever}. Saves about {saves} of {k}; risk: {risk}.")
    best = R._read_json(c.state / "best.json")
    if best.get("sigma") == 0:
        print(f"- noise: sigma is 0, so `loop.noise_runs` ({c.loop_cfg['noise_runs']}) can drop to 1 "
              "at the next baseline; saves (noise_runs-1) evaluations once; risk: a metric that "
              "becomes noisy later goes unmeasured (kl begin and kl doctor then warn).")
    print("- scout: run `kl scout` once per session, not per cycle; saves its network time; "
          "risk: fewer fresh ideas.")
    print(f"Apply model/budget levers only through `{kl()} staff --goal speed --apply` "
          "(inside the allowlist in team.yaml); edit loop settings by hand (human).")
    budget = c.team.get("cycle_time_budget_s")
    target = int(budget) if isinstance(budget, (int, float)) else max(1, math.ceil(
        _total(rows_t[-1]) * 0.8))
    me = f"python {Path(__file__).resolve()} --root {c.root}"
    print("Record the incident so it cannot recur silently:")
    print(f'  {kl()} lesson add "Cycle too slow: {top} was {sums[top] / whole:.0%} of the time" '
          f'"<root cause from the numbers above>" "Keep cycles under {target}s: <lever you chose>"')
    print(f"  {kl()} lesson check L-00N -- {me} report --assert-cycle-under {target}")
    return 0


QUOTE = re.compile(r"[\"“]([^\"”]{8,300})[\"”]\s*\((https://[^\s)]+)\)")


def _norm(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(text)).lower().split())


def cmd_cite(c, a) -> int:
    """Opt-in, network. Dead links and quotes missing from the cited page."""
    text = Path(a.file).read_text(encoding="utf-8")
    urls = list(dict.fromkeys(u.rstrip(".,;") for u in re.findall(r"https://[^\s)>\]\"']+", text)))[:50]
    pages, bad = {}, 0
    for u in urls:
        pages[u] = scout._fetch(u, as_json=False) if scout.safe_url(u) else None
        if pages[u] is None:
            print(f"DEAD {u}")
            bad += 1
    for quote, u in QUOTE.findall(text):
        if pages.get(u) is not None and _norm(quote) not in _norm(pages[u]):
            print(f"QUOTE NOT FOUND in {u}: {quote[:80]}")
            bad += 1
    print(f"cite: {len(urls)} urls checked, {bad} problems")
    return 1 if bad else 0


# --- fast path: next, try, handoff, apply -------------------------------------
# Fewer commands and less output for the same cycle. They call the commands above
# (card, check, eval, keep, discard): the rules live there, not here.

EXIT_WAIT, EXIT_DISCARDED = 3, 4  # `kl try` / `kl apply`: 0 kept, 1 refused, 2 fence
DECISIVE_REL = 0.01  # a light gain skips the audit only if it also clears 1% of |best|
LINE_CAP = 300  # `kl try` prints longer lines cut, with the path of the full text


def _short(c, p: Path) -> str:
    """A path relative to the project root when it is inside it (fewer characters to read)."""
    try:
        return p.relative_to(c.root).as_posix()
    except ValueError:
        return str(p)


def _decisive(best: float, bar: float, metric: float) -> bool:
    """Clears the keep bar by the bar's own margin again, and by DECISIVE_REL of |best|."""
    return metric - bar >= max(bar - best, DECISIVE_REL * abs(best))


def _critiqued(c, n) -> bool:
    p = c.state / "debate" / f"{n}.md"
    return p.exists() and "## Critique" in p.read_text(encoding="utf-8")


def _memory(c, query: str, top: int = 3) -> list[str]:
    """Lessons and rejected hypotheses that match `query` (what a card must not repeat)."""
    out = []
    for _, r in lessons.recall(c.state, query, 50):
        verdict = re.search(r"\[(\w+)\]\s*$", r["_text"])
        if r["kind"] == "lesson" or (r["kind"] == "hypothesis" and verdict
                                     and verdict.group(1) in R.REJECTED + ("duplicate",)):
            out.append(f"  {r['kind']} {r['ref']}: {' '.join(r['_text'].split())[:130]}")
    return out[:top]


def next_text(c) -> str:
    best = R._read_json(c.state / "best.json")
    if best.get("metric") is None:
        return f"not started: run `{kl()} begin`"
    bar = _bar(c, best)
    cyc = [r for r in ledger.read_rows(c.state) if int(r["cycle"]) >= 1]
    k = lambda s: sum(r["status"] == s for r in cyc)  # noqa: E731
    out = [f"best {best['metric']:.6f}  bar {bar:.6f}  sigma {best.get('sigma') or 0:.6f}  "
           f"| cycles {len(cyc)} (keep {k('keep')}, discard {k('discard')}, crash {k('crash')})",
           f"workspace: {_short(c, c.workspace)}"]
    if warn := R.ceiling_warning(best["metric"], bar, c.loop_cfg["metric_max"]):
        out.append(warn)
    if why := R.brake(best["metric"], c.loop_cfg, cyc):
        return "\n".join(out + [f"STOP: {why}", f"Paste `{kl()} report` to the user; start no cycle."])
    cy = _cycle(c)
    if "card" in cy:
        return "\n".join(out + [f"pending card {cy['n']}: {cy['parsed']['hypothesis'][:80]}",
                                f"finish it: `{kl()} try` (continues it) or `{kl()} discard`"])
    hyps = R.read_hypotheses(c.state)
    nxt = R.human_hypotheses(c.root / "program.md", hyps)
    out.append("next hypothesis: " + (nxt[0] if nxt else "none listed; propose your own"))
    query = nxt[0] if nxt else " ".join(r["description"] for r in cyc[-3:]) or "metric"
    mem = _memory(c, query)
    out += (["memory (do not repeat):"] + mem) if mem else ["memory: nothing relevant"]
    qs = c.state / "questions.md"
    if nq := len(qs.read_text(encoding="utf-8").splitlines()) if qs.exists() else 0:
        out.append(f"open questions: {nq} (ask the human; `{kl()} status` lists them)")
    out += [f"card skeleton (fill, save outside this repo, edit, then `{kl()} try FILE`):",
            "HYPOTHESIS: " + (nxt[0] if nxt else "?"), "ALTERNATIVES: ?", "CHANGE: ?",
            "EXPECT: ?", f"REJECT IF: metric <= {bar:.6f}", "MISSING: none"]
    return "\n".join(out)


def cmd_next(c, a) -> int:
    text = next_text(c)
    if "card skeleton" in text:  # a cycle starts here; `kl try` dates the card from it
        R._write_json(c.state / "next.json", {"t0": time.time()})
    print(text)
    return 0


def _try_discard(c, a, reason: str) -> int:
    cmd_discard(c, SimpleNamespace(reason=reason, refuted=False, tokens=a.tokens))
    return EXIT_DISCARDED


def _save_stderr(c) -> str:
    """evaluate.py's full stderr (control characters stripped, secrets redacted) to a file."""
    text = re.sub(r"(?![\n\t])" + R.CONTROL_RX, "", R.LAST_STDERR[0])
    for kind, rx in R.SECRET_PATTERNS.items():
        text = rx.sub(f"[{kind} redacted]", text)
    path = c.state / "eval-stderr.txt"
    path.write_text(text[-65536:], encoding="utf-8")
    return str(path)


def _try_open(c, a) -> int:
    """Gates, evaluation and the decision for the open card, through cmd_check,
    cmd_eval, cmd_keep and cmd_discard. Stops (EXIT_WAIT) for a missing verdict."""
    cy = _cycle(c)
    n, parsed = cy["n"], cy["parsed"]
    if R.declared_heavy(parsed, c.heavy_globs) and not _critiqued(c, n):
        print(f"WAIT heavy card {n}: the critic round comes first. A fresh-context Critic reads "
              f"only the card; save its reply outside this repo, run `{kl()} debate {n} --critic "
              f"FILE`, then `{kl()} try` again (no repo access: `{kl()} handoff --critic`)")
        return EXIT_WAIT
    if cmd_check(c, a) != 0:
        return _try_discard(c, a, "a gate failed")
    R.LAST_STDERR[0] = ""
    if cmd_eval(c, a) != 0:
        if R.LAST_STDERR[0].strip():
            print(f"full evaluate.py stderr: {_save_stderr(c)}")
        return _try_discard(c, a, "evaluation crashed")
    cy, best = _cycle(c), _best(c)
    metric, bar = cy["metric"], _bar(c, best)
    if R.is_measurement(parsed):
        return _try_discard(c, a, f"measurement: metric {metric:.6f}, keep-bar {bar:.6f}")
    if not metric > bar:
        return _try_discard(c, a, "metric did not beat the keep bar")
    heavy, tag = cy["gate"]["heavy"], cy["gate"]["diff"]
    why = "heavy change" if heavy else (
        "this project audits every keep (loop.audit_every_keep)" if c.loop_cfg.get("audit_every_keep")
        else None if _decisive(best["metric"], bar, metric) else "the gain is not decisive")
    if why and not a.audit_verdict:
        print(f"WAIT audit required ({why}): give a fresh-context Auditor the card, `git -C "
              f"{_short(c, c.workspace)} diff`, metric {metric:.6f} and `DIFF: {tag}`; save its reply outside "
              f"this repo, then `{kl()} try --audit-verdict FILE` (no repo access: "
              f"`{kl()} handoff --audit`; another vendor: `{kl()} audit --vendor NAME`)")
        return EXIT_WAIT
    try:
        cmd_keep(c, SimpleNamespace(card=None, audit_verdict=a.audit_verdict, tokens=a.tokens,
                                    evaluated=(tag, metric)))
    except BadVerdict:
        raise  # the cycle stays open: audit this diff, then `kl try --audit-verdict FILE`
    except Refuse as exc:
        print(f"keep refused: {exc}")
        return _try_discard(c, a, "keep refused")
    return 0


def _capped(c, fn) -> int:
    """Run fn, printing each line cut at LINE_CAP; the full text goes to .keeploop/last-try.txt."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            return fn()
    finally:
        text = buf.getvalue()
        lines = text.splitlines()
        full = c.state / "last-try.txt"
        if any(len(l) > LINE_CAP for l in lines):
            full.write_text(text, encoding="utf-8")
        for l in lines:
            print(l if len(l) <= LINE_CAP else f"{l[:LINE_CAP]} ... [full: {full}]")


def cmd_try(c, a) -> int:
    def body():
        cy = _cycle(c)
        text = None if a.file is None else (
            sys.stdin.read() if a.file == "-" else Path(a.file).read_text(encoding="utf-8"))
        if "card" in cy:
            if text is not None and text.strip() not in (cy["card"].strip(), cy.get("src", "")):
                raise Refuse(f"card {cy['n']} is still open with another text: `{kl()} try` "
                             f"(no FILE) continues it, `{kl()} discard` drops it")
        elif text is None:
            raise Refuse(f"no open card: `{kl()} try CARD`")
        else:
            _best(c)
            _fence_check(c)
            _register(c, text, edited=True)
            _put(c, src=text.strip())
        return _try_open(c, a)
    return _capped(c, body)


# handoff / apply: one paste each way for a chat AI with no repo access

FILE_BLOCK = re.compile(r"^(`{3,})file:(.*)$")
GIT_NAMES = {".git", ".gitattributes", ".gitignore", ".gitmodules"}
APPLY_MAX_FILES, APPLY_MAX_BYTES = 50, 2_000_000


def _section(path: Path, title: str) -> str:
    if not path.exists():
        return ""
    m = re.search(rf"^## {re.escape(title)}\s*(.*?)(?=^## |\Z)", path.read_text(encoding="utf-8"),
                  re.S | re.M)
    return m.group(1).strip() if m else ""


def _fence_for(text: str) -> str:
    return "`" * max([3] + [len(m) + 1 for m in re.findall(r"`{3,}", text)])


def _packet_files(c, globs: list[str] | None, max_chars: int) -> tuple[list[str], list[str], dict]:
    """Whole tracked files that fit max_chars, as file blocks; what was left out, why;
    and {path: sha256} of the files shown (`kl apply` overwrites only those)."""
    tracked = sorted(f for f in R.git(c.workspace, "-c", "core.quotepath=off", "ls-files", "-z")
                     .split("\0") if f)
    if globs:
        tracked = [f for f in tracked if any(fnmatch.fnmatch(f, g) or fnmatch.fnmatch(
            Path(f).name, g) for g in globs)]
    secret = {f for _, f in R.scan_secrets(c.workspace, tracked)}
    blocks, left, used, shown = [], [], 0, {}
    for f in tracked:
        p = c.workspace / f
        if f in secret:
            left.append(f"{f} (looks like it holds a secret)")
            continue
        if p.is_symlink() or not p.is_file():
            continue
        data = p.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        if text is None or "\0" in text:
            left.append(f"{f} (binary)")
            continue
        fence = _fence_for(text)
        tag = "(protected: read only)\n" if R.is_protected(f, c.protect) else ""
        block = f"{tag}{fence}file:{f}\n{text}{'' if text.endswith(chr(10)) or not text else chr(10)}{fence}"
        if used + len(block) > max_chars:
            left.append(f"{f} ({len(text)} chars, over --max-chars)")
            continue
        blocks.append(block)
        shown[f] = hashlib.sha256(data).hexdigest()
        used += len(block)
    return blocks, left, shown


REPLY_FORMAT = """\
## Your reply: exactly this format, nothing before the card

HYPOTHESIS: what you believe and why
ALTERNATIVES: a competing explanation this change tells apart
CHANGE: the smallest change
EXPECT: the expected effect on the metric
REJECT IF: metric <= {bar} (or a stricter number with < > below or above)
MISSING: what you do not know and need from the human, or none
```file:relative/path/inside/the/workspace
<the COMPLETE new content of that file>
```

Rules: one card, one idea. One block per file you change or create, with the
whole new content (never a diff, never "..."), the path exactly as shown above.
If the content holds ``` lines, open and close its block with more backticks.
Never a protected path, never a path outside the workspace. Add `DIFFERENT:`
only to re-propose a rejected hypothesis, `TIER: heavy` for a manifest, CI or
migration change. Unknowns go under MISSING; never guess. Do not claim a
result: keeploop applies your files, runs the gates and the fixed evaluation,
and keeps the change only if the metric beats {bar}."""


def handoff_text(c, globs, max_chars) -> str:
    best = _best(c)
    bar = _bar(c, best)
    if why := R.brake(best["metric"], c.loop_cfg, ledger.read_rows(c.state)):
        raise Refuse(f"{why}. Report with `{kl()} report`")
    if "card" in _cycle(c):
        raise Refuse(f"card {_cycle(c)['n']} is still open: `{kl()} try` or `{kl()} discard` it first")
    if _dirty(c):
        raise Refuse(f"workspace has uncommitted changes: run `{kl()} discard` first")
    hyps = R.read_hypotheses(c.state)
    cyc = [r for r in ledger.read_rows(c.state) if int(r["cycle"]) >= 1]
    doc = (c.root / "evaluate.py").read_text(encoding="utf-8") if (c.root / "evaluate.py").exists() else ""
    m = re.match(r'\s*(?:"""|\'\'\')(.*?)(?:"""|\'\'\')', doc, re.S)
    how = f"eval_cmd: {c.team['eval_cmd']}" if c.team.get("eval_cmd") else (
        " ".join(m.group(1).split())[:600] if m else "")
    out = ["# keeploop handoff: one cycle (paste all of this into your chat AI)", "",
           "You are the Analyst and the Engineer of keeploop for ONE cycle. You have no files "
           "and no terminal: everything you know is below. Answer with the reply format at the "
           "end and nothing else.", "", "## Mission", _section(c.root / "program.md", "Mission")
           or "(none written)", "", "## Metric",
           f"evaluate.py prints one number, higher is better. best {best['metric']:.6f}, "
           f"sigma {best.get('sigma') or 0:.6f}, keep bar {bar:.6f}: a change is kept only if "
           f"the metric is above the bar."]
    out += [f"How it is measured: {how}"] if how else []
    nxt = R.human_hypotheses(c.root / "program.md", hyps)
    out += ["", "## Next hypothesis from the human (test it first)",
            *([f"- {h}" for h in nxt[:3]] or ["none listed; propose your own"])]
    out += ["", "## Recent cycles (newest last)",
            *([f"{r['cycle']} {r['status']} {r['metric'] or '-'} {r['description'][:160]}"
               for r in cyc[-8:]] or ["none yet"])]
    tested = R.already_tested(hyps).splitlines()[:8]
    out += ["", "## Rejected hypotheses (do not repeat without a DIFFERENT: line)",
            *(tested or ["none"])]
    open_l = [l for l in lessons.review(c.state, c.loop_cfg)
              if l["standing"] in ("provisional", "ineffective")]
    out += ["", "## Open lessons (rules to follow)",
            *([f"- {l['id']}: {l['guardrail'][:200]}" for l in open_l[:8]] or ["none"])]
    out += ["", "## Protected paths (never change)", ", ".join(c.protect) or "none"]
    blocks, left, shown = _packet_files(c, globs, max_chars)
    R._write_json(c.state / "handoff.json", {"commit": best["commit"], "files": shown})
    out += ["", "## Workspace files (current, complete)", *blocks]
    if left:
        out += ["Not shown (do not write these): " + "; ".join(left[:30])]
    out += ["", REPLY_FORMAT.format(bar=f"{bar:.6f}")]
    return "\n".join(out) + "\n"


def review_text(c, kind: str) -> str:
    """The packet for an outside verdict on the open cycle: the critic or the auditor."""
    cy = _cycle(c)
    if "card" not in cy:
        raise Refuse(f"no open card: `{kl()} handoff` starts a cycle")
    head = ("# keeploop {} (paste into a NEW chat, or another AI: never the one that wrote "
            "the {})\n\n")
    if kind == "critic":
        return (head.format("critic", "card") + R.critic_prompt(cy["card"], _standards(c))
                + f"\n\nThen the user saves the reply to a file outside the repo and runs "
                  f"`{kl()} debate {cy['n']} --critic FILE`, then `{kl()} try`.\n")
    best = _best(c)
    _fence_check(c)
    changed, diff, heavy, fail = _gates(c, best, cy["parsed"])
    if fail:
        raise Refuse(f"{fail[1]}: `{kl()} try` discards it; nothing to audit")
    metric = cy.get("metric")
    if metric is None:
        raise Refuse(f"no metric yet: run `{kl()} try` first")
    return (head.format("audit", "change") + _audit_prompt(c, cy, best, diff, heavy, metric)
            + f"\n\nEnd your reply with this exact last line:\nDIFF: {_tag(diff)}\n\n"
              f"Then the user saves the reply to a file outside the repo and runs "
              f"`{kl()} try --audit-verdict FILE`.\n")


def cmd_handoff(c, a) -> int:
    if a.audit or a.critic:
        print(review_text(c, "audit" if a.audit else "critic"), end="")
    else:
        print(handoff_text(c, a.files, a.max_chars), end="")
    return 0


def parse_reply(text: str) -> tuple[str, list[tuple[str, str]]]:
    """A chat AI's reply -> (card text, [(path, content)]). Data only: nothing in it runs."""
    lines = text.replace("\r\n", "\n").split("\n")
    card, files, i = [], [], 0
    while i < len(lines):
        m = FILE_BLOCK.match(lines[i])
        if not m:
            if not files:  # the card is everything before the first file block
                card.append(lines[i])
            i += 1
            continue
        fence, path, j = m.group(1), m.group(2).strip(), i + 1
        while j < len(lines) and lines[j].rstrip() != fence:
            j += 1
        if j == len(lines):
            raise Refuse(f"the file block for {path[:80]!r} is never closed with {fence}")
        body = lines[i + 1:j]
        files.append((path, "\n".join(body) + "\n" if body else ""))
        i = j + 1
    return "\n".join(card), files


def safe_rel(c, raw: str) -> str:
    """A plain relative path inside the workspace that no rule protects, or Refuse."""
    p = raw.strip()
    bad = (not p or len(p) > 240 or "\\" in p or ":" in p or "~" in p or p.startswith("/")
           or any(ord(ch) < 32 or ord(ch) == 127 for ch in p))
    parts = p.split("/")
    bad = bad or any(s in ("", ".", "..") or s != s.rstrip(". ") or s.casefold() in GIT_NAMES
                     for s in parts)
    if bad:
        raise Refuse(f"refused path {raw[:80]!r}: only plain relative paths inside the workspace "
                     "(no absolute path, .., backslash, drive, ~ or .git file)")
    if R.is_protected(p, c.protect):
        raise Refuse(f"refused path {p!r}: protected")
    cur = c.workspace
    for s in parts:
        cur = cur / s
        if cur.is_symlink():
            raise Refuse(f"refused path {p!r}: goes through a symlink")
    if cur.is_dir() or not cur.resolve().is_relative_to(c.workspace.resolve()):
        raise Refuse(f"refused path {p!r}: not a file inside the workspace")
    return p


def cmd_apply(c, a) -> int:
    def body():
        try:
            text = Path(a.file).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise Refuse("the reply is not UTF-8 text")
        card, files = parse_reply(text)
        rels = [safe_rel(c, p) for p, _ in files]  # every path, before anything is written
        if len({r.casefold() for r in rels}) != len(rels):
            raise Refuse("the reply writes the same file twice")
        if len(files) > APPLY_MAX_FILES or sum(len(b) for _, b in files) > APPLY_MAX_BYTES:
            raise Refuse(f"the reply is too big (at most {APPLY_MAX_FILES} files, "
                         f"{APPLY_MAX_BYTES} chars)")
        _best(c)
        _fence_check(c)
        if "card" in _cycle(c):
            raise Refuse(f"card {_cycle(c)['n']} is still open: `{kl()} try` or `{kl()} discard` it first")
        if _dirty(c):
            raise Refuse(f"workspace has uncommitted changes: run `{kl()} discard` first")
        shown = _json(c.state / "handoff.json", {}).get("files", {})
        for rel in rels:  # a full-file block replaces the whole file: it must have been shown whole
            t = c.workspace / rel
            if t.exists() and shown.get(rel) != _sha_file(t):
                raise Refuse(f"refused path {rel!r}: the last `{kl()} handoff` did not show this "
                             "file whole as it is now; run handoff again (with --files) and reply again")
        _register(c, card)  # pre-registered: the card is fixed before any file is written
        for rel, content in zip(rels, (b for _, b in files)):
            safe_rel(c, rel)
            target = c.workspace / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8", newline="") as f:
                f.write(content)
        print(f"applied {len(rels)} file(s): " + (", ".join(rels)[:200] or "none"))
        return _try_open(c, a)
    return _capped(c, body)


# --- staffing ---------------------------------------------------------------

def _staffing(c) -> tuple[list[str], int | None]:
    s = c.team.get("staffing") if isinstance(c.team.get("staffing"), dict) else {}
    cap = s.get("max_tokens_per_role")
    return packs._words(s.get("allow_models")), cap if isinstance(cap, int) else None


def staff_proposal(c, goal: str = "balanced") -> tuple[dict, str]:
    """{role: {model, heavy_model, token_budget, effort, reason}} and a stats line."""
    models, cap = _staffing(c)
    rows = [r for r in ledger.read_rows(c.state) if int(r["cycle"]) >= 1]
    n = len(rows)
    rate = lambda pred: sum(1 for r in rows if pred(r)) / n if n else 0.0  # noqa: E731
    crash, disc = rate(lambda r: r["status"] == "crash"), rate(lambda r: r["status"] == "discard")
    heavy = rate(lambda r: "tier: heavy" in r["description"])
    toks = [int(r["tokens"] or 0) for r in rows]
    avg = sum(toks) / n if n and sum(toks) else 0
    stats = (f"{n} cycles: crash {crash:.0%}, discard {disc:.0%}, heavy {heavy:.0%}, "
             f"avg tokens/cycle {avg:.0f}" + ("" if avg else " (not recorded for these cycles)")
             + ". Per-role tokens are not in the ledger; budgets scale by the cycle total.")

    def step(cur, d):  # one step along allow_models (cheapest first)
        if not models:
            return cur
        i = models.index(cur) if cur in models else (len(models) // 2)
        return models[max(0, min(len(models) - 1, i + d))]

    budgets = {r: int(c.roles.get(r, {}).get("token_budget", c.loop_cfg["token_budget_per_role"]))
               for r in R.ROLES}
    total = sum(budgets.values())
    scale = 1.0
    if avg and avg * 1.5 < total:
        scale = avg * 1.5 / total
    elif avg and avg > 0.8 * total and cap:
        scale = 1.25
    out = {}
    for role in R.ROLES:
        cfg = c.roles.get(role, {}) if isinstance(c.roles.get(role), dict) else {}
        cur = cfg.get("model")
        model, effort, why = cur, "medium", "no change: too few cycles to judge" if n < 5 else "no change"
        if role == "engineer" and n >= 5:
            if crash >= 0.4:
                model, effort, why = step(cur, 1), "high", f"crash rate {crash:.0%}: stronger model"
            elif crash == 0 and disc < 0.5:
                model, why = step(cur, -1), f"no crashes, discard {disc:.0%}: cheaper model is enough"
        if role == "analyst" and n >= 5 and disc >= 0.6:
            effort, why = "high", f"discard rate {disc:.0%}: cards are not discriminating"
        hm = None
        if role == "auditor":
            effort = "high" if heavy >= 0.2 else "low"
            if heavy >= 0.2 and models:
                hm, why = models[-1], f"heavy share {heavy:.0%}: strongest allowed model for heavy audits"
        b = int(budgets[role] * scale * (0.8 if goal == "cost" else 1.0)) // 1000 * 1000 or budgets[role]
        b = max(5000, min(b, cap)) if cap else min(b, budgets[role])
        if b != budgets[role]:
            why += f"; token_budget {budgets[role]} -> {b}"
        if goal in ("speed", "cost") and models:  # cheapest-first list: one step down is faster
            model, effort, hm = step(cur, -1), "low", None
            why = f"goal {goal}: next faster allowed model"
        elif goal == "quality" and models:
            model, effort = step(cur, 1), "high"
            why = "goal quality: next stronger allowed model"
        out[role] = {"model": model, "heavy_model": hm, "token_budget": b, "effort": effort,
                     "reason": why}
    return out, stats


def set_role_key(text: str, role: str, key: str, value) -> str:
    """Set roles.<role>.<key> in team.yaml text, keeping every comment; text unchanged if the role is absent."""
    lines = text.split("\n")
    in_roles, start = False, None
    for i, l in enumerate(lines):
        if re.match(r"roles:\s*(#.*)?$", l):
            in_roles = True
        elif in_roles and l.strip() and not l.startswith(" ") and not l.lstrip().startswith("#"):
            in_roles = False
        elif in_roles and re.match(rf"  {re.escape(role)}:\s*(#.*)?$", l):
            start = i
    if start is None:
        return text
    end = start + 1
    while end < len(lines) and (lines[end].startswith("    ") or not lines[end].strip()):
        end += 1
    while not lines[end - 1].strip():
        end -= 1
    for i in range(start + 1, end):
        if re.match(rf"    {re.escape(key)}:", lines[i]):
            lines[i] = f"    {key}: {value}"
            break
    else:
        lines.insert(end, f"    {key}: {value}")
    return "\n".join(lines)


def _recall_lines(c, q, top) -> list[str]:
    return [f"  {r['kind']} {r['ref']}: {' '.join(r['_text'].split())[:160]}"
            for _, r in lessons.recall(c.state, q, top)]


def cmd_recall(c, a) -> int:
    hits = _recall_lines(c, a.query, a.top)
    g = lessons.global_cfg(c.team)
    hits += [f"  global lesson {r['id']} ({r['project']}): {r['guardrail'][:160]}"
             for r in lessons.global_recall(a.query, g)]
    print("\n".join(hits) if hits else "nothing in memory matches; it is new")
    return 0


def cmd_map(c, a) -> int:
    m = codemap.build(c.workspace, c.state / "map.json")
    if not a.query:
        print(codemap.render(m, c.loop_cfg["repo_map_max_chars"]))
        return 0
    print(codemap.query(m, a.query))
    if hits := _recall_lines(c, a.query, 3):
        print("related memory:\n" + "\n".join(hits))
    return 0


def cmd_staff(c, a) -> int:
    if a.apply:
        # Before ANY write: a team.yaml that differs from the sealed one is a tamper, and
        # re-sealing it below would launder it. Passing this check means team.yaml is
        # byte-identical to the sealed file, so the `staffing:` allowlist read from it
        # (c.team) is the sealed allowlist, not one an agent added afterwards.
        _fence_check(c)
    proposal, stats = staff_proposal(c, a.goal)
    body = ["# Staffing proposal", "", stats, ""]
    for role, p in proposal.items():
        body.append(f"- {role}: model={p['model'] or '(unchanged)'}"
                    + (f" heavy_model={p['heavy_model']}" if p["heavy_model"] else "")
                    + f" effort={p['effort']} token_budget={p['token_budget']} - {p['reason']}")
    body += ["", "Spawn subagents / new sessions with the model and effort above. "
             "`kl staff --apply` writes only model, heavy_model and token_budget into "
             "team.yaml, and only inside its `staffing:` allowlist."]
    (c.state / "staffing.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    print("\n".join(body[:2 + len(proposal) + 2]))
    if not a.apply:
        return 0
    models, cap = _staffing(c)
    if not models and cap is None:
        raise Refuse("no `staffing:` allowlist in team.yaml (allow_models / max_tokens_per_role): "
                     "nothing applied")
    path = c.root / "team.yaml"
    text, done = path.read_text(encoding="utf-8"), []
    for role, p in proposal.items():
        cur = c.roles.get(role, {}) if isinstance(c.roles.get(role), dict) else {}
        for key in ("model", "heavy_model"):
            if p[key] and p[key] in models and p[key] != cur.get(key):
                text, done = set_role_key(text, role, key, p[key]), done + [f"{role}.{key}={p[key]}"]
        if cap and p["token_budget"] <= cap and p["token_budget"] != cur.get(
                "token_budget", c.loop_cfg["token_budget_per_role"]):
            text = set_role_key(text, role, "token_budget", p["token_budget"])
            done.append(f"{role}.token_budget={p['token_budget']}")
    path.write_text(text, encoding="utf-8")
    load_team(path)  # still parses
    f = _json(c.state / "fence.json", None)
    if f is not None:  # kl is the legitimate editor of team.yaml: refresh only that entry
        f["files"]["team.yaml"] = R._sha(path)
        R._write_json(c.state / "fence.json", f)
    print("applied: " + (", ".join(done) or "nothing to change"))
    return 0


# --- packs ------------------------------------------------------------------

PACK_YAML = r"""name: {name}
status: experimental
profession: TODO the field this pack serves
description: TODO one sentence
# THE HARD QUESTION. keeploop only learns as well as its metric. Answer both:
#  1. What AUTOMATIC metric (a number a script prints, higher is better)?
#  2. How was it validated against REAL outcomes (sales, user ratings, defects
#     found later)? If it was not, say so: the pack stays experimental.
metric: TODO the automatic metric that evaluate.py will print
metric_validation: TODO how it was checked against real outcomes, or "not validated"
taste_file: taste.md
rubric_file: rubric.md
# Topics the scout searches (comma separated).
scout_topics: TODO topic one, TODO topic two
# Specialist reviewers: their checklists join the audit of HEAVY changes only.
# One line each (checklist: text) or a file inside this folder (checklist_file: x.md).
# Slop gate (optional): `name: regex => reason`, matched on lines the diff ADDS;
# a hit is a crash before any AI sees the change. Prefix (?i) for case-insensitive.
# slop:
#   filler: (?i)\bgame-?changer\b => empty superlative
roles:
  reviewer-one:
    checklist: TODO what this specialist checks on heavy changes
"""
PACK_TASTE = """# Taste - {name}

TODO: what "good" looks like in this field beyond the metric. Interview the
user; write short, checkable principles and the anti-patterns the Auditor
should flag on sight.
"""
PACK_RUBRIC = """# Rubric - {name}

| Criterion | Weight | Gate |
|---|---|---|
| TODO criterion that must never fail | 50 | yes |
| TODO quality criterion | 50 | no |

Anchors: TODO 90+ = ..., 70 = ..., 50 = ..., below 50 on a gate = hard fail.
"""


def cmd_pack(c, a) -> int:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", a.name):
        raise Refuse("pack name: lowercase letters, digits and - only")
    if re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", a.name, re.I):
        raise Refuse(f"{a.name!r} is a reserved device name on Windows")
    d = c.root / "packs" / a.name
    if d.exists():
        raise Refuse(f"{d} already exists")
    d.mkdir(parents=True)
    for fname, tpl in (("pack.yaml", PACK_YAML), ("taste.md", PACK_TASTE), ("rubric.md", PACK_RUBRIC)):
        (d / fname).write_text(tpl.format(name=a.name), encoding="utf-8")
    print(f"scaffolded {d}: fill every TODO by interviewing the user (metric first), "
          f"then set `pack: {a.name}` in team.yaml")
    return 0


# --- entry ------------------------------------------------------------------

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kl", description=__doc__.split("\n\n")[0],
                                epilog="--root PATH may come first. See AGENTS.md.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("begin", help="baseline + noise + fence snapshot").add_argument(
        "--accept-changes", action="store_true", help="human: re-snapshot after a legit change")
    sub.add_parser("status", help="compact state for the CEO")
    sub.add_parser("next", help="fast path: compact brief, memory and a card skeleton")
    s = sub.add_parser("try", help="fast path: card + check + eval + keep or discard (exit 3: "
                       "needs a verdict, 4: discarded)")
    s.add_argument("file", nargs="?", help="the card (omit to continue the open card)")
    s.add_argument("--audit-verdict", metavar="FILE")
    s.add_argument("--tokens", type=int, default=0)
    s = sub.add_parser("handoff", help="one packet to paste into a chat AI with no repo access")
    s.add_argument("--files", nargs="+", metavar="GLOB", help="workspace files to include")
    s.add_argument("--max-chars", type=int, default=24000, help="cap on included file text")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--audit", action="store_true", help="the auditor packet for the open cycle")
    g.add_argument("--critic", action="store_true", help="the critic packet for the open card")
    s = sub.add_parser("apply", help="write a chat AI's reply (card + files), then the try flow")
    s.add_argument("file")
    s.add_argument("--audit-verdict", metavar="FILE", help=argparse.SUPPRESS)
    s.add_argument("--tokens", type=int, default=0)
    sub.add_parser("card", help="validate + register a hypothesis card").add_argument("file")
    sub.add_parser("check", help="deterministic gates on the workspace diff")
    sub.add_parser("eval", help="fenced evaluate.py vs the keep bar")
    s = sub.add_parser("audit", help="optional cross-vendor audit")
    s.add_argument("--vendor", required=True)
    s.add_argument("--model")
    s = sub.add_parser("keep", help="re-run everything; commit only if proven")
    s.add_argument("--card", type=int)
    s.add_argument("--audit-verdict", metavar="FILE")
    s.add_argument("--tokens", type=int, default=0)
    s = sub.add_parser("discard", help="reset to best + ledger row")
    s.add_argument("--reason", default="")
    s.add_argument("--refuted", action="store_true",
                   help="examined and rejected on evidence without an eval (needs --reason)")
    s.add_argument("--tokens", type=int, default=0)
    s = sub.add_parser("debate", help="record the one critic round of a heavy card")
    s.add_argument("card_id", type=int)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--critic", metavar="FILE")
    g.add_argument("--reply", metavar="FILE")
    s = sub.add_parser("report", help="run facts from the ledger (paste verbatim)")
    s.add_argument("--html", metavar="FILE", help="also write a self-contained HTML page: summary + chart")
    s.add_argument("--svg", metavar="FILE", help="also write the chart alone as an SVG (README-ready)")
    s.add_argument("--assert-cycle-under", type=float, metavar="SECONDS",
                   help="exit 1 if the last cycle took longer (a lesson check)")
    sub.add_parser("cite", help="opt-in, network: dead links and quotes missing from pages").add_argument("file")
    sub.add_parser("lesson", help="add | check | review | list (see lessons.py)")
    sub.add_parser("scout", help="trend scout (see scout.py)")
    sub.add_parser("init", help="write keeploop's files into a folder, or --example NAME DEST")
    sub.add_parser("run", help="the headless loop (run.py): --mock, --iterations N")
    s = sub.add_parser("staff", help="staffing proposal")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--goal", choices=["balanced", "speed", "quality", "cost"], default="balanced")
    sub.add_parser("slow", help="why is it slow: bottleneck phase, levers, lesson commands")
    s = sub.add_parser("map", help="cached code index; --query NAME: defs, importers, memory")
    s.add_argument("--query")
    s = sub.add_parser("recall", help="BM25 over lessons, hypotheses, debates, questions, ledger")
    s.add_argument("query")
    s.add_argument("--top", type=int, default=5)
    s = sub.add_parser("level", help="the CEO's choice of light / fast / rigorous from the stakes and the noise")
    s.add_argument("--stakes", required=True, choices=list(STAKES),
                   help="what a wrong change costs: " + "; ".join(f"{k} = {v}" for k, v in STAKES.items()))
    s.add_argument("--apply", action="store_true", help="write loop.profile in team.yaml")
    s = sub.add_parser("doctor", help="init-time: run evaluate.py N times, report sigma and what it means")
    s.add_argument("--runs", type=int, default=5)
    s.add_argument("--want", type=float, metavar="GAIN", help="the smallest real gain you care about")
    sub.add_parser("quickstart", help="tests | command | prompt | buildtime: a control folder "
                   "with that evaluate.py for your repo")
    sub.add_parser("import-lite", help="continue a keeploop-lite session: LEDGER.md [DIR]")
    s = sub.add_parser("pack", help="pack new NAME")
    s.add_argument("action", choices=["new"])
    s.add_argument("name")
    return p


def cmd_init(argv: list[str]) -> int:
    """`kl init`: no project is loaded (load() would create .keeploop/ in the cwd)."""
    src = scaffold.source()
    names = scaffold.example_names(src)
    p = argparse.ArgumentParser(prog=f"{kl()} init", description=(
        "Write keeploop's editable files (AGENTS.md, program.md, team.yaml, a demo "
        "evaluate.py, packs/, .claude/) into DIR. Existing files are never overwritten."))
    p.add_argument("dir", nargs="?", type=Path, help="default: the current folder; "
                   "with --example: the new sandbox folder (required)")
    p.add_argument("--example", choices=names or None, metavar="NAME",
                   help="build a worked example's sandbox in DIR: " + (", ".join(names) or "none"))
    a = p.parse_args(argv)
    cli = kl() == "kl"  # a pip-installed kl: the copies say `kl ...`, no code is copied
    try:
        if a.example:
            if a.dir is None:
                raise Refuse(f"--example needs a new folder: `{kl()} init --example {a.example} DEST`")
            example = src / "examples" / a.example
            root, ws = scaffold.make_sandbox(example, a.dir, with_code=not cli, src=src)
            print(f"sandbox ready: workspace {ws}")
            for line in scaffold.missing_requirements(example):
                print(line)
            print(f"next: cd {root} && {kl()} begin   (headless: "
                  f"{'kl run' if cli else 'python run.py'})")
            return 0
        dest = (a.dir or Path.cwd()).resolve()
        written, kept = scaffold.init(dest, rewrite=cli, src=src)
    except SystemExit as exc:  # scaffold refuses with SystemExit (shared with make_sandbox.py)
        raise Refuse(str(exc).removeprefix("refused: "))
    print(f"kl init: wrote {len(written)} files in {dest}" + (
        f"; kept {len(kept)} that were already there: " + ", ".join(kept[:8])
        + (" ..." if len(kept) > 8 else "") if kept else ""))
    for rel in ("AGENTS.md", "team.yaml", "evaluate.py"):
        if rel in kept:
            print(f"warning: your {rel} was kept, so keeploop's was not written. Run "
                  f"`{kl()} init` in a new, empty folder unless this one is already keeploop's.")
    print(f"next: cd {dest} && {kl()} begin   (the demo; then follow AGENTS.md, "
          f"'Pointing keeploop at the user's own repo')")
    return 0


def doctor_text(runs: list[float], loop_cfg: dict, want: float | None, secs: float) -> list[str]:
    """What the measured noise means for this loop (kl doctor)."""
    mean, sd = statistics.fmean(runs), statistics.stdev(runs)
    z, th, n0 = float(loop_cfg["noise_z"]), float(loop_cfg["keep_threshold"]), int(loop_cfg["noise_runs"])
    smallest = max(abs(mean) * th, z * sd)
    out = [f"evaluate.py, {len(runs)} runs on the current workspace: " + ", ".join(f"{x:.6f}" for x in runs),
           f"mean {mean:.6f}  sigma {sd:.6f} (sample stdev)  range {max(runs) - min(runs):.6f}"
           f"  {secs:.1f}s per run"]
    if sd == 0:
        out.append("deterministic: no noise. A change is kept when it beats the best by more than "
                   f"keep_threshold ({th:g} x best = {abs(mean) * th:.6f}); light changes skip the "
                   "confirm re-run.")
        return out
    out.append(f"a change must gain more than {smallest:.6f} to be kept "
               f"({'noise_z ' + format(z, 'g') + ' x sigma' if z * sd >= abs(mean) * th else 'keep_threshold'}"
               + (f", {smallest / abs(mean):.1%} of the mean" if mean else "") + ")")
    if n0 < 5:
        out.append(f"warning: loop.noise_runs is {n0}: the baseline estimates sigma from {n0} runs, "
                   "and that estimate swings widely (docs/proof/sweep.tsv: 3-run sigmas from "
                   "0.0017 to 0.026 for an evaluation whose sigma is about 0.014). Set noise_runs: 5 or more in team.yaml.")
    if want is not None and want > 0:
        k = math.ceil((z * sd / want) ** 2) if z * sd > want else 1
        out.append(f"to keep a real gain of {want:g}: " + (
            "already detectable." if k == 1 else
            f"the noise is too large. Average {k} repeats inside evaluate.py (sigma falls as "
            f"1/sqrt(repeats); use the median for timings with outliers), fix seeds, or score "
            f"more cases."))
    elif mean and smallest / abs(mean) > 0.01:
        out.append("warning: gains under that are invisible to the loop: real but small "
                   "improvements will be discarded. Reduce the noise in evaluate.py (repeats + "
                   "mean or median, fixed seeds, more cases), or say which gain matters with "
                   "`--want GAIN`.")
    return out


def unmeasured_loop(best: dict, loop_cfg: dict, measured_sd: float) -> list[str]:
    """kl doctor on a loop whose keep bar is its best without the noise having been shown
    to be 0: a baseline from one run, a noisy score under a sigma-0 baseline, or a
    noise_runs below 2 for the next baseline."""
    out = []
    if best.get("metric") is not None:
        n, sigma = best.get("noise_runs"), float(best.get("sigma") or 0.0)
        if n is not None and int(n) < 2:
            out.append(f"WARNING: this loop's baseline came from {n} run: its sigma was never "
                       "measured and its keep bar is its best. A human must take a new baseline "
                       "with loop.noise_runs 3 or more.")
        elif sigma == 0 and measured_sd > 0:
            out.append(f"WARNING: this loop's baseline sigma is 0, so its keep bar is its best, but "
                       f"evaluate.py is noisy now (sigma {measured_sd:.6f}): a lucky run would be kept. "
                       "A human must take a new baseline with loop.noise_runs 3 or more.")
    if int(loop_cfg["noise_runs"]) < 2:
        out.append(R.UNMEASURED)
    return out


STAKES = {
    "low": "a draft or a personal file you can redo",
    "medium": "something other people use, that you can still roll back",
    "high": "work people rely on, or a result you will publish or ship",
}


def level_for(stakes: str, sigma: float) -> tuple[str, list[str]]:
    """The CEO's choice of `loop.profile` -> (profile, reasons). Pure: the user's answer
    about stakes, and the evaluation's measured noise."""
    if stakes == "high":
        return "rigorous", ["a wrong keep is costly: 5 noise runs, a re-run before every keep, "
                            "an Auditor verdict on every keep, the full Analyst"]
    if stakes == "low" and sigma == 0:
        return "light", ["a wrong keep is cheap to undo and the score does not move between runs: "
                         "at most 3 cycles, stop after 2 without a keep, no re-run, fewer AI "
                         "calls; the noise is still measured (3 baseline runs)"]
    why = ["fewer AI calls and shorter prompts, the full keep law"]
    if stakes == "low":
        why.append(f"not light: the score moves between runs (sigma {sigma:.6f}), so the noise "
                   "is still measured and a keep is re-run")
    return "fast", why


def _set_profile(team: Path, name: str) -> None:
    text = team.read_text(encoding="utf-8")
    if re.search(r"^  profile:.*$", text, re.M):
        text = re.sub(r"^  profile:.*$", f"  profile: {name}", text, count=1, flags=re.M)
    elif re.search(r"^loop:[ \t]*$", text, re.M):
        text = re.sub(r"^loop:[ \t]*\n", f"loop:\n  profile: {name}\n", text, count=1, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\n\nloop:\n  profile: {name}\n"
    team.write_text(text, encoding="utf-8")


def cmd_level(c, a) -> int:
    best = R._read_json(c.state / "best.json")
    if best.get("metric") is not None:
        sigma, src = float(best.get("sigma") or 0.0), f"baseline ({best.get('noise_runs', c.loop_cfg['noise_runs'])} runs)"
    else:  # not begun: measure, like kl doctor, without logging anything
        if problem := R.workspace_error(c.root, c.workspace):
            raise Refuse(problem)
        runs = []
        for _ in range(3):
            metric, error = _evaluate(c)
            if metric is None:
                raise Refuse(f"evaluate.py failed: {error}")
            runs.append(metric)
        sigma, src = statistics.pstdev(runs), "3 runs just now"
    name, why = level_for(a.stakes, sigma)
    print(f"stakes: {a.stakes} ({STAKES[a.stakes]}); score noise: sigma {sigma:.6f} from {src}")
    print(f"level: {name}")
    print("\n".join(f"  {w}" for w in why))
    print("  always on: lessons (a mistake is never repeated), the fence, the gates, "
          "loop.target and loop.stall_cycles")
    if int(c.loop_cfg["noise_runs"]) < 2:  # an explicit loop.noise_runs: 1 wins over any level
        print(R.UNMEASURED)
    cur = (c.team.get("loop") or {}).get("profile")
    if a.apply:
        _set_profile(c.root / "team.yaml", name)
        print(f"team.yaml: loop.profile {cur or '(none)'} -> {name}"
              + ("; run `" + kl() + " begin --accept-changes` if a fence is set" if (c.state / "fence.json").exists() else ""))
    else:
        print(f"to use it: `{kl()} level --stakes {a.stakes} --apply` (writes loop.profile in team.yaml)"
              + (f"; now: {cur}" if cur else ""))
    return 0


def cmd_doctor(c, a) -> int:
    if problem := R.workspace_error(c.root, c.workspace):
        raise Refuse(problem)
    runs, start = [], time.monotonic()
    for i in range(max(3, a.runs)):
        metric, error = _evaluate(c)
        if metric is None:
            raise Refuse(f"evaluate.py failed on run {i + 1}: {error}")
        runs.append(metric)
    print("\n".join(doctor_text(runs, c.loop_cfg, a.want, (time.monotonic() - start) / len(runs))))
    print("\n".join(unmeasured_loop(R._read_json(c.state / "best.json"), c.loop_cfg, statistics.stdev(runs))))
    print("nothing was logged: kl doctor only measures (the baseline is `" + kl() + " begin`)")
    return 0


def cmd_quickstart(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog=f"{kl()} quickstart", description=(
        "Write a keeploop control folder for your git repo, with an evaluate.py from a "
        "template. Existing files are never overwritten."))
    p.add_argument("template", choices=list(quickstart.TEMPLATES))
    p.add_argument("dir", nargs="?", type=Path, help="default: <repo>-keeploop beside the repo")
    p.add_argument("--workspace", type=Path, help="the repo the loop may change (default: cwd)")
    a = p.parse_intermixed_args(argv[1:])  # DIR may follow --workspace (Python < 3.12 too)
    try:
        print("\n".join(quickstart.quickstart(a.template, a.workspace, a.dir, rewrite=kl() == "kl",
                                              src=scaffold.source())))
    except SystemExit as exc:
        raise Refuse(str(exc).removeprefix("refused: "))
    return 0


def cmd_import_lite(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog=f"{kl()} import-lite", description=(
        "Continue a keeploop-lite chat session in the CLI: LEDGER.md is the saved ledger block."))
    p.add_argument("ledger", type=Path)
    p.add_argument("dir", nargs="?", type=Path, help="a new folder (default: keeploop-from-lite)")
    a = p.parse_args(argv)
    try:
        print("\n".join(quickstart.import_lite(a.ledger, a.dir or Path("keeploop-from-lite"),
                                               rewrite=kl() == "kl", src=scaffold.source())))
    except (SystemExit, OSError) as exc:
        raise Refuse(str(exc).removeprefix("refused: "))
    return 0


COMMANDS = {"begin": cmd_begin, "status": cmd_status, "card": cmd_card, "check": cmd_check,
            "eval": cmd_eval, "audit": cmd_audit, "keep": cmd_keep, "discard": cmd_discard,
            "staff": cmd_staff, "pack": cmd_pack, "report": cmd_report, "slow": cmd_slow, "debate": cmd_debate, "cite": cmd_cite,
            "map": cmd_map, "recall": cmd_recall, "doctor": cmd_doctor, "level": cmd_level, "next": cmd_next,
            "try": cmd_try, "handoff": cmd_handoff, "apply": cmd_apply}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = ROOT if (ROOT / "team.yaml").exists() else Path.cwd()  # pip-installed: the project is cwd
    if argv[:1] == ["--root"] and len(argv) > 1:
        root, argv = Path(argv[1]), argv[2:]
    if argv[:1] == ["init"]:
        try:
            return cmd_init(argv[1:])
        except Refuse as exc:
            print(f"kl: REFUSED: {exc}")
            return 1
    if argv[:1] in (["quickstart"], ["import-lite"]):
        try:
            return cmd_quickstart(argv) if argv[0] == "quickstart" else cmd_import_lite(argv[1:])
        except Refuse as exc:
            print(f"kl: REFUSED: {exc}")
            return 1
    if argv[:1] == ["run"]:  # passthrough: run.py's own parser, the project kl resolved
        return R.main(argv[1:], root=root)
    try:
        if argv[:2] == ["lesson", "share"]:  # a human copies one lesson to the global store
            if len(argv) != 3:
                raise Refuse(f"usage: {kl()} lesson share L-ID")
            c = load(root)
            g = lessons.global_cfg(c.team)
            row = lessons.share(c.state, argv[2], g, c.root.name)
            print(f"shared {argv[2]} as {row['id']} in {lessons.global_store(g)}"
                  + ("" if g["enabled"] else "  (reading it is off: set global_lessons: enabled: "
                                             "true in team.yaml to use shared lessons here)"))
            return 0
        if argv[:1] in (["lesson"], ["scout"]):  # passthrough: their own parsers, '--' intact
            c = load(root)
            return (lessons.main(argv[1:], c.state, c.loop_cfg) if argv[0] == "lesson"
                    else scout.main(argv[1:], c.root))
        a = parser().parse_args(argv)
        return COMMANDS[a.cmd](load(root), a)
    except Refuse as exc:
        print(f"kl: REFUSED: {exc}")
        return 1
    except R.Tampered as exc:
        print("kl: STOPPED, the fence was broken (a human must inspect, then "
              f"`{kl()} begin --accept-changes`):\n  " + "\n  ".join(exc.files[:20]))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
