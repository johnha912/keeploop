"""Brakes against doing more than was asked: loop.target and loop.stall_cycles.

Run:  python -X utf8 -m unittest discover -s tests
"""

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run as R  # noqa: E402
import scaffold  # noqa: E402


def rows(*statuses):
    return [{"cycle": "0", "status": "baseline"}] + [
        {"cycle": str(i), "status": s} for i, s in enumerate(statuses, 1)]


def py(*args, cwd):
    return subprocess.run([sys.executable, "-X", "utf8", *map(str, args)], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8")


class TestBrake(unittest.TestCase):
    def test_off_by_default(self):
        cfg = {"target": None, "stall_cycles": 0}
        self.assertIsNone(R.brake(1.0, cfg, rows("discard") * 50))

    def test_target(self):
        cfg = {"target": 0.8, "stall_cycles": 0}
        self.assertIsNone(R.brake(0.79, cfg, rows()))
        self.assertIn("target reached", R.brake(0.8, cfg, rows()))  # at the target is enough
        self.assertIn("target reached", R.brake(0.95, cfg, rows()))

    def test_stall_counts_the_latest_streak_only(self):
        cfg = {"target": None, "stall_cycles": 3}
        self.assertIsNone(R.brake(0.5, cfg, rows("discard", "discard", "keep", "crash", "discard")))
        self.assertIn("stalled: 3", R.brake(0.5, cfg, rows("keep", "discard", "crash", "discard")))


class TestBrakeInTheTools(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def set_loop(self, root: Path, line: str):
        team = root / "team.yaml"
        text = team.read_text(encoding="utf-8")
        team.write_text(re.sub(r"^loop:\n", f"loop:\n  {line}\n", text, count=1, flags=re.M),
                        encoding="utf-8")

    def test_kl_status_says_stop_and_kl_card_refuses_at_the_target(self):
        root, ws = scaffold.make_sandbox(ROOT / "examples" / "marketing-research",
                                         self.tmp / "mr", with_code=True, src=ROOT)
        self.set_loop(root, "target: 0.95")  # the kept report scores 1.0: already enough
        out = py("kl.py", "begin", cwd=root)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("STOP: target reached: best 1.000000 >= target 0.950000", out.stdout)
        card = self.tmp / "card.md"
        card.write_text("HYPOTHESIS: x\nALTERNATIVES: y\nCHANGE: z\nEXPECT: metric up\n"
                        "REJECT IF: metric below 0.99\nMISSING: none\n", encoding="utf-8")
        out = py("kl.py", "card", card, cwd=root)
        self.assertEqual(out.returncode, 1)
        self.assertIn("REFUSED: target reached", out.stdout)
        self.assertEqual((root / ".keeploop" / "results.tsv").read_text(encoding="utf-8")
                         .count("\n"), 2)  # header + baseline: the refusal logs no cycle

    def test_run_py_stops_before_a_cycle_at_the_target(self):
        proj = self.tmp / "demo"
        scaffold.init(proj, rewrite=False, src=ROOT)
        self.set_loop(proj, "target: 0.1")  # the demo baseline is far above 0.1
        out = py(ROOT / "run.py", "--root", proj, "--mock", "--iterations", "3", cwd=proj)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("run: stopping — target reached", out.stdout)
        self.assertNotIn("cycle 1:", out.stdout)


if __name__ == "__main__":
    unittest.main()
