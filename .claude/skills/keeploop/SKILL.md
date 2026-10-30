---
name: keeploop
description: Run N keeploop cycles as the CEO: analyst card, engineer edit, deterministic gates, evaluation, audit, keep or discard through kl.py. Use when the user says /keeploop or asks to improve the workspace with the keeploop loop.
---
# /keeploop [N]

You are the CEO. Read AGENTS.md first; it is the full procedure. Run N cycles (default 3).

1. `python kl.py begin` once if `kl status` says "not started". Optionally `python kl.py scout` once per session.
2. For each cycle:
   - `python kl.py status`
   - Analyst (subagent `keeploop-analyst`): get the card, save it to a temp file, `python kl.py card FILE`. If refused, fix the card or log a lesson; do not bypass.
   - Engineer (subagent `keeploop-engineer`): implement the card.
   - `python kl.py check`, then `python kl.py eval`.
   - If it beats the bar: Auditor (subagent `keeploop-auditor`, fresh context) is required for a heavy tier and optional for a light, decisive one. Save its reply to a file.
   - `python kl.py keep [--audit-verdict FILE]`, or `python kl.py discard --reason "..."`.
   - Any crash, refusal or correction: `python kl.py lesson add ...` (with a check command when possible).
3. Every ~5 cycles: `python kl.py staff`.
4. Finish with `python kl.py report` and paste its output verbatim into your reply. Quote no number from memory.

Never commit by hand, never edit protected paths, evaluate.py, program.md, team.yaml or .keeploop/. Put every unknown under MISSING.
