"""Round 6 gaps: report/slow/timing, staff speed, debate, critic round, code map, recall."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import codemap  # noqa: E402
import ledger  # noqa: E402
import lessons  # noqa: E402
import vendors  # noqa: E402
from prepare import load_team  # noqa: E402
from test_core import run_with  # noqa: E402
from test_kl import Project, card  # noqa: E402


def timing(p, rows):
    with (p.state / "timing.jsonl").open("w", encoding="utf-8") as f:
        for i, r in enumerate(rows, 1):
            f.write(json.dumps({"cycle": i, **r}) + "\n")


class TestReportSlowStaffDebate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def started(self, **kw):
        p = Project(self._tmp.name, **kw)
        self.assertEqual(p.kl("begin"), 0, p.out)
        return p

    def test_report_slow_and_assert_cycle_under_use_the_timing_rows(self):
        p = self.started(edit_team=lambda t: t + "cycle_time_budget_s: 50\n")
        timing(p, [{"analyst": 5, "eval": 10}, {"analyst": 5, "eval": 90, "audit": 20}])
        self.assertEqual(p.kl("report"), 0)
        self.assertIn("analyst 10s, eval 100s, audit 20s", p.out)
        self.assertIn("slowest: eval (77%)", p.out)  # 100 of 130
        self.assertIn("last cycle: 115s", p.out)
        self.assertIn("cycles over the 50s budget: 2", p.out)
        self.assertEqual(p.kl("slow"), 0)
        self.assertIn("Bottleneck: eval", p.out)
        self.assertIn("report --assert-cycle-under 50", p.out)
        self.assertIn("kl.py lesson add", p.out)
        self.assertEqual(p.kl("report", "--assert-cycle-under", "100"), 1)
        self.assertEqual(p.kl("report", "--assert-cycle-under", "200"), 0)

    def test_staff_speed_picks_an_allowed_faster_model_and_keeps_max_run_tokens(self):
        edit = lambda t: t.replace("loop:\n", "loop:\n  max_run_tokens: 777\n", 1).replace(  # noqa: E731
            "  engineer:\n    vendor: mock", "  engineer:\n    vendor: mock\n    model: m-big", 1
        ) + "\nstaffing:\n  allow_models: m-small, m-big\n  max_tokens_per_role: 40000\n"
        p = self.started(edit_team=edit)
        self.assertEqual(p.kl("staff", "--goal", "speed", "--apply"), 0, p.out)
        team = load_team(p.work / "team.yaml")
        self.assertEqual(team["roles"]["engineer"]["model"], "m-small")
        self.assertIn("  max_run_tokens: 777\n", (p.work / "team.yaml").read_text())

    def test_debate_is_one_round_and_append_only(self):
        p = self.started(team_extra="heavy: config.json")
        self.assertEqual(p.card(), 0)
        crit = Path(self._tmp.name) / "crit.md"
        crit.write_text("OBJECTIONS: x\nSTRONGEST ALTERNATIVE: y\nREJECT-IF CHECK: z\n"
                        "VERDICT: revise\n", encoding="utf-8")
        reply = Path(self._tmp.name) / "reply.md"
        reply.write_text("KEEP: the objection does not apply", encoding="utf-8")
        self.assertEqual(p.kl("debate", "1", "--reply", str(reply)), 1)  # reply needs a critique
        self.assertEqual(p.kl("debate", "1", "--critic", str(crit)), 0, p.out)
        first = (p.state / "debate" / "1.md").read_text(encoding="utf-8")
        self.assertEqual(p.kl("debate", "1", "--critic", str(crit)), 1)  # no second critique
        self.assertEqual(p.kl("debate", "1", "--reply", str(reply)), 0, p.out)
        self.assertEqual(p.kl("debate", "1", "--reply", str(reply)), 1)  # no second reply
        text = (p.state / "debate" / "1.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith(first))  # append-only


class Counting(vendors.MockVendor):
    calls: list = []
    verdict = "VERDICT: revise"

    def complete(self, prompt, *, role, max_tokens, cwd=None):
        res = super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)
        if "You are the Critic" in prompt:
            self.calls.append("critic")
            res.text = f"OBJECTIONS: a\nSTRONGEST ALTERNATIVE: b\nREJECT-IF CHECK: c\n{self.verdict}"
        elif "A critic reviewed it" in prompt:
            self.calls.append("revision")
        return res


class TestCriticRound(unittest.TestCase):
    def count(self, extra, verdict="VERDICT: revise"):
        Counting.calls, Counting.verdict = [], verdict
        with tempfile.TemporaryDirectory() as tmp:
            run_with(Counting, tmp, 1, team_extra=extra)
        return list(Counting.calls)

    def test_light_cards_make_no_critic_call_heavy_ones_one_plus_one_revision(self):
        self.assertEqual(self.count(""), [])
        self.assertEqual(self.count("heavy: config.json"), ["critic", "revision"])
        self.assertEqual(self.count("heavy: config.json", "VERDICT: proceed"), ["critic"])


def git(ws, *args):
    subprocess.run(["git", "-C", str(ws), *args], check=True, capture_output=True)


class TestMapAndRecall(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name) / "ws"
        self.ws.mkdir()
        (self.ws / "a.py").write_text("def foo():\n    pass\n\nclass Bar:\n    def meth(self): pass\n")
        (self.ws / "b.py").write_text("from a import foo\n")
        (self.ws / "c.ts").write_text("import { x } from './a';\nexport function tsfn() {}\n")
        git(self.ws, "init", "-q")
        git(self.ws, "add", "-A")
        self.cache = Path(self._tmp.name) / "map.json"

    def test_incremental_by_content_hash(self):
        with mock.patch.object(codemap, "_parse", wraps=codemap._parse) as parse:
            codemap.build(self.ws, self.cache)
            self.assertEqual(parse.call_count, 3)
            parse.reset_mock()
            codemap.build(self.ws, self.cache)
            self.assertEqual(parse.call_count, 0)  # nothing changed
            (self.ws / "b.py").write_text("from a import foo\nx = 1\n")
            codemap.build(self.ws, self.cache)
            self.assertEqual([c.args[0] for c in parse.call_args_list], ["b.py"])

    def test_query_finds_the_def_and_its_importers(self):
        m = codemap.build(self.ws, self.cache)
        out = codemap.query(m, "foo")
        self.assertIn("defined: a.py (def foo)", out)
        self.assertIn("imported by a.py: b.py, c.ts", out)
        self.assertIn("c.ts", codemap.query(m, "tsfn"))
        self.assertIn("a.py: def foo, class Bar", codemap.render(m, 3000))  # top level only

    def test_recall_ranks_the_matching_lesson_first_and_prompt_injects_k(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            for i in range(10):
                lessons.record(state, what=f"filler event {i}", root_cause="noise",
                               guardrail=f"Rule number {i} about widgets", trigger_cycle=i)
            lessons.record(state, what="migration dropped a column", root_cause="no backup",
                           guardrail="Snapshot the database before any migration", trigger_cycle=11)
            ledger.append_row(state, {"cycle": 1, "status": "discard", "description": "tried caching"})
            top = lessons.recall(state, "database migration", 3)
            self.assertEqual(top[0][1]["ref"], "L-011")
            text = lessons.guardrails_text(state, "database migration", 4)
            self.assertLessEqual(text.count("- **L-"), 4)
            self.assertIn("L-011", text)
            self.assertEqual(lessons.guardrails_text(state, "x", 0).count("- **L-"), 11)  # no cap: all


class TestRecallChangeAndKlName(unittest.TestCase):
    def test_recall_finds_hypothesis_by_change_word_and_old_rows_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            import run as R
            R.record_hypothesis(state, 1, {"hypothesis": "lr 0.03 beats 0.01", "reject_if": "x",
                                           "change": "learning_rate 0.03 only"}, "supported", 1.0, 0.5)
            with (state / "hypotheses.jsonl").open("a", encoding="utf-8") as f:  # old row, no change
                f.write(json.dumps({"cycle": 2, "hypothesis": "old row", "verdict": "rejected"}) + "\n")
            top = lessons.recall(state, "learning_rate", 3)
            self.assertEqual(top[0][1]["ref"], "cycle 1")
            self.assertEqual(lessons.recall(state, "old", 3)[0][1]["ref"], "cycle 2")

    def test_kl_invocation_name_follows_argv0(self):
        import kl
        for argv0, want in (("/usr/bin/kl", "kl"), ("C:\\Scripts\\kl.exe", "kl"),
                            ("kl.py", "python kl.py"), ("python -m unittest", "python kl.py")):
            with mock.patch.object(sys, "argv", [argv0]):
                self.assertEqual(kl.kl(), want)


class TestSearchStillWorks(unittest.TestCase):
    def test_design_search_runs_through_the_shared_ranker(self):
        out = subprocess.run([sys.executable, "-I", str(ROOT / "packs/ui-design/search.py"),
                              "dark dashboard", "--top", "1"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("score", out.stdout)


if __name__ == "__main__":
    unittest.main()
