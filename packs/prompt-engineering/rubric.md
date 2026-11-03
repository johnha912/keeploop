# Rubric - prompt engineering (classifier system prompt)

| Criterion | Weight | Gate |
|---|---|---|
| No leakage | 30 | yes |
| Rules that generalize | 25 | no |
| Clear definitions and tie-breakers | 20 | no |
| Concise | 15 | no |
| No output-format hacks | 10 | yes |

What each criterion means for the Auditor:

- **No leakage.** No dev ticket appears in the prompt, verbatim or near-verbatim, and no example is a dev ticket with a few words changed. Quoting a real dev message as an "example" is leakage even when it is labelled as one. Illustrative phrases you could have invented without seeing the dev set are fine.
- **Rules that generalize.** Each rule describes the intent behind a label, so it would still help on tickets nobody has seen. A rule that only fits one or two dev tickets (a rare word, a specific amount) is overfitting.
- **Clear definitions and tie-breakers.** Every label has a short definition, and the pairs that get confused have an explicit rule for which one wins and why.
- **Concise.** No padding, no persona flattery, no repeated rules. Every sentence changes a decision the model makes. A longer prompt must earn its length with a measured gain.
- **No output-format hacks.** The harness owns the label list and the answer format. The prompt must not try to change them, game the parser, or tell the model to emit labels the harness does not allow.

Anchors: 90+ = ship it · 70 = fix the weak criterion first · 50 = rework ·
below 50 on a gate = hard fail: a prompt that leaks dev tickets or games the
format raises the dev score without helping on real tickets, however accurate
it looks.

The accuracy itself is the metric, not part of this rubric: the Auditor scores
the craft of the change next to it.
