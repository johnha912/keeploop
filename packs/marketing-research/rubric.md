# Rubric - marketing research (consumer insight report)

| Criterion | Weight | Gate |
|---|---|---|
| Clear research objectives (each module states its business question and the decision it informs) | 20 | yes |
| Non-leading, unbiased evidence (neutral search terms, every brand measured the same way, quotes chosen by a stated rule, headlines no stronger than the data) | 25 | yes |
| Correct measure choice (the right metric for the question, proxies named as proxies, base size and confidence interval on every share, no share reported on a base under 30) | 20 | no |
| Logical flow (answer first, modules in funnel order: awareness, penetration, profile, positioning, perception, segmentation; method and limits after the findings) | 15 | no |
| Decision-ready insight output (each module ends in a so-what and a recommendation for the client) | 20 | no |

Anchors: 90+ = could go to the client · 70 = fix the weak criterion first ·
50 = rework · below 50 on a gate = hard fail: a report without clear
objectives, or with cherry-picked or leading evidence, gives a decision
nobody can trust, however polished it looks.

Hard rule outside the weights: every number in the report must exist in
the analysis output (`data/metrics.json`). A report with one untraceable
number is invalid, not low-scoring; the scorer exits 2.

The weights above match `examples/marketing-research/evaluate.py`, which
scores each check against one criterion (see `FORMAT.md` there).
