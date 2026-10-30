# Taste — software engineering

What "good" looks like here, beyond a passing metric:

- **Boring on purpose.** Prefer the straightforward solution a new teammate
  understands in one reading. Cleverness is a cost, not a feature.
- **No speculative abstraction.** Add a layer only when the second real use
  case exists, not when it might someday.
- **Tests are part of the change.** A fix without a regression test is a
  promise, not a fix.
- **Small diffs.** One idea per change; unrelated cleanup rides separately.
- **Climb the ladder before writing code.** Stop at the first rung that
  holds: does this need to exist at all; is it already in the codebase; does
  the standard library do it; does the platform do it natively; does an
  installed dependency do it; can it be one line. Only then write new code.
- **Red, then green.** A bug fix starts with a test that fails for the
  reported reason, then the smallest change that makes it pass.
- **Verify before "done".** Build, type-check, lint, run the tests, read
  your own diff. A change the Engineer did not run is not finished.
- **Mark the corners you cut.** A deliberate shortcut with a known ceiling
  gets a comment naming the ceiling and the upgrade path, so it is a
  decision on record rather than a surprise.
- **Names carry the documentation.** If a function needs a paragraph to
  explain its name, rename it.
- **Delete with confidence.** Dead code is removed, not commented out —
  version control remembers.

Anti-patterns the Auditor flags on sight: silent error swallowing,
catch-all handlers that hide failures, configuration by global mutation,
a "temporary" flag with no removal date, a new dependency for
what a few lines of stdlib do, an interface with one implementation.
