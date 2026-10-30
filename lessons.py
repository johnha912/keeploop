"""lessons.py — the never-repeat engine.

Implements the standing incident protocol as code. A failure becomes a
*closed* lesson only after all four steps:

    1. root cause recorded honestly          -> lesson.what / lesson.root_cause
    2. the surface the next run reads is adjusted -> guardrail text, injected
       into every future prompt via guardrails.md
    3. an automated check where possible     -> lesson.check: an argv list run
       inside the workspace (exit 0 = pass)
    4. the check is verified live            -> the loop replays all active
       checks against every candidate before a keep is finalized

Storage: `.keeploop/lessons.jsonl`, append-only, one JSON object per line.
Lesson rows are never rewritten; later `{"event": "retrigger"|"check", ...}`
lines are folded into them on load. A repeat of an active guardrail is a
retrigger event (no duplicate lesson) and extends the lesson's life.
Guardrails: `.keeploop/guardrails.md`, regenerated from active lessons,
capped at CONFIG["guardrail_max_chars"].

Security: a check command comes only from a human at this CLI. Lessons the
loop records on its own never carry a command, so no command ever
originates from vendor or web output.

CLI:  python lessons.py list
      python lessons.py add "<what>" "<root cause>" "<guardrail>" [-- cmd ...]
      python lessons.py check L-001 -- cmd ...
      python lessons.py review       (status of each lesson, derived from the ledger)

Status (derived, never stored): enforced = has a check (not injected into
prompts: the check runs on every keep); ineffective = re-triggered and has no
check, so the text did not work; effective = CONFIG lesson_effective_after
clean cycles since creation; provisional = anything else.
"""

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import bm25
import ledger
import vendors
from prepare import CONFIG, STATE_DIR


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append(state_dir: Path, row: dict) -> None:
    with (state_dir / "lessons.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_lessons(state_dir: Path = STATE_DIR) -> list[dict]:
    """Lesson rows with event lines folded in (adds `last_ts`)."""
    path = state_dir / "lessons.jsonl"
    if not path.exists():
        return []
    by_id, out = {}, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        event = row.get("event")
        if event is None:
            row["last_ts"] = row["ts"]
            row["retriggers"] = 0
            by_id[row["id"]] = row
            out.append(row)
        elif row.get("id") in by_id:
            if event == "retrigger":
                by_id[row["id"]]["last_ts"] = max(by_id[row["id"]]["last_ts"], row["ts"])
                by_id[row["id"]]["retriggers"] += 1
            elif event == "check":
                by_id[row["id"]]["check"] = row.get("check")
    return out


def active_lessons(state_dir: Path = STATE_DIR, cfg: dict = CONFIG) -> list[dict]:
    """Lessons still enforced: status=active and re-triggered inside the window.
    `cfg` is the project's merged config (team.yaml `loop:` overrides)."""
    now = datetime.now(timezone.utc)
    return [l for l in load_lessons(state_dir) if l.get("status") == "active"
            and (now - datetime.fromisoformat(l["last_ts"])).days
            <= cfg["lesson_retire_after_days"]]


def retrigger(state_dir: Path, lesson_id: str) -> None:
    _append(state_dir, {"event": "retrigger", "id": lesson_id, "ts": _now()})


def attach_check(state_dir: Path, lesson_id: str, argv: list[str], cfg: dict = CONFIG) -> None:
    _append(state_dir, {"event": "check", "id": lesson_id, "ts": _now(),
                        "check": argv})
    render_guardrails(state_dir, cfg)  # an enforced lesson leaves the prompts


def enforced(lesson: dict) -> bool:
    """True when the lesson has a check, which replay() runs on every keep."""
    return isinstance(lesson.get("check"), list) and bool(lesson["check"])


def status_of(lesson: dict, rows: list[dict], cfg: dict = CONFIG) -> tuple[str, int]:
    """(status, clean cycles since creation), derived on demand: the log is append-only.

    enforced: has a check. ineffective: re-triggered, no check (the text did not
    stop it). effective: `lesson_effective_after` ledger cycles since creation
    with no re-trigger. provisional: anything else. Rows that carry the lesson's
    own id (its creation and re-triggers) are not clean cycles.
    """
    since = sum(1 for r in rows if int(r["cycle"]) >= 1 and r["ts"] > lesson["ts"]
                and r.get("lesson_id") != lesson["id"])
    if enforced(lesson):
        return "enforced", since
    if lesson.get("retriggers"):
        return "ineffective", since
    return ("effective" if since >= cfg["lesson_effective_after"] else "provisional"), since


def review(state_dir: Path = STATE_DIR, cfg: dict = CONFIG) -> list[dict]:
    """Active lessons with `standing` (the derived status) and `since` added."""
    rows = ledger.read_rows(state_dir)
    out = []
    for l in active_lessons(state_dir, cfg):
        standing, since = status_of(l, rows, cfg)
        out.append({**l, "standing": standing, "since": since})
    return out


def hint(lesson_id: str) -> str:
    return f"attach a check: python lessons.py check {lesson_id} -- <cmd>"


def record(state_dir: Path, *, what: str, root_cause: str, guardrail: str,
           trigger_cycle: int | None, check: list[str] | None = None,
           cfg: dict = CONFIG) -> dict:
    """Append a lesson (or retrigger the active one with this guardrail)."""
    for lesson in active_lessons(state_dir, cfg):
        if lesson["guardrail"] == guardrail:
            retrigger(state_dir, lesson["id"])
            return lesson
    lesson = {
        "id": f"L-{len(load_lessons(state_dir)) + 1:03d}",
        "ts": _now(),
        "trigger_cycle": trigger_cycle,
        "what": what,
        "root_cause": root_cause,
        "guardrail": guardrail,
        "check": check,
        "status": "active",
        "retired_ts": None,
    }
    _append(state_dir, lesson)
    render_guardrails(state_dir, cfg)
    return lesson


def render_guardrails(state_dir: Path = STATE_DIR, cfg: dict = CONFIG) -> Path:
    """Regenerate guardrails.md from active lessons, within the char cap."""
    lines = ["# Guardrails",
             "",
             "(generated from active lessons by lessons.py — do not edit by hand)",
             ""]
    for lesson in active_lessons(state_dir, cfg):
        if not enforced(lesson):  # a check already enforces it; keep prompts short
            lines.append(f"- **{lesson['id']}**: {lesson['guardrail']}")
    text = "\n".join(lines) + "\n"
    cap = cfg["guardrail_max_chars"]
    if len(text) > cap:  # compaction: keep the newest lessons that fit
        kept = lines[:3]
        for line in reversed(lines[3:]):
            if len("\n".join(kept + [line])) <= cap:
                kept.insert(3, line)
        text = "\n".join(kept) + "\n"
    path = state_dir / "guardrails.md"
    path.write_text(text, encoding="utf-8")
    return path


def replay(state_dir: Path, workspace: Path, cfg: dict = CONFIG) -> list[tuple[str, str]]:
    """Run every active lesson's check in the workspace; return failures.

    Step 4 of the protocol: proof the guardrail still holds. A missing
    binary, a timeout or a nonzero exit all count as failure. The checks run
    untrusted workspace code with no secrets in the environment; run.py calls
    this inside the same fence as the vendors.
    """
    failures = []
    for lesson in active_lessons(state_dir, cfg):
        argv = lesson.get("check")
        if not isinstance(argv, list) or not argv:
            continue
        try:
            binary = shutil.which(argv[0])
            if binary is None:
                raise FileNotFoundError(argv[0])
            proc = subprocess.run([binary, *argv[1:]], cwd=workspace,
                                  capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=cfg["eval_timeout_s"],
                                  env=vendors.safe_env())
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append((lesson["id"], f"check could not run: {exc}"))
            continue
        if proc.returncode != 0:
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or [""]
            failures.append((lesson["id"], f"check {argv} exited "
                                           f"{proc.returncode}: {tail[0][:100]}"))
    return failures


def guardrails_text(state_dir: Path = STATE_DIR, query: str = "", k: int = 0,
                    cfg: dict = CONFIG) -> str:
    """guardrails.md, or (more than k open lessons and a query) only the k most relevant.
    Enforced lessons are never injected; their checks still run on every replay."""
    path = state_dir / "guardrails.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    open_l = [l for l in active_lessons(state_dir, cfg) if not enforced(l)]
    if not (k and query.strip() and len(open_l) > k):
        return text
    rows = [{**l, "_text": f"{l['what']} {l['root_cause']} {l['guardrail']}"} for l in open_l]
    top = [r for _, r in bm25.bm25_rank(query, rows)[:k]]
    head = f"# Guardrails (top {k} relevant of {len(open_l)} open)\n\n"
    return head + "\n".join(f"- **{r['id']}**: {r['guardrail']}" for r in top) + "\n"


def memory_rows(state_dir: Path = STATE_DIR) -> list[dict]:
    """Everything the team remembers, one searchable row each: kind, ref, _text."""
    rows = [{"kind": "lesson", "ref": l["id"], "_text": f"{l['what']} {l['root_cause']} "
             f"{l['guardrail']}"} for l in load_lessons(state_dir)]
    hyp = state_dir / "hypotheses.jsonl"
    for line in (hyp.read_text(encoding="utf-8").splitlines() if hyp.exists() else []):
        h = json.loads(line) if line.strip() else None
        if h:
            rows.append({"kind": "hypothesis", "ref": f"cycle {h.get('cycle')}", "_text":
                         f"{h.get('hypothesis', '')} {h.get('change', '')} [{h.get('verdict', '')}]"})
    for p in sorted((state_dir / "debate").glob("*.md")):
        rows.append({"kind": "debate", "ref": p.name, "_text": p.read_text(encoding="utf-8")})
    q = state_dir / "questions.md"
    rows += [{"kind": "question", "ref": "questions.md", "_text": t}
             for t in (q.read_text(encoding="utf-8").splitlines() if q.exists() else []) if t.strip()]
    rows += [{"kind": "ledger", "ref": f"cycle {r['cycle']}", "_text": f"{r['description']} "
              f"[{r['status']}]"} for r in ledger.read_rows(state_dir)]
    return rows


def recall(state_dir: Path, query: str, top: int = 5) -> list[tuple[float, dict]]:
    return [(s, r) for s, r in bm25.bm25_rank(query, memory_rows(state_dir)) if s > 0][:top]


def main(argv: list[str], state: Path | None = None, cfg: dict = CONFIG) -> int:
    state = state or STATE_DIR
    cut = argv.index("--") if "--" in argv else len(argv)
    args, cmd = argv[:cut], argv[cut + 1:]
    if args[:1] == ["review"]:
        for l in review(state, cfg):
            print(f"{l['id']}  [{l['standing']}]  re-triggered {l['retriggers']}x, "
                  f"{l['since']} cycles since creation  {l['what']}")
            if l["standing"] == "ineffective":
                print(f"      {hint(l['id'])}")
    elif args[:1] in ([], ["list"]):
        for lesson in load_lessons(state):
            print(f"{lesson['id']}  [{lesson['status']}]  {lesson['what']}")
            print(f"      guardrail: {lesson['guardrail']}")
            if lesson.get("check"):
                print(f"      check: {lesson['check']}")
    elif args[0] == "add" and len(args) == 4:
        lesson = record(state, what=args[1], root_cause=args[2],
                        guardrail=args[3], trigger_cycle=None, check=cmd or None, cfg=cfg)
        print(f"recorded {lesson['id']}")
    elif args[0] == "check" and len(args) == 2 and cmd:
        attach_check(state, args[1], cmd, cfg)
        print(f"check attached to {args[1]}")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
