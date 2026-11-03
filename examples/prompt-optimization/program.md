# program.md - the charter (prompt optimization, edit me, human)

This file is the team's standing orders. Every agent reads it before a cycle. Only the
human edits it.

## Mission

Improve `prompt.md`, the system prompt of a banking support-ticket classifier, measured
ONLY by the accuracy `evaluate.py` prints on the visible dev set. A hidden holdout of
the same labels is scored only on the baseline and the final result; no role ever sees
it. A gain that does not carry to the holdout is overfitting, and it will be reported.
The format of `prompt.md` is in `FORMAT.md` next to this file.

## Hypotheses to test

Written as claims the metric can confirm or reject. The Analyst tests these, in order,
before proposing its own.

- A one-line definition for every label beats a bare label list.
- Explicit tie-breakers for the most confused label pairs beat definitions alone.
- A short decision order (first ask what the customer wants, then what went wrong) beats
  per-label rules.
- A longer prompt is not better: cutting a rule that never changes a decision keeps accuracy.

## The experiment contract

1. **Hypothesis first.** Every cycle starts as a card in labelled lines: HYPOTHESIS,
   ALTERNATIVES (at least one competing explanation), CHANGE (the smallest one that
   discriminates), EXPECT, REJECT IF (fixed before the evaluation runs) and MISSING (what
   information would change the decision, or "none"). A card without them is a crash.
2. **Say what you do not know.** A gap goes under MISSING for the human, never a fluent
   guess. Rejected hypotheses are remembered; one is re-proposed only with what is different.
3. **The metric is the truth.** Keep a change only if the metric improves by at least the
   `keep_threshold` in `team.yaml` AND the audit passes.
4. **The evaluation is sacred.** Nobody changes anything outside the workspace
   (`evaluate.py`, `holdout.py`, this charter, `team.yaml`, `.keeploop/`) or any path under
   `protect` (`data`). Copying dev messages into `prompt.md` is leakage: a discard.
5. **Append-only memory.** Never edit or delete a ledger row or a lesson.

## Roles and gates

- **Analyst** reads the per-label breakdown and confusions, then writes one card. No code.
- **Engineer** implements exactly the card by editing `prompt.md`. Nothing else.
- **QC gates** (fence, protected paths, secret scan, diff size) are code, not opinion.
- **Auditor** checks the real diff against the card and the pack rubric (leakage,
  generalization, definitions, concision, format hacks). It never fixes what it audits.

## Craft standards (the pack)

The `prompt-engineering` pack is binding. Hard gates in its rubric do not average out: a
prompt that leaks dev messages or games the format is a discard even if accuracy rises.

## Definition of done

A cycle is done when its row is in `results.tsv`. Nothing is done because someone said so.
