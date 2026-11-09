---
name: keeploop
description: Run N keeploop cycles as the CEO: analyst card, engineer edit, deterministic gates, evaluation, audit, keep or discard through kl.py. Use when the user says /keeploop or asks to improve the workspace with the keeploop loop.
---
# /keeploop [N]

You are the CEO. AGENTS.md is the full procedure; its "Fast path" section is all a routine cycle needs. Run N cycles (default 3).

0. Worked example? `python tools/make_sandbox.py examples/<name> <new short folder>`, then work from the folder it prints.
1. `python kl.py begin` once if `kl next` says "not started". Optionally `python kl.py scout` once per session.
2. For each cycle:
   - `python kl.py next`. A `STOP:` line: go to step 4. A pending card: `python kl.py try` finishes it, or `python kl.py discard`.
   - Analyst (subagent `keeploop-analyst`, or yourself for a simple card): fill the skeleton `kl next` printed; save it to a temp file outside the repo.
   - Engineer (subagent `keeploop-engineer`, or yourself): implement exactly the card in the workspace.
   - `python kl.py try FILE`. Exit 0 kept, 4 discarded, 1 refused (fix the reason, run it again; never bypass).
   - Exit 3: it prints the next command. Heavy card: Critic (subagent `keeploop-critic`), `python kl.py debate N --critic FILE`, `python kl.py try`. Audit required (heavy change, or a gain that is not decisive): Auditor (subagent `keeploop-auditor`, fresh context) with the card, the workspace `git diff`, the metric and the `DIFF:` id from the WAIT line; save its reply, then `python kl.py try --audit-verdict FILE`.
   - Any refusal or user correction: `python kl.py lesson add ...` (with a check command when possible). Gate failures and crashes already got their lesson from `kl try`.
3. Every ~5 cycles: `python kl.py staff`. Asked only where things stand? Measure and report; run no cycle.
4. Finish with `python kl.py report` and paste its output verbatim into your reply. Quote no number from memory.

Never commit by hand, never edit protected paths, evaluate.py, program.md, team.yaml or .keeploop/. Put every unknown under MISSING.
