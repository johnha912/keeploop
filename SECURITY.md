# Security

keeploop is a **reference implementation** you copy and run on your own
machine. It ships with no warranty (see `LICENSE`). You are responsible for
which vendors you connect, which workspace you point it at, and what you let
those tools do. Read this page before you run it with a real AI vendor.

## What keeploop does on your machine

| It does | It does not |
|---|---|
| Run the vendor CLIs you name in `team.yaml` (the `claude`, `codex`, `gemini` presets or any CLI you declare under `vendors:`) as subprocesses, prompt on stdin, never through a shell. `kl` runs one only for `kl audit --vendor` | Install anything, phone home, or collect telemetry |
| Run `evaluate.py`, `holdout.py` and lesson check commands. These are your files, but they execute code the Engineer wrote in the workspace | Execute any text that came from a vendor reply or a web page |
| Edit, commit, reset, and `git clean -fd` inside the **workspace** you configure | Delete ignored files such as `.env` |
| Fetch `api.github.com`, `hn.algolia.com` and `export.arxiv.org` when you run `scout.py` / `kl scout`, and the https links in a file you pass to `kl cite`. Every fetch and redirect must stay https and resolve to a public address (no loopback, private, link-local or reserved hosts), with a 2 MB cap and a 10 s timeout. DNS rebinding between the check and the connection is not handled | Run anything it fetches; proposals and pages are only read as text |
| Send prompts, and the workspace diff, to the vendors you configured | Store or read API keys; each CLI keeps its own login |

It has zero third-party Python dependencies, so there is no package supply
chain to compromise.

## Guards built into the loop

1. **Fence.** Before and after every phase that runs code you did not
   write (vendor calls, the evaluation, the holdout, lesson checks), keeploop
   takes a SHA-256 of every file in the project folder outside the
   workspace (the evaluation, the charter, `team.yaml`, the state in
   `.keeploop/`, the project's own `.git` and `__pycache__`), plus the
   workspace's `.git/config`, `.git/info/` and `.git/hooks/`, and checks the
   workspace index for hidden-file flags (`skip-worktree`,
   `assume-unchanged`). Any difference stops the run with exit code 2, and
   no further git command runs in that workspace.
2. **Protected paths.** `protect:` in `team.yaml` lists workspace paths or
   globs (your tests, your eval data) that no change may touch. They are
   checked by content against the last commit, not only through the diff.
3. **Secret gate.** The full content of every added or modified file,
   binary files included, is scanned for common credential formats (AWS,
   GitHub, OpenAI/Anthropic, Google, Slack keys, private keys) and key file
   names (`.env`, `*.pem`, `*.key`, `id_rsa`, `.npmrc`, and others). A hit
   is a crash; the change is never evaluated or sent to another vendor, and
   the ledger records the kind of match and the file, never the value.
   Encoded or split secrets are not detected.
4. **Scrubbed environment.** Variables whose names look like tokens,
   secrets, passwords or keys are removed before a vendor CLI, the
   evaluation or a check starts. Each CLI keeps only its own vendor's
   variables (`ANTHROPIC_*` for claude, `OPENAI_*` for codex, `GEMINI_*` and
   `GOOGLE_*` for gemini). A custom vendor sees only the `env_keep`
   prefixes you declare, and even under those prefixes a secret-looking
   name is dropped unless you list its exact name under `env_allow`. The
   scout sends `GITHUB_TOKEN` to `api.github.com` only.
5. **Git hardening.** Every git call the loop makes disables hooks and
   fsmonitor; the diffs it reads disable external diff drivers and
   textconv.
6. **Edit rights only for the Engineer.** Analyst and Auditor CLIs run
   without edit flags.
7. **Clean start, clean revert.** The loop refuses a workspace with
   uncommitted changes, and discarded work is removed with
   `git reset --hard` + `git clean -fd`.

## What the guards do not cover

**Interactive mode.** When your own AI drives `kl`, it has the same file
rights as `kl`. `kl keep` re-runs every gate before it commits, but the
fence snapshot in `.keeploop/` is tamper-evident, not tamper-proof. Your
AI tool's permission prompts are the outer wall; keep them on. Review any
lesson check command your AI proposes, because it runs on every keep.

They detect; they do not contain. A vendor CLI with edit or command rights
runs with your user account's permissions, so it can **read** any file you
can and, if its mode allows network access, send it somewhere. The fence
watches the project folder only: if `workspace:` points outside it, the
rest of your disk is not watched. `evaluate.py`, `holdout.py` and lesson
checks run the Engineer's code, so treat a run like running an untrusted
pull request.

## Your side of the deal

- **Use a dedicated workspace.** Point `workspace:` at a separate clone or
  `git worktree` (`git worktree add ../myrepo-keeploop -b keeploop`), never
  at a checkout holding work you have not committed.
- **Keep secrets out of the workspace.** Anything in it can be read by the
  vendor CLIs and appears in diffs sent to the Auditor's vendor. Keep
  credentials in your environment or a secret manager.
- **Review each CLI's permission mode.** The Engineer runs with
  `--permission-mode acceptEdits` (claude), `--full-auto` (codex), or
  `--approval-mode auto_edit` (gemini). Read what those modes allow in the
  version you have installed; flags change between releases.
- **Run real vendors in a container or VM** when the machine holds anything
  you would not hand to a stranger's pull request.
- **Treat scout proposals as untrusted text.** They are titles and links
  from public sites. Read them yourself before acting on one.
- **Only add lesson checks you understand.** `python lessons.py check`
  stores a command that runs before every keep.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability
reporting on this repository (Security tab → "Report a vulnerability") with
steps to reproduce.
