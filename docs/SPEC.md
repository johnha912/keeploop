# Engineering Spec - keeploop 0.1

The contract an engineer (human or AI) implements, reviews or extends
against. Defaults live in `prepare.CONFIG`; `team.yaml` can override some of
them (see section 4 for which). Version: `prepare.__version__`. Every claim
below points at code; section 7 also points at tests.

## 1. Components

Principle: keeploop runs no model. Your AI (Claude Code, Codex, Gemini CLI,
Cursor, Copilot, ...) is the CEO and does the thinking. `kl` only measures,
gates, records and refuses. The one exception is `kl audit --vendor`, which
calls a vendor CLI you name.

Two modes over the same gates:

- **Interactive** (`kl.py`): your AI drives the cycle from `AGENTS.md`; each
  step is a `kl` command; state in `.keeploop/cycle.json`.
- **Headless** (`run.py`): the loop calls vendor CLIs for the Analyst,
  Engineer and Auditor itself, unattended.

| File | Role | Edited by |
|---|---|---|
| `AGENTS.md` | The org chart and exact cycle any agent reads; single source of the interactive procedure | Maintainers |
| `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md` | Pointer files: "read AGENTS.md" | Maintainers |
| `.claude/agents/keeploop-{analyst,engineer,auditor,critic,scout}.md`, `.claude/skills/keeploop/` | Optional Claude Code accelerators (subagents, `/keeploop [N]`) | Maintainers |
| `kl.py` | Interactive tools: `begin status card debate check eval audit keep discard report slow recall map staff pack cite`, plus `lesson` and `scout` passthroughs | Maintainers |
| `prepare.py` | Setup, `CONFIG`, `__version__`, the `git()` helper, the restricted YAML loader | Maintainers |
| `program.md` | Charter: mission, keep rule, `## Hypotheses to test`. Its `## Mission` feeds the scout | Human |
| `team.yaml` | Workspace, protect, heavy, pack, roles, vendors, staffing, loop overrides | Human (`kl staff --apply` inside its allowlist) |
| `run.py` | The headless loop, the QC gates, the fence, `keep_bar` | Maintainers |
| `vendors.py` | Vendor adapters, custom CLI vendors, fallback, env scrubbing | Maintainers |
| `ledger.py` | Append-only `results.tsv` | Nobody by hand |
| `lessons.py` | Lessons, guardrails, replay checks, `recall` memory | Loop (data), human (checks) |
| `codemap.py` | Cached code index of the workspace (`kl map`, the Analyst's repo map) | Maintainers |
| `bm25.py` | The one BM25 ranker (`kl recall`, guardrail selection, the ui-design search) | Maintainers |
| `scout.py` | Trend scout -> `proposals.md` | Maintainers |
| `rubric.py` | Weighted rubric with gates | Maintainers |
| `packs.py`, `packs/<name>/` | Profession packs | Maintainers, pack authors |
| `evaluate.py` | **The user's** fixed metric | Human only |
| `holdout.py` | Optional hidden second metric | Human only |
| `.keeploop/` | State (section 5) and the demo `workspace/` | Loop and `kl` |

## 2. The workspace

A git repository the team may change, set by `workspace:` (default
`.keeploop/workspace`, a demo repo created by `prepare.py`).
`run.workspace_error` refuses (exit 1) a workspace that is the root or
contains it, is not a git repository, or has uncommitted changes. Each cycle
starts at the last kept commit and ends there: a keep is a commit, everything
else is `git reset --hard <base>` + `git clean -fd` (never `-x`, so ignored
files survive).

## 3. One cycle

Headless (`run.py`, `cycle()`); the interactive mapping follows.

```
0. BASELINE   once, before cycle 1: evaluate the untouched workspace noise_runs
              times; mean = best, pstdev = sigma; best.json + ledger row 0.
              With holdout.py, its baseline is scored and stored too.
1. PROPOSE    Analyst: charter + guardrails + taste + repo map + ledger tail +
              already-tested hypotheses + untested human hypotheses.
              Guardrails are the recall_top_k most relevant open lessons when
              more than that are open (BM25 over the last 3 ledger rows and
              the next human hypotheses). A lesson with a check is not
              injected; its check runs on every keep.
              Card = labelled lines: HYPOTHESIS, ALTERNATIVES, CHANGE, EXPECT,
              REJECT IF, MISSING, optional DIFFERENT and TIER. Workspace
              reverted after the call.
              - HYPOTHESIS, CHANGE, REJECT IF or MISSING missing -> crash + lesson.
              - REJECT IF not falsifiable (names `metric`, or a number with
                < > <= >= below above under over at least at most fewer more)
                -> crash + lesson.
              - MISSING other than none / n/a / - goes to questions.md.
1b. DUPLICATE  Jaccard word overlap of HYPOTHESIS vs every rejected or
    PRECHECK   inconclusive one >= duplicate_jaccard -> discard, verdict
              `duplicate`, no Engineer call. A non-empty DIFFERENT skips this.
1c. CHALLENGE  Heavy cards only (`TIER: heavy`, or CHANGE names a file the
              heavy globs match): the auditor role's vendor (heavy_model if
              set) returns OBJECTIONS / STRONGEST ALTERNATIVE / REJECT-IF
              CHECK / VERDICT. On `revise` the Analyst answers once with a
              revised card (must parse and be falsifiable) or `KEEP: reason`.
              Max one round. Light cards make no critic call. The debate
              never decides; the metric does.
2. IMPLEMENT  Engineer edits the workspace (only role with edit rights).
              The loop stages everything (an agent commit is soft-reset first).
3. QC GATES   in order, deterministic, before any vendor sees the diff:
              protected path touched          -> crash + lesson
              secret in file name or content  -> crash + lesson
              pack slop pattern on an added line -> crash + lesson
              added+removed lines > max_diff_lines -> discard + lesson
              Tier: heavy if lines > heavy_diff_lines or a changed path
              matches the heavy globs, else light.
4. EVALUATE   python evaluate.py <workspace> -> one float, or crash.
              Repairable (empty diff, evaluation crash): up to engineer_repairs
              more Engineer calls with the error. Still failing -> crash +
              lesson. Repaired -> the first failure still gets its lesson.
5. DECIDE 1   bar = best + max(abs(best) * keep_threshold, noise_z * sigma).
              metric <= bar -> discard now. No Auditor call is spent.
6. AUDIT      One Auditor call (heavy_model for a heavy change) returns the
              verdict, and in the same reply the rubric scores (pack rubric)
              and, on heavy changes only, the pack's specialist checklists.
              Input: card, diff (8000 chars), metric, standards, checklist:
              hypothesis tested, scope, no evaluation gaming, guardrails,
              security, craft. Approved only if the reply starts with APPROVED.
7. DECIDE 2   audit not approved                    -> discard + lesson
              rubric < best_rubric - 5              -> discard
              confirm: re-run the evaluation; not beats(min of both) -> discard.
                Skipped only for a light change when sigma is 0
                (`needs_confirm`: heavy, or confirm_keep and sigma > 0).
              replay_on_keep: any active lesson check fails -> discard,
                lesson re-triggered
              otherwise -> keep: git commit, best.json
8. RECORD     one results.tsv row, always; one hypotheses.jsonl row per parsed
              card (verdicts in section 5); one timing.jsonl row.
              After the last cycle: hidden holdout scored once on the final
              HEAD; WARNING if its gain is negative or under half the
              evaluation gain.
```

Per-phase timing: the console line shows `time a= e= v= q=` (analyst,
engineer, evaluation, audit seconds); `timing.jsonl` holds analyst, critic,
engineer, eval, confirm, audit seconds per cycle.

Every vendor call, evaluation, holdout score and lesson check is fenced
(`guarded`): a sha256 fingerprint of every file outside the workspace (root
`.git` and the state dir included, `.git/objects` excluded), plus the
workspace's `.git/config`, `info/` and `hooks/`, is taken before and after;
the index is checked for `skip-worktree` / `assume-unchanged`. Any
difference: crash, lesson, the run stops with exit 2, and no further git
command runs in the workspace. `VendorUnavailable` (all vendors in a role's
list failed) is a crash with no lesson. `max_consecutive_crashes` in a row
stop the run with exit 0, as does `max_run_tokens` (checked after the cycle).

Every git call carries `-c core.hooksPath=<state>/nohooks -c
core.fsmonitor=false`; diffs add `--no-ext-diff --no-textconv`.

### Interactive mapping

The same functions (`R.parse_card`, `R.qc_gates`, `R.keep_bar`,
`R.needs_confirm`, `lessons.replay`, ...) back both modes. `kl begin` takes
the fence snapshot; every later command refuses (exit 2) if it changed.

| Step | `kl` command | Notes |
|---|---|---|
| 0 Baseline | `begin` | Same `take_baseline` as `run.py`; also writes `fence.json` with the `best.json` seal. `--accept-changes` is for a human after a legitimate change. |
| - Memory | `status`, `recall QUERY`, `map [--query NAME]` | Open lessons, questions, recently rejected, next human hypothesis; BM25 over memory; defs and importers. |
| 1 Propose, 1b | `card FILE\|-` | Parse, falsifiable check, duplicate precheck. Failures are logged as crash (with lesson) or discard (duplicate) and refused. Prints `heavy card` if heavy. |
| 1c Challenge | `debate ID --critic FILE` / `--reply FILE` | One critique (must end `VERDICT: proceed\|revise`), one reply; append-only `debate/<id>.md`. |
| 2 Implement | (your Engineer edits the workspace) | |
| 3 Gates | `check` | PASS/FAIL, tier, `diff=<id>` (sha256 prefix of the diff). |
| 4-5 Evaluate | `eval` | Fenced `evaluate.py` against the keep bar. |
| 6 Audit | (fresh-context Auditor) or `audit --vendor NAME [--model M]` | The only command that needs an AI CLI. Output ends with `DIFF: <id>`. |
| 7 Decide | `keep [--audit-verdict FILE]` | Re-runs fence, gates, evaluation, bar, audit verdict (diff id must match; heavy requires it), rubric regression, confirm, lesson replay; commits only if all hold. |
| 7 Decide | `discard [--reason]` | Reset to best, ledger row, verdict, lesson if a gate failed. |
| 8 Record | `report`, `slow` | Facts from the ledger; bottleneck phase and levers. |
| Staffing | `staff [--goal speed\|quality\|cost] [--apply]` | Section 4. |
| Packs, memory | `pack new NAME`, `lesson ...`, `scout ...`, `cite FILE` | |

Differences from headless: the Auditor is optional for a light change that
beats the bar (the CEO decides; `keep` demands a verdict only for heavy);
`kl keep` warns, not blocks, on a heavy card with no recorded critique; the
ledger's `role_vendors` is `interactive`; `timing.jsonl` rows carry `eval`,
`confirm`, `audit` and `agent` (card-to-verdict wall time minus those).

## 4. Parameters

`prepare.CONFIG`. "Loop" = can be overridden under `loop:` in `team.yaml`
(`run.project_config` takes only keys of `CONFIG`). Keys marked "no" are
read straight from `CONFIG` by `lessons.py`, `vendors`/`scout.py` call sites
or the evaluation runner, so a `loop:` entry has no effect on them.

| Name | Default | Loop | Meaning |
|---|---|---|---|
| `max_iterations` | 20 | yes | Cycles per run; `--iterations` overrides |
| `keep_threshold` | 0.0 | yes | Minimum gain relative to `abs(best)` |
| `confirm_keep` | true | yes | Re-run before a keep when sigma > 0 (heavy always re-runs) |
| `engineer_repairs` | 1 | yes | Extra Engineer calls for a repairable failure |
| `repo_map_max_chars` | 3000 | yes (`run.py`); `kl map` uses the default | Analyst repo map size |
| `max_diff_lines` | 400 | yes | Size gate, added+removed lines |
| `max_consecutive_crashes` | 3 | yes | Crashes in a row that stop a run |
| `eval_timeout_s` | 120 | no | Evaluation and lesson-check timeout |
| `noise_runs` | 3 | yes | Baseline evaluations; their pstdev is sigma |
| `noise_z` | 2.0 | yes | A keep must beat best by `noise_z * sigma` |
| `max_run_tokens` | 2,000,000 | yes | Estimated tokens per run; reached -> stop |
| `duplicate_jaccard` | 0.8 | yes | Card vs a rejected one at or above this: no Engineer call |
| `heavy_diff_lines` | 100 | yes | A bigger diff is heavy: forced confirm, heavy_model, required audit |
| `ledger_tail_for_prompt` | 10 | yes | Ledger rows shown to the Analyst |
| `token_budget_per_role` | 50,000 | no | Default `max_tokens` per role; set `token_budget` per role instead |
| `vendor_timeout_s` | 240 | no | Per vendor call |
| `guardrail_max_chars` | 4,000 | no | `guardrails.md` keeps the newest lessons that fit |
| `lesson_retire_after_days` | 90 | no | Counted from the last re-trigger |
| `lesson_effective_after` | 10 | no | Clean ledger cycles before a lesson counts as effective |
| `replay_on_keep` | true | yes | Run lesson checks before a keep |
| `recall_top_k` | 8 | yes | More open lessons than this: inject only the k most relevant |
| `scout_max_proposals` | 3 | no (`--max`) | Per scout run |
| `scout_min_relevance` | 0.35 | no (`--min-score`) | Applies to the relevance factor |

No key of the earlier spec was removed. `keep_threshold` now feeds the bar
`max(abs(best) * keep_threshold, noise_z * sigma)`.

`team.yaml` keys (restricted YAML, `prepare.load_team`):

| Key | Meaning |
|---|---|
| `pack` | Pack name under `packs/` (default `software`) |
| `workspace` | The git repo the team edits (default `.keeploop/workspace`) |
| `protect` | Comma-separated globs inside the workspace no change may touch; case-insensitive, no absolute path or `..` (startup error) |
| `heavy` | Globs that make a change heavy. Absent = `DEFAULT_HEAVY` (manifests, lockfiles, Dockerfile, `migrations/*`, `.github/*`); `heavy:` with no value = size only |
| `roles.<analyst\|engineer\|auditor>.vendor` | Vendor name or ordered fallback list `a, b` |
| `roles.<role>.token_budget` | `max_tokens` for that role |
| `roles.<role>.model` | Passed to the CLI as its model flag; letters, digits and `. _ : / -` only; applies to every CLI in a fallback list; checked even for the mock |
| `roles.auditor.heavy_model` | Model for heavy audits and the critic (only the auditor's is used) |
| `vendors.<name>` | Custom CLI vendor: `cmd`, `edit_args`, `model_flag`, `env_keep`, `env_allow` (section 6) |
| `staffing.allow_models`, `staffing.max_tokens_per_role` | Allowlist for `kl staff --apply`; absent = nothing is applied. Must be present when `kl begin` seals the fence; `staff --apply` exits 2 if the fence is broken |
| `cycle_time_budget_s` | `kl report` flags cycles over it; `kl slow` uses it as the lesson-check target |
| `loop.<key>` | The "yes" rows above |

`kl staff [--goal ...]` writes `.keeploop/staffing.md` (model, effort,
token_budget per role from crash and discard rates, heavy share and
tokens). `--apply` edits only `roles.<r>.model`, `heavy_model` (values
inside `allow_models`) and `token_budget` (up to `max_tokens_per_role`),
keeps comments, and refreshes only the `team.yaml` entry of the fence.

## 5. File formats

All under `.keeploop/` unless noted.

### `results.tsv` (append-only)
Columns: `cycle ts role_vendors metric best_metric status tokens lesson_id
description` (`ledger.FIELDS`). `status` is `keep`, `discard` or `crash`
(anything else raises). Cycle 0 is the baseline. `role_vendors` names the
vendor that served each role (`interactive` for `kl`). `description` (240
chars max) holds the card, gate notes, `verdict: <v>`, `tier: light|heavy`,
the audit line, `rubric: N`, `critic: proceed|revise`, and
`audit: fresh-context (same vendor)` when the Auditor and Engineer were
served by the same vendor. A secret is described by kind and file, never by
value.

### `hypotheses.jsonl` (append-only)
```json
{"cycle": 3, "ts": "...", "hypothesis": "... (300 chars max)",
 "reject_if": "... (200 chars max)", "verdict": "rejected",
 "metric": 0.942, "best_before": 0.992}
```
Verdicts (`verdict_of`, plus the duplicate path): `supported` (keep),
`rejected` (metric did not beat the bar), `inconclusive` (metric beat the
bar, keep blocked by audit, rubric, confirm or replay), `untested` (crash,
or no metric), `duplicate` (refused by the precheck, `metric` null). The last
20 rejected or inconclusive rows (2000 chars max) are shown to the Analyst
as "already tested". Bullets under `## Hypotheses to test` in `program.md`
that no registry hypothesis contains (case-insensitive, whitespace
collapsed) are offered first, five at most.

### `lessons.jsonl` (append-only)
```json
{"id": "L-001", "ts": "...", "trigger_cycle": 4, "what": "...",
 "root_cause": "...", "guardrail": "...", "check": null,
 "status": "active", "retired_ts": null}
{"event": "retrigger", "id": "L-001", "ts": "..."}
{"event": "check", "id": "L-001", "ts": "...", "check": ["python", "-m", "pytest", "tests/x.py"]}
```
Event rows are folded in on load; lessons are never rewritten. Recording a
guardrail an active lesson already has appends a re-trigger. A `check` is an
argv list run in the workspace, fenced, with the scrubbed environment (exit
0 = pass). Checks are added only through `python lessons.py add ... -- <cmd>`
/ `check <id> -- <cmd>` (`kl lesson ...`); the loop never stores a command
from vendor or web output. Derived standing (`kl lesson review`): `enforced`
(has a check), `ineffective` (re-triggered, no check), `effective`
(`lesson_effective_after` clean cycles), `provisional`.
`guardrails.md` is regenerated from active lessons without a check.

### `best.json`
`{"metric": float, "sigma": float, "rubric": float | null, "commit": "<sha>"}`.
In interactive mode `fence.json` stores its sha256; a change made outside
`kl` is refused until a human runs `kl begin --accept-changes`.

### `debate/<card>.md`
Append-only, written by `kl debate`: `## Critique` then `## Reply`, one each.

### `map.json`
Cache of `codemap.build`: per tracked file `{sha, defs, top, imports}`; only
files whose content hash changed are re-parsed. Python via `ast`; JS/TS, Go,
Rust, Java by regex (names only); files over 200 KB are indexed by hash only.
`importers` is name-based, so approximate.

### `staffing.md`, `proposals.md`
`staffing.md`: the last `kl staff` proposal. `proposals.md`: scout output,
appended; every entry says "needs an experiment card before adoption".

### Others
- `questions.md`: `- (cycle N) <MISSING text>`, deduped by exact text; for the
  human, never put into a prompt.
- `timing.jsonl`: per-cycle seconds (section 3).
- `holdout.json`: hidden baseline and final scores; never read into a prompt
  or the ledger.
- `scout_seen.json`: URLs already fetched. `nohooks/`: empty hooks dir.
- `cycle.json`, `fence.json`: interactive-mode state.

### `team.yaml`
Restricted YAML: up to three levels of `key: value`, scalars, `#` comments,
no lists (comma-separated strings instead). See `team.yaml` in the repo.

## 6. Vendor interface

```python
class Vendor:
    name: str
    is_mock: bool
    def available(self) -> bool: ...
    def complete(self, prompt: str, *, role: str, max_tokens: int,
                 cwd: Path | None = None) -> VendorResult: ...
```
`VendorResult(text, tokens_in, tokens_out, model, latency_s)`; tokens are
estimated at 4 characters each. Adapters return text for task failures and
raise `VendorUnavailable` when the vendor cannot be called (missing binary,
timeout, non-zero exit).

`CliVendor` resolves the binary with `shutil.which` (Windows `.cmd`/`.exe`
shims), sends the prompt on stdin, never uses a shell, adds edit flags for
the Engineer only, and appends `<model_flag> <model>` when a model is set.

| Name | Command | Engineer flags | Env kept (prefixes) |
|---|---|---|---|
| `mock` | built in, deterministic, offline | n/a | n/a |
| `claude-cli` | `claude -p` | `--permission-mode acceptEdits` | `ANTHROPIC_`, `CLAUDE_` |
| `codex-cli` | `codex exec` | `--full-auto` | `OPENAI_`, `CODEX_` |
| `gemini-cli` | `gemini` | `--approval-mode auto_edit` | `GEMINI_`, `GOOGLE_`, `GOOGLE_GENAI_` |

`api:*` names raise `VendorUnavailable` (not implemented in 0.1).

**Generic CLI vendor.** Any CLI can serve a role from `team.yaml`, no code
change:
```yaml
vendors:
  myvendor:
    cmd: mycli --print        # binary plus the flag that reads stdin and prints
    edit_args: --allow-edits  # engineer only
    model_flag: --model       # default --model
    env_keep: MYVENDOR_       # env prefixes this CLI may see
    env_allow: MYVENDOR_API_KEY  # exact secret-looking names let through
```
Under an `env_keep` prefix, a name that matches the scrub words below is
still dropped unless it is listed exactly in `env_allow`; each `env_allow`
name must start with an `env_keep` prefix. Presets are unaffected.
Strings are split like argv (`shlex`). The name is `[a-z0-9-]` and must not
shadow a preset or `mock`. `cmd` is required. An `env_keep` prefix must look
like `NAME_`, at least 4 characters, not secret-looking, and not a generic
cloud or forge prefix (`AWS_`, `AZURE_`, `GITHUB_`, `GH_`, `GITLAB_`, `NPM_`,
`PYPI_`, `SSH_`, `GPG_`, `DOCKER_`, `KUBE`, `GOOGLE_APPLICATION`); otherwise
the vendor is refused. Check your CLI's own docs for its flags.

**Environment scrubbing.** `safe_env` drops every variable whose name
contains TOKEN, SECRET, PASSWORD, PASSWD, CREDENTIAL, API_KEY, APIKEY,
PRIVATE_KEY or ACCESS_KEY, except those under the vendor's own prefixes. The
same scrub applies to the evaluation, the holdout and lesson checks (which
also get `PYTHONDONTWRITEBYTECODE=1` where run by `run.py`).

**Fallback.** `FallbackVendor` tries a role's `vendor: a, b` list in order
and records which one served (`served`, shown in the ledger). Preflight drops
members whose binary is missing and exits 1 if a role has none, or a model
name is invalid.

## 7. Safety invariants

Listed only where a test covers the claim (`tests/`, run by
`python -m unittest discover -s tests`).

1. Nothing outside the workspace changes during a vendor call without the
   run stopping (exit 2): `test_tamper_fence_stops_the_run`, `TestFence`
   (same-size edit with restored mtime, root hook and `__pycache__` plants,
   evaluation, baseline and lesson check run inside the fence). A planted
   workspace git config stops it too: `test_planted_git_config_stops_the_run_before_git_add`.
2. A protected path, including through `skip-worktree` or `assume-unchanged`,
   is a crash with a lesson: `test_protected_gate`, `test_glob_gate_in_a_run`,
   `test_skip_worktree_cannot_hide_a_protected_edit`,
   `test_index_flags_and_protected_dirty_see_through_assume_unchanged`.
3. A diff containing a credential is a crash and its value appears in no
   state file: `test_secret_gate_blocks_and_never_logs_the_value`; binary,
   NUL-padded, `-diff` attributed and odd-case file names are scanned
   (`TestSecretGate`). (Not tested: "never sent to a vendor"; the order is
   in `qc_gates`, which runs before evaluation and audit.)
4. Planted hooks and fsmonitor commands never run through the loop's git
   calls: `test_planted_hook_and_fsmonitor_never_run`.
5. Every attempted cycle adds one ledger row; the clean mock run leaves the
   workspace clean at the last kept commit with `evaluate.py` byte-identical:
   `test_five_cycles_produce_ledger_lessons_and_improvement`.
6. The audit verdict parser rejects "NOT APPROVED": `test_verdict_parsing`.
7. `GITHUB_TOKEN` is sent only to `api.github.com`:
   `test_github_token_only_to_api_github`.
8. A prose card is a crash with a lesson and no registry row:
   `test_prose_analyst_crashes_with_lesson`. (Not tested: that the Engineer
   is never called; the early return is in `cycle()`.)
9. Secret-looking environment variables never reach vendors, evaluation or
   lesson checks: `TestEnvironment`.
10. A noise-level gain is not kept (`test_noise_raises_the_bar_for_a_keep`,
    `test_keep_refuses_when_the_metric_is_within_noise`); the hidden holdout
    never reaches a prompt or the ledger
    (`test_numbers_never_reach_a_prompt_or_the_ledger`); a duplicate card
    makes no Engineer call (`test_repeat_skips_the_engineer`); light cards
    make no critic call (`test_light_cards_make_no_critic_call_heavy_ones_one_plus_one_revision`);
    a clear discard makes no Auditor call (`test_clear_discard_makes_no_auditor_call`).
11. Interactive mode: editing `evaluate.py` or lowering `best.json` by hand
    is detected and refused (`test_tampering_is_refused`); `kl keep` refuses
    a heavy change without a matching audit verdict
    (`test_heavy_change_needs_a_matching_audit_verdict`); everything except
    `kl audit --vendor` runs with no AI CLI
    (`test_everything_but_audit_runs_with_no_ai_cli`).
12. A generic vendor gets the prompt on stdin and a scrubbed environment,
    and dangerous declarations are refused
    (`test_generic_cli_vendor_gets_stdin_and_a_scrubbed_env`,
    `test_generic_vendor_refuses_dangerous_declarations`).

**Honest limit of interactive mode.** In `kl` the user's AI has the same
file rights as `kl`. The fence snapshot (`fence.json`) and the `best.json`
seal are tamper-evident, not tamper-proof: an agent that rewrites the
snapshot too is not stopped. For unattended work use `run.py`, or an
OS-level sandbox.

## 8. Scout

Sources: GitHub search (repos created in the last 14 days for the topics),
Hacker News Algolia, arXiv cs.AI RSS. Stdlib `urllib`, 10 s timeout, a
failing source prints one line and is skipped; exit 0 offline.

Topics: the active pack's `scout_topics` (comma-separated in `pack.yaml`)
replace the generic queries (`ai-agents`, `llm`, `agentic-workflow`) and the
built-in terms; with no `scout_topics` the generic ones are used. The words
of `## Mission` in `program.md` are added to the terms.

`score = relevance x momentum x recency`. Relevance is
`min(1, matched terms / 4)`; momentum is `log1p(points + comments)` (HN) or
`log1p(stars / age_days)` (GitHub) divided by the max in the same source
(arXiv 1.0); recency is `exp(-age_days / 14)`. Titles lose control and
markdown-active characters and are capped at 200 characters; only `https`
URLs are written; responses are capped at 2 MB. `GITHUB_TOKEN`, if set, goes
only to `api.github.com`. `--dry-run` prints and writes nothing.

## 9. Packs and the rubric

`packs/<name>/pack.yaml` keys read by the code: `taste_file` (default
`taste.md`), `rubric_file` (default `rubric.md`), `scout_topics`, `roles`,
`slop`. Other keys (`profession`, `description`, `metric`,
`metric_validation`, `metric_examples`) are documentation.

- **Taste** (`taste.md`): injected whole into the Analyst, Engineer and
  Auditor prompts.
- **Rubric** (`rubric.md`): table `Criterion | Weight | Gate`. Total =
  weighted mean (0-100); a gate criterion under 50 caps the total at 49; no
  parsable scores gives `null` and a metric-only decision; a total more than
  5 below the best rubric blocks a keep. The mock vendor scores fixed
  70..90 values.
- **Roles** (specialists): each `roles.<name>` has `checklist: text` or
  `checklist_file: x.md` (must stay inside the pack folder). The checklists
  join the one audit call of heavy changes only; failed items carry the
  reviewer's name.
- **Slop**: `slop:` lines `name: regex => reason`, matched on lines the diff
  adds. A hit is a crash with a lesson before any model sees the change. An
  invalid regex is skipped with a warning.
- **`kl pack new NAME`**: scaffolds `pack.yaml`, `taste.md`, `rubric.md` full
  of TODOs (name `[a-z0-9-]`, refuses an existing folder). The first question
  is the metric: what automatic number, and how it was validated against real
  outcomes; without a metric the loop cannot learn.
- Optional `data/` and a search script (`packs/ui-design/search.py`, BM25).

Shipped: `software` (security and performance specialists, slop markers),
`ui-design` (searchable styles, palettes, fonts), `marketing-content` (stock
filler slop patterns).

## 10. Acceptance for a release

- `python prepare.py` succeeds on a clean clone and is idempotent.
- `python run.py --mock --iterations 5` exits 0 offline with keeps at cycles
  1, 2, 5, a discard at 3, a crash with lesson L-001 at 4, best metric 1.0
  (verdicts supported, supported, rejected, untested, supported).
- `python -m unittest discover -s tests` passes in both default and `-X utf8` mode (currently 138 tests).
- `python scout.py --dry-run` exits 0 online and offline (manual check, no
  test).
- `CHANGELOG.md` has a section for `prepare.__version__` (checked by
  `TestVersion`).
- `docs/DEMO-OUTPUT.txt` is regenerated from a fresh copy.
