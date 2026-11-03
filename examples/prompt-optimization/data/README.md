# Data: Banking77 subset

- **Source:** Banking77, PolyAI, test split.
  https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/test.csv
- **License:** CC BY 4.0. Attribution: Casanueva et al., "Efficient Intent Detection with
  Dual Sentence Encoders" (2020), PolyAI. Messages are shown unchanged apart from trimmed
  whitespace and a shuffled order.
- **Intents (10), chosen by a rule written before any scoring:** every top-up, transfer and
  cash-withdrawal intent whose name states a status (failed, reverted, pending, declined,
  not received) or timing. The rule gives exactly 10: `declined_cash_withdrawal`,
  `declined_transfer`, `failed_transfer`, `pending_cash_withdrawal`, `pending_top_up`,
  `pending_transfer`, `top_up_failed`, `top_up_reverted`,
  `transfer_not_received_by_recipient`, `transfer_timing`. They are near-duplicates of each
  other (the same money movement, a different state), so a bare label list confuses the model.
- **Selection rule:** the test split has 40 messages per intent. Per intent, sort them,
  shuffle with `random.Random("77:<intent>")`, then the first 20 go to `dev.jsonl` and the
  next 20 to `holdout.jsonl` (disjoint, 200 items each). Each file is then shuffled with a
  fixed seed so a batch of 25 is not one label. Seed: 77. Rebuild with
  `python -X utf8 prepare_data.py` (the raw CSV is downloaded to a temp folder, not the
  repo); the output is byte-for-byte reproducible.
- **Files:** `dev.jsonl` (visible to the team by design) and `holdout.jsonl` (never shown to a
  prompt; the loop's `holdout.py` reads a copy kept outside the workspace).

## Sets tried and their baselines

Baseline prompt: `You classify banking customer messages into one of the given labels.`
Scored with the shipped `evaluate.py` and `holdout.py` through `run.evaluate_workspace`.
These are setup measurements taken before the loop started. They were reported by hand
and are not saved as log files in this example; the loop's own numbers are in `../run/`.

| Set | Size (dev + holdout) | Dev baseline | Holdout baseline | Outcome |
|---|---|---|---|---|
| 1. Hand-picked card/transfer/refund intents (`card_arrival`, `card_delivery_estimate`, `lost_or_stolen_card`, `card_not_working`, `declined_card_payment`, `pending_card_payment`, `card_payment_fee_charged`, `request_refund`, `transfer_not_received_by_recipient`, `balance_not_updated_after_bank_transfer`) | 100 + 100 | 0.89 to 0.93 (7 runs, mean 0.909) | 0.85 to 0.88 (5 runs) | dropped: headroom below the keep bar |
| 2. The status-intent rule above (the current set) | 200 + 200 | 0.875, 0.860, 0.880 (mean 0.8717, sigma 0.0085) | 0.810 (1 run) | kept: the hardest reasonable set by the rule; no further search |

With set 2 the keep bar is `best + max(best * 0.01, 2 * sigma)` = 0.8887, about 0.017 above
the mean baseline. Set 1 was tried first with scorer variants whose output format crashed;
only the runs with the shipped scorer are listed.

## Limit

The workspace fence stops a vendor CLI from writing outside the workspace, not from reading
files outside it. A role CLI could technically read `holdout.jsonl` at the keeploop root.
Nothing in this setup prevents that; the Auditor rubric (no leakage) and the holdout gain
check are the defenses.
