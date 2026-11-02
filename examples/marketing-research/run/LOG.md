# Team log: what went wrong while building this example

This page is the credits and the honest record for the keeploop marketing-research worked example. The main [README](../README.md) is the consumer-insight report. This log is where the team's own performance lives, and it does not belong in the report.

## How the example was built

The user briefed a lead agent. The lead staffed an Analyst, an Engineer, an Auditor, a Tech agent and a Content agent. The Auditor always worked in a fresh context and judged each change against a written card, not against the lead's story.

We keep this log because the mistakes taught more than the results did. Each one below produced a rule. If you brief a similar project, the rules and the template at the end will save you the same detours.

Evidence for the keeploop cycle 2 (the insight report) is in `run/cycle-2/`. Evidence for cycle 1 (the questionnaire) is in `run/cycle-1/transcript.txt`, `run/cycle-1/audit-1.txt`, `run/cycle-1/card-1.md` and `run/cycle-1/cycle-1.diff`.

## Mistakes, in the order they happened

### 1. The wrong deliverable
- **What happened:** The first brief asked for a "worked example" and used rubric terms from questionnaire design (non-leading questions, scale choice, question flow). It named no data source and no end reader. The lead built and optimized a survey questionnaire. The real goal was a consumer-insight report. Later, when asked for Knaflic-style dashboards, the lead charted the keeploop run's scores (team performance) instead of consumer insight.
- **Why:** The brief used the vocabulary of one deliverable and never said who would read the result or what they would decide. The lead did not push back, even though a questionnaire with no fieldwork cannot produce consumer numbers.
- **Caught by:** The user.
- **Rules now:**
  - Name the end reader, the decision, and the data source before building.
  - Ask the lead to restate the deliverable in 3 lines and wait for OK.
  - Team performance belongs in a log or credits, not in the report.
  - The lead should flag when a deliverable cannot produce the numbers it implies.

### 2. The demo holdout file
- **What happened:** Starting the loop (`python kl.py begin`) refused. The demo `holdout.py` imported the demo scorer, which had been replaced.
- **Why:** We swapped in a profession scorer but left the demo's holdout file behind.
- **Caught by:** keeploop itself, at `begin`. It is recorded as lesson L-001 in `run/cycle-1/transcript.txt`.
- **Rule now:** When you swap in a profession scorer, delete or rewrite the demo `holdout.py` in the same step.

### 3. The Engineer's brief was wider than the card (cycle 1)
- **What happened:** The lead's instruction to the Engineer allowed edits to Objective and Analysis lines that the card said to keep.
- **Why:** The lead paraphrased the card instead of quoting it, and the paraphrase was looser.
- **Caught by:** The fresh-context Auditor, which judged the diff against the card and flagged a scope breach. See `run/cycle-1/audit-1.txt`.
- **Rule now:** An instruction to the Engineer may narrow a card, never widen it. Quote the card's CHANGE line and add nothing.

### 4. The score went up, but the audit failed (cycle 1)
- **What happened:** The score rose from 0.949106 to 0.959319, above the keep bar of 0.958597. But the survey was still about 1166 s long against a 600 s budget. The card's REJECT IF condition triggered, the Auditor replied CHANGES REQUESTED, `kl keep` refused, and the cycle was discarded.
- **Why:** The metric did not measure the survey length the card cared about.
- **Caught by:** The Auditor and the pre-registered REJECT IF. Numbers are in `run/cycle-1/transcript.txt` and `run/cycle-1/audit-1.txt`.
- **Rule now (L-002):** An improving metric never overrides a failed audit. Fix the cause and re-propose.

### 5. A wrong causal explanation
- **What happened:** The lead told the writers the N1 gain came from "deleting passing questions". The counts (38/41 before, 38/39 after) show that two failing questions were deleted.
- **Why:** The explanation sounded plausible and was never checked against the counts.
- **Caught by:** The Content agent, before publication.
- **Rule now:** Check any causal explanation against the raw counts before writing it down.

### 6. Reddit's own API was blocked
- **What happened:** Reddit's own JSON endpoints returned 403 to unauthenticated requests.
- **What we did:** The team used the public Arctic Shift archive of Reddit instead.
- **Caught by:** The lead agent's probe, before the crawl.

### 7. Fan communities bias the comparison
- **What happened:** Some brands have their own subreddit (Aritzia, Shein, Uniqlo). Zara and H&M had none with data.
- **Why it matters:** Brand subreddits are fan communities, so comparing them across brands is biased.
- **Caught by:** The lead agent, reading the crawl manifest.
- **Rules now:**
  - Every cross-brand number comes from general fashion subreddits, where each brand is searched the same way.
  - Brand-subreddit data is used only as within-brand context.
  - A cell under 30 is shown as "base too small" and never back-filled.

### 8. A crawl sized without timing it
- **What happened:** The team started a keyword crawl without timing the archive's search endpoint. At about 7 minutes per task it would have taken about 14 hours. It had been started in a way that left no handle to stop it, and the agent was not permitted to stop processes on the machine, so a human approved stopping it. The crawl was restarted with smaller time slices and shorter retries, under a 75-minute budget.
- **Why:** We guessed the cost instead of measuring one request.
- **Caught by:** The Tech agent, which reported itself blocked.
- **Rules now:**
  - Time one request per endpoint before sizing a crawl.
  - Start long jobs so they can be stopped.
  - Prefer short retries and smaller windows over long back-offs.
  - A smaller honest sample beats a late one.

### 9. The App Store feed came back empty
- **What happened:** Apple's review feed sometimes returned an empty page for a valid request.
- **Caught by:** The Tech agent, during the crawl.
- **Rule now:** Retry an empty page before treating it as the last one.

### 10. Blank charts and stale screenshots
- **What happened:** Interactive charts rendered blank because the chart library loaded after the chart code. Separately, a visual check once looked at a stale screenshot file.
- **Caught by:** The Tech agent, during visual checks.
- **Rules now:**
  - Load the chart library in the page head.
  - Write every check screenshot to a fresh file name.

### 11. A misleading caption
- **What happened:** An earlier GIF in this repo was captioned "Real output", but colors and typing delays had been added.
- **Caught by:** The QC reviewer.
- **Rule now:** Say what was added, for example "recorded from real output, colours added".

### 12. A re-run destroyed 200 real App Store reviews
- **What happened:** A re-run truncated the raw App Store file before the new fetch succeeded. The fetch returned empty feeds, and the 200 reviews collected earlier were lost. The final report therefore has store-level ratings only, with no review text.
- **Why:** The script opened the original file for writing first and fetched second.
- **Caught by:** The Tech agent.
- **Rule now:** Write raw data to a temp file and replace the original only on success.

### 13. Subreddit names compared case-sensitively
- **What happened:** r/Shein and r/Oldnavy were counted as general subreddits, so brand fan communities leaked into the cross-brand numbers.
- **Why:** The brand-subreddit list was matched against names with different capitalization.
- **Caught by:** The Tech agent, before the final analysis.
- **Rule now:** Compare source names case-insensitively.

### 14. The scorer saturated on the first real draft
- **What happened:** The first real draft scored 1.000 on the first version of the scorer, while it still held an unsourced claim about who posts on Reddit and a heading ("skew Gen Z") that its own intervals did not support. A score at the maximum leaves the loop nothing to keep.
- **Why:** The scorer had no check for either problem, and we recorded no baseline against a real draft first.
- **Caught by:** The lead agent, reading the draft.
- **Rules now:**
  - Score one real draft before recording a baseline.
  - If it saturates, add checks that leave headroom, with the human's approval, before `kl begin`.
  - Disclose that the scorer was tightened after the first score. Here two checks (B1, U1) were added and the draft was not changed; the README says so.

### 15. A quoted argument was typed unquoted
- **What happened:** The lead typed `python kl.py recall` with a multi-word query and no quotes. `kl` rejected it with "unrecognized arguments" and nothing was recorded.
- **Caught by:** `kl` itself, at the command line. It is visible in `run/cycle-2/transcript.txt`.
- **Rule now:** Pass a multi-word `recall` query as one quoted argument, then re-run.

### 16. Charts exposed two comparisons the intervals do not support
- **What happened:** Building charts from the kept report surfaced two comparisons that the intervals do not support. Module 5 says Zara is more negative than H&M, but their negative intervals overlap (14.8% to 22.5% vs 7.5% to 15.1%). Module 6 says Segment 1 is more negative than the Uniqlo-led group, but those intervals overlap too (12.9% to 23.1% vs 8.6% to 17.5%). Neither the score nor the Auditor had caught them.
- **Caught by:** The Tech agent's chart build, which asserts the interval behind each comparative claim.
- **Rule now:** A "more/higher than" claim needs non-overlapping intervals. Add a check for it before the next cycle.

### 17. The score saturated again after the keep
- **What happened:** After the keep the best score was 1.000000 and the bar 1.010000, so the known issues (the two above, the Summary's "positioned on trend", and the module 3 "shares overlap" wording) cannot be fixed through the loop until a human adds checks with headroom.
- **Rule now:** Plan the scorer's headroom before the cycle, not after.

### 18. Set iteration order changed between runs
- **What happened:** In the supplementary re-run, Python set iteration order differed from run to run, so an "unchanged" claim about the existing data could not be trusted by eye.
- **Caught by:** The Tech agent.
- **Rule now:** An "unchanged" claim needs sorted iteration and a byte-prefix check.

## How to brief this kind of work

Copy this template and fill the brackets.

- **GOAL:** Consumer insight report on [topic], for [reader], to decide [decision].
- **DATA:** [crawl Reddit/forums/reviews | real survey | desk research]; window [..]; market [..].
- **FINAL OUTPUT:** dynamic report (dashboard) + static report (PDF), style [Knaflic/consulting], with the supporting formulas.
- **KEEPLOOP IS USED TO:** score and improve [the insight report]; rubric: [..].
- **TEAM PERFORMANCE:** log/credits only.
- **RULES:** no invented numbers; every number traces to the data.
- **BEFORE STARTING:** restate the final deliverable in 3 lines and wait for my OK.

## Cycle 2 (insight report)

Evidence: `run/cycle-2/transcript.txt`, `card.md`, `audit.txt`, `cycle.diff`.

- **Card:** The draft's module 3 heading said age-reporting authors "skew Gen Z", though the Gen Z and Millennial intervals overlap (40.8% to 72.8% vs 24.7% to 56.3%). The limits also said Reddit "skews young, male and US" with no source. The card reworded the heading and deleted the clause, two lines in `report.md`.
- **Check:** `kl check` printed PASS (light tier, 1 file, 4 changed lines).
- **Eval:** Score 0.970000 to 1.000000. Only U1 changed, from 0/2 to 1/1. Keep bar 0.979700, sigma 0.000000.
- **Audit:** APPROVED. The diff matched the card word for word, and the new heading claims no more than `data/metrics.json` shows. The Auditor did not re-run the scorer.
- **Keep:** `KEPT cycle 1: metric 1.000000 (bar 0.979700); best is now 1.000000`. The report shows +0.030000 over baseline in 105 s of agent time (`kl` numbers cycles per sandbox, so this is cycle 1 there).
- **Open:** The score is saturated again (best 1.000000, bar 1.010000). The Summary's "positioned on trend" versus module 4 (style/trend tied to Uniqlo) is the next card. It was not run, and it cannot be kept until a human adds headroom to the score.
- **Minor audit notes:** "who posts there is not measured in this data" is slightly too absolute, and 11 of the 13 authors who gave a gender are female.
