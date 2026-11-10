"""The CEO's choice of how heavy the loop is: `kl level --stakes low|medium|high`.

Run:  python -X utf8 -m unittest discover -s tests
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import kl as K  # noqa: E402
import run as R  # noqa: E402
import scaffold  # noqa: E402
from prepare import CONFIG, PROFILES  # noqa: E402


def kl(*args):
    return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "kl.py"), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8")


class TestRule(unittest.TestCase):
    def test_stakes_and_noise_pick_the_level(self):
        self.assertEqual(K.level_for("low", 0.0)[0], "light")
        self.assertEqual(K.level_for("low", 0.01)[0], "fast")  # noisy: the noise is still measured
        self.assertEqual(K.level_for("medium", 0.0)[0], "fast")
        self.assertEqual(K.level_for("high", 0.0)[0], "rigorous")
        self.assertEqual(K.level_for("high", 0.02)[0], "rigorous")

    def test_profiles_only_set_known_keys_and_never_switch_off_safety(self):
        for name, preset in PROFILES.items():
            self.assertTrue(set(preset) <= set(CONFIG), name)
            for safety in ("replay_on_keep", "max_diff_lines", "max_consecutive_crashes"):
                self.assertNotIn(safety, preset, name)  # lessons, gates and brakes stay as set
        self.assertEqual(PROFILES["rigorous"]["noise_runs"], 5)
        self.assertTrue(PROFILES["rigorous"]["audit_every_keep"])
        self.assertLessEqual(PROFILES["light"]["max_iterations"], 3)


NOISY = ("import random, sys\n"
         "random.seed()\n"
         "print(f'{0.5 + random.gauss(0, 0.02):.6f}')\n")  # the contract: one float, higher is better


def set_loop(team: Path, line: str) -> None:
    text = team.read_text(encoding="utf-8")
    team.write_text(text.replace("loop:\n", f"loop:\n  {line}\n", 1), encoding="utf-8")


class TestUnmeasuredNoise(unittest.TestCase):
    """0.3.1: a keep bar that collapses to the best without the noise shown to be 0 is
    never silent (light + a noisy evaluate.py used to be)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "p"
        scaffold.init(self.proj, rewrite=False, src=ROOT)
        (self.proj / "evaluate.py").write_text(NOISY, encoding="utf-8")

    def test_light_on_a_noisy_score_measures_the_noise(self):
        set_loop(self.proj / "team.yaml", "profile: light")
        out = kl("--root", self.proj, "begin")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("(3 runs)", out.stdout)
        best = json.loads((self.proj / ".keeploop" / "best.json").read_text(encoding="utf-8"))
        self.assertGreater(best["sigma"], 0)  # the bar is best + 2 sigma, not the best
        self.assertEqual(best["noise_runs"], 3)
        self.assertNotIn("WARNING", out.stdout)

    def test_an_explicit_single_run_warns_at_begin_in_the_ledger_and_in_level(self):
        set_loop(self.proj / "team.yaml", "noise_runs: 1")
        out = kl("--root", self.proj, "begin")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("WARNING: sigma is NOT measured", out.stdout)
        tsv = (self.proj / ".keeploop" / "results.tsv").read_text(encoding="utf-8")
        self.assertIn("WARNING sigma not measured", tsv.splitlines()[1])  # the baseline row
        self.assertEqual(len(tsv.splitlines()[0].split("\t")), len(tsv.splitlines()[1].split("\t")))
        out = kl("--root", self.proj, "level", "--stakes", "low")
        self.assertIn("WARNING: sigma is NOT measured", out.stdout)
        out = kl("--root", self.proj, "doctor", "--runs", "3")
        self.assertIn("baseline came from 1 run", out.stdout)

    def test_doctor_flags_a_sigma_0_baseline_over_a_noisy_score(self):
        # a loop begun on a deterministic score (0.3.0 wrote no noise_runs into best.json)
        (self.proj / "evaluate.py").write_text("print('0.500000')\n", encoding="utf-8")
        self.assertEqual(kl("--root", self.proj, "begin").returncode, 0)
        best_p = self.proj / ".keeploop" / "best.json"
        best = json.loads(best_p.read_text(encoding="utf-8"))
        best.pop("noise_runs")
        best_p.write_text(json.dumps(best), encoding="utf-8")
        (self.proj / "evaluate.py").write_text(NOISY, encoding="utf-8")  # the score became noisy
        out = kl("--root", self.proj, "doctor", "--runs", "4")
        self.assertIn("baseline sigma is 0, so its keep bar is its best", out.stdout)


class TestCommand(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "p"
        scaffold.init(self.proj, rewrite=False, src=ROOT)

    def test_recommends_then_applies_and_the_baseline_follows(self):
        out = kl("--root", self.proj, "level", "--stakes", "low")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("level: light", out.stdout)
        self.assertIn("always on: lessons", out.stdout)
        self.assertNotIn("profile: light", (self.proj / "team.yaml").read_text(encoding="utf-8"))
        out = kl("--root", self.proj, "level", "--stakes", "low", "--apply")
        self.assertIn("loop.profile (none) -> light", out.stdout)
        self.assertEqual(R.project_config(self.proj)["loop_cfg"]["noise_runs"], 3)  # light measures noise
        out = kl("--root", self.proj, "begin")
        self.assertIn("(3 runs)", out.stdout)  # light still measures the noise (0.3.1)
        self.assertNotIn("WARNING", out.stdout)
        out = kl("--root", self.proj, "level", "--stakes", "high", "--apply")
        self.assertIn("light -> rigorous", out.stdout)
        cfg = R.project_config(self.proj)["loop_cfg"]
        self.assertTrue(cfg["audit_every_keep"] and cfg["noise_runs"] == 5)

    def test_rigorous_try_waits_for_an_auditor_on_a_decisive_gain(self):
        import json
        kl("--root", self.proj, "level", "--stakes", "high", "--apply")
        kl("--root", self.proj, "begin")
        card = Path(self._tmp.name) / "card.md"
        card.write_text("HYPOTHESIS: A learning rate near 0.03 scores higher than 0.01.\n"
                        "ALTERNATIVES: noise; the evaluation is deterministic.\n"
                        "CHANGE: set learning_rate to 0.03.\nEXPECT: the metric rises.\n"
                        "REJECT IF: the metric does not beat the keep bar.\nMISSING: none\n",
                        encoding="utf-8")
        cfg = self.proj / ".keeploop" / "workspace" / "config.json"
        data = json.loads(cfg.read_text(encoding="utf-8"))
        data["learning_rate"] = 0.03
        cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
        out = kl("--root", self.proj, "try", card)
        self.assertEqual(out.returncode, 3, out.stdout + out.stderr)  # waiting for a verdict
        self.assertIn("audits every keep", out.stdout)


if __name__ == "__main__":
    unittest.main()
