"""The 0.3.0 launch pieces: the noisy-eval proof run, --narrate, kl report --html,
kl doctor, kl quickstart, kl import-lite, global lessons, the eval cache.

Run:  python -X utf8 -m unittest discover -s tests
"""

import ast
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import kl as K  # noqa: E402
import lessons  # noqa: E402
import proof_run  # noqa: E402
import quickstart  # noqa: E402
import report  # noqa: E402
import run as R  # noqa: E402
import scaffold  # noqa: E402
import vendors  # noqa: E402

EXAMPLE = ROOT / "examples" / "noisy-eval"


def py(*args, cwd=ROOT, env=None):
    return subprocess.run([sys.executable, "-X", "utf8", *map(str, args)], cwd=cwd, env=env,
                          capture_output=True, text=True, encoding="utf-8")


class Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)


class TestNoisyEval(Tmp):
    def ws(self, **over):
        cfg = {**json.loads((EXAMPLE / "config.json").read_text(encoding="utf-8")), **over}
        (self.tmp / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        return self.tmp

    def test_seeded_noise_replays_and_varies_per_call(self):
        ws = self.ws()

        def three(state):
            env = {**os.environ, "KEEPLOOP_DEMO_SEED": "7", "KEEPLOOP_DEMO_STATE": str(state)}
            return [py(EXAMPLE / "evaluate.py", ws, env=env).stdout.strip() for _ in range(3)]
        a, b = three(self.tmp / "s1.json"), three(self.tmp / "s2.json")
        self.assertEqual(a, b)  # the same seed replays exactly
        self.assertGreater(len(set(a)), 1)  # and each call is a new sample: noise

    def test_holdout_is_noiseless_and_invalid_config_exits_2(self):
        ws = self.ws()
        outs = {py(EXAMPLE / "holdout.py", ws).stdout.strip() for _ in range(2)}
        self.assertEqual(outs, {"0.657400"})
        self.ws(few_shot=False)  # a bool is not a few-shot count
        self.assertEqual(py(EXAMPLE / "evaluate.py", self.tmp).returncode, 2)

    def test_mock_script_is_valid_and_engineer_follows_the_card(self):
        script = R.mock_script(EXAMPLE)
        self.assertEqual(len(script), 20)
        m = vendors.MockVendor()
        m.script = script
        card = m.complete("x", role="analyst", max_tokens=10).text
        (self.tmp / "config.json").write_text('{"temperature": 0.7, "few_shot": 0}', encoding="utf-8")
        m.complete(f"Experiment card:\n{card}\n", role="engineer", max_tokens=10, cwd=self.tmp)
        self.assertEqual(json.loads((self.tmp / "config.json").read_text())["temperature"], 0.5)
        (self.tmp / "mock_script.json").write_text('[{"set": {"a": 1}}]', encoding="utf-8")
        with self.assertRaises(ValueError):
            R.mock_script(self.tmp)


class TestProofRun(Tmp):
    def test_headline_seed_reproduces_proof_json(self):
        """The release gate in miniature (tools/proof_run.py --check runs every seed)."""
        want = json.loads((ROOT / "docs" / "proof" / "proof.json").read_text(encoding="utf-8"))
        for mode in proof_run.MODES:
            got = proof_run.one(mode, proof_run.HEADLINE_SEED, want["cycles"], self.tmp, None)
            self.assertEqual(got, want["headline"][mode], mode)

    def test_committed_files_match_proof_json(self):
        proof = json.loads((ROOT / "docs" / "proof" / "proof.json").read_text(encoding="utf-8"))
        for mode in proof_run.MODES:
            with (ROOT / "docs" / "proof" / mode / "results.tsv").open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f, delimiter="\t"))
            kept = [int(r["cycle"]) for r in rows if r["status"] == "keep" and int(r["cycle"]) >= 1]
            self.assertEqual(kept, proof["headline"][mode]["kept_cycles"])
        md = (ROOT / "docs" / "proof" / "PROOF.md").read_text(encoding="utf-8")
        self.assertIn(f"| changes kept | {proof['headline']['naive']['kept']} | "
                      f"{proof['headline']['keeploop']['kept']} |", md)

    def test_demo_selection_rule_and_its_run(self):
        import render_demo
        proof = json.loads((ROOT / "docs" / "proof" / "proof.json").read_text(encoding="utf-8"))
        seed, a, b = render_demo.select(proof)
        self.assertLess(a, b)
        out = (ROOT / "docs" / "assets" / "demo-run" / "keeploop" / "stdout.txt").read_text(encoding="utf-8")
        head, cyc, tail = render_demo.blocks(out)
        self.assertTrue(any("inside the noise band" in ln for ln in cyc[a]))
        self.assertTrue(any(ln.strip().startswith("KEEP") for ln in cyc[b]))
        for name in ("keeploop-demo.gif", "keeploop-demo.mp4", "keeploop-demo-poster.png"):
            size = (ROOT / "docs" / "assets" / name).stat().st_size
            self.assertTrue(0 < size < 15_000_000, name)


class TestNarrateAndReport(Tmp):
    def test_narrate_is_off_by_default_and_reports_the_bar(self):
        env = {**os.environ, "KEEPLOOP_DEMO_SEED": "2", "KEEPLOOP_DEMO_STATE": str(self.tmp / "n.json")}
        q, _ = scaffold.make_sandbox(EXAMPLE, self.tmp / "quiet", with_code=True, src=ROOT)
        quiet = py(q / "run.py", "--mock", "--iterations", "1", cwd=q, env=env)
        self.assertEqual(quiet.returncode, 0, quiet.stdout + quiet.stderr)
        self.assertNotIn("  analyst ", quiet.stdout)
        root, _ = scaffold.make_sandbox(EXAMPLE, self.tmp / "ne", with_code=True, src=ROOT)
        loud = py(root / "run.py", "--mock", "--narrate", "--iterations", "2", cwd=root, env=env)
        self.assertIn("  analyst   HYPOTHESIS:", loud.stdout)
        self.assertRegex(loud.stdout, r"evaluate  \d\.\d{6}   best \d\.\d{6}   bar \d\.\d{6} = best \+ 2σ")
        page = self.tmp / "r.html"
        out = py(root / "kl.py", "report", "--html", page, "--svg", self.tmp / "r.svg", cwd=root)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("summary: 2 experiments", out.stdout)
        html = page.read_text(encoding="utf-8")
        self.assertIn("<svg", html)
        self.assertIn("holdout", html)
        self.assertTrue((self.tmp / "r.svg").read_text(encoding="utf-8").startswith("<svg"))

    def test_chart_marks_kept_filled_and_discarded_hollow(self):
        run = report.read_run(ROOT / "docs" / "proof" / "naive")
        svg = report.chart_svg(run, 0.0)
        kept = sum(r["status"] == "keep" for r in run["rows"] if int(r["cycle"]) >= 1)
        self.assertEqual(svg.count('class="dot kept"'), kept)
        self.assertEqual(svg.count('class="dot disc"'), 20 - kept)
        self.assertIn('class="band"', svg)  # the noise band is drawn even for a naive run
        self.assertNotIn('class="bar"', svg)  # but no keep bar: naive has none
        self.assertIn("20 experiments, 6 kept", report.summary(run))


class TestDoctor(unittest.TestCase):
    def test_deterministic_and_noisy(self):
        cfg = {"noise_z": 2.0, "keep_threshold": 0.0, "noise_runs": 3}
        self.assertIn("deterministic", "\n".join(K.doctor_text([0.5] * 4, cfg, None, 0.1)))
        out = "\n".join(K.doctor_text([0.60, 0.64, 0.62, 0.66, 0.58], cfg, 0.01, 0.1))
        self.assertIn("a change must gain more than", out)
        self.assertIn("noise_runs is 3", out)
        self.assertIn("Average", out)  # 0.01 is below 2 sigma: repeats needed


class TestQuickstart(Tmp):
    def test_every_template_is_valid_python(self):
        for name in quickstart.TEMPLATES:
            ast.parse(quickstart.template_text(name))

    def test_tests_template_end_to_end(self):
        repo = self.tmp / "app"
        (repo / "tests").mkdir(parents=True)
        (repo / "tests" / "test_a.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n"
            "    def test_bad(self): self.fail()\n", encoding="utf-8")
        for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t",
                                                     "commit", "-qm", "x"]):
            subprocess.run(["git", *args], cwd=repo, check=True)
        out = py(ROOT / "kl.py", "quickstart", "tests", cwd=repo)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        ctl = self.tmp / "app-keeploop"
        self.assertIn("workspace: ../app", (ctl / "team.yaml").read_text(encoding="utf-8"))
        ev = ctl / "evaluate.py"
        ev.write_text(ev.read_text(encoding="utf-8").replace(
            '["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]',
            '["python", "-m", "unittest", "discover", "-s", "tests"]'), encoding="utf-8")
        out = py(ROOT / "kl.py", "--root", ctl, "doctor", "--runs", "3")
        self.assertIn("mean 0.500000", out.stdout)
        self.assertIn("deterministic", out.stdout)
        out = py(ROOT / "kl.py", "quickstart", "tests", "--workspace", repo, repo / "inside")
        self.assertIn("REFUSED", out.stdout)  # the control folder must not be in the repo

    def test_import_lite(self):
        out = py(ROOT / "kl.py", "import-lite", ROOT / "lite" / "EXAMPLE.md", self.tmp / "il")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        art = (self.tmp / "il" / "artifact" / "artifact.md").read_text(encoding="utf-8")
        self.assertIn("Banana bread", art)
        prog = (self.tmp / "il" / "kl" / "program.md").read_text(encoding="utf-8")
        self.assertIn("L1 (cycle 2)", prog)
        src = (self.tmp / "il" / "kl" / "evaluate.py").read_text(encoding="utf-8")
        ast.parse(src)
        self.assertIn("MAX_WORDS = 30", src)
        self.assertEqual(py(ROOT / "kl.py", "import-lite", ROOT / "README.md",
                            self.tmp / "x").returncode, 1)


class TestGlobalLessons(Tmp):
    def test_off_by_default_capped_when_on(self):
        self.assertFalse(lessons.global_cfg({})["enabled"])
        g = lessons.global_cfg({"global_lessons": {"enabled": True, "path": str(self.tmp / "g"),
                                                   "max_lessons": 9, "max_tokens": 10_000}})
        self.assertEqual(g["max_lessons"], 5)  # the hard cap
        state = self.tmp / "s"
        state.mkdir()
        for i in range(8):
            lessons.record(state, what=f"timeout {i}", root_cause="slow eval",
                           guardrail=f"keep the eval under {i} minutes timeout", trigger_cycle=1)
            lessons.share(state, f"L-{i + 1:03d}", g, "proj")
        self.assertEqual(lessons.share(state, "L-001", g, "proj")["id"], "G-001")  # no duplicate
        self.assertEqual(len(lessons.global_recall("eval timeout minutes", g)), 5)
        self.assertEqual(lessons.global_recall("eval timeout", {**g, "enabled": False}), [])
        self.assertLessEqual(len(lessons.global_recall("eval timeout", {**g, "max_tokens": 30})), 1)
        self.assertIn("Lessons from other projects", lessons.global_text("timeout", g))


class TestEvalCache(Tmp):
    def test_cache_only_for_a_deterministic_eval(self):
        proj = self.tmp / "demo"
        scaffold.init(proj, rewrite=False, src=ROOT)
        team = proj / "team.yaml"
        team.write_text(team.read_text(encoding="utf-8").replace(
            "loop:\n", "loop:\n  eval_cache: true\n", 1), encoding="utf-8")
        out = py(ROOT / "run.py", "--root", proj, "--mock", "--iterations", "8")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        cache = json.loads((proj / ".keeploop" / "eval_cache.json").read_text(encoding="utf-8"))
        self.assertTrue(cache)  # sigma 0: scores are reused for identical files
        root, _ = scaffold.make_sandbox(EXAMPLE, self.tmp / "ne", with_code=True, src=ROOT)
        team = root / "team.yaml"
        team.write_text(team.read_text(encoding="utf-8").replace(
            "loop:\n", "loop:\n  eval_cache: true\n", 1), encoding="utf-8")
        out = py(root / "run.py", "--mock", "--iterations", "3", cwd=root)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertFalse((root / ".keeploop" / "eval_cache.json").exists())  # noisy: never


if __name__ == "__main__":
    unittest.main()
