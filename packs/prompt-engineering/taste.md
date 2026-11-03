# Taste - prompt engineering (classifier system prompt)

- **Read the errors first.** Start from the confusion summary: which label
  pairs are mixed up, and why. A prompt change without a named confusion is a
  guess.
- **Define by intent.** One short line per label says what the customer is
  trying to do or what went wrong, not which words they use.
- **Tie-breakers for confusable pairs.** When two labels overlap, say which
  wins and the test that decides it ("the card never arrived" versus "the card
  arrived but does not work").
- **No leakage.** Never paste a dev ticket, or a lightly reworded one, into
  the prompt. Write illustrative phrases you could have made up blind.
- **Generalize.** A rule must plausibly help on tickets you have not seen. If
  it only fixes one dev ticket, it is memorization.
- **Short beats long.** Every sentence must change a decision. Cut repeated
  rules, flattery and personas. Add length only when a measured gain pays for
  it.
- **The harness owns the format.** Labels, ordering and the answer shape are
  supplied by the caller. The prompt describes how to decide, not how to print.
- **One idea per change.** Edit one rule or one definition per cycle so a gain
  or a loss has one cause.
- **Distrust small gains.** With 200 items one item is 0.005. A gain of a few
  items may be noise; the hidden holdout is the check.
