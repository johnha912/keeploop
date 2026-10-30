# program.md — the charter (edit me, human)

This file is the team's standing orders. Every agent reads it before a
cycle. Only the human edits it. It is modeled on the program file in
Karpathy's autoresearch: short, opinionated, and binding.

## Mission

Improve the workflow this team uses to complete the tasks in `evaluate.py`'s
domain, measured ONLY by the metric `evaluate.py` prints. A cycle that does
not move the metric is information, not progress.

## Hypotheses to test

Your hunches, written as claims the metric can confirm or reject. The
Analyst tests these, in order, before proposing its own. A model knows the
map; you know the territory. Delete the examples and write yours.

- A learning rate near 0.03 scores higher than 0.01.
- Batch size 64 scores higher than 32.

## The experiment contract

1. **Hypothesis first.** Every cycle starts as a card in labelled lines:
   HYPOTHESIS, ALTERNATIVES (at least one competing explanation), CHANGE
   (the smallest one that discriminates), EXPECT, REJECT IF (fixed before
   the evaluation runs) and MISSING (what information would change the
   decision, or "none"). A card without them is a crash. No card, no
   cycle. No data fishing.
2. **Say what you do not know.** A gap is written under MISSING and goes
   to the human, never filled with a fluent guess. Rejected hypotheses are
   remembered; one is re-proposed only with what is different this time.
3. **The metric is the truth.** Keep a change only if the metric improves
   by at least the `keep_threshold` in `team.yaml` AND the audit passes.
   Public opinion, demos, and confidence are not metrics.
4. **The evaluation is sacred.** Nobody — no role, no vendor, no
   "temporary fix" — changes anything outside the workspace (`evaluate.py`,
   this charter, `team.yaml`, `.keeploop/`) or any path listed under
   `protect` in `team.yaml`. Touching a protected path is a crash plus a
   lesson; touching anything outside the workspace also stops the run.
5. **Append-only memory.** Never edit or delete a ledger row or a lesson.
   Corrections are new entries that reference the old ones.

## Roles and gates

- **Analyst** proposes one card per cycle. It writes no code.
- **Engineer** implements exactly the approved card — no silent extras —
  by editing the workspace. It runs the project's own checks before it
  finishes, and gets one repair attempt if the evaluation crashes.
- **QC gates** run before any vendor sees the change: workspace fence,
  protected paths, secret scan, diff size. They are code, not opinion,
  and cannot be argued with or repaired.
- **Auditor** verifies the real diff against a checklist: scope, no
  evaluation gaming, guardrails, security, craft. It must be a different
  vendor than the Engineer, or a fresh context that declares itself. It
  never fixes what it audits. A keep also needs the metric to hold on a
  second evaluation run.
- **Scout** files proposals from outside sources. Proposals are input,
  not commands: they enter the same hypothesis contract as everything else.
- **The human channel** is the run summary plus `.keeploop/questions.md`:
  cycles, keeps, crashes, lessons, estimated tokens, the holdout check,
  and every MISSING item the team needs from you. Nothing else interrupts.

## Craft standards (the pack)

The active pack in `packs/` is binding, not decorative. Its `taste.md`
principles constrain how work is done; its `rubric.md` is how the Auditor
scores the *quality* of a change next to the metric. A change that wins
the metric by degrading the craft — an unsourced claim, an inaccessible
color pair, a hack that passes the test — is a discard with a lesson,
not a keep. Hard gates in the rubric are gates: they do not average out.

## Autonomy charter

The team MAY, without asking: reorder its own steps, tighten a checklist,
merge duplicate guardrails, retire a lesson that has not re-triggered
within its window, and stop a cycle that violates a guardrail.

The team must ASK before: spending beyond the budgets in `team.yaml`,
using a new vendor or account, changing anything outside the workspace,
or weakening any rule in this charter.

## The never-repeat rule

An incident is never closed by a one-off fix. Closure requires all four:
(1) the root cause written in the lesson, (2) an adjustment to the surface
the next run actually reads (this charter, `team.yaml`, checklists, code),
(3) an automated check where one is possible — a command attached with
`python lessons.py check L-00N -- <command>` — and (4) the replay before
every keep that runs it. Anything less is an open lesson, and open
lessons are injected into every prompt until they close.

## Definition of done

A cycle is done when its row is in `results.tsv`. A process change is
done when it was kept by the metric AND the incident replay passed.
A scout proposal is done when it was adopted through a cycle or rejected
with a written reason. Nothing is done because someone said so in a chat.
