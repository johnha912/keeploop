"""Speed levers of the headless loop: fused, auto_cards, the lean `profile: fast`,
confirm_skip_z, the scorer-stderr handle, and the mock's latency and call log.

Run:  python -X utf8 -m unittest discover -s tests
"""

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import bench_cycle  # noqa: E402
import prepare  # noqa: E402
import run as R  # noqa: E402
import scaffold  # noqa: E402
import vendors  # noqa: E402

SPEED_KEYS = ("profile", "fused", "auto_cards", "confirm_skip_z", "eval_stderr_handle")


class Project(unittest.TestCase):
    """A fresh demo project per test; run() in process with a call spy on the mock."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.proj = self.tmp / "p"
        scaffold.init(self.proj, rewrite=False, src=ROOT)
        self.calls = []  # (role, prompt, reply)

    def loop(self, **keys):
        bench_cycle.set_loop(self.proj / "team.yaml", {k: v for k, v in keys.items()})

    def run_loop(self, n, evals=None):
        orig, calls = vendors.MockVendor.complete, self.calls

        def spy(v, prompt, *, role, max_tokens, cwd=None):
            res = orig(v, prompt, role=role, max_tokens=max_tokens, cwd=cwd)
            calls.append((role, prompt, res.text))
            return res
        patches = [mock.patch.object(vendors.MockVendor, "complete", spy)]
        if evals is not None:  # scripted scores instead of evaluate.py
            seq = iter(evals)
            patches.append(mock.patch.object(
                R, "evaluate_workspace", lambda *a, **k: (next(seq), "")))
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            stack.enter_context(contextlib.redirect_stdout(out))
            rc = R.run(self.proj, mock=True, iterations=n, narrate=True)
        self.out = out.getvalue()
        return rc

    def state(self, name):
        return self.proj / ".keeploop" / name

    def rows(self):
        lines = self.state("results.tsv").read_text(encoding="utf-8").splitlines()[1:]
        return [dict(zip(("cycle", "ts", "rv", "metric", "best", "status", "tokens", "lesson",
                          "desc"), l.split("\t"))) for l in lines if not l.startswith("0\t")]

    def hyps(self):
        return [json.loads(l) for l in
                self.state("hypotheses.jsonl").read_text(encoding="utf-8").splitlines() if l]

    def roles(self):
        return [c[0] for c in self.calls]

    def config(self):
        return json.loads((self.proj / ".keeploop" / "workspace" / "config.json")
                          .read_text(encoding="utf-8"))


class TestConfigAndProfile(unittest.TestCase):
    def test_every_lever_is_off_by_default(self):
        self.assertEqual({k: prepare.CONFIG[k] for k in SPEED_KEYS},
                         {"profile": None, "fused": False, "auto_cards": False,
                          "confirm_skip_z": 0.0, "eval_stderr_handle": False})

    def test_profile_fast_and_explicit_keys_win(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "team.yaml").write_text("loop:\n  profile: fast\n  recall_top_k: 6\n",
                                            encoding="utf-8")
            cfg = R.project_config(root)["loop_cfg"]
            fast = prepare.PROFILES["fast"]
            for k, v in fast.items():
                if k != "recall_top_k":
                    self.assertEqual(cfg[k], v, k)
            self.assertEqual(cfg["recall_top_k"], 6)  # written under loop: beats the preset
            self.assertEqual(cfg["confirm_skip_z"], 0.0)  # not in the fast profile
            self.assertEqual(cfg["noise_z"], prepare.CONFIG["noise_z"])  # keep law untouched
            for k in ("keep_threshold", "noise_z", "noise_runs", "confirm_keep"):
                self.assertNotIn(k, fast)

    def test_no_profile_is_the_plain_config(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "team.yaml").write_text("loop:\n  max_iterations: 3\n", encoding="utf-8")
            self.assertEqual(R.project_config(Path(d))["loop_cfg"],
                             {**prepare.CONFIG, "max_iterations": 3})

    def test_unknown_profile_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "team.yaml").write_text("loop:\n  profile: turbo\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown profile 'turbo'"):
                R.project_config(Path(d))


class TestMockLatencyAndLog(unittest.TestCase):
    def test_spec(self):
        spec = "analyst=2,engineer=4,auditor=0.5"
        self.assertEqual([vendors.mock_latency(r, spec) for r in ("analyst", "engineer", "auditor")],
                         [2.0, 4.0, 0.5])
        self.assertEqual(vendors.mock_latency("critic", spec), 0.0)
        self.assertEqual(vendors.mock_latency("auditor", "1.5"), 1.5)
        self.assertEqual(vendors.mock_latency("auditor", "engineer=3, 0.25"), 0.25)
        self.assertEqual(vendors.mock_latency("analyst", ""), 0.0)
        with self.assertRaises(vendors.VendorUnavailable):
            vendors.mock_latency("analyst", "analyst=fast")

    def test_off_by_default_and_sleeps_when_set(self):
        v = vendors.MockVendor()
        env = {k: v for k, v in os.environ.items() if k != "KEEPLOOP_MOCK_LATENCY"}
        with mock.patch.dict(os.environ, env, clear=True):
            start = time.monotonic()
            v.complete("x", role="auditor", max_tokens=10)
            self.assertLess(time.monotonic() - start, 0.1)
        with mock.patch.dict(os.environ, {"KEEPLOOP_MOCK_LATENCY": "auditor=0.2"}):
            start = time.monotonic()
            res = v.complete("x", role="auditor", max_tokens=10)
            self.assertGreaterEqual(time.monotonic() - start, 0.2)
            self.assertGreaterEqual(res.latency_s, 0.2)

    def test_call_log(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "calls.jsonl"
            with mock.patch.dict(os.environ, {"KEEPLOOP_MOCK_LOG": str(log)}):
                vendors.MockVendor().complete("hello", role="auditor", max_tokens=10)
            rec = json.loads(log.read_text(encoding="utf-8"))
            self.assertEqual((rec["role"], rec["fused"]), ("auditor", False))
            self.assertGreater(rec["tokens"], 0)


class TestCardHelpers(unittest.TestCase):
    CARD = ("HYPOTHESIS: a\nALTERNATIVES: b\nCHANGE: c\nEXPECT: d\n"
            "REJECT IF: the metric does not beat the bar\nMISSING: none")

    def test_card_block_cuts_text_around_the_card(self):
        reply = f"I looked around.\n\n{self.CARD}\n\nDone: edited config.json."
        self.assertEqual(R.card_block(reply), self.CARD)
        self.assertEqual(R.parse_card(R.card_block(reply))["missing"], "none")
        self.assertEqual(R.card_block("no card here"), "no card here")

    def test_auto_card(self):
        card = R.auto_card("  Batch size 64   scores higher. ", R.parse_protect(R.DEFAULT_HEAVY))
        p = R.parse_card(card)
        self.assertEqual(p["hypothesis"], "Batch size 64 scores higher.")
        self.assertEqual(p["change"], "the smallest change that tests it")
        self.assertEqual(p["expect"], "the metric rises")
        self.assertEqual(p["reject_if"], "the metric does not beat the keep bar")
        self.assertEqual(p["missing"], "none")
        self.assertEqual(p["tier"], "")
        self.assertTrue(R.falsifiable(p["reject_if"]))
        heavy = R.parse_card(R.auto_card("Pinning numpy in pyproject.toml helps.",
                                         R.parse_protect(R.DEFAULT_HEAVY)))
        self.assertEqual(heavy["tier"], "heavy")  # the critic round still runs

    def test_prompts(self):
        ask = R.fused_ask(["tests"])
        self.assertTrue(ask.startswith(vendors.FUSED_MARK))
        self.assertIn("Protected paths (never touch): tests.", ask)
        self.assertTrue(ask.endswith(R.CARD_LINES))
        self.assertTrue(R.ANALYST_ASK.endswith(R.CARD_LINES))
        self.assertNotIn(vendors.FUSED_MARK, R.ANALYST_ASK)


class TestDefaultUnchanged(Project):
    def test_default_cycle_calls(self):
        self.assertEqual(self.run_loop(6), 0)
        self.assertEqual([r["status"] for r in self.rows()],
                         ["keep", "keep", "discard", "crash", "keep", "discard"])
        self.assertEqual(self.roles().count("analyst"), 6)
        self.assertFalse(any(vendors.FUSED_MARK in p for _, p, _ in self.calls))
        self.assertNotIn("card by", self.state("results.tsv").read_text(encoding="utf-8"))


class TestFused(Project):
    def test_one_engineer_call_writes_and_builds(self):
        self.loop(fused="true")
        self.assertEqual(self.run_loop(6), 0)
        self.assertNotIn("analyst", self.roles())
        # the same decisions as the default run: the same edits, now one call each
        self.assertEqual([r["status"] for r in self.rows()],
                         ["keep", "keep", "discard", "crash", "keep", "discard"])
        # 6 fused calls, one repair on the crash, 3 audits
        self.assertEqual(self.roles().count("engineer"), 7)
        self.assertEqual(self.roles().count("auditor"), 3)
        h = self.hyps()
        self.assertEqual(h[0]["hypothesis"], "Setting learning_rate to 0.03 helps.")
        self.assertTrue(all("card by engineer (fused)" in r["desc"] for r in self.rows()))
        repair = [p for r, p, _ in self.calls if "Your last attempt failed" in p]
        self.assertEqual(len(repair), 1)
        self.assertNotIn(vendors.FUSED_MARK, repair[0])  # a repair builds the fixed card
        self.assertIn("HYPOTHESIS: Setting dropout to 1.5 helps.", repair[0])

    def test_scripted_and_duplicate_dropped_before_evaluation(self):
        self.loop(fused="true")
        (self.proj / "mock_script.json").write_text(json.dumps([
            {"hypothesis": "SGD trains this model better than Adam.", "set": {"optimizer": "sgd"}},
            {"hypothesis": "SGD trains this model better than Adam.", "set": {"optimizer": "sgd"}},
            {"hypothesis": "Batch size 64 is better.", "set": {"batch_size": 64}},
        ]), encoding="utf-8")
        seen = []
        real = R.evaluate_workspace

        def ev(root, ws, script="evaluate.py", *a, **k):
            seen.append(json.loads((Path(ws) / "config.json").read_text(encoding="utf-8")))
            return real(root, ws, script, *a, **k)
        with mock.patch.object(R, "evaluate_workspace", ev):
            self.assertEqual(self.run_loop(3), 0)
        self.assertEqual([r["status"] for r in self.rows()], ["discard", "discard", "keep"])
        self.assertEqual([h["verdict"] for h in self.hyps()], ["rejected", "duplicate", "supported"])
        dup = self.rows()[1]
        self.assertIn("duplicate of cycle 1", dup["desc"])
        self.assertIn("fused edit dropped before evaluation", dup["desc"])
        self.assertEqual(dup["metric"], "")
        # 3 baseline runs + cycle 1 + cycle 3: the duplicate's sgd edit was never scored
        self.assertEqual(len(seen), 5)
        self.assertEqual([c["optimizer"] for c in seen[3:]], ["sgd", "adam"])
        self.assertEqual(self.config()["optimizer"], "adam")  # and it was reset
        self.assertEqual(self.config()["batch_size"], 64)

    def test_reply_without_a_card_is_a_crash_and_the_edit_goes(self):
        self.loop(fused="true")
        orig = vendors.MockVendor.complete

        def no_card(v, prompt, *, role, max_tokens, cwd=None):
            res = orig(v, prompt, role=role, max_tokens=max_tokens, cwd=cwd)
            if vendors.FUSED_MARK in prompt:
                res.text = "I changed the learning rate."
            return res
        with mock.patch.object(vendors.MockVendor, "complete", no_card):
            self.assertEqual(self.run_loop(1), 0)
        row = self.rows()[0]
        self.assertEqual(row["status"], "crash")
        self.assertIn("not in the labelled format", row["desc"])
        self.assertEqual(self.config()["learning_rate"], 0.01)

    def test_card_not_falsifiable_is_a_crash(self):
        self.loop(fused="true")
        orig = vendors.MockVendor.complete

        def vague(v, prompt, *, role, max_tokens, cwd=None):
            res = orig(v, prompt, role=role, max_tokens=max_tokens, cwd=cwd)
            res.text = res.text.replace("REJECT IF: the metric does not beat the best so far.",
                                        "REJECT IF: it looks wrong")
            return res
        with mock.patch.object(vendors.MockVendor, "complete", vague):
            self.run_loop(1)
        self.assertEqual(self.rows()[0]["status"], "crash")
        self.assertIn("REJECT IF is not falsifiable", self.rows()[0]["desc"])
        self.assertEqual(self.config()["learning_rate"], 0.01)


class TestFusedHeavyCard(Project):
    def patched(self, critic: str):
        orig = vendors.MockVendor.complete

        def fake(v, prompt, *, role, max_tokens, cwd=None):
            res = orig(v, prompt, role=role, max_tokens=max_tokens, cwd=cwd)
            if vendors.FUSED_MARK in prompt:
                res.text += "\nTIER: heavy"
            elif prompt.startswith("Card:") and "You are the Critic" in prompt:
                res.text = critic
            elif role == "analyst":
                res.text = "KEEP: the card stands"
            return res
        return mock.patch.object(vendors.MockVendor, "complete", fake)

    def test_critic_proceeds_and_the_fused_edit_is_kept(self):
        self.loop(fused="true")
        with self.patched("OBJECTIONS: none\nVERDICT: proceed"):
            self.run_loop(1)
        self.assertEqual(self.roles(), ["engineer", "auditor", "auditor"])  # build, critic, audit
        self.assertIn("critic: proceed", self.rows()[0]["desc"])
        self.assertEqual(self.rows()[0]["status"], "keep")

    def test_critic_revise_drops_the_edit_and_the_engineer_builds_again(self):
        self.loop(fused="true")
        with self.patched("OBJECTIONS: too broad\nVERDICT: revise"):
            self.run_loop(1)
        self.assertEqual(self.roles()[:4], ["engineer", "auditor", "analyst", "engineer"])
        self.assertNotIn(vendors.FUSED_MARK, self.calls[3][1])  # the plain Engineer prompt


class TestAutoCards(Project):
    def test_program_hypotheses_first_with_no_analyst_call(self):
        self.loop(auto_cards="true")
        self.assertEqual(self.run_loop(3), 0)
        h = self.hyps()
        self.assertEqual([x["hypothesis"] for x in h[:2]],
                         ["A learning rate near 0.03 scores higher than 0.01.",
                          "Batch size 64 scores higher than 32."])
        self.assertEqual(h[0]["change"], "the smallest change that tests it")
        self.assertEqual(h[0]["reject_if"], "the metric does not beat the keep bar")
        self.assertEqual(self.roles().count("analyst"), 1)  # cycle 3 only: the list is done
        self.assertIn("card by program.md", self.rows()[0]["desc"])
        self.assertEqual([r["status"] for r in self.rows()][:2], ["keep", "keep"])

    def test_scripted_mock_builds_the_closest_entry(self):
        self.loop(auto_cards="true")
        (self.proj / "mock_script.json").write_text(json.dumps([
            {"hypothesis": "Dropout of 0.2 regularises better.", "set": {"dropout": 0.2}},
            {"hypothesis": "A learning rate of 0.03 trains faster.", "set": {"learning_rate": 0.03}},
        ]), encoding="utf-8")
        self.run_loop(1)
        self.assertEqual(self.config()["learning_rate"], 0.03)
        self.assertEqual(self.config()["dropout"], 0.1)

    def test_over_long_hypothesis_is_left_to_the_analyst(self):
        program = self.proj / "program.md"
        text = program.read_text(encoding="utf-8")
        program.write_text(text.replace("- A learning rate near 0.03", "- " + "x " * 160 + "A learning rate near 0.03"),
                           encoding="utf-8")
        self.loop(auto_cards="true")
        self.run_loop(1)
        self.assertEqual(self.hyps()[0]["hypothesis"], "Batch size 64 scores higher than 32.")


class TestLeanPrompts(Project):
    def test_fast_caps_shrink_the_analyst_prompt(self):
        def ledger_rows(prompt):  # header + rows
            return prompt.split("Recent ledger:\n")[1].split("\n\n")[0].count("\n") + 1
        self.run_loop(8)
        default = [p for r, p, _ in self.calls if r == "analyst"][-1]
        self.setUp()
        self.loop(profile="fast", auto_cards="false", fused="false")  # the lean caps alone
        self.run_loop(8)
        lean = [p for r, p, _ in self.calls if r == "analyst"][-1]
        self.assertLess(len(lean), len(default))
        self.assertEqual((ledger_rows(default), ledger_rows(lean)), (9, 4))  # 8 rows -> 3

    def test_stderr_handle(self):
        state = self.tmp
        (state / "scorer_notes.json").write_text(json.dumps({"commit": "abc", "stderr": "e" * 1000}),
                                                  encoding="utf-8")
        best = {"commit": "abc"}
        self.assertEqual(R.scorer_notes(state, best, 400), "e" * 400)  # default: unchanged
        cut = R.scorer_notes(state, best, 400, handle=True)
        self.assertTrue(cut.startswith("e" * 400 + "\n[cut at 400 of 1000 chars; all of it: "))
        self.assertIn(str((state / "scorer_notes.json").resolve()), cut)
        self.assertEqual(R.scorer_notes(state, best, 2000, handle=True), "e" * 1000)  # not cut
        self.assertEqual(R.scorer_notes(state, {"commit": "old"}, 400, handle=True), "")


class TestConfirmSkip(Project):
    def test_sigma_upper(self):
        self.assertAlmostEqual(R.sigma_upper(1.0, 3), 5.408, places=3)  # sqrt(3 / 0.1026)
        self.assertAlmostEqual(R.sigma_upper(1.0, 10), 1.734, places=3)  # sqrt(10 / 3.325)
        self.assertAlmostEqual(R.sigma_upper(2.0, 2), 2 * 22.553, places=2)  # sqrt(2 / 0.00393)
        self.assertEqual(R.sigma_upper(1.0, 1), float("inf"))

    def test_rule(self):
        cfg = {**prepare.CONFIG, "noise_runs": 10, "confirm_skip_z": 4}
        big = 4 * R.sigma_upper(0.01, 10) + 0.5  # best 0.5
        self.assertTrue(R.confirm_skippable(big + 1e-9, 0.5, 0.01, False, cfg))
        self.assertFalse(R.confirm_skippable(big - 1e-3, 0.5, 0.01, False, cfg))
        self.assertFalse(R.confirm_skippable(big, 0.5, 0.01, True, cfg))   # heavy: always re-run
        self.assertFalse(R.confirm_skippable(big, 0.5, 0.0, False, cfg))   # sigma 0
        self.assertFalse(R.confirm_skippable(9.0, 0.5, 0.01, False, prepare.CONFIG))  # off
        self.assertFalse(R.confirm_skippable(9.0, 0.5, 0.01, False,
                                             {**cfg, "confirm_skip_z": 2.0}))  # not above noise_z

    def test_in_the_loop(self):
        # baseline 0.50/0.51/0.49: sigma 0.00816, upper bound 0.0441; 3 * that = 0.132
        self.loop(confirm_skip_z="3")
        self.run_loop(1, evals=[0.50, 0.51, 0.49, 0.90])  # +0.40: no re-run
        self.assertEqual(self.rows()[0]["status"], "keep")
        self.assertIn("confirm skipped", self.rows()[0]["desc"])
        self.assertNotIn("confirm_metric", self.hyps()[0])

    def test_small_gain_still_confirms(self):
        self.loop(confirm_skip_z="3")
        self.run_loop(1, evals=[0.50, 0.51, 0.49, 0.60, 0.59])  # +0.10 < 0.132: re-run
        self.assertEqual(self.rows()[0]["status"], "keep")
        self.assertNotIn("confirm skipped", self.rows()[0]["desc"])
        self.assertEqual(self.hyps()[0]["confirm_metric"], 0.59)
        self.assertEqual(self.rows()[0]["metric"], "0.590000")  # the lower of the two


class TestBenchSetLoop(unittest.TestCase):
    def test_set_and_add(self):
        with tempfile.TemporaryDirectory() as d:
            team = Path(d) / "team.yaml"
            team.write_text("roles:\n  analyst:\n    vendor: mock\nloop:\n  max_iterations: 20\n",
                            encoding="utf-8")
            bench_cycle.set_loop(team, {"max_iterations": "3", "profile": "fast"})
            self.assertEqual(R.load_team(team)["loop"], {"profile": "fast", "max_iterations": 3})
            self.assertTrue(re.search(r"^    vendor: mock$", team.read_text(encoding="utf-8"), re.M))


if __name__ == "__main__":
    unittest.main()
