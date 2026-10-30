"""Core invariants for keeploop (docs/SPEC.md §6–§7).

Run:  python -X utf8 -m unittest discover -s tests
"""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evaluate  # noqa: E402
import ledger  # noqa: E402
import lessons  # noqa: E402
import packs  # noqa: E402
import rubric  # noqa: E402
import scout  # noqa: E402
import run as run_mod  # noqa: E402
import vendors  # noqa: E402
from prepare import CONTROL_RX, INITIAL_WORKSPACE, load_team  # noqa: E402

FAIL = [sys.executable, "-c", "import sys; sys.exit(1)"]
PASS = [sys.executable, "-c", "import sys; sys.exit(0)"]


def make_project(tmp: str, team_extra: str = "") -> Path:
    """A throwaway copy of the project (code, packs, charter, team.yaml)."""
    work = Path(tmp)
    for item in ROOT.iterdir():
        if item.suffix == ".py" or item.name in ("team.yaml", "program.md"):
            shutil.copy(item, work / item.name)
    shutil.copytree(ROOT / "packs", work / "packs")
    if team_extra:
        with (work / "team.yaml").open("a", encoding="utf-8") as f:
            f.write("\n" + team_extra + "\n")
    return work


def run_with(vendor_cls, tmp, iterations, team_extra="", before=None):
    """In-process run with MockVendor replaced by vendor_cls; returns (rc, work)."""
    work = make_project(tmp, team_extra)
    if before:  # set the workspace up first, then let the test plant things
        with contextlib.redirect_stdout(io.StringIO()):
            run_mod.setup(work)
        before(work)
    original = vendors.MockVendor
    vendors.MockVendor = vendor_cls
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = run_mod.run(work, mock=True, iterations=iterations)
    finally:
        vendors.MockVendor = original
    run_with.out = out.getvalue()  # console text of the last call
    return rc, work


class TestTeamYaml(unittest.TestCase):
    def test_shipped_team_yaml_parses(self):
        team = load_team(ROOT / "team.yaml")
        self.assertEqual(team["pack"], "software")
        self.assertEqual(team["workspace"], ".keeploop/workspace")
        self.assertIn("engineer", team["roles"])
        self.assertEqual(team["loop"]["max_iterations"], 20)


class TestLedger(unittest.TestCase):
    def test_append_and_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            ledger.append_row(state, {"cycle": 1, "status": "keep",
                                      "description": "first"})
            ledger.append_row(state, {"cycle": 2, "status": "crash",
                                      "description": "second"})
            rows = ledger.read_rows(state)
            self.assertEqual([r["status"] for r in rows], ["keep", "crash"])
            self.assertIn("second", ledger.tail_text(state, 1))

    def test_invalid_status_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ledger.append_row(Path(tmp), {"cycle": 1, "status": "shrug"})


class TestLessons(unittest.TestCase):
    def rec(self, state, guardrail="Validate ranges.", check=None):
        return lessons.record(state, what="dropout 1.5 crashed", root_cause="x",
                              guardrail=guardrail, trigger_cycle=4, check=check)

    def test_dedupe_retrigger_and_new_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            first = self.rec(state)
            again = self.rec(state)
            other = self.rec(state, guardrail="Something else.")
            self.assertEqual((first["id"], again["id"], other["id"]),
                             ("L-001", "L-001", "L-002"))
            rows = (state / "lessons.jsonl").read_text().splitlines()
            self.assertEqual(sum('"event"' in r for r in rows), 1)
            self.assertIn("Validate ranges", (state / "guardrails.md").read_text())

    def test_retrigger_extends_retire_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
            (state / "lessons.jsonl").write_text(json.dumps({
                "id": "L-001", "ts": old, "what": "w", "root_cause": "c",
                "guardrail": "g", "check": None, "status": "active"}) + "\n")
            self.assertEqual(lessons.active_lessons(state), [])
            lessons.retrigger(state, "L-001")
            self.assertEqual(len(lessons.active_lessons(state)), 1)

    def test_replay_runs_checks_in_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            self.rec(state, "pass rule", PASS)
            self.assertEqual(lessons.replay(state, state), [])
            bad = self.rec(state, "fail rule", FAIL)
            failures = lessons.replay(state, state)
            self.assertEqual([f[0] for f in failures], [bad["id"]])
            lessons.attach_check(state, bad["id"], ["no-such-binary-xyz"])
            self.assertEqual(len(lessons.replay(state, state)), 1)


class TestApproved(unittest.TestCase):
    def test_verdict_parsing(self):
        self.assertFalse(run_mod.approved("NOT APPROVED: scope creep"))
        self.assertFalse(run_mod.approved("CHANGES REQUESTED"))
        self.assertTrue(run_mod.approved("**APPROVED** ok"))
        self.assertTrue(run_mod.approved("\n> approved"))


class TestCliVendor(unittest.TestCase):
    def test_prompt_goes_on_stdin(self):
        v = vendors.CliVendor(
            "t", [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
            [], 30)
        self.assertTrue(v.available())
        self.assertEqual(v.complete('quote " and \'x\'\nline', role="analyst",
                                    max_tokens=1).text, 'QUOTE " AND \'X\'\nLINE')

    def test_missing_binary_is_unavailable(self):
        v = vendors.CliVendor("t", ["no-such-binary-xyz"], [], 5)
        self.assertFalse(v.available())
        with self.assertRaises(vendors.VendorUnavailable):
            v.complete("x", role="engineer", max_tokens=1)


class TestEvaluate(unittest.TestCase):
    def test_optimum_beats_initial(self):
        optimum = {"learning_rate": 0.03, "batch_size": 64,
                   "dropout": 0.2, "optimizer": "adam"}
        self.assertGreater(evaluate.score(optimum),
                           evaluate.score(INITIAL_WORKSPACE))
        self.assertAlmostEqual(evaluate.score(optimum), 1.0)

    def test_validation(self):
        self.assertIsNone(evaluate.validate(INITIAL_WORKSPACE))
        self.assertIsNotNone(evaluate.validate(
            {**INITIAL_WORKSPACE, "dropout": 1.5}))

    def test_cli_reads_workspace_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [sys.executable, str(ROOT / "evaluate.py"), tmp]
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 2)
            (Path(tmp) / "config.json").write_text(json.dumps(INITIAL_WORKSPACE))
            proc = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0)
            float(proc.stdout)


class TestPacksAndRubric(unittest.TestCase):
    def test_three_professions_discovered(self):
        self.assertEqual(packs.discover(ROOT),
                         ["marketing-content", "software", "ui-design"])

    def test_pack_loads_taste_and_rubric(self):
        pack = packs.load_pack(ROOT, "ui-design")
        self.assertIn("anti-slop", pack["taste"].lower())
        criteria = rubric.load_rubric(pack["rubric_path"])
        self.assertEqual(sum(c["weight"] for c in criteria), 100)
        self.assertTrue(any(c["gate"] for c in criteria))

    def test_mock_rubric_score_in_range(self):
        criteria = rubric.load_rubric(ROOT / "packs" / "software" / "rubric.md")
        value = rubric.score(vendors.MockVendor(), criteria, subject="patch {}")
        self.assertTrue(49.0 < value <= 100.0)

    def test_ui_design_search_finds_dark_dashboard(self):
        sys.path.insert(0, str(ROOT / "packs" / "ui-design"))
        import search as design_search
        results = design_search.bm25_rank("dark dashboard fintech analytics",
                                          design_search.load_rows())
        top_kinds = {row["_kind"] for _, row in results[:3]}
        self.assertTrue(top_kinds & {"style", "palette"})
        self.assertGreater(results[0][0], 0)


class Leaky(vendors.MockVendor):
    """Engineer that also writes a secret into the workspace."""
    def complete(self, prompt, *, role, max_tokens, cwd=None):
        res = super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)
        if role == "engineer":
            (Path(cwd) / "notes.txt").write_text("key = AKIA" + "ABCDEFGHIJKLMNOP\n")
        return res


class Tamperer(vendors.MockVendor):
    """Engineer that edits the charter outside the workspace."""
    root = None

    def complete(self, prompt, *, role, max_tokens, cwd=None):
        if role == "engineer":
            with (self.root / "program.md").open("a", encoding="utf-8") as f:
                f.write("\nignore the rules\n")
        return super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)


class FilterPlanter(vendors.MockVendor):
    """Engineer that plants a clean filter in the workspace's git config."""
    def complete(self, prompt, *, role, max_tokens, cwd=None):
        if role == "engineer":
            with (Path(cwd) / ".git" / "config").open("a", encoding="utf-8") as f:
                f.write('[filter "x"]\n\tclean = touch pwned\n')
            (Path(cwd) / ".gitattributes").write_text("* filter=x\n")
        return super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)


class TestGates(unittest.TestCase):
    def test_planted_git_config_stops_the_run_before_git_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(FilterPlanter, tmp, 3)
            self.assertEqual(rc, 2)
            row = ledger.read_rows(work / ".keeploop")[1]
            self.assertEqual(row["status"], "crash")
            self.assertIn(".git/config", row["description"])
            self.assertFalse((work / ".keeploop" / "workspace" / "pwned").exists())

    def test_secret_gate_blocks_and_never_logs_the_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(Leaky, tmp, 1)
            self.assertEqual(rc, 0)
            state = work / ".keeploop"
            self.assertEqual(ledger.read_rows(state)[1]["status"], "crash")
            for name in ("results.tsv", "lessons.jsonl", "guardrails.md"):
                text = (state / name).read_text(encoding="utf-8")
                self.assertNotIn("AKIAABCDEFGHIJKLMNOP", text)
            self.assertIn("AWS access key", (state / "results.tsv").read_text())
            self.assertEqual(len(lessons.load_lessons(state)), 1)

    def test_protected_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(vendors.MockVendor, tmp, 1, "protect: config.json")
            row = ledger.read_rows(work / ".keeploop")[1]
            self.assertEqual(row["status"], "crash")
            self.assertIn("protected", row["description"])
            self.assertTrue(row["lesson_id"])

    def test_tamper_fence_stops_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            Tamperer.root = Path(tmp).resolve()
            rc, work = run_with(Tamperer, tmp, 3)
            self.assertEqual(rc, 2)
            state = work / ".keeploop"
            rows = ledger.read_rows(state)
            self.assertEqual(len(rows), 2)  # baseline + the crash; run stopped
            self.assertEqual(rows[1]["status"], "crash")
            self.assertIn("program.md", rows[1]["description"])
            self.assertEqual(len(lessons.load_lessons(state)), 1)


class TestHardening(unittest.TestCase):
    def test_planted_hook_and_fsmonitor_never_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp).resolve() / "marker"

            def plant(work):
                ws = work / ".keeploop" / "workspace"
                (ws / ".git" / "hooks" / "post-commit").write_text(
                    f"#!/bin/sh\necho hook >> '{marker.as_posix()}'\n")
                subprocess.run(["git", "-C", str(ws), "config", "core.fsmonitor",
                                f"echo fsm >> '{marker.as_posix()}'"], check=True)
                # sanity: the plant does fire under plain git
                subprocess.run(["git", "-C", str(ws), "-c", "user.name=a", "-c",
                                "user.email=a@b", "commit", "-q", "--allow-empty",
                                "-m", "x"], check=True)
                subprocess.run(["git", "-C", str(ws), "status"], capture_output=True)
                self.assertTrue(marker.exists())
                marker.unlink()

            rc, work = run_with(vendors.MockVendor, tmp, 2, before=plant)
            self.assertEqual(rc, 0)
            rows = ledger.read_rows(work / ".keeploop")
            self.assertIn("keep", [r["status"] for r in rows[1:]])
            self.assertFalse(marker.exists())


class Down(vendors.Vendor):
    name = "down"

    def complete(self, prompt, *, role, max_tokens, cwd=None):
        raise vendors.VendorUnavailable("down")


class TestFallback(unittest.TestCase):
    def test_next_vendor_serves_and_is_reported(self):
        fb = vendors.FallbackVendor([Down(), vendors.MockVendor()])
        self.assertTrue(fb.complete("x", role="analyst", max_tokens=1).text)
        self.assertEqual(fb.served, "mock")
        with self.assertRaises(vendors.VendorUnavailable):
            vendors.FallbackVendor([Down()]).complete("x", role="analyst", max_tokens=1)

    def test_run_skips_missing_cli_and_logs_served_vendor(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = make_project(tmp)
            team = (work / "team.yaml").read_text(encoding="utf-8")
            (work / "team.yaml").write_text(
                team.replace("vendor: mock", "vendor: no-such-cli, mock"),
                encoding="utf-8")
            vendors.CLI_VENDORS["no-such-cli"] = (["no-such-binary-xyz"], [])
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = run_mod.run(work, mock=False, iterations=1)
            finally:
                del vendors.CLI_VENDORS["no-such-cli"]
            self.assertEqual(rc, 0)
            row = ledger.read_rows(work / ".keeploop")[1]
            self.assertIn("engineer=mock", row["role_vendors"])

    def test_runtime_fallback_inside_run(self):
        class FlakyFirst(vendors.MockVendor):
            name = "flaky"

            def complete(self, prompt, *, role, max_tokens, cwd=None):
                raise vendors.VendorUnavailable("boom")

        fb = vendors.FallbackVendor([FlakyFirst(), vendors.MockVendor()])
        self.assertEqual(fb.complete("x", role="auditor", max_tokens=1).text[:8], "APPROVED")
        self.assertEqual(fb.served, "mock")


class TestRepoMap(unittest.TestCase):
    def test_cap_and_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "ok.py").write_text("class A: pass\ndef f(): pass\n")
            (ws / "bad.py").write_text("def (:\n")
            for i in range(30):
                (ws / f"file_{i:02d}.txt").write_text("x")
            subprocess.run(["git", "-C", tmp, "init", "-q"], check=True)
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
            full = run_mod.repo_map(ws, 10_000)
            self.assertIn("ok.py: class A, def f", full)
            self.assertIn("bad.py", full)
            small = run_mod.repo_map(ws, 200)
            self.assertLessEqual(len(small), 200)
            self.assertRegex(small, r"\d+ more files omitted")


class TestRubricStable(unittest.TestCase):
    def test_mock_score_ignores_subject(self):
        criteria = rubric.load_rubric(ROOT / "packs" / "software" / "rubric.md")
        self.assertEqual(rubric.score(vendors.MockVendor(), criteria, subject="one"),
                         rubric.score(vendors.MockVendor(), criteria, subject="two"))


class FakeResp:
    last_read = None  # the size the caller asked for

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        FakeResp.last_read = n
        return self.body.encode()[:None if n < 0 else n]


class TestScout(unittest.TestCase):
    def fetch_with(self, fn, payload):
        orig = scout._fetch
        scout._fetch = lambda url, as_json=True: payload
        try:
            return fn()
        finally:
            scout._fetch = orig

    def test_scoring_order(self):
        yesterday = scout._now().timestamp() - 86400
        hits = [{"title": t, "url": u, "points": p, "num_comments": c,
                 "created_at_i": yesterday} for t, u, p, c in (
            ("Big agent workflow eval", "https://a.example/1", 500, 200),
            ("Small agent workflow eval", "https://a.example/2", 5, 0))]
        items = self.fetch_with(scout.fetch_hn, {"hits": hits})
        items = list({i["url"]: i for i in items}.values())  # as main() does
        ranked = scout.rank(items, scout.TERMS)
        self.assertEqual(ranked[0]["url"], "https://a.example/1")
        self.assertAlmostEqual(ranked[0]["mom"], 1.0)
        self.assertLess(ranked[1]["mom"], 1.0)
        old = scout.rank([{**items[0], "age": 60.0}], scout.TERMS)[0]
        self.assertLess(old["score"], ranked[0]["score"])

    def test_arxiv_xml_and_mission_terms(self):
        xml = ("<rss><channel><item><title>Agent eval</title>"
               "<link>https://arxiv.org/abs/1</link>"
               "<description>&lt;p&gt;LLM&lt;/p&gt;</description></item></channel></rss>")
        items = self.fetch_with(scout.fetch_arxiv, xml)
        self.assertEqual((items[0]["signal"], items[0]["summary"]), (1.0, "LLM"))
        words = scout.mission_terms(ROOT / "program.md")
        self.assertIn("workflow", words)
        self.assertNotIn("improve", words)

    def test_sanitising(self):
        title = scout.clean_title("Hi [x](javascript:alert(1)) <b>!`*_#|\x07\n" + "a" * 300)
        self.assertNotRegex(title, r"[\[\]()<>!`*_#|\x00-\x1f]")
        self.assertLessEqual(len(title), 200)
        self.assertIsNone(scout.safe_url("http://x.example/"))
        self.assertIsNone(scout.safe_url("javascript:alert(1)"))
        self.assertIsNone(scout.safe_url("https://x.example/a b"))
        self.assertEqual(scout.safe_url("https://x.example/a"), "https://x.example/a")

    def test_bidi_and_c1_controls_stripped_and_response_capped(self):
        title = scout.clean_title("a‮evil⁦x⁩\x85y\x9bz‏")
        self.assertEqual(title, "a evil x y z")
        with mock.patch.object(scout, "_check_url"), mock.patch.object(
                scout, "_open", lambda req, timeout=None: FakeResp("{}")):
            scout._fetch("https://x.example/")
        self.assertEqual(FakeResp.last_read, 2_000_000)

    def test_github_token_only_to_api_github(self):
        seen = []

        def fake(req, timeout=None):
            seen.append((req.full_url, req.get_header("Authorization")))
            return FakeResp("{}")

        old_env = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = "tok123"
        try:
            with mock.patch.object(scout, "_check_url"), mock.patch.object(scout, "_open", fake):
                scout.fetch_github()
                scout.fetch_hn()
                scout.fetch_arxiv()
        finally:
            if old_env is None:
                del os.environ["GITHUB_TOKEN"]
            else:
                os.environ["GITHUB_TOKEN"] = old_env
        self.assertEqual(len(seen), 7)
        for url, auth in seen:
            want = "Bearer tok123" if url.split("/")[2] == "api.github.com" else None
            self.assertEqual(auth, want)


FULL_CARD = """hypothesis: Batch 64 is better
because the gradient is less noisy.
**ALTERNATIVES:** it is just the seed; a re-run tells them apart
Change: set batch_size to 64
EXPECT: metric rises
Reject If: metric does not beat best
MISSING: Which GPU do we train on?"""


class Prose(vendors.MockVendor):
    def complete(self, prompt, *, role, max_tokens, cwd=None):
        res = super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)
        if role == "analyst":
            res.text = "Great idea: try a higher learning rate, it should help a lot!"
        return res


class Capture(vendors.MockVendor):
    prompts: list = []

    def complete(self, prompt, *, role, max_tokens, cwd=None):
        res = super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)
        if role == "analyst":
            self.prompts.append(prompt)
            res.text = res.text.replace(
                "HYPOTHESIS: ", "HYPOTHESIS: Batch size 64 scores higher than 32. ")
        return res


class TestHypothesisFirst(unittest.TestCase):
    def test_parse_card(self):
        card = run_mod.parse_card(FULL_CARD)
        self.assertEqual(card["hypothesis"], "Batch 64 is better because the gradient is less noisy.")
        self.assertEqual(card["reject_if"], "metric does not beat best")
        self.assertIn("seed", card["alternatives"])
        self.assertIsNone(run_mod.parse_card(FULL_CARD.replace("Reject If", "Note")))
        self.assertIsNone(run_mod.parse_card(FULL_CARD.replace(
            "MISSING: Which GPU do we train on?", "MISSING:")))

    def test_prose_analyst_crashes_with_lesson(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(Prose, tmp, 1)
            state = work / ".keeploop"
            row = ledger.read_rows(state)[1]
            self.assertEqual((rc, row["status"]), (0, "crash"))
            self.assertTrue(row["lesson_id"])
            self.assertEqual(run_mod.read_hypotheses(state), [])

    def test_questions_deduped_and_none_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            for n, text in enumerate(["Which GPU?", "Which GPU?", "none", "N/A", "-",
                                      "What budget?"], 1):
                run_mod.ask_human(state, n, text)
            lines = (state / "questions.md").read_text().splitlines()
            self.assertEqual(lines, ["- (cycle 1) Which GPU?", "- (cycle 6) What budget?"])

    def test_human_hypothesis_offered_then_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = make_project(tmp)
            (work / "program.md").write_text(
                "## Mission\n\nx\n\n## Hypotheses to test\n\n"
                "- Batch size 64 scores higher than 32.\n\n## Other\n")
            Capture.prompts = []
            original = vendors.MockVendor
            vendors.MockVendor = Capture
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    run_mod.run(work, mock=True, iterations=2)
            finally:
                vendors.MockVendor = original
            marker = "Human hypotheses (test the first one not yet in the registry"
            self.assertIn(marker, Capture.prompts[0])
            self.assertIn("Batch size 64 scores higher than 32.", Capture.prompts[0])
            self.assertNotIn(marker, Capture.prompts[1])


class TestMockLoopEndToEnd(unittest.TestCase):
    def test_five_cycles_produce_ledger_lessons_and_improvement(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = make_project(tmp)
            env = {**os.environ, "PYTHONPATH": str(work), "PYTHONUTF8": "1"}
            for _ in range(2):  # idempotent
                subprocess.run([sys.executable, "prepare.py"], cwd=work, env=env,
                               check=True, capture_output=True, text=True)
            proc = subprocess.run(
                [sys.executable, "run.py", "--mock", "--iterations", "5"],
                cwd=work, env=env, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            state = work / ".keeploop"
            rows = ledger.read_rows(state)
            self.assertEqual(len(rows), 6)  # baseline + 5 cycles
            statuses = [r["status"] for r in rows[1:]]
            self.assertEqual(statuses, ["keep", "keep", "discard", "crash", "keep"])
            self.assertEqual([h["verdict"] for h in run_mod.read_hypotheses(state)],
                             ["supported", "supported", "rejected", "untested", "supported"])
            for wanted in ("keep", "discard", "crash"):
                self.assertIn(wanted, statuses)
            self.assertGreaterEqual(len(lessons.load_lessons(state)), 1)
            best = json.loads((state / "best.json").read_text())
            self.assertGreater(best["metric"], float(rows[0]["metric"]))
            ws = state / "workspace"
            log = subprocess.run(["git", "-C", str(ws), "log", "--oneline"],
                                 capture_output=True, text=True, check=True).stdout
            self.assertEqual(len(log.splitlines()), 1 + statuses.count("keep"))
            self.assertIn("initial workspace", log)
            status = subprocess.run(["git", "-C", str(ws), "status", "--porcelain"],
                                    capture_output=True, text=True, check=True).stdout
            self.assertEqual(status, "")
            self.assertEqual((work / "evaluate.py").read_bytes(),
                             (ROOT / "evaluate.py").read_bytes())

    def test_dirty_workspace_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = make_project(tmp)
            with contextlib.redirect_stdout(io.StringIO()):
                run_mod.setup(work)
                (work / ".keeploop" / "workspace" / "config.json").write_text("{}")
                self.assertEqual(run_mod.run(work, mock=True, iterations=1), 1)


KEY = "AKIA" + "IOSFODNN7EXAMPLE"  # shaped like an AWS key; split so scanners skip this file


def attacker(fn):
    """Mock engineer that also runs fn(workspace, root) once, on its first call."""
    class Attacker(vendors.MockVendor):
        done = False

        def complete(self, prompt, *, role, max_tokens, cwd=None):
            if role == "engineer" and not Attacker.done:
                Attacker.done = True
                fn(Path(cwd), Path(cwd).parents[1])
            return super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)
    return Attacker


def sh(*args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout


def commit_all(repo):
    sh("git", "add", "-A", cwd=repo)
    sh("git", "-c", "user.name=a", "-c", "user.email=a@b", "commit", "-qm", "x", cwd=repo)


def resume(sigma):
    """before-hook: a resumed run, best.json already holds the baseline and sigma."""
    def seed(work):
        ws = work / ".keeploop" / "workspace"
        (work / ".keeploop" / "best.json").write_text(json.dumps({
            "metric": 0.828178, "rubric": None, "sigma": sigma,
            "commit": sh("git", "rev-parse", "HEAD", cwd=ws).strip()}))
    return seed


class TestFence(unittest.TestCase):
    """QC's attacks on the fence, one test each: every one must stop the run (exit 2)."""

    def stopped(self, fn, *, team_extra="", before=None, needle="", after=None):
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(attacker(fn), tmp, 1, team_extra, before)
            rows = ledger.read_rows(work / ".keeploop")
            self.assertEqual(rc, 2, run_with.out)
            self.assertEqual(len(rows), 2)  # baseline + the crash; the run stopped
            self.assertEqual(rows[1]["status"], "crash")
            self.assertIn(needle, rows[1]["description"])
            self.assertIn("STOPPED", run_with.out)
            if after:
                after(work / ".keeploop" / "workspace")

    def test_same_size_edit_with_restored_mtime(self):
        def forge(ws, root):
            t = root / "team.yaml"
            st = t.stat()
            t.write_bytes(t.read_bytes().replace(b"max_iterations: 20", b"max_iterations: 99"))
            os.utime(t, ns=(st.st_atime_ns, st.st_mtime_ns))
        self.stopped(forge, needle="team.yaml")

    def test_lessons_rewritten_in_place_never_reaches_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp).resolve() / "pwned"

            def seed(work):
                lessons.record(work / ".keeploop", what="w", root_cause="x" * 400,
                               guardrail="g", trigger_cycle=None)

            def inject(ws, root):
                p = root / ".keeploop" / "lessons.jsonl"
                st, old = p.stat(), p.read_bytes()
                cmd = json.dumps([sys.executable, "-c", f"open({str(marker)!r}, 'w')"])
                new = old.replace(b'"check": null', b'"check": ' + cmd.encode(), 1)
                new = new.replace(b"x" * (len(new) - len(old)), b"", 1)  # same size
                self.assertEqual(len(new), len(old))
                p.write_bytes(new)
                os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
            with tempfile.TemporaryDirectory() as tmp2:
                rc, work = run_with(attacker(inject), tmp2, 1, before=seed)
                self.assertEqual(rc, 2)
                self.assertIn("lessons.jsonl", ledger.read_rows(work / ".keeploop")[1]["description"])
            self.assertFalse(marker.exists())

    def test_root_git_hook_and_pycache_plant(self):
        def hook(ws, root):
            (root / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\necho pwned\n")

        def pyc(ws, root):
            (root / "__pycache__").mkdir(exist_ok=True)
            (root / "__pycache__" / "x.pyc").write_bytes(b"x")
        self.stopped(hook, needle="pre-commit",
                     before=lambda work: sh("git", "init", "-q", cwd=work))
        self.stopped(pyc, needle="x.pyc")

    def test_evaluation_runs_inside_the_fence(self):
        def edit_eval(work):  # an evaluation that runs a hook the workspace provides
            src = (ROOT / "evaluate.py").read_text(encoding="utf-8")
            (work / "evaluate.py").write_text(
                "import pathlib, sys\nh = pathlib.Path(sys.argv[1]) / 'hook.py'\n"
                "if h.exists():\n    exec(h.read_text())\n" + src, encoding="utf-8")

        def plant(ws, root):
            (ws / "hook.py").write_text(
                f"open({str(root / 'team.yaml')!r}, 'a').write('# pwned')\n")
        # no git ran afterwards: the plant was not cleaned up
        self.stopped(plant, before=edit_eval, needle="team.yaml",
                     after=lambda ws: self.assertTrue((ws / "hook.py").exists()))

    def test_baseline_evaluation_runs_inside_the_fence(self):
        def edit_eval(work):
            src = (work / "evaluate.py").read_text(encoding="utf-8")
            (work / "evaluate.py").write_text(
                "open('program.md', 'a').write('x')\n" + src, encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            work = make_project(tmp)
            edit_eval(work)
            cwd = os.getcwd()
            os.chdir(work)  # the planted line writes a relative path
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(run_mod.run(work, mock=True, iterations=1), 2)
            finally:
                os.chdir(cwd)

    def test_lesson_check_runs_inside_the_fence(self):
        def seed(work):
            code = f"open({str(work / 'team.yaml')!r}, 'a').write('# pwned')"
            lessons.record(work / ".keeploop", what="w", root_cause="c", guardrail="g",
                           trigger_cycle=None, check=[sys.executable, "-c", code])
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(vendors.MockVendor, tmp, 1, before=seed)
            self.assertEqual(rc, 2)
            row = ledger.read_rows(work / ".keeploop")[1]
            self.assertIn("team.yaml", row["description"])
            self.assertEqual(row["status"], "crash")

    def test_skip_worktree_cannot_hide_a_protected_edit(self):
        def seed(work):
            ws = work / ".keeploop" / "workspace"
            (ws / "locked.txt").write_text("orig\n")
            commit_all(ws)

        def hide(ws, root):
            sh("git", "update-index", "--skip-worktree", "locked.txt", cwd=ws)
            (ws / "locked.txt").write_text("TAMPERED\n")
        def untouched(ws):  # nothing was kept or reset
            self.assertEqual(sh("git", "rev-list", "--count", "HEAD", cwd=ws).strip(), "2")
            self.assertEqual((ws / "locked.txt").read_text(), "TAMPERED\n")
        self.stopped(hide, before=seed, team_extra="protect: locked.txt",
                     needle="locked.txt", after=untouched)

    def test_index_flags_and_protected_dirty_see_through_assume_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            sh("git", "init", "-q", cwd=ws)
            (ws / "sub").mkdir()
            (ws / "keep.txt").write_text("a\n")
            (ws / "sub" / "x.lock").write_text("a\n")
            commit_all(ws)
            self.assertEqual(run_mod.index_flags(ws), [])
            self.assertEqual(run_mod.protected_dirty(ws, ["*.lock", "keep.txt"]), [])
            sh("git", "update-index", "--assume-unchanged", "sub/x.lock", cwd=ws)
            (ws / "sub" / "x.lock").write_text("b\n")
            (ws / "keep.txt").unlink()
            self.assertEqual(run_mod.index_flags(ws), ["sub/x.lock"])
            self.assertEqual(sh("git", "status", "--porcelain", cwd=ws).count("x.lock"), 0)
            self.assertEqual(sorted(run_mod.protected_dirty(ws, ["*.lock", "keep.txt"])),
                             ["keep.txt", "sub/x.lock"])


class TestSecretGate(unittest.TestCase):
    def blocked(self, files, kind="AWS access key", **kw):
        def plant(ws, root):
            for name, data in files.items():
                (ws / name).write_bytes(data)
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(attacker(plant), tmp, 1, **kw)
            row = ledger.read_rows(work / ".keeploop")[1]
            self.assertEqual((rc, row["status"]), (0, "crash"), row)
            self.assertIn(kind, row["description"])
            for name in ("results.tsv", "lessons.jsonl", "guardrails.md"):
                self.assertNotIn(KEY, (work / ".keeploop" / name).read_text(encoding="utf-8"))

    def test_plus_plus_line_is_not_a_header(self):
        self.blocked({"n.txt": f"++ {KEY}\n".encode()})

    def test_binary_and_nul_padded_files_are_scanned(self):
        self.blocked({"b.bin": b"\x00" + KEY.encode() + b"\x00"})
        self.blocked({"u.txt": f"k={KEY}\n".encode("utf-16")})

    def test_diff_attribute_does_not_blind_the_scan(self):
        self.blocked({".gitattributes": b"*.txt -diff\n",
                      "n.txt": KEY.encode() + b"\n" + b"x\n" * 5000})

    def test_diff_attribute_and_binary_do_not_dodge_the_size_cap(self):
        for files in ({".gitattributes": b"*.txt -diff\n", "n.txt": b"x\n" * 20_000},
                      {"b.bin": b"\x00" * 40_000}):
            def plant(ws, root, files=files):
                for name, data in files.items():
                    (ws / name).write_bytes(data)
            with tempfile.TemporaryDirectory() as tmp:
                rc, work = run_with(attacker(plant), tmp, 1)
                row = ledger.read_rows(work / ".keeploop")[1]
                self.assertEqual(row["status"], "discard")
                self.assertIn("exceeds", row["description"])

    def test_secret_file_names_any_case(self):
        names = [".ENV", "prod.env", ".env.local", ".Npmrc", ".pypirc", ".netrc", "a.PEM",
                 "k.key", "c.p12", "c.pfx", "ID_RSA", "id_dsa", "id_ecdsa", "id_ed25519",
                 "Credentials-prod.json", "sub/dir/.env"]
        with tempfile.TemporaryDirectory() as tmp:
            hits = run_mod.scan_secrets(Path(tmp), names)
            self.assertEqual(sorted(f for _, f in hits), sorted(names))
            self.assertEqual(run_mod.scan_secrets(Path(tmp), ["env.py", "keys.txt", "a.json"]), [])

    def test_auditor_sees_binary_content(self):
        seen = []

        class Spy(vendors.MockVendor):
            def complete(self, prompt, *, role, max_tokens, cwd=None):
                if role == "engineer":
                    (Path(cwd) / "b.bin").write_bytes(b"\x00visible-line\x00")
                if role == "auditor":
                    seen.append(prompt)
                return super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)
        with tempfile.TemporaryDirectory() as tmp:
            run_with(Spy, tmp, 1)
        self.assertIn("visible-line", seen[0])


class TestEnvironment(unittest.TestCase):
    ENV = {"GITHUB_TOKEN": "t", "MY_PASSWORD": "p", "AWS_ACCESS_KEY_ID": "a",
           "ANTHROPIC_API_KEY": "k", "CLAUDE_CODE_OAUTH_TOKEN": "o", "OPENAI_API_KEY": "k2",
           "PLAIN_VAR": "ok"}

    def test_safe_env(self):
        with mock.patch.dict(os.environ, self.ENV):
            self.assertEqual({k for k in vendors.safe_env() if k in self.ENV}, {"PLAIN_VAR"})
            kept = vendors.safe_env(("ANTHROPIC_", "CLAUDE_"))
            self.assertEqual({k for k in kept if k in self.ENV},
                             {"PLAIN_VAR", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"})
        self.assertEqual(vendors.ENV_KEEP["codex-cli"], ("OPENAI_", "CODEX_"))
        self.assertEqual(vendors.get_vendor("gemini-cli").env_keep,
                         ("GEMINI_", "GOOGLE_", "GOOGLE_GENAI_"))

    def test_cli_vendor_evaluation_and_checks_get_the_safe_env(self):
        code = "import os; print(sorted(k for k in os.environ if k in %r))" % (tuple(self.ENV),)
        with mock.patch.dict(os.environ, self.ENV), tempfile.TemporaryDirectory() as tmp:
            v = vendors.CliVendor("t", [sys.executable, "-c", code], [], 30, ("ANTHROPIC_",))
            self.assertEqual(v.complete("x", role="analyst", max_tokens=1).text,
                             "['ANTHROPIC_API_KEY', 'PLAIN_VAR']")
            root = Path(tmp)
            (root / "evaluate.py").write_text(
                "import os\nprint(1.0 if 'GITHUB_TOKEN' not in os.environ else 0.0)\n")
            self.assertEqual(run_mod.evaluate_workspace(root, root), (1.0, ""))
            lessons.record(root, what="w", root_cause="c", guardrail="g", trigger_cycle=None,
                           check=[sys.executable, "-c",
                                  "import os, sys; sys.exit('GITHUB_TOKEN' in os.environ)"])
            self.assertEqual(lessons.replay(root, root), [])


class TestProtect(unittest.TestCase):
    def test_normalised_globbed_and_case_insensitive(self):
        protect = run_mod.parse_protect(r" ./Tests\, *.LOCK ,docs/, ./ ,Sub/Dir//")
        self.assertEqual(protect, ["tests", "*.lock", "docs", "sub/dir"])
        for path in ("tests/a.py", "TESTS/A.py", "a/b/Cargo.lock", "docs", "sub/dir/x"):
            self.assertTrue(run_mod.is_protected(path, protect), path)
        for path in ("testsx/a.py", "lock.txt", "doc/a", "sub/other"):
            self.assertFalse(run_mod.is_protected(path, protect), path)

    def test_absolute_or_parent_entries_are_a_startup_error(self):
        for bad in ("/etc", "C:\\x", "c:x", "a/../b", "..", "\\\\srv\\share", "./../x"):
            with self.assertRaises(ValueError, msg=bad):
                run_mod.parse_protect("ok, " + bad)
        with tempfile.TemporaryDirectory() as tmp:
            work = make_project(tmp, "protect: ../outside")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(run_mod.run(work, mock=True, iterations=1), 1)
            self.assertIn("protect", out.getvalue())

    def test_glob_gate_in_a_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(vendors.MockVendor, tmp, 1, "protect: *.JSON")
            row = ledger.read_rows(work / ".keeploop")[1]
            self.assertEqual(row["status"], "crash")
            self.assertIn("protected", row["description"])


class TestEvalErrorText(unittest.TestCase):
    def test_control_characters_never_reach_lessons_or_ledger(self):
        def evil_eval(work):
            src = (work / "evaluate.py").read_text(encoding="utf-8")
            (work / "evaluate.py").write_text(src.replace(
                'print(f"INVALID WORKSPACE: {error}"',
                'print(f"\\x1b[2J\\u202e\\x9bINVALID WORKSPACE: {error}"'), encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(vendors.MockVendor, tmp, 4, before=evil_eval)
            state = work / ".keeploop"
            self.assertEqual(ledger.read_rows(state)[4]["status"], "crash")
            texts = [r["description"] for r in ledger.read_rows(state)]
            texts += [l["what"] for l in lessons.load_lessons(state)]
            self.assertTrue(any("INVALID WORKSPACE" in t for t in texts))
            for t in texts:
                self.assertIsNone(re.search(CONTROL_RX, t), repr(t))


class TestNoise(unittest.TestCase):
    def test_bar(self):
        self.assertAlmostEqual(run_mod.keep_bar(0.5, 0.0, 2.0, 0.01), 0.52)
        self.assertAlmostEqual(run_mod.keep_bar(0.5, 0.1, 2.0, 0.01), 0.55)
        self.assertAlmostEqual(run_mod.keep_bar(0.5, 0.0, 2.0, 0.0), 0.5)

    def test_sigma_measured_at_baseline_and_zero_when_deterministic(self):
        def noisy(work):
            src = (work / "evaluate.py").read_text(encoding="utf-8")
            (work / "evaluate.py").write_text(
                "import random\n" + src.replace(
                    'print(f"{score(cfg):.6f}")',
                    'print(f"{score(cfg) + random.uniform(-0.02, 0.02):.6f}")'),
                encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(vendors.MockVendor, tmp, 0, before=noisy)
            best = json.loads((work / ".keeploop" / "best.json").read_text())
            self.assertGreater(best["sigma"], 0)
            self.assertRegex(run_with.out, r"sigma = 0\.0\d+ \(3 runs\)")
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(vendors.MockVendor, tmp, 0)
            self.assertEqual(json.loads((work / ".keeploop" / "best.json").read_text())["sigma"], 0)
            self.assertIn("sigma = 0.000000", run_with.out)

    def test_noise_raises_the_bar_for_a_keep(self):
        for sigma, status in ((0.0, "keep"), (0.5, "discard")):  # demo gain is +0.11
            with tempfile.TemporaryDirectory() as tmp:
                rc, work = run_with(vendors.MockVendor, tmp, 1, before=resume(sigma))
                self.assertEqual(ledger.read_rows(work / ".keeploop")[0]["status"], status)


class Everything(vendors.MockVendor):
    """Records every prompt, whatever the role."""
    prompts: list = []

    def complete(self, prompt, *, role, max_tokens, cwd=None):
        self.prompts.append(prompt)
        return super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)


class TestHoldout(unittest.TestCase):
    def test_demo_scores_a_different_optimum(self):
        import holdout
        best_eval = {"learning_rate": 0.03, "batch_size": 64, "dropout": 0.2, "optimizer": "adam"}
        self.assertLess(holdout.score(best_eval), 1.0)
        self.assertAlmostEqual(holdout.score({**best_eval, "dropout": 0.25}), 1.0)
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [sys.executable, str(ROOT / "holdout.py"), tmp]
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 2)
            (Path(tmp) / "config.json").write_text(json.dumps({**best_eval, "dropout": 1.5}))
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 2)

    def test_numbers_never_reach_a_prompt_or_the_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            Everything.prompts = []
            rc, work = run_with(Everything, tmp, 5)
            state = work / ".keeploop"
            self.assertEqual(rc, 0)
            held = json.loads((state / "holdout.json").read_text())
            self.assertEqual(sorted(held), ["baseline", "eval_baseline", "eval_final", "final"])
            self.assertGreater(held["final"], held["baseline"])
            self.assertEqual(held["eval_final"], 1.0)
            self.assertRegex(run_with.out, r"holdout: 0\.818\d+ -> 0\.998\d+ \(\+0\.17\d+\); evaluation")
            self.assertNotIn("WARNING", run_with.out)
            hay = "\n".join(Everything.prompts) + "".join(
                p.read_text(encoding="utf-8") for p in state.iterdir()
                if p.is_file() and p.name != "holdout.json")
            self.assertGreater(len(Everything.prompts), 10)
            for key in ("baseline", "final"):
                self.assertNotIn(f"{held[key]:.6f}", hay)
                self.assertNotIn(str(held[key]), hay)

    def test_overfitting_prints_a_warning(self):
        def inverted(work):  # holdout falls as the evaluation climbs
            (work / "holdout.py").write_text(
                "import json, sys\nfrom pathlib import Path\nfrom evaluate import score\n"
                "print(1 - score(json.loads((Path(sys.argv[1]) / 'config.json').read_text())))\n")
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(vendors.MockVendor, tmp, 2, before=inverted)
            self.assertEqual(rc, 0)
            self.assertIn("WARNING", run_with.out)
            self.assertIn("overfitting", run_with.out)

    def test_no_holdout_file_means_no_holdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(vendors.MockVendor, tmp, 1, before=lambda w: (w / "holdout.py").unlink())
            self.assertEqual(rc, 0)
            self.assertFalse((work / ".keeploop" / "holdout.json").exists())
            self.assertNotIn("holdout", run_with.out)

    def test_broken_holdout_stops_before_cycle_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(vendors.MockVendor, tmp, 1, before=lambda w: (w / "holdout.py").write_text("raise SystemExit(2)"))
            self.assertEqual(rc, 1)
            self.assertIn("baseline holdout failed", run_with.out)


class TestBudget(unittest.TestCase):
    def test_run_stops_after_the_cycle_that_reaches_the_ceiling(self):
        def tiny(work):
            t = (work / "team.yaml").read_text(encoding="utf-8")
            (work / "team.yaml").write_text(
                t.replace("  max_iterations: 20", "  max_iterations: 20\n  max_run_tokens: 1"),
                encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(vendors.MockVendor, tmp, 3, before=tiny)
            self.assertEqual(rc, 0)
            self.assertEqual(len(ledger.read_rows(work / ".keeploop")), 2)  # baseline + 1 cycle
            self.assertIn("run: budget reached", run_with.out)


class AuditorCount(vendors.MockVendor):
    """Counts auditor calls (and the prompts they got)."""
    prompts: list = []

    def complete(self, prompt, *, role, max_tokens, cwd=None):
        if role == "auditor" and "You are the Auditor" in prompt:  # critic calls: see test_kl
            self.prompts.append(prompt)
        return super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)


def count_evaluations(fn):
    """Run fn(); return how many times evaluate.py (not holdout.py) was run."""
    calls, orig = [], run_mod.evaluate_workspace
    run_mod.evaluate_workspace = lambda r, w, script="evaluate.py", timeout=None: (
        calls.append(script), orig(r, w, script, timeout))[1]
    try:
        fn()
    finally:
        run_mod.evaluate_workspace = orig
    return calls.count("evaluate.py")


def edit_team(old, new):
    def edit(work):
        t = (work / "team.yaml").read_text(encoding="utf-8")
        assert old in t
        (work / "team.yaml").write_text(t.replace(old, new), encoding="utf-8")
    return edit


class TestAuditOnlyWhenItMatters(unittest.TestCase):
    def test_clear_discard_makes_no_auditor_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            AuditorCount.prompts = []
            rc, work = run_with(AuditorCount, tmp, 5)
            rows = ledger.read_rows(work / ".keeploop")
            self.assertEqual([r["status"] for r in rows[1:]],
                             ["keep", "keep", "discard", "crash", "keep"])
            self.assertEqual(len(AuditorCount.prompts), 3)  # was 4: cycle 3 is a clear discard
            self.assertNotIn("audit:", rows[3]["description"])
            self.assertIn("verdict: rejected", rows[3]["description"])

    def test_one_audit_call_carries_verdict_and_rubric(self):
        criteria = rubric.load_rubric(ROOT / "packs" / "software" / "rubric.md")
        text = "APPROVED: fine\n" + "\n".join(f"{c['name']}: 80" for c in criteria)
        calls = []

        class Real(vendors.MockVendor):  # not a mock: its reply is parsed
            is_mock = False

            def complete(self, prompt, *, role, max_tokens, cwd=None):
                res = super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)
                if role == "auditor":
                    calls.append(prompt)
                    res.text = text
                return res
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(Real, tmp, 1)
            row = ledger.read_rows(work / ".keeploop")[1]
        self.assertEqual(row["status"], "keep")
        self.assertEqual(len(calls), 1)  # verdict and rubric from one reply
        self.assertIn("'Criterion: NN'", calls[0])
        self.assertIn("rubric: 80", row["description"])

    def test_parse_scores_total_and_gate(self):
        criteria = [{"name": "Visual hierarchy", "weight": 60, "gate": True},
                    {"name": "Typography", "weight": 40, "gate": False}]
        reply = "CHANGES REQUESTED\nvisual hierarchy: 80\nTypography = 60.5\nnoise 99"
        scores = rubric.parse_scores(reply, criteria)
        self.assertEqual(scores, {"Visual hierarchy": 80.0, "Typography": 60.5})
        self.assertAlmostEqual(rubric.total(scores, criteria), 72.2)
        self.assertEqual(rubric.total({"Visual hierarchy": 40, "Typography": 100}, criteria),
                         rubric.GATE_CAP)  # a failed gate caps the total
        self.assertIsNone(rubric.parse_scores("APPROVED", criteria))

        class Real(vendors.Vendor):
            pass
        self.assertAlmostEqual(rubric.reply_score(Real(), criteria, reply), 72.2)
        self.assertIsNone(rubric.reply_score(Real(), criteria, "APPROVED"))
        self.assertIsNone(rubric.reply_score(Real(), None, reply))
        self.assertEqual(rubric.reply_score(vendors.MockVendor(), criteria, ""),
                         rubric.score(vendors.MockVendor(), criteria, subject="x"))


class TestConfirmAndTier(unittest.TestCase):
    def evals(self, iterations=1, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            n = count_evaluations(lambda: run_with(vendors.MockVendor, tmp, iterations, **kw))
            return n, ledger.read_rows(Path(tmp) / ".keeploop")

    def test_light_deterministic_change_skips_the_confirm_run(self):
        n, rows = self.evals()
        self.assertEqual(n, 3 + 1)  # three baseline runs, one cycle, no confirm
        self.assertIn("tier: light", rows[1]["description"])

    def test_noise_forces_the_confirm_run(self):
        n, _ = self.evals(before=resume(0.0001))  # resumed: no baseline runs
        self.assertEqual(n, 2)

    def test_heavy_by_glob_and_by_size_always_confirms(self):
        n, rows = self.evals(before=edit_team("workspace:", "heavy: config.json\nworkspace:"))
        self.assertEqual(n, 3 + 2)
        self.assertIn("tier: heavy", rows[1]["description"])
        n, rows = self.evals(before=edit_team("  max_iterations: 20",
                                              "  max_iterations: 20\n  heavy_diff_lines: 1"))
        self.assertEqual(n, 3 + 2)
        self.assertIn("tier: heavy", rows[1]["description"])

    def test_tier_globs(self):
        heavy = run_mod.parse_protect(run_mod.DEFAULT_HEAVY, "heavy")
        for f in ("requirements.txt", "REQUIREMENTS-dev.txt", "pyproject.toml", "Cargo.lock",
                  "sub/package.json", "migrations/001_init.sql", ".github/workflows/ci.yml",
                  "Dockerfile", "go.mod"):
            self.assertTrue(run_mod.is_heavy([f], heavy), f)
        for f in ("src/app.py", "config.json", "README.md", "docs/migrations.md"):
            self.assertFalse(run_mod.is_heavy([f], heavy), f)
        self.assertTrue(run_mod.is_heavy(["a.py", "go.mod"], heavy))


class TestDuplicatePrecheck(unittest.TestCase):
    class Echo(vendors.MockVendor):
        """Always proposes the same hypothesis; the engineer always sets sgd (rejected)."""
        engineer_calls = 0
        different = ""

        def complete(self, prompt, *, role, max_tokens, cwd=None):
            if role == "engineer":  # own edit instead of the mock's script
                type(self).engineer_calls += 1
                path = Path(cwd) / "config.json"
                path.write_text(json.dumps({**json.loads(path.read_text()), "optimizer": "sgd"}))
                return vendors.VendorResult("done", 1, 1, "echo", 0.0)
            res = super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)
            if role == "analyst":
                res.text = ("HYPOTHESIS: Plain sgd beats adam on this toy run.\nCHANGE: set sgd\n"
                            "REJECT IF: the metric falls\nMISSING: none\n"
                            + (f"DIFFERENT: {self.different}\n" if self.different else ""))
            return res

    def go(self, different):
        class Echo(self.Echo):
            engineer_calls = 0
        Echo.different = different
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(Echo, tmp, 2)
            state = work / ".keeploop"
            return (Echo.engineer_calls, ledger.read_rows(state)[1:],
                    [h["verdict"] for h in run_mod.read_hypotheses(state)])

    def test_repeat_skips_the_engineer(self):
        calls, rows, verdicts = self.go("")
        self.assertEqual(calls, 1)
        self.assertEqual([r["status"] for r in rows], ["discard", "discard"])
        self.assertIn("duplicate of cycle 1", rows[1]["description"])
        self.assertEqual(rows[1]["metric"], "")
        self.assertEqual(verdicts, ["rejected", "duplicate"])

    def test_different_label_bypasses_it(self):
        calls, rows, verdicts = self.go("adds momentum")
        self.assertEqual(calls, 2)
        self.assertEqual(verdicts, ["rejected", "rejected"])

    def test_jaccard_and_card_label(self):
        self.assertEqual(run_mod.jaccard("The Cat, sat!", "the cat sat"), 1.0)
        self.assertAlmostEqual(run_mod.jaccard("a b c d", "a b c e"), 0.6)
        self.assertEqual(run_mod.jaccard("", ""), 0.0)
        self.assertEqual(run_mod.parse_card(FULL_CARD)["different"], "")
        self.assertEqual(run_mod.parse_card(FULL_CARD + "\nDIFFERENT: adds momentum")["different"],
                         "adds momentum")

    def test_demo_hypotheses_stay_below_the_threshold(self):
        v = vendors.MockVendor()
        hyps = [run_mod.parse_card(v.complete("x", role="analyst", max_tokens=1).text)["hypothesis"]
                for _ in vendors.MockVendor.PATCH_SCRIPT]
        worst = max(run_mod.jaccard(a, b) for i, a in enumerate(hyps) for b in hyps[i + 1:])
        self.assertLess(worst, 0.8)


class TestModelPerRole(unittest.TestCase):
    def test_model_reaches_argv_and_is_validated(self):
        code = "import sys; print(sys.argv[1:])"
        v = vendors.CliVendor("t", [sys.executable, "-c", code], [], 30, (), "good-model:1.5/x_y")
        self.assertEqual(v.complete("x", role="analyst", max_tokens=1).text,
                         "['--model', 'good-model:1.5/x_y']")
        v = vendors.CliVendor("t", [sys.executable, "-c", code], [], 30)
        self.assertEqual(v.complete("x", role="analyst", max_tokens=1).text, "[]")
        self.assertEqual(vendors.get_vendor("claude-cli", model="m1").model, "m1")
        for bad in ("a b", "x;rm", "", "a" * 81, "m\n", "$(x)"):
            with self.assertRaises(vendors.VendorUnavailable, msg=repr(bad)):
                vendors.get_vendor("claude-cli", model=bad)

    def test_bad_model_name_exits_1_even_for_the_mock(self):
        for key in ("model", "heavy_model"):
            with tempfile.TemporaryDirectory() as tmp:
                work = make_project(tmp)
                edit_team("  engineer:\n    vendor: mock", f"  engineer:\n    vendor: mock\n"
                          f"    {key}: bad name;x")(work)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(run_mod.run(work, mock=True, iterations=1), 1)
                self.assertIn("bad model name", out.getvalue())

    def test_auditor_heavy_model_serves_heavy_changes_only(self):
        used = []

        class Tagged(vendors.MockVendor):
            def __init__(self, model):
                super().__init__()
                self.model = model

            def complete(self, prompt, *, role, max_tokens, cwd=None):
                if role == "auditor" and "You are the Auditor" in prompt:  # not the critic
                    used.append(self.model)
                return super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)
        orig = vendors.get_vendor
        vendors.get_vendor = lambda name, *, timeout_s=240, model=None: Tagged(model)
        try:
            for team_extra, want in (("", "light-m"), ("heavy: config.json", "heavy-m")):
                used.clear()
                with tempfile.TemporaryDirectory() as tmp:
                    work = make_project(tmp, team_extra)
                    edit_team("  auditor:\n    vendor: mock",
                              "  auditor:\n    vendor: mock\n    model: light-m\n"
                              "    heavy_model: heavy-m")(work)
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(run_mod.run(work, mock=True, iterations=1), 0)
                self.assertEqual(used, [want])
        finally:
            vendors.get_vendor = orig


class TestTiming(unittest.TestCase):
    def test_cycle_line_and_summary_show_phase_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(vendors.MockVendor, tmp, 2)
            self.assertEqual(len(re.findall(
                r"^cycle \d+: .*  time a=\d+s e=\d+s v=\d+s q=\d+s$", run_with.out, re.M)), 2)
            self.assertRegex(run_with.out,
                             r"time: analyst \d+s, engineer \d+s, eval \d+s, audit \d+s")
            self.assertNotIn("time", ledger.read_rows(work / ".keeploop")[1]["description"])


class TestLessonReview(unittest.TestCase):
    def craft(self, state):
        now = datetime.now(timezone.utc)
        iso = lambda delta: (now - delta).isoformat(timespec="seconds")
        base = {"what": "w", "root_cause": "c", "guardrail": "g", "status": "active",
                "trigger_cycle": 1, "retired_ts": None}
        rows = [
            {**base, "id": "L-001", "ts": iso(timedelta(days=5)), "check": PASS},
            {**base, "id": "L-002", "ts": iso(timedelta(days=5)), "check": None},
            {"event": "retrigger", "id": "L-002", "ts": iso(timedelta(days=2))},
            {**base, "id": "L-003", "ts": iso(timedelta(days=5)), "check": None},
            {**base, "id": "L-004", "ts": iso(timedelta(hours=12)), "check": None},
        ]
        (state / "lessons.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        for i in range(1, 12):  # 10 clean cycles + one that carries L-003's own id
            ledger.append_row(state, {"cycle": i, "ts": iso(timedelta(days=1)), "status": "keep",
                                      "lesson_id": "L-003" if i == 1 else ""})
        ledger.append_row(state, {"cycle": 0, "ts": iso(timedelta(days=1)), "status": "keep"})

    def test_statuses_derived_from_ledger_and_lessons(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            self.craft(state)
            got = {l["id"]: (l["standing"], l["since"], l["retriggers"])
                   for l in lessons.review(state)}
            self.assertEqual(got, {"L-001": ("enforced", 11, 0), "L-002": ("ineffective", 11, 1),
                                   "L-003": ("effective", 10, 0), "L-004": ("provisional", 0, 0)})
            self.assertNotIn("standing", (state / "lessons.jsonl").read_text())  # derived only

    def test_cli_review_hints_at_a_check_for_ineffective_lessons(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.craft(Path(tmp))
            out = io.StringIO()
            with mock.patch.object(lessons, "STATE_DIR", Path(tmp)), \
                    contextlib.redirect_stdout(out):
                self.assertEqual(lessons.main(["review"]), 0)
            text = out.getvalue()
            self.assertIn("L-002  [ineffective]  re-triggered 1x", text)
            self.assertIn("attach a check: python lessons.py check L-002 -- <cmd>", text)
            self.assertNotIn("check L-003", text)

    def test_run_asks_a_human_once_and_prints_counts(self):
        def seed(work):
            state = work / ".keeploop"
            for _ in range(2):  # the same guardrail twice: a retrigger, no check
                lessons.record(state, what="w", root_cause="c", guardrail="g", trigger_cycle=1)
        with tempfile.TemporaryDirectory() as tmp:
            rc, work = run_with(vendors.MockVendor, tmp, 1, before=seed)
            qs = (work / ".keeploop" / "questions.md").read_text()
            self.assertIn("attach a check: python lessons.py check L-001 -- <cmd>", qs)
            self.assertIn("0 enforced, 1 ineffective, 0 effective, 0 provisional", run_with.out)
            run_mod.ask_human(work / ".keeploop", 9,
                              f"L-001 keeps recurring and its text did not stop it: "
                              f"{lessons.hint('L-001')}")
            self.assertEqual(len((work / ".keeploop" / "questions.md").read_text().splitlines()), 1)

    def test_enforced_lessons_are_not_rendered_into_guardrails(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            lessons.record(state, what="w", root_cause="c", guardrail="Text only.",
                           trigger_cycle=1)
            checked = lessons.record(state, what="w2", root_cause="c", guardrail="Has a check.",
                                     trigger_cycle=1, check=PASS)
            text = (state / "guardrails.md").read_text()
            self.assertIn("Text only.", text)
            self.assertNotIn("Has a check.", text)
            self.assertIn("Has a check.", (state / "lessons.jsonl").read_text())
            lessons.attach_check(state, "L-001", PASS)  # attaching later removes it too
            self.assertNotIn("Text only.", (state / "guardrails.md").read_text())
            self.assertEqual(lessons.replay(state, state), [])
            self.assertEqual(checked["id"], "L-002")


class TestVersion(unittest.TestCase):
    def test_version_is_semver_and_in_changelog(self):
        from prepare import __version__
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [{__version__}]", changelog)


if __name__ == "__main__":
    unittest.main()
