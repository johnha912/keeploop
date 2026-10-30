# Changelog

All notable changes to keeploop are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html):

- **MAJOR** when a change breaks `team.yaml`, the `evaluate.py` contract,
  or the `results.tsv` / `lessons.jsonl` formats.
- **MINOR** for new features that keep those working (a vendor, a gate,
  a pack, a scout source).
- **PATCH** for fixes that change no interface.

Before 1.0.0, a MINOR release may still break the formats; when it does,
the entry says so under **Changed** with the migration step.

## Releasing

1. Move the items under **Unreleased** into a new version section with
   today's date.
2. Set `__version__` in `prepare.py`; it is the only place the version
   lives (`pyproject.toml` reads it, a test checks this file matches).
3. Run `python -m unittest discover -s tests`.
4. Commit, then tag and push: `git tag -a vX.Y.Z -m "keeploop X.Y.Z"`,
   `git push --follow-tags`, and create the GitHub release from the tag
   with this section as its notes.

## [Unreleased]

### Added

- `kl pack add <url-or-name>`: import a profession pack from a skill repo, a
  `SKILL.md`, a `README.md` or a `.md` link, or resolve a bare name with
  GitHub search (several matches are listed, never picked). The result is a
  **draft** with provenance (source, time, sha256); only `.md`/`.yaml`/`.csv`
  are written, never code. Secrets, slop, oversized files, a rubric that does
  not sum to 100 or a name clash refuse the import with nothing written.
- `kl pack approve <name>` (human-only) re-runs the gates with a complete
  rubric and flips the pack to active; `kl pack list` shows status and source.
- A draft pack refuses to load (`packs.DraftPack`) in `kl`, `run.py` and the
  scout until it is approved.

### Fixed

- `kl()` recognises a Windows-style argv0 (`C:\Scripts\kl.exe`) on Linux and
  macOS; the suite now passes on POSIX too (#1).
- The scout prints why a source was refused (the exception message), not
  only its class. The SSRF guard is unchanged.

## [0.1.0] - 2026-10-29

First public release.

### Added

**Agent-native layer (your AI is the CEO)**
- `AGENTS.md`: the self-contained org chart and cycle any agent reads, with
  pointer files `CLAUDE.md`, `GEMINI.md` and
  `.github/copilot-instructions.md`.
- Optional Claude Code accelerators: subagents
  `.claude/agents/keeploop-{analyst,engineer,auditor,critic,scout}.md`
  (auditor and critic read-only) and the `/keeploop [N]` skill.
- `kl.py`, deterministic tools that never call a model except
  `kl audit --vendor`:
  - `begin`, `status`, `card`, `debate`, `check`, `eval`, `keep`,
    `discard`, `report`, `slow`, `recall`, `map`, `staff`, `pack new`,
    `cite`, plus `lesson` and `scout` passthroughs.
  - `kl keep` re-runs every gate, the evaluation, the confirm run and the
    lesson replay before it commits.

**The loop**
- The loop over a git workspace: Analyst card, Engineer edit, fixed
  `evaluate.py`, Auditor verdict, keep as `git commit`, discard as
  `git reset --hard` + `git clean -fd`, one `results.tsv` row per cycle.
  `run.py` runs it headless.
- Engineer repair attempt (`engineer_repairs`, default 1) when the
  evaluation crashes or the change is empty.
- Noise-aware keep:
  - `noise_runs` evaluations measure sigma before the first cycle.
  - A keep must beat the best by `max(abs(best)*keep_threshold, noise_z*sigma)`.
  - The confirm re-run is skipped only for light changes when sigma is 0.
- Optional `holdout.py`, scored before and after a run and never shown in
  any prompt or the ledger; a warning when its gain lags the eval gain.
- `max_run_tokens` run budget and per-phase timing in the ledger.

**Hypotheses and anti-hallucination**
- Hypothesis-first cards in labelled lines (HYPOTHESIS, ALTERNATIVES,
  CHANGE, EXPECT, REJECT IF, MISSING, optional DIFFERENT). REJECT IF must
  be measurable.
- Hypothesis registry `.keeploop/hypotheses.jsonl` with verdicts
  supported, rejected, inconclusive, untested and duplicate. A
  near-duplicate card (`duplicate_jaccard`) is refused before any edit.
- Human hypotheses under `## Hypotheses to test` in `program.md` go first.
  `MISSING` items collect in `.keeploop/questions.md`.
- Critic challenge round on heavy cards: one critique, at most one
  revision, recorded append-only in `.keeploop/debate/`.
- `kl report` for progress claims from the ledger. `kl cite` (opt-in,
  network) checks links and quotes; every fetch and redirect must stay
  https and reach a public address.

**QC gates**

Deterministic, run before any vendor sees a change:
- content-hash fence over the project folder outside the workspace, plus
  the workspace's `.git/config`, `info/` and `hooks/`, around every phase
  that runs untrusted code;
- index-flag check (`skip-worktree`, `assume-unchanged`);
- protected paths checked by content;
- secret scan of full file contents, binary included;
- per-pack slop patterns;
- diff size cap.

**Speed and staffing**
- Light/heavy tiers (`heavy:` globs, `heavy_diff_lines`) and per-role
  `model:` / `heavy_model:`.
- The Auditor is called only when the metric beats the bar, and the rubric
  is scored in the same call.
- Prompts get the `recall_top_k` most relevant lessons.
- `kl slow` names the bottleneck phase and the levers to cut it.
- `kl staff [--goal speed|quality|cost] [--apply]` proposes model and
  budget per role and applies only inside the `staffing:` allowlist that
  was in `team.yaml` when `kl begin` sealed it; it exits 2 on a broken
  fence.
- Every key under `loop:` in `team.yaml` applies everywhere, including
  `kl map`, lessons and the vendor and eval timeouts.

**Lessons and memory**
- Lesson engine: guardrails, duplicate lessons merged into re-triggers,
  retirement from the last re-trigger, and human-attached check commands
  replayed before every keep.
- `kl lesson review` statuses: enforced, effective, ineffective,
  provisional.
- `kl recall`: BM25 over lessons, hypotheses (including each card's
  CHANGE, stored in `hypotheses.jsonl`), debates, questions and the ledger.
- `kl map`: a cached code index with an imported-by lookup, re-parsing
  only changed files.

**Vendors**
- `claude`, `codex` and `gemini` presets, plus any CLI declared in
  `team.yaml` (`cmd`, `edit_args`, `model_flag`, `env_keep`,
  `env_allow`). Under a kept prefix, a secret-looking variable passes only
  if its exact name is in `env_allow`.
- The prompt goes on stdin; there is no shell; edit rights go to the
  Engineer only.
- The environment is scrubbed of token-like variables.
- Ordered per-role fallback, and a deterministic `mock`.

**Git hardening**
- Hooks and fsmonitor are disabled for every git call the loop makes.
- External diff drivers and textconv are disabled for the diffs it reads.
- A run stops without touching git again when the fence trips.

**Scout, packs and project files**
- Trend scout: Hacker News, arXiv and new GitHub repositories, scored by
  relevance × momentum × recency against the mission and the pack's
  `scout_topics`; untrusted text sanitised; `--dry-run`.
- Profession packs `software`, `ui-design` (with a searchable style,
  palette and font base) and `marketing-content`. Each has `taste.md`, a
  gated `rubric.md`, specialist reviewers and slop patterns.
  `kl pack new` scaffolds another.
- `python run.py --version`, `SECURITY.md`, this changelog.
- `pip install .` provides a `kl` command; installed, it uses the current
  directory as the project root, and its messages say `kl <cmd>`.
- `AGENTS.md` tells the AI to run the loop when the user simply asks for
  something measurable to get better, and to set up the metric with the
  user on first use. `.claude/settings.json` pre-approves the
  read-and-measure `kl` commands in Claude Code; `lesson`, `audit`, `cite`,
  `begin --accept-changes` and `staff --apply` still ask.
