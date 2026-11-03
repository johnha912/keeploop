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

One-time setup: on PyPI and on TestPyPI, add a Trusted Publisher (pending
publisher for a new project) for repository `johnha912/keeploop`, workflow
`publish.yml`, environment `pypi` (TestPyPI: `testpypi`). No API token is
stored anywhere.

1. Move the items under **Unreleased** into a new version section with
   today's date.
2. Set `__version__` in `prepare.py`, the only place the version lives
   (`setup.py` reads it), and the version badge in the three READMEs; a
   test checks both.
3. Run `python -m unittest discover -s tests` and
   `python tools/check_dist.py` (build, contents, clean-venv install,
   smoke test). Merge to `main`.
4. Rehearse: Actions -> publish -> Run workflow on `main`. It uploads
   `X.Y.Z.devN` to TestPyPI and installs it back with pip and pipx on
   Linux and Windows.
5. Tag once: `git tag -a vX.Y.Z -m "keeploop X.Y.Z"` and
   `git push origin vX.Y.Z`. The publish workflow refuses a tag that does
   not match `__version__`, runs the same gate, uploads to PyPI, installs
   it back from PyPI with pip and pipx, and only then creates the GitHub
   release with this section as its notes.

## [Unreleased]

## [0.2.0] - 2026-11-03

### Changed

- The wheel installs one top-level name, `keeploop/`: the engine modules
  live inside it, and the `kl` command is `keeploop:main`, which puts that
  folder on `sys.path` only while kl runs. Before, `kl`, `run`, `prepare`,
  `packs` and the others were top-level modules that could clash with other
  packages. `evaluate.py` and `holdout.py` are no longer installed as
  modules at all (`evaluate` clashed with an unrelated PyPI package); the
  demo `evaluate.py` ships as a file `kl init` copies. A clone still runs
  `python kl.py` from the repo root, unchanged.
- The PyPI description is README.md with every relative link and image
  pinned to the release tag (PyPI cannot resolve repo paths). The version
  badge in the READMEs said 0.1.0; it now matches, and a test keeps it so.
- `project.license` is an SPDX string; building needs setuptools 77 or newer.

### Fixed

First-run gaps found by building the worked examples' sandboxes from a fresh clone:

- `kl begin`, `kl status` and `run.py` warn "baseline at ceiling" when the
  keep bar is at or above the top of the metric's scale, so every cycle
  would be discarded (for example a 1.000000 baseline on a 0..1 score with
  `keep_threshold: 0.01` gives a bar of 1.010000). The top is the new
  optional loop key `metric_max` (both examples set `1.0`); without it, a
  best of exactly 1.0 prints a hint to set it.
- The marketing-research example has its own `program.md` with market
  research hypotheses; its sandbox no longer opens with the framework's demo
  hypothesis about learning rates. The sandbox also carries `FORMAT.md` and
  `samples/`, which that charter and `evaluate.py --self-check` refer to.
  Its README points to the verbatim transcript instead of embedding it, and
  the reproduce step now commits the reversed draft (`kl begin` refuses a
  dirty workspace, which the old step left behind).
- `tools/make_sandbox.py` reads an optional `# sandbox requires: CMD (why)`
  line and prints a warning before the `next:` command when CMD is not on
  PATH. The prompt-optimization example declares `claude`: its scorer calls
  Claude CLI, and its "claude CLI not found" error now says so and names the
  offline `--self-check`.

- On Windows a pip-installed `kl` called itself `python kl.py` in every
  hint it printed: the launcher reports `kl.EXE` and the name check was
  case-sensitive. Found by the new Windows dist job.

Four gaps found by the prompt-optimization worked example:

- `run.py` now leaves the `.keeploop/fence.json` that `kl` expects, so
  `kl card`, `check`, `eval` and `discard` work after a headless run
  without `kl begin --accept-changes`. It refreshes the fence only if the
  old one still held at the start and nothing changed during the run, so
  a headless run never re-seals a change made outside `kl`. A run that
  stops on a broken fence leaves `.keeploop/tampered.txt`, which blocks
  any re-seal (and plain `kl begin`) until `kl begin --accept-changes`.
- `kl eval` with an open card re-runs the `kl check` gates first and
  refuses, without running the evaluation, when one fails (as `kl keep`
  already did).
- A keep refused by the confirm re-run keeps the re-run score:
  `confirm_metric` in `hypotheses.jsonl`, and `unconfirmed: re-run <score>
  below the bar` right after the verdict in the ledger, before the
  240-character cut. Both modes; a passing re-run's score is kept too.

### Added

- `kl init [DIR]`: a pip/pipx install is the engine only; `kl init` copies
  the files a project edits (AGENTS.md, CLAUDE.md, GEMINI.md, BOOTSTRAP.md,
  program.md, team.yaml, the demo evaluate.py, packs/, .claude/ agents,
  skill and settings, a .gitignore) into the folder. It never overwrites a
  file, and warns when the folder has its own AGENTS.md, team.yaml or
  evaluate.py. In the copies, `python kl.py` reads `kl`, `python run.py`
  reads `kl run`.
- `kl init --example NAME DEST`: the worked example's sandbox for a pip
  install (no code copy; `tools/make_sandbox.py` stays for a clone, and
  both use the new `scaffold.py`).
- `kl run [--mock] [--iterations N]`: the headless loop from a pip install
  (same as `python run.py`).
- Packaging: `setup.py` packs every file `scaffold.py` lists into the wheel
  (`keeploop_assets/`) and the sdist; `tools/check_dist.py` builds both,
  checks their contents, installs the wheel in a clean venv and runs
  `kl init` -> `kl begin` -> `kl status` -> `kl run --mock`, plus the
  marketing-research sandbox. CI runs it on Linux and Windows. With
  `--from-index SPEC` it installs from an index instead, with `--kl PATH`
  it smoke-tests an existing install (pipx).
- `.github/workflows/publish.yml`: a `vX.Y.Z` tag runs the gate, uploads to
  PyPI with Trusted Publishing (OIDC, no token), installs the release back
  from PyPI with pip and pipx on Linux and Windows, then creates the GitHub
  release from `tools/release_notes.py` (this file's section). Run by hand,
  it rehearses on TestPyPI with an `X.Y.Z.devN` version.
- The headless Analyst sees `evaluate.py`'s stderr for the current best
  (per-label breakdowns and the like), with control characters stripped and
  secrets redacted. Never `holdout.py`'s. Capped by the new loop key
  `eval_stderr_max_chars` (default 1500, `0` = off). About +200 tokens per
  cycle on the example's breakdown, no extra vendor call. The Goodhart
  trade-off is in docs/GUIDE.md.
- `tools/make_sandbox.py examples/<name> DEST`: builds a worked example's
  sandbox (control copy of keeploop plus a fresh git workspace) in about a
  second, from two `# sandbox root:` / `# sandbox workspace:` lines in the
  example's `team.yaml`. It always removes the demo `holdout.py` (L-001) and
  refuses holdout files in the workspace and a DEST inside the repo.
- README demo GIF of the offline mock run (baseline, keeps, a discard, a
  crash that becomes a lesson), re-recorded with `python docs/record_demo.py`.

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
