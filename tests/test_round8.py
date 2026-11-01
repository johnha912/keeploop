"""Round 8: kl check with no card (#9), refuted verdict (#8), measurement cards (#7),
eval_cmd for non-Python projects (#6).

Run:  python -X utf8 -m unittest discover -s tests
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import lessons  # noqa: E402
import run as run_mod  # noqa: E402
from test_core import make_project  # noqa: E402
from test_kl import Project, card  # noqa: E402

EXE = Path(sys.executable).as_posix()
MEASURE = "MEASUREMENT: yes\n"
READ_LR = "import json\nprint(json.load(open('config.json'))['learning_rate'])\n"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        self.side = Path(tempfile.mkdtemp())  # scorer scripts stay outside the fenced project
        self.addCleanup(lambda: shutil.rmtree(self.side, ignore_errors=True))

    def started(self, **kw):
        p = Project(self.tmp, **kw)
        self.assertEqual(p.kl("begin"), 0, p.out)
        return p

    def eval_cmd(self, source, name="score.py") -> str:
        """team.yaml line running `source` as a script; the outer quotes are one stripped pair."""
        path = self.side / name
        path.write_text(source, encoding="utf-8")
        return f"""eval_cmd: '"{EXE}" "{path.as_posix()}"'"""

    def hyps(self, p):
        return [json.loads(l) for l in (p.state / "hypotheses.jsonl").read_text().splitlines()]


class TestCheckWithNoCard(Base):
    def test_no_open_card_is_the_reported_cause_and_nothing_is_written(self):
        p = self.started()
        rows, cycle = len(p.rows()), (p.state / "cycle.json").exists()
        self.assertEqual(p.kl("check"), 1)
        self.assertIn("no open card", p.out)
        self.assertNotIn("no files were changed", p.out)
        self.assertEqual((len(p.rows()), (p.state / "cycle.json").exists()), (rows, cycle))

    def test_open_card_with_no_edit_still_says_no_files_were_changed(self):
        p = self.started()
        p.card()
        self.assertEqual(p.kl("check"), 1)
        self.assertIn("no files were changed", p.out)


class TestRefutedVerdict(Base):
    def test_discard_refuted_records_verdict_and_is_remembered(self):
        p = self.started()
        p.card(hyp="Setting momentum to 0.9 helps")
        self.assertEqual(p.kl("discard", "--refuted", "--reason", "premise check: no momentum key"), 0, p.out)
        self.assertEqual(self.hyps(p)[-1]["verdict"], "refuted")
        self.assertIn("verdict: refuted", p.rows()[-1]["description"])
        self.assertEqual(p.rows()[-1]["status"], "discard")
        self.assertIn("cycle 1 [refuted]", run_mod.already_tested(self.hyps(p)))
        self.assertIn("cycle 1 [refuted]", (p.kl("status"), p.out)[1])
        self.assertEqual(p.card(hyp="Setting momentum to 0.9 helps"), 1)  # a repeat is a duplicate
        self.assertIn("duplicate of cycle 1", p.out)
        self.assertEqual(p.kl("report"), 0)
        self.assertIn("refuted 1", p.out)

    def test_refuted_needs_a_reason_and_changes_nothing_without_it(self):
        p = self.started()
        p.card()
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("discard", "--refuted"), 1)
        self.assertIn("--reason", p.out)
        self.assertEqual(p.kl("discard", "--refuted", "--reason", "  "), 1)
        self.assertEqual(len(p.rows()), 1)  # no row
        self.assertEqual(json.loads((p.ws / "config.json").read_text())["learning_rate"], 0.03)  # no reset

    def test_a_crash_never_records_refuted(self):
        p = self.started(team_extra="protect: config.json")
        p.card()
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("check"), 1)  # protected path -> crash
        self.assertEqual(p.kl("discard", "--refuted", "--reason", "x"), 1)
        self.assertEqual(p.kl("discard", "--reason", "gate"), 0)
        self.assertEqual((p.rows()[-1]["status"], self.hyps(p)[-1]["verdict"]), ("crash", "untested"))

    def test_plain_discard_stays_untested_without_a_metric(self):
        p = self.started()
        p.card()
        self.assertEqual(p.kl("discard", "--reason", "gave up"), 0)
        self.assertEqual(self.hyps(p)[-1]["verdict"], "untested")


class TestMeasurementCard(Base):
    def mcard(self, p, **kw):
        return p.kl("card", "-", stdin=card(**kw) + MEASURE)

    def test_check_passes_with_no_diff_and_discard_is_refuted_without_a_lesson(self):
        p = self.started()
        self.assertEqual(self.mcard(p), 0, p.out)
        self.assertEqual(p.kl("check"), 0)
        self.assertIn("measurement card, no diff expected", p.out)
        before = len(lessons.load_lessons(p.state))
        self.assertEqual(p.kl("discard", "--reason", "measured: premise false"), 0, p.out)
        row = p.rows()[-1]
        self.assertEqual((row["status"], row["lesson_id"]), ("discard", ""))
        self.assertIn("verdict: refuted", row["description"])
        self.assertEqual(self.hyps(p)[-1]["verdict"], "refuted")
        self.assertEqual(len(lessons.load_lessons(p.state)), before)

    def test_a_measurement_card_that_edits_files_fails_check(self):
        p = self.started()
        self.mcard(p)
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("check"), 1)
        self.assertIn("measurement card must not edit files", p.out)

    def test_keep_refuses_a_measurement_card_even_with_a_gain(self):
        p = self.started()
        self.mcard(p)
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("keep"), 1)
        self.assertIn("nothing to keep", p.out)
        self.assertEqual(p.commits(), 1)

    def test_audit_refuses_a_measurement_card_without_leaving_a_crash(self):
        p = self.started()
        self.mcard(p)
        self.assertEqual(p.kl("audit", "--vendor", "mock"), 1)
        self.assertIn("no diff to audit", p.out)
        self.assertEqual(p.kl("discard", "--reason", "measured"), 0, p.out)
        self.assertEqual((p.rows()[-1]["status"], p.rows()[-1]["lesson_id"]), ("discard", ""))

    def test_cards_without_the_label_still_crash_on_an_empty_diff(self):
        p = self.started()
        p.card()
        self.assertEqual(p.kl("check"), 1)
        self.assertIn("no files were changed", p.out)
        self.assertEqual(p.kl("discard"), 0)
        self.assertEqual(p.rows()[-1]["status"], "crash")
        self.assertTrue(p.rows()[-1]["lesson_id"])
        self.assertEqual(self.hyps(p)[-1]["verdict"], "untested")
        self.assertFalse(run_mod.is_measurement(run_mod.parse_card(card() + "MEASUREMENT: no\n")))


class TestEvalCmd(Base):
    def spy(self):
        calls, orig = [], run_mod.evaluate_workspace

        def wrapper(r, w, script="evaluate.py", timeout=None, **kw):
            calls.append((script, kw.get("eval_cmd")))
            return orig(r, w, script, timeout, **kw)
        return calls, mock.patch.object(run_mod, "evaluate_workspace", wrapper)

    def test_eval_prints_the_metric_the_command_printed_with_cwd_in_the_workspace(self):
        p = self.started(team_extra=self.eval_cmd(READ_LR))
        self.assertAlmostEqual(json.loads((p.state / "best.json").read_text())["metric"], 0.01)
        p.card()
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("eval"), 0, p.out)
        self.assertIn("metric 0.030000", p.out)
        self.assertEqual(p.kl("keep"), 0, p.out)
        self.assertAlmostEqual(json.loads((p.state / "best.json").read_text())["metric"], 0.03)

    def test_failing_command_at_baseline_refuses_begin_with_no_best(self):
        p = Project(self.tmp, team_extra=self.eval_cmd("import sys\nsys.exit(3)\n"))
        self.assertEqual(p.kl("begin"), 1)
        self.assertIn("baseline evaluation failed", p.out)
        self.assertIsNone(json.loads((p.state / "best.json").read_text())["metric"])

    def test_failure_modes_after_a_good_baseline(self):
        good = self.eval_cmd(READ_LR)
        p = self.started(team_extra=good)
        best = (p.state / "best.json").read_bytes()
        p.card()
        p.edit(learning_rate=0.03)
        rows = len(p.rows())
        for src in ("import sys\nsys.exit(3)\n", "print('no metric here')\n", "", "raise SystemExit('boom')\n"):
            self.eval_cmd(src)  # rewrite the scorer outside the fenced root
            self.assertEqual(p.kl("eval"), 1, src)
            self.assertIn("FAIL evaluation crashed", p.out)
            self.assertEqual(p.kl("keep"), 1)
            self.assertEqual(((p.state / "best.json").read_bytes(), len(p.rows()), p.commits()),
                             (best, rows, 1))
        metric, err = run_mod.evaluate_workspace(p.work, p.ws, eval_cmd="no-such-program-keeploop")
        self.assertIsNone(metric)
        self.assertIn("eval_cmd could not start", err)
        metric, err = run_mod.evaluate_workspace(p.work, p.ws, eval_cmd="'unbalanced")
        self.assertEqual((metric, "not parseable" in err), (None, True))

    def test_timeout_is_a_crash(self):
        p = self.started(team_extra=self.eval_cmd(READ_LR))
        self.eval_cmd("import time\ntime.sleep(30)\n")
        metric, err = run_mod.evaluate_workspace(
            p.work, p.ws, timeout=1, eval_cmd=f'"{EXE}" "{(self.side / "score.py").as_posix()}"')
        self.assertEqual((metric, "timed out" in err), (None, True))

    def test_the_command_is_fenced_like_evaluate_py(self):
        p = Project(self.tmp, team_extra=self.eval_cmd(
            "open('../../planted.txt', 'w').write('x')\nprint(1.0)\n"))  # cwd = workspace -> project root
        self.assertEqual(p.kl("begin"), 2, p.out)  # fenced at the baseline too
        self.eval_cmd(READ_LR)
        (p.work / "planted.txt").unlink()
        self.assertEqual(p.kl("begin"), 0, p.out)
        self.eval_cmd("open('../../planted.txt', 'w').write('x')\nprint(1.0)\n")
        p.card()
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("eval"), 2, p.out)
        self.assertIn("fence was broken", p.out)

    def test_the_command_runs_with_secrets_scrubbed(self):
        src = "import os\nprint(1.0 if 'KL_TEST_API_KEY' in os.environ else 2.0)\n"
        with mock.patch.dict(os.environ, {"KL_TEST_API_KEY": "hunter2"}):
            p = self.started(team_extra=self.eval_cmd(src))
        self.assertEqual(json.loads((p.state / "best.json").read_text())["metric"], 2.0)

    def test_every_evaluation_call_site_passes_the_merged_value(self):
        calls, patch = self.spy()
        with patch:
            p = self.started(team_extra=self.eval_cmd(READ_LR) + "\nheavy: config.json")
            p.card()
            p.edit(learning_rate=0.03)
            self.assertEqual(p.kl("audit", "--vendor", "mock"), 0, p.out)  # audit's own eval
            verdict = self.side / "verdict.txt"
            verdict.write_text(p.out, encoding="utf-8")
            self.assertEqual(p.kl("eval"), 0, p.out)
            self.assertEqual(p.kl("keep", "--audit-verdict", str(verdict)), 0, p.out)  # keep + confirm
        want = f'"{EXE}" "{(self.side / "score.py").as_posix()}"'
        evals = [c for c in calls if c[0] == "evaluate.py"]
        self.assertGreaterEqual(len(evals), 6)  # 3 baseline + audit + eval + keep (+ confirm)
        self.assertTrue(all(c[1] == want for c in evals), evals)

    def test_headless_run_uses_it_and_holdout_is_never_replaced(self):
        work = Path(self.tmp)
        make_project(self.tmp, self.eval_cmd(READ_LR))
        calls, patch = self.spy()
        with patch, contextlib.redirect_stdout(io.StringIO()):
            run_mod.run(work, mock=True, iterations=1)
        evals = [c for c in calls if c[0] == "evaluate.py"]
        self.assertTrue(evals and all(c[1] for c in evals), calls)
        (work / "hold.py").write_text("print(7.0)\n", encoding="utf-8")
        ws = work / ".keeploop" / "workspace"
        self.assertEqual(run_mod.evaluate_workspace(work, ws, "hold.py", eval_cmd=evals[0][1]), (7.0, ""))

    def test_absent_key_changes_nothing(self):
        calls, patch = self.spy()
        with patch:
            p = self.started()
        self.assertTrue(calls and all(c[1] is None for c in calls))
        self.assertGreater(json.loads((p.state / "best.json").read_text())["metric"], 0)


class TestBootstrapInSync(unittest.TestCase):
    """#10: BOOTSTRAP.md carries AGENTS.md verbatim; editing one without the other fails here."""

    def test_agents_block_is_verbatim(self):
        boot = (ROOT / "BOOTSTRAP.md").read_text(encoding="utf-8")
        block = boot.split("<!-- BEGIN AGENTS.md (verbatim) -->\n", 1)[1].split("<!-- END AGENTS.md -->", 1)[0]
        self.assertEqual(block, (ROOT / "AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
