"""kl.py - deterministic tools for the AI you already use (Claude Code, Codex,
Gemini CLI, Cursor, Copilot, ...). keeploop is not an AI: your AI is the CEO and
reads AGENTS.md; kl only measures, gates, records and refuses. Stdlib only, and
every command except `kl audit --vendor` runs with no AI CLI installed.

    python kl.py begin                  baseline, noise, fence snapshot
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
    python kl.py pack add SOURCE        import a pack from a link or a name, as a DRAFT
    python kl.py pack approve NAME      human-only: re-run the gates, draft -> active
    python kl.py pack list              packs with status and source

HONEST LIMIT: in interactive mode the user's AI has the same file rights as kl.
The fence snapshot and the best.json seal in .keeploop/ are TAMPER-EVIDENT (a
changed evaluate.py, charter, team.yaml or best.json is detected and refused),
not tamper-proof: an agent that rewrites the snapshot too is not stopped. Use
the headless run.py, or an OS-level sandbox, when that matters.

Exit codes: 0 ok, 1 refused (reason printed), 2 fence broken.
"""

import sys

sys.dont_write_bytecode = True  # a .pyc written under the project would trip the fence

import argparse
import contextlib
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
import packimport
import packs
import rubric as rubric_mod
import run as R
import scout
import vendors
from prepare import ROOT, load_team, setup


class Refuse(Exception):
    pass


def kl() -> str:
    """How the user types this tool: `kl` when pip-installed, else `python kl.py`."""
    # PureWindowsPath splits on both "/" and "\", so a Windows-style argv0
    # (C:\Scripts\kl.exe) is recognised on Linux/macOS too, not only on Windows.
    return "kl" if PureWindowsPath(sys.argv[0]).name.lower() in ("kl", "kl.exe") else "python kl.py"


# --- context and state ------------------------------------------------------

def load(root: Path, need_pack: bool = True) -> SimpleNamespace:
    """need_pack=False (the `pack` commands): a draft pack selected in team.yaml
    is tolerated, so `kl pack approve` can still run."""
    root = root.resolve()
    with contextlib.redirect_stdout(io.StringIO()):
        state = setup(root)
    try:
        cfg = R.project_config(root)
    except ValueError as exc:
        raise Refuse(str(exc))
    c = SimpleNamespace(root=root, state=state, **cfg)
    c.roles = c.team.get("roles") if isinstance(c.team.get("roles"), dict) else {}
    try:
        c.pack = packs.load_pack(root, c.team.get("pack", "software"))
    except packs.DraftPack as exc:
        if need_pack:
            raise Refuse(str(exc))
        c.pack = None
    c.criteria = rubric_mod.load_rubric(c.pack["rubric_path"]) if c.pack else None
    return c


def _sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def _json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _snap(c) -> dict:
    """R.fingerprint minus what kl itself writes (.keeploop/), bytecode, and the
    root .git churn that `git status` causes (config/hooks/info stay covered)."""
    keep_git = (".git/config", ".git/hooks/", ".git/info/")
    return {k: v for k, v in R.fingerprint(c.root, c.workspace).items()
            if not k.startswith(".keeploop/") and "__pycache__/" not in k
            and (not k.startswith(".git/") or k.startswith(keep_git))}


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
                                                  c.loop_cfg["eval_timeout_s"]))


def _gates(c, best):
    changed, diff, heavy, fail = R.qc_gates(c.workspace, best["commit"], c.protect,
                                            c.heavy_globs, c.loop_cfg, packs.slop_rules(c.pack))
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


def cmd_card(c, a) -> int:
    best = _best(c)
    text = sys.stdin.read() if a.file == "-" else Path(a.file).read_text(encoding="utf-8")
    if "card" in _cycle(c):
        raise Refuse(f"card {_cycle(c)['n']} is still open: `kl keep` or `kl discard` it first")
    if _dirty(c):
        raise Refuse(f"workspace has uncommitted changes: run `{kl()} discard` first")
    n = _next_cycle(c)
    parsed = R.parse_card(text)
    if not parsed:
        lid = _learn(c, R.L_NO_CARD, n)
        _row(c, n, "crash", None, lid, "card is not in the labelled format", best=best)
        raise Refuse("card needs HYPOTHESIS, CHANGE, REJECT IF and MISSING (label: text); "
                     f"logged as {lid}")
    _vet(c, parsed, n, best)
    _put(c, n=n, card=text, parsed=parsed, fail=None, metric=None, t0=time.time())
    print(f"card {n} registered")
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
    _fence_check(c)
    changed, diff, heavy, fail = _gates(c, best)
    if fail:
        _put(c, fail=list(fail))
        print(f"FAIL {fail[1]}")
        return 1
    _put(c, fail=None)
    print(f"PASS tier={'heavy' if heavy else 'light'} files={len(changed)} "
          f"lines={R.diff_size(c.workspace)} diff={hashlib.sha256(diff.encode()).hexdigest()[:12]}")
    return 0


def cmd_eval(c, a) -> int:
    best = _best(c)
    _fence_check(c)
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


def cmd_audit(c, a) -> int:
    best = _best(c)
    cy = _cycle(c)
    if "card" not in cy:
        raise Refuse("no registered card: `kl card` first")
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
        prompt = R.audit_prompt(
            cy["card"], diff, metric, best["metric"],
            f"{lessons.guardrails_text(c.state, cfg=c.loop_cfg)}\n\nCraft standards:\n{(c.pack or {}).get('taste', '')}",
            c.criteria, packs.specialists_text(c.pack), heavy)
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
    _fence_check(c)
    changed, diff, heavy, fail = _gates(c, best)
    if fail:
        _stop_on_fail(c, fail)
    if (heavy or R.declared_heavy(parsed, c.heavy_globs)) and "## Critique" not in (
            (c.state / "debate" / f"{n}.md").read_text(encoding="utf-8")
            if (c.state / "debate" / f"{n}.md").exists() else ""):
        print("kl: warning: heavy card kept without a recorded critique (kl debate); "
              "not blocking, the metric and the audit still decide")
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
            raise Refuse("audit verdict is missing its `DIFF: <id>` line (printed by `kl check`) "
                         "or is for a different diff: audit again")
        if not R.approved(text):
            _stop_on_fail(c, ("discard", "audit: " + " ".join(text.split())[:80], R.L_AUDIT))
        rscore = rubric_mod.reply_score(vendors.Vendor(), c.criteria, text)
        if R.rubric_regressed(rscore, best):
            raise Refuse(f"rubric regressed from {best['rubric']:.0f} to {rscore:.0f}")
    elif heavy:
        raise Refuse("heavy change: needs --audit-verdict FILE (an APPROVED audit of this diff)")
    if R.needs_confirm(heavy, c.loop_cfg, best.get("sigma") or 0.0):
        metric2, error = _timed(c, "confirm_s", lambda: _evaluate(c))
        if metric2 is None or not metric2 > bar:
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
    R.record_hypothesis(c.state, n, parsed, "supported", metric, before)
    _log_time(c, n)
    _row(c, n, "keep", metric, "", f"card: {card1[:90]} | verdict: supported | tier: "
         f"{'heavy' if heavy else 'light'}", a.tokens, best)
    _clear(c)
    print(f"KEPT cycle {n}: metric {metric:.6f} (bar {bar:.6f}); best is now {best['metric']:.6f}")
    return 0


def cmd_discard(c, a) -> int:
    best = _best(c)
    _fence_check(c)  # never run git in a workspace whose config may be poisoned
    cy = _cycle(c)
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
    notes += ([fail[1]] if fail else []) + ([f"discard: {a.reason}"] if a.reason else [])
    if "card" in cy:
        verdict = R.verdict_of(status, metric, _bar(c, best))
        notes.insert(1, f"verdict: {verdict}")
        R.record_hypothesis(c.state, n, cy["parsed"], verdict, metric, best["metric"])
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
              "becomes noisy later goes unmeasured.")
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
    if a.action == "list":
        print("\n".join(packimport.listing(c.root)))
        return 0
    if not a.name:
        raise Refuse(f"`{kl()} pack {a.action}` needs " + ("a source (https URL or name)"
                                                            if a.action == "add" else "a NAME"))
    if a.action in ("add", "approve"):
        slop, cap = packs.slop_rules(c.pack), c.loop_cfg.get(
            "guardrail_max_chars", packimport.CONFIG["guardrail_max_chars"])
        try:
            lines = (packimport.add(c.root, c.state, a.name, a.as_name, slop=slop, cap=cap)
                     if a.action == "add" else
                     packimport.approve(c.root, c.state, a.name, slop=slop, cap=cap))
        except packimport.ImportRefused as exc:
            raise Refuse(f"pack {a.action}: {exc}")
        print("\n".join(lines))
        return 0
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
    s.add_argument("--tokens", type=int, default=0)
    s = sub.add_parser("debate", help="record the one critic round of a heavy card")
    s.add_argument("card_id", type=int)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--critic", metavar="FILE")
    g.add_argument("--reply", metavar="FILE")
    s = sub.add_parser("report", help="run facts from the ledger (paste verbatim)")
    s.add_argument("--assert-cycle-under", type=float, metavar="SECONDS",
                   help="exit 1 if the last cycle took longer (a lesson check)")
    sub.add_parser("cite", help="opt-in, network: dead links and quotes missing from pages").add_argument("file")
    sub.add_parser("lesson", help="add | check | review | list (see lessons.py)")
    sub.add_parser("scout", help="trend scout (see scout.py)")
    s = sub.add_parser("staff", help="staffing proposal")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--goal", choices=["balanced", "speed", "quality", "cost"], default="balanced")
    sub.add_parser("slow", help="why is it slow: bottleneck phase, levers, lesson commands")
    s = sub.add_parser("map", help="cached code index; --query NAME: defs, importers, memory")
    s.add_argument("--query")
    s = sub.add_parser("recall", help="BM25 over lessons, hypotheses, debates, questions, ledger")
    s.add_argument("query")
    s.add_argument("--top", type=int, default=5)
    s = sub.add_parser("pack", help="pack new NAME | add SOURCE [--name N] | approve NAME | list")
    s.add_argument("action", choices=["new", "add", "approve", "list"])
    s.add_argument("name", nargs="?", help="pack name, or for `add` an https URL or a bare name")
    s.add_argument("--name", dest="as_name", help="add: the pack folder name (default: from the source)")
    return p


COMMANDS = {"begin": cmd_begin, "status": cmd_status, "card": cmd_card, "check": cmd_check,
            "eval": cmd_eval, "audit": cmd_audit, "keep": cmd_keep, "discard": cmd_discard,
            "staff": cmd_staff, "pack": cmd_pack, "report": cmd_report, "slow": cmd_slow, "debate": cmd_debate, "cite": cmd_cite,
            "map": cmd_map, "recall": cmd_recall}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = ROOT if (ROOT / "team.yaml").exists() else Path.cwd()  # pip-installed: the project is cwd
    if argv[:1] == ["--root"] and len(argv) > 1:
        root, argv = Path(argv[1]), argv[2:]
    try:
        if argv[:1] in (["lesson"], ["scout"]):  # passthrough: their own parsers, '--' intact
            c = load(root)
            return (lessons.main(argv[1:], c.state, c.loop_cfg) if argv[0] == "lesson"
                    else scout.main(argv[1:], c.root))
        a = parser().parse_args(argv)
        return COMMANDS[a.cmd](load(root, need_pack=a.cmd != "pack"), a)
    except Refuse as exc:
        print(f"kl: REFUSED: {exc}")
        return 1
    except R.Tampered as exc:
        print("kl: STOPPED, the fence was broken (a human must inspect, then "
              f"`{kl()} begin --accept-changes`):\n  " + "\n  ".join(exc.files[:20]))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
