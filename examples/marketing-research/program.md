# program.md - the charter (consumer insight report, edit me, human)

This file is the team's standing orders. Every agent reads it before a cycle. Only the
human edits it.

## Mission

Improve `report.md`, the consumer insight report for Fieldnote Apparel (brief in
`brief.md`), measured ONLY by the score `evaluate.py` prints (0 to 1, higher is better).
Every number must trace to `data/metrics.json`, every quote to `data/quotes.json`. The
format of `report.md` is in `FORMAT.md` next to this file; the scorer's code is not
shared with the report writer.

The shipped `report.md` already scores 1.000000, the top of the scale: no edit can beat
the keep bar until a human adds a stricter check to `evaluate.py` (`kl begin` warns about
this). To run the cycle from the 0.970000 draft instead, reverse the kept edit first
(README, "How to reproduce").

## Hypotheses to test

Written as claims the metric can confirm or reject. The Analyst tests these, in order,
before proposing its own.

- Dropping or sourcing every claim about who posts on Reddit (age, gender, country) that has neither a number from `data/metrics.json` nor a dated source raises the score.
- The Summary names for the target brand only attributes that module 4 measures for that brand (today "positioned on trend" is tied to Uniqlo, not Zara).
- Writing each brand comparison as one bullet per brand, never two brands on one line, lets the claim-binding check test every number without losing a finding.
- A gap between two shares whose 95% intervals overlap is reported as "no measured difference", never as a lead or a skew.
- A Recommendation that names one first action for Fieldnote and the survey question that would confirm it beats a list of options.

## The experiment contract

1. **Hypothesis first.** Every cycle starts as a card in labelled lines: HYPOTHESIS,
   ALTERNATIVES (at least one competing explanation), CHANGE (the smallest one that
   discriminates), EXPECT, REJECT IF (fixed before the evaluation runs) and MISSING (what
   information would change the decision, or "none"). A card without them is a crash.
2. **Say what you do not know.** A gap goes under MISSING for the human, never a fluent
   guess. Rejected hypotheses are remembered; one is re-proposed only with what is different.
3. **The metric is the truth.** Keep a change only if the score improves by at least the
   `keep_threshold` in `team.yaml` AND the audit passes.
4. **The evaluation is sacred.** Nobody changes anything outside the workspace
   (`evaluate.py`, this charter, `team.yaml`, `.keeploop/`) or any path under `protect`
   (`brief.md`, `data`). Rewriting the objectives or the evidence to fit the report is a
   discard.
5. **Append-only memory.** Never edit or delete a ledger row or a lesson.

## Roles and gates

- **Analyst** reads the per-check breakdown (`python evaluate.py <workspace>` prints it on
  stderr) and `data/metrics.json`, then writes one card. No edits.
- **Engineer** implements exactly the card by editing `report.md`. Nothing else.
- **QC gates** (fence, protected paths, secret scan, diff size) are code, not opinion.
- **Auditor** checks the real diff against the card, the data and the pack rubric
  (objectives, non-leading evidence, measure choice, logical flow, decision-ready output).
  It never fixes what it audits.

## Craft standards (the pack)

The `marketing-research` pack is binding. A number that is not in the analysis output, a
share without its base, a proxy presented as the real measure or the most extreme quote
passed off as typical is a discard even if the score rises.

## Definition of done

A cycle is done when its row is in `results.tsv`. Nothing is done because someone said so.
