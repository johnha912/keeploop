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

One tag, `vX.Y.Z` on `main`, publishes to PyPI and creates the GitHub
release. The one-time PyPI setup and the steps are in
[docs/RELEASING.md](docs/RELEASING.md).

## [Unreleased]

## [0.3.2] - 2026-11-11

### Fixed

A context-hygiene patch: long runs no longer degrade quietly. No new features; the
`evaluate.py` contract, `team.yaml` semantics and the `results.tsv` / `lessons.jsonl`
formats are unchanged.

- **The driving agent is told to start fresh every ~5 cycles.** All loop state is on
  disk and `kl next` resumes it, but nothing told the agent to rotate, so in one long
  session every `kl next` / `kl try` output piled up in its context. AGENTS.md, the
  `/keeploop` skill and BOOTSTRAP.md (chat mode: a new chat and a fresh `kl handoff`
  packet) now say: finish the cycle, stop, ask the user to start a fresh session,
  resume with `kl next`. docs/GUIDE.md explains it to the user in plain words ("Long
  runs: a fresh session every ~5 cycles").
- **`kl next` nudges at every 5th completed cycle.** One `session:` line, derived from
  the ledger's completed-cycle count (no new state). It says kl counts cycles and
  cannot see sessions. Not printed after a `STOP:` line or while a card is pending.
- **keeploop-lite carries a run to a new chat** (en, vi, zh-CN; full and mini). A fixed
  state block of about 300 words (the locked scorecard, the best score, the best
  version or where it is, the discarded ideas, the lessons) is refreshed every cycle
  and is what **save** prints, with one resume line. About every 6 cycles the AI
  suggests saving and moving, with one sentence on why: a long chat slowly loses the
  locked scorecard and the ideas already discarded. Each EXAMPLE now moves to a new
  chat after cycle 3 and runs cycle 4 from the block alone.
- **Token savings are stated as what was measured.** The README's −33% tokens and −26%
  time per cycle are prompt size (characters / 4) and wall time on the scripted
  offline mock; a real AI's answer quality with shorter prompts has not been measured,
  and the README (en, vi, zh-CN) now says so.

### Changed

- README (en, vi) and llms.txt state the MINI skill's size as measured again: about
  1,600 words in English (the state block added about 330).
- Per-cycle cost (`tools/bench_cycle.py`, mock demo, median of 7 reps x 6 cycles): the
  headless cycle runs unchanged code (run.py and everything it imports are untouched);
  tokens and AI calls per cycle are identical (3390.8 tokens; 1.0 / 1.167 / 0.5 calls).

## [0.3.1] - 2026-11-10

### Fixed

A patch release: five findings from an external review of 0.3.0, each reproduced on
`69c3fcc` before it was fixed. No new features; `evaluate.py`, `team.yaml` semantics and
the `results.tsv` / `lessons.jsonl` formats are unchanged.

- **The fence now covers a git worktree's real git dir** (security). In a worktree, the
  setup AGENTS.md recommends, `<workspace>/.git` is a pointer file. The fence hashed
  `<workspace>/.git/config`, `hooks/` and `info/`, which do not exist there, so a
  change to the main repository's shared `.git/config` (a `core.hooksPath`, an alias)
  or a new hook went undetected. They are now read where git reads them: the common git
  dir (`git rev-parse --git-common-dir`) and the worktree's own git dir, from git's
  pointer files, without running git. A plain-repo workspace keeps the same fence
  entries. **Upgrading:** a worktree loop sealed by 0.3.0 asks once for
  `kl begin --accept-changes` (its fence gains the `<git-common>/` entries).
- **`profile: light` measures the noise.** It ran one baseline evaluation, so sigma was
  0 and the keep bar was the best itself, with nothing checking that the score is
  deterministic; on a noisy `evaluate.py` a lucky run was kept. Light now takes 3
  baseline runs (still at most 3 cycles, stop after 2 without a keep, no re-run). A
  deterministic score still gets sigma 0; a noisy one keeps its best + 2σ bar.
- **An unmeasured sigma is never silent.** With an explicit `loop.noise_runs: 1`, the
  baseline prints a loud warning, the ledger's baseline row says so (in its free-text
  description; the columns are unchanged), `best.json` records the run count, and
  `kl level` repeats it. `kl doctor` flags an existing loop whose baseline came from one
  run, or whose sigma-0 baseline now sits over a noisy score.
- **No version promises in shipped text.** The `api:*` refusal, the `team.yaml`
  template, the `vendors.py` docstring and docs/SPEC.md said the API vendors "land in
  v0.2". They now say what works: `claude-cli`, `codex-cli`, `gemini-cli`, any CLI
  declared under `vendors:` (a hosted API can be reached through one), or `mock`. A
  test keeps shipped text free of such promises.

### Changed

- **Default `loop.noise_runs` is 5, was 3.** `kl doctor` itself warned that a 3-run sigma
  swings widely (docs/proof/sweep.tsv: 0.0017 to 0.026 for a true sigma of about
  0.014). The cost is **2 more baseline evaluations, once per loop setup, never per
  cycle**: `noise_runs` drives evaluations only in the baseline (`run.take_baseline`);
  elsewhere it is arithmetic (`sigma_upper`) or text. `examples/noisy-eval` pins
  `noise_runs: 3`, so the proof run reproduces as before.
- Per-cycle cost (`tools/bench_cycle.py`, mock demo, median of 7 reps x 6 cycles): tokens
  and AI calls per cycle are identical to 0.3.0 (3390.8 tokens; 1.0 / 1.167 / 0.5
  calls); wall time is within run-to-run noise (+2.2% and -0.6% in two interleaved
  0.3.0 / 0.3.1 pairs).
- CI tests Python 3.13 as well (3.10 to 3.13, `requires-python >=3.10`).

## [0.3.0] - 2026-11-10

### Added

- The proof run (`docs/proof/`, `python tools/proof_run.py`): a naive keep-if-better
  loop and keeploop on the same 20 proposals and the same deliberately noisy
  evaluation (`examples/noisy-eval`: a random 1,000 of 10,000 dev cases per call,
  plus a 5,000-case holdout the loop never sees), on 25 seeds fixed before running.
  The means: 2.76 vs 0.44 changes kept with no true gain, and a loop score that
  overstated the holdout by +0.017 vs +0.005. The price: 2.64 vs 1.28 true gains
  discarded, and a lower holdout than naive on 9 of 25 seeds (seed 1 included).
  `--check` re-runs it and must match `proof.json` exactly; CI and the release
  workflow run it (the golden gate; never part of a cycle). A post-hoc sensitivity
  run with `noise_runs: 10` is in `docs/proof/posthoc-noise_runs-10/`.
- `run.py --narrate` (`kl run --narrate`): each step of a cycle on screen: the card,
  the diff, the score against best and the keep bar, the decision. Off by default.
- `kl report --html FILE` / `--svg FILE`: the ledger as one shareable page with a
  summary line and a chart (kept filled, discarded hollow, running best, noise band;
  `report.py`, stdlib, no model call).
- `kl doctor`: runs `evaluate.py` N times before a project starts and says how noisy it
  is, the smallest gain the keep bar lets through, and how many repeats a wanted gain
  needs. Warns when `noise_runs` is below 5.
- `kl quickstart tests|command|prompt|buildtime`: a control folder beside your repo
  with an `evaluate.py` from a template and `workspace:` already set.
- `kl import-lite LEDGER.md`: continue a keeploop-lite chat session in the CLI (best
  version -> workspace, scorecard and gates -> a model-judge `evaluate.py`, lessons ->
  `program.md`).
- Opt-in lessons shared across projects: `kl lesson share L-ID` and `global_lessons:`
  in `team.yaml` (off by default; at most 5 lessons within a token budget).
- `loop.eval_cache` (off by default): reuse a score for identical workspace files and
  `evaluate.py`, only when sigma is 0.
- Cost-routing guidance in `team.yaml` (cheap models where a mistake is cheap, the
  strongest for the Auditor). Text only.
- The launch demo: `docs/assets/keeploop-demo.gif` / `.mp4` / `-poster.png`, rendered
  by `tools/render_demo.py` (build-time only: Pillow + ffmpeg) from a re-run of seed 2
  of the proof sweep, chosen by a rule fixed in the script.
- `tools/bench_cycle.py`: per-cycle wall time and tokens of the mock loop; before and
  after this release in `docs/proof/bench-*.json`.
- The mock vendor can follow a `mock_script.json` (used by `examples/noisy-eval`); a
  scripted engineer applies the patch named on the card, so a dropped duplicate card
  never puts the analyst and engineer out of step.
- AGENTS.md: run `kl doctor` before `kl begin` on a new project.
- The CEO sizes the loop to the job. Its first-time interview also asks what a wrong change
  would cost (a draft to redo, something others use, work to publish or ship), and
  `kl level --stakes low|medium|high [--apply]` turns the answer and the score's noise into
  `loop.profile`: `light` (at most 3 cycles, stop after 2 without a keep, one baseline run, no
  re-run, fewer AI calls), `fast`, or `rigorous` (5 noise runs, a re-run and an Auditor
  verdict on every keep). Lessons, the fence, the gates and the brakes stay on at every level.
  keeploop-lite asks the same question in setup and starts in careful mode for something that
  goes out once (en, vi, zh-CN, full and mini).
- The fast path for your own AI: `kl next` (one brief instead of `status` + `recall`) and
  `kl try card.md` (card, gates, evaluation, keep or discard in one command). A routine
  cycle takes 2 `kl` commands instead of 6, and AGENTS.md opens with a fast-path section
  of about 1,350 characters, so the AI need not read the whole 12,000-character file to
  run a cycle (measured on the offline demo). `kl try` asks for an Auditor verdict on a
  heavy change or a light gain that is not decisive, stricter than `kl keep` alone.
- `kl handoff` / `kl apply` for chat AIs without repo access (ChatGPT, Gemini,
  Perplexity): one packet out, one reply in, one round trip per cycle instead of one
  command at a time. BOOTSTRAP.md uses them. `apply` never executes the reply and refuses
  unsafe or unseen paths.
- keeploop-lite fast mode (en, vi, zh-CN): a compact report per cycle with the full ledger
  every 3 cycles, `run N cycles` (up to 5 in one reply), `save`, and `careful mode` for the
  old pace. The full best version is no longer reprinted every cycle, so the chat uses
  less of its context and the person sends fewer messages.
- `lite/KEEPLOOP-LITE-MINI.md` (en, vi, zh-CN): the same loop in about 1,200 words for
  small context windows and search assistants, and `llms.txt` at the repo root, an index
  of these files for AIs that browse.
- Claude Code permissions: `kl next`, `kl try` and `kl doctor` are allowed; `kl handoff`
  and `kl apply` ask first.

- Brakes against doing more than was asked, set by the human in
  `team.yaml`: `loop.target` (good enough; at or above it the job is done)
  and `loop.stall_cycles` (that many cycles in a row without a keep). When
  either trips, `kl status` prints a `STOP:` line, `kl card` refuses a new
  card (no ledger row) and `run.py` stops before the next cycle. Both are off
  unless set. Before, nothing but `max_iterations`, crashes and the token
  budget stopped a loop that kept finding cards to try.
- AGENTS.md (and BOOTSTRAP.md, the /keeploop skill): "measuring is not
  improving". Asked where things stand, the AI measures and reports and
  starts no cycle; it stops at a `STOP:` line even before 3 cycles; the
  first-time interview asks what score is good enough.

- Animations in one light design system (`tools/figure/kl.css`: your AI as a team, each
  role in its own colour), made by `tools/render_figure.py` from committed files only
  (build-time only: Playwright's Chromium, ffmpeg, Pillow):
  - `docs/assets/keeploop-team.gif`, the README hero: you and the CEO (your AI); the
    first-time questions of AGENTS.md; the team it staffs (Analyst on a cheap model,
    Engineer on your main model, Auditor on the strongest); a cycle in two commands with
    real `kl next` / `kl try` output (`docs/assets/demo-run/fastpath.txt`); the measured
    speed strip (`docs/proof/bench-latency-*.json`). Loops seamlessly.
  - `docs/assets/keeploop-x.mp4`, a 54-second 16:9 video for X with the same story: give
    your AI a team, it asks first (the illustrative lite example), it staffs the team, two
    commands a cycle, it keeps only what clears the noise (with the price), fewer calls and
    tokens, where it works.
  - `docs/assets/keeploop-guide-chat.mp4` and `keeploop-guide-code.mp4` (+ GIFs), two
    30-second step-by-step guides, one for chat apps (keeploop-lite: paste or save the file,
    the setup questions, the scorecard, the team, "run 3 cycles", "save", on the lite
    example) and one for coding agents (one prompt, the four questions, `kl level`, the
    team, `kl next` / `kl try`, `kl report`, `kl handoff` / `kl apply`). Rendered by
    `tools/render_guides.py`, which refuses to render if a quoted line is not word for word
    in its source file or a `kl` command shown does not exist.
  - `docs/assets/keeploop-gate.gif`, "the keep gate", in the README's new "Why trust the
    keeps" section: three real changes from the proof run on one number line.
- Measured speed of `profile: fast` on the offline demo with simulated call latency
  (`docs/proof/bench-latency-default.json`, `-fast.json`): tokens per cycle 3390.8 to
  2257.8 (-33%), time per cycle 7.81 s to 5.81 s (-26%), AI calls per cycle 2.7 to 1.7.
- README (en, vi, zh-CN): opens on what keeploop is for: your AI as a team with a CEO
  beside you, in order of what matters (easy, asks first and staffs the team, fast, saves
  tokens, keeps only real gains). The noise proof and its trade-off moved to "Why trust
  the keeps".
- The version badge in the three READMEs reads PyPI and links to
  <https://pypi.org/project/keeploop/>, so it no longer needs a hand edit per
  release; the test now checks the PyPI badge instead of a version string.

### Changed (README figures and guides)

- The two README figures are static paper figures with one motion each:
  `keeploop-team.gif` (Fig. 1) is the complete team board, and a glow steps through
  the stages; `keeploop-gate.gif` (Fig. 2) is three settled scenes (cycles 7, 8 and 14)
  joined by instant cuts. Both have a caption, and their first and last frames are
  identical.
- The two user guides are about 2.5 times slower (about 80 s each), paced so the
  headline and text of each step can be read. Their motion engine
  (`tools/figure/deck.js`) now runs on GSAP, which `tools/render_guides.py` fetches at
  build time, pinned (nothing of it is committed). The steps form one tall page that
  scrolls to the next step; headlines rise word by word; commands are typed; icons are
  drawn in; and in the chat guide the kept score flies to "best so far".
- The README shows each guide as a GIF where it is used: the chat guide under the
  keeploop-lite box, the coding-AI guide under Quick start (a). The full-size videos
  are in [docs/GUIDE.md](docs/GUIDE.md#video-guides), "Video guides".

## [0.2.0] - 2026-11-04

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

- `publish.yml` read `prepare.py` with the runner's default encoding; on
  Windows (cp1252) the rehearsal's verify job failed before installing.
  Found by the first TestPyPI rehearsal, before any tag: both version
  patches now use UTF-8 and every step runs with `PYTHONUTF8=1`.

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

- `lite/`: keeploop-lite, the chat-only edition. `KEEPLOOP-LITE.md` is one
  self-contained file you paste into a chat app (ChatGPT, Claude, Gemini).
  The chat AI runs the same keep-or-discard loop on everyday work, such as
  a post, a CV or a plan. It runs a setup interview, then a locked
  scorecard with pass/fail gates, a team whose roles are named for the
  task (propose, make, check, plus at most one specialist), and a scored
  baseline. Each cycle is a hypothesis card that waits for a yes, one
  change, and a fresh check under an evidence rule ("can't measure this
  here" = 0). The cycle ends with a keep or a discard and a reprinted
  ledger, which is the memory you carry to a new chat. The file is
  model-agnostic and has skill frontmatter, so the same file works
  pasted, as Project or Gem instructions, or as a skill. The loop is
  self-enforced, not enforced by machine. Includes a Vietnamese version
  (`KEEPLOOP-LITE.vi.md`) and an illustrative example (`EXAMPLE.md`).
  The READMEs gain a routing block for people and a short note for AI
  assistants: a coding agent uses the full version, a chat assistant
  uses lite. The note informs rather than instructs, so assistants do
  not treat it as prompt injection. Docs only: no code, pack or contract
  changed.
- Translations in sync: `lite/KEEPLOOP-LITE.zh-CN.md` (Chinese skill) and
  `lite/EXAMPLE.vi.md` / `EXAMPLE.zh-CN.md`; the prompt-optimization example
  README in Vietnamese and Chinese. Each README now routes to the
  keeploop-lite file and example in its own language. In the translated
  READMEs the quick-start prompt, the diagram labels and the chart alt texts
  are translated; real program output and verbatim records stay English.
  The marketing-research READMEs show the current `team.yaml`.
- README: a third way to start, `pipx install keeploop` then `kl init`
  in a new folder; the clone stays for reading the source. The examples
  line names `kl init --example`.
- `docs/RELEASING.md`: the one-time PyPI and TestPyPI setup (Trusted
  Publishing) and the release steps.
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
