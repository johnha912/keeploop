# program.md - the charter (noisy-eval example, edit me, human)

## Mission

Raise the accuracy that `evaluate.py` prints for the question-answering pipeline in
`config.json`. The evaluation is noisy on purpose: every call scores a random 1,000 of
10,000 dev cases, so the same config scores a little differently each time. A change
that beats the best by less than the noise is not evidence; keep only what clears the
keep bar.

## Hypotheses to test

- Few-shot examples in the prompt raise accuracy.
- Reranking the retrieved passages raises accuracy.

## The experiment contract

1. **Hypothesis first.** Every cycle starts as a card in labelled lines (HYPOTHESIS,
   ALTERNATIVES, CHANGE, EXPECT, REJECT IF, MISSING). No card, no cycle.
2. **The metric is the truth, measured against its own noise.** Keep a change only if
   it beats the best by more than the keep bar in `team.yaml` and the confirm re-run
   agrees.
3. **The evaluation is sacred.** Only `config.json` in the workspace may change.
