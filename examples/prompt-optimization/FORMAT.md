# Format of prompt.md

This is the only spec the Engineer gets about the scorer. The scorer's code is not shared.
Workspace files: `prompt.md` (yours to edit) and `data/dev.jsonl` (read-only, protected).

## What prompt.md is

- The SYSTEM prompt of a small language model that classifies banking customer messages.
- The caller adds the rest: the allowed label list, the numbered messages, and the answer
  format (a JSON object of labels). Do not repeat or change those; say how to decide.
- Plain text or Markdown, not empty, at most 6000 characters. A missing, empty or longer file
  is invalid and scores nothing.

## What is scored

- Accuracy on the dev set: one label per message, exact match with the true label. A label
  outside the allowed list counts as wrong.
- `data/dev.jsonl` has one `{"text": ..., "label": ...}` per line. You may read it to learn
  which labels get confused. Quoting dev messages in prompt.md is leakage and fails the audit.

## Rules

- Edit only `prompt.md`. The scorer, the holdout and `data/` are off limits.
- Describe intent and tie-breakers; do not paste dev messages or lightly reworded copies.
- Do not try to change the output format or to steer the parser.
