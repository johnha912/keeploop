"""The CEO's choice of how heavy the loop is: `kl level --stakes low|medium|high`.

Run:  python -X utf8 -m unittest discover -s tests
"""

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
        self.assertEqual(R.project_config(self.proj)["loop_cfg"]["noise_runs"], 1)
        out = kl("--root", self.proj, "begin")
        self.assertIn("(1 runs)", out.stdout)  # light: one baseline run, no noise measurement
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
