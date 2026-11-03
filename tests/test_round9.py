"""Gaps the prompt-optimization example exposed: fence after a headless run, kl eval
after a failed gate, the confirm re-run in the record, scorer stderr for the Analyst.

Run:  python -X utf8 -m unittest discover -s tests
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import ledger  # noqa: E402
import run as run_mod  # noqa: E402
import vendors  # noqa: E402
from test_core import edit_team, resume, run_with  # noqa: E402
from test_kl import Project  # noqa: E402


def headless(p, iterations=1, vendor=vendors.MockVendor):
    original, vendors.MockVendor = vendors.MockVendor, vendor
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = run_mod.run(p.work, mock=True, iterations=iterations)
    finally:
        vendors.MockVendor = original
    return rc, out.getvalue()


def hyps(state):
    return [json.loads(l) for l in (state / "hypotheses.jsonl").read_text().splitlines()]


def low_confirm(value=0.1):
    """evaluate_workspace spy: the 2nd evaluate.py call of the process returns `value`."""
    calls, orig = [], run_mod.evaluate_workspace

    def spy(r, w, script="evaluate.py", timeout=None, **kw):
        res = orig(r, w, script, timeout, **kw)
        if script == "evaluate.py":
            calls.append(script)
            if len(calls) == 2:
                return value, ""
        return res
    return mock.patch.object(run_mod, "evaluate_workspace", spy)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name


class TestFenceAfterHeadlessRun(Base):
    def test_kl_works_on_the_state_a_headless_run_leaves(self):
        p = Project(self.tmp)
        rc, _ = headless(p, 2)
        self.assertEqual(rc, 0)
        self.assertTrue((p.state / "fence.json").exists())
        self.assertEqual(p.card(hyp="Setting dropout to 0.3 helps"), 0, p.out)
        p.edit(dropout=0.3)
        for cmd in ("check", "eval"):
            self.assertEqual(p.kl(cmd), 0, (cmd, p.out))
        self.assertEqual(p.kl("discard"), 0, p.out)

    def test_a_headless_run_never_launders_a_broken_fence(self):
        p = Project(self.tmp)
        self.assertEqual(p.kl("begin"), 0, p.out)
        sealed = (p.state / "fence.json").read_text()
        with (p.work / "program.md").open("a", encoding="utf-8") as f:
            f.write("\n<!-- changed outside kl -->\n")
        rc, out = headless(p, 1)
        self.assertEqual(rc, 0)
        self.assertEqual((p.state / "fence.json").read_text(), sealed)
        self.assertIn("fence.json left as it was", out)
        self.assertEqual(p.card(), 1)  # still refused until a human accepts the change

    def test_a_halt_then_a_rerun_never_seals_the_tamper(self):
        class Tamper(vendors.MockVendor):
            done = False

            def complete(self, prompt, *, role, max_tokens, cwd=None):
                if role == "engineer" and not Tamper.done:
                    Tamper.done = True
                    with (Path(cwd).parents[1] / "program.md").open("a", encoding="utf-8") as f:
                        f.write("\n<!-- written by an agent -->\n")
                    return vendors.VendorResult("done", 1, 1, "mock-1", 0.0)  # workspace stays clean
                return super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)
        p = Project(self.tmp)
        self.assertEqual(headless(p, 1, Tamper)[0], 2)
        rc, out = headless(p, 1)  # re-run without inspecting
        self.assertEqual(rc, 0)
        self.assertFalse((p.state / "fence.json").exists())
        self.assertIn("fence.json left as it was", out)
        self.assertEqual(p.kl("begin"), 1)  # kl begin does not seal it either
        self.assertEqual(p.kl("begin", "--accept-changes"), 0, p.out)  # a human accepts
        self.assertEqual(headless(p, 1)[0], 0)
        self.assertEqual(p.card(hyp="Setting dropout to 0.3 helps"), 0, p.out)


class TestEvalAfterFailedCheck(Base):
    def test_eval_refuses_while_a_gate_fails_and_runs_no_evaluation(self):
        p = Project(self.tmp, team_extra="protect: config.json")
        self.assertEqual(p.kl("begin"), 0, p.out)
        p.card()
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("check"), 1)
        calls, orig = [], run_mod.evaluate_workspace
        with mock.patch.object(run_mod, "evaluate_workspace",
                               lambda *a, **k: (calls.append(1), orig(*a, **k))[1]):
            self.assertEqual(p.kl("eval"), 1)
        self.assertIn("FAIL gate: protected path touched", p.out)
        self.assertEqual(calls, [])
        self.assertEqual(p.kl("discard"), 0, p.out)


class LongCards(vendors.MockVendor):
    """Long hypotheses and audit replies: the ledger description overflows 240 chars."""

    def complete(self, prompt, *, role, max_tokens, cwd=None):
        res = super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)
        if role == "analyst":
            res.text = res.text.replace("helps.", "helps, " + "because " * 30 + ".")
        elif role == "auditor":
            res.text = "APPROVED " + "every item holds " * 20
        return res


class TestConfirmResultIsRecorded(Base):
    def test_headless_ledger_and_registry_keep_the_rerun_score(self):
        with low_confirm():
            rc, work = run_with(LongCards, self.tmp, 1, before=resume(0.0001))
        self.assertEqual(rc, 0)
        row = ledger.read_rows(work / ".keeploop")[-1]
        self.assertEqual(row["status"], "discard")
        self.assertIn("unconfirmed: re-run 0.100000", row["description"])
        self.assertEqual(hyps(work / ".keeploop")[-1]["confirm_metric"], 0.1)

    def test_kl_keep_refused_by_the_rerun_is_recorded_by_discard(self):
        p = Project(self.tmp)
        self.assertEqual(p.kl("begin"), 0, p.out)
        p.card()
        p.edit(learning_rate=0.03)
        with low_confirm(), mock.patch.object(run_mod, "needs_confirm", lambda *a: True):
            self.assertEqual(p.kl("keep"), 1)
        self.assertIn("unconfirmed", p.out)
        self.assertEqual(p.kl("discard"), 0, p.out)
        self.assertIn("unconfirmed: re-run 0.100000", p.rows()[-1]["description"])
        self.assertEqual(hyps(p.state)[-1]["confirm_metric"], 0.1)

    def test_a_later_keep_attempt_clears_the_old_rerun(self):
        p = Project(self.tmp)
        self.assertEqual(p.kl("begin"), 0, p.out)
        p.card()
        p.edit(learning_rate=0.03)
        with low_confirm(), mock.patch.object(run_mod, "needs_confirm", lambda *a: True):
            self.assertEqual(p.kl("keep"), 1)
        p.edit(learning_rate=0.0001)  # now below the bar: no confirm run this time
        self.assertEqual(p.kl("keep"), 1)
        self.assertEqual(p.kl("discard"), 0, p.out)
        self.assertNotIn("unconfirmed", p.rows()[-1]["description"])
        self.assertNotIn("confirm_metric", hyps(p.state)[-1])

    def test_kl_keep_records_a_passing_rerun_too(self):
        p = Project(self.tmp)
        self.assertEqual(p.kl("begin"), 0, p.out)
        p.card()
        p.edit(learning_rate=0.03)
        with mock.patch.object(run_mod, "needs_confirm", lambda *a: True):
            self.assertEqual(p.kl("keep"), 0, p.out)
        self.assertIn("confirm_metric", hyps(p.state)[-1])


FAKE_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
DIAG = ("import sys as _s; _s.stderr.write('per-label accuracy:\\n  9/10  top_up\\x1b[31m\\n"
        f"{FAKE_KEY}\\n' + '#9#' * 1000)\n")


class Spy(vendors.MockVendor):
    prompts: list = []

    def complete(self, prompt, *, role, max_tokens, cwd=None):
        if role == "analyst":
            self.prompts.append(prompt)
        return super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)


def noisy_scorers(work):
    for name, tag in (("evaluate.py", ""), ("holdout.py", "HOLDOUT-ONLY")):
        p = work / name
        p.write_text(DIAG.replace("per-label", tag + "per-label") + p.read_text(encoding="utf-8"),
                     encoding="utf-8")


class TestAnalystSeesScorerStderr(Base):
    def analyst_prompts(self, team_edit=None):
        Spy.prompts = []

        def before(work):
            noisy_scorers(work)
            if team_edit:
                team_edit(work)
        rc, _ = run_with(Spy, self.tmp, 2, before=before)
        self.assertEqual(rc, 0, run_with.out)
        return Spy.prompts

    def test_capped_cleaned_redacted_never_holdout(self):
        prompts = self.analyst_prompts()
        self.assertEqual(len(prompts), 2)
        for prompt in prompts:
            self.assertIn("Scorer diagnostics", prompt)
            self.assertIn("9/10  top_up", prompt)
            self.assertNotIn("\x1b", prompt)
            self.assertNotIn(FAKE_KEY, prompt)
            self.assertNotIn("HOLDOUT-ONLY", prompt)
            self.assertLessEqual(prompt.count("#9#"), 500)

    def test_zero_turns_it_off(self):
        prompts = self.analyst_prompts(edit_team(
            "  max_iterations: 20", "  max_iterations: 20\n  eval_stderr_max_chars: 0"))
        self.assertFalse(any("Scorer diagnostics" in p for p in prompts))


if __name__ == "__main__":
    unittest.main()
