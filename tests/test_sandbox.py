"""tools/make_sandbox.py: one command builds a worked example's sandbox.

Run:  python -X utf8 -m unittest discover -s tests
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import make_sandbox as ms  # noqa: E402


def repo_status() -> str:
    return subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--ignored"],
                          capture_output=True, text=True, check=True).stdout


def ws_files(ws: Path) -> set[str]:
    return {p.relative_to(ws).as_posix() for p in ws.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(ws).parts}


class TestMakeSandbox(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def build(self, name: str):
        example = ROOT / "examples" / name
        root, ws = ms.make(example, self.tmp / name)
        files = ms.manifest(example)
        self.assertEqual(ws_files(ws), set(files["workspace"]))
        self.assertFalse([f for f in ws_files(ws) if "holdout" in f.lower()])
        for rel in files["root"]:
            self.assertEqual((root / rel).read_bytes(), (example / rel).read_bytes())
        self.assertFalse((root / "examples").exists() or (root / ".keeploop").exists())
        log = subprocess.run(["git", "-C", str(ws), "log", "--oneline"],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(len(log.splitlines()), 1)
        return root, ws

    def test_both_examples_build_and_the_repo_is_untouched(self):
        before = repo_status()
        root, ws = self.build("marketing-research")
        self.assertFalse((root / "holdout.py").exists())  # demo holdout removed (L-001)
        out = subprocess.run([sys.executable, "-X", "utf8", str(root / "evaluate.py"), str(ws)],
                             capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "1.000000")  # the kept report, wired correctly
        root, _ = self.build("prompt-optimization")
        self.assertTrue((root / "data" / "holdout.jsonl").exists())
        self.assertEqual(repo_status(), before)

    def test_refusals(self):
        fake = self.tmp / "ex"
        fake.mkdir()
        (fake / "team.yaml").write_text(
            "# sandbox root: team.yaml\n# sandbox workspace: data/holdout.jsonl\n")
        with self.assertRaises(SystemExit):
            ms.manifest(fake)
        (fake / "team.yaml").write_text(
            "# sandbox root: team.yaml\n# sandbox workspace: nope.md\n")
        with self.assertRaises(SystemExit):
            ms.manifest(fake)  # missing file: refused before anything is copied
        (fake / "team.yaml").write_text("workspace: ../ws\n")
        with self.assertRaises(SystemExit):
            ms.manifest(fake)
        example = ROOT / "examples" / "prompt-optimization"
        with self.assertRaises(SystemExit):
            ms.make(example, ROOT / "sandbox-out")
        self.assertFalse((ROOT / "sandbox-out").exists())
        with self.assertRaises(SystemExit):
            ms.make(example, self.tmp)  # not empty


if __name__ == "__main__":
    unittest.main()
