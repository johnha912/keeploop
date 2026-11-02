# questionnaire.md format

`evaluate.py` reads `<workspace>/questionnaire.md`. A full example that
scores 1.0 is `samples/good.md`; `samples/bad.md` scores 0.46.

```
# Any title (ignored)

## Screener                       <- a module; its name is free text
Objective: what this module must find out
Decision: the business decision the answers inform
Analysis: how the answers will be analysed (cross-tab, top-2-box, ...)

1. [single] Question text?        <- number, [type], stem
   Awareness: unaided             <- optional: unaided | aided
   Scale: Very bad | Bad | Neither good nor bad | Good | Very good
   - option                       <- answer options (or grid rows)
```

- Types: `single` and `multi` need at least 2 `- ` options; `open` has none;
  `scale` and `grid` need a `Scale:` line (grid: the `- ` lines are rows).
- `Objective/Decision/Analysis` go directly under the `##` heading, before
  the module's first question. A question belongs to the module above it.
- Scale points are written low to high or high to low, separated by `|`,
  one word label per point. Prefix `unipolar:` for intensity scales
  (`Scale: unipolar: Not at all | Slightly | Moderately | Very | Extremely`);
  they skip the balance check.
- Lines starting with `>` or `<!--` are notes and ignored. Anything else
  that does not match is an error (exit 2 with the line number).
- Name the first module "Screener" and the last "Demographics" (the checks
  look for `screen` and `demograph` in the name).

## What is checked (weights sum to 100)

| Id | Criterion | Wt | Check |
|---|---|---|---|
| O1 | Clear research objectives | 10 | every module has `Objective:` |
| O2 | Clear research objectives | 10 | every question is under a module |
| N1 | Non-leading wording | 15 | no phrase such as "don't you agree", "obviously", "our excellent" |
| N2 | Non-leading wording | 10 | no stem with an ask-verb (satisfied, rate, like, know, use, buy...) joined by "and" |
| S1 | Correct scale choice | 4 | every scale point has a word label (1-5 alone fails) |
| S2 | Correct scale choice | 4 | equal positive and negative points (word lists; neutral points count as neither) |
| S3 | Correct scale choice | 3 | all scales run the same direction |
| S4 | Correct scale choice | 2 | 4 to 7 points |
| S5 | Correct scale choice | 2 | `single` stem has no "select all"; `multi` stem has no "select one" |
| L1 | Correct scale choice | 3 | each `Awareness: aided` list has "None of these" and "Other (specify)" |
| L2 | Correct scale choice | 2 | numeric bands (18-24, 65+, under 18) do not overlap |
| F1 | Logical question flow | 4 | first module is the screener |
| F2 | Logical question flow | 4 | last module is demographics |
| F3 | Logical question flow | 4 | an `unaided` question comes before every `aided` one |
| F4 | Logical question flow | 3 | estimated length within 10 minutes |
| D1 | Decision-ready output | 10 | every module has `Decision:` |
| D2 | Decision-ready output | 10 | every module has `Analysis:` |

Each check scores the share of its items that pass (for example 3 of 4
modules with an objective = 0.75 of its weight). A check with nothing to
test (no scale questions, no aided lists) gets full credit.
Length estimate: single 15 s, multi 25 s, open 45 s, scale 15 s, grid
10 s + 8 s per row; budget `LENGTH_BUDGET_S` (600 s) in `evaluate.py`.

## Known limits

These are word-list heuristics. They catch the clear anti-patterns, not
subtle bias; "and" in a brand name can false-flag N2; balance depends on the
small polarity word lists in `evaluate.py`. A passing score does not mean
respondents will answer well (not validated; see `metric_validation` in
`packs/marketing-research/pack.yaml`).

Self-check (good beats bad, bad input is rejected):
`python examples/marketing-research/evaluate.py --self-check`
