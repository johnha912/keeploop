"""scaffold.py and `kl init`: the files a project gets, and what a pip install packs.

The installed path itself (wheel contents, clean venv, `kl init` -> `kl begin`)
is tools/check_dist.py, run in CI; these tests cover the same code from a clone.

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

import scaffold  # noqa: E402


def kl(*args, cwd=ROOT):
    return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "kl.py"), *map(str, args)],
                          cwd=cwd, capture_output=True, text=True, encoding="utf-8")


class TestScaffold(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_bundle_lists_framework_and_example_files(self):
        files = scaffold.bundle_files(ROOT)
        for rel in scaffold.REQUIRED + ["BOOTSTRAP.md", ".claude/skills/keeploop/SKILL.md",
                                        "examples/marketing-research/data/metrics.json",
                                        "examples/prompt-optimization/data/holdout.jsonl"]:
            self.assertIn(rel, files)
        for name in ("software", "ui-design", "marketing-research", "marketing-content",
                     "prompt-engineering"):
            self.assertIn(f"packs/{name}/pack.yaml", files)
        self.assertFalse([f for f in files if "__pycache__" in f or f.endswith(".pyc")])
        self.assertNotIn("holdout.py", files)  # the demo holdout never ships (L-001)
        self.assertFalse([f for f in files if f.startswith(("examples/marketing-research/run/",
                                                            "examples/marketing-research/report/"))])
        self.assertTrue(all((ROOT / f).is_file() for f in files))

    def test_kl_init_writes_never_overwrites_and_runs(self):
        proj = self.tmp / "proj"
        out = kl("init", proj)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        for rel in scaffold.REQUIRED + [".gitignore"]:
            self.assertTrue((proj / rel).is_file(), rel)
        # from a clone the copies are verbatim: `python kl.py` is how this user runs kl
        self.assertEqual((proj / "AGENTS.md").read_bytes(), (ROOT / "AGENTS.md").read_bytes())
        (proj / "program.md").write_text("# mine\n", encoding="utf-8")
        out = kl("init", proj)
        self.assertIn("wrote 0 files", out.stdout)
        self.assertEqual((proj / "program.md").read_text(encoding="utf-8"), "# mine\n")
        out = kl("--root", proj, "begin")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("baseline metric =", out.stdout)

    def test_kl_init_warns_when_the_folder_has_its_own_agents_md(self):
        (self.tmp / "AGENTS.md").write_text("theirs\n", encoding="utf-8")
        out = kl("init", self.tmp)
        self.assertEqual(out.returncode, 0)
        self.assertIn("your AGENTS.md was kept", out.stdout)
        self.assertEqual((self.tmp / "AGENTS.md").read_text(encoding="utf-8"), "theirs\n")

    def test_rewrite_for_a_pip_installed_kl(self):
        written, _ = scaffold.init(self.tmp, rewrite=True, src=ROOT)
        for rel in written:
            if Path(rel).suffix in scaffold.TEXT:
                text = (self.tmp / rel).read_text(encoding="utf-8")
                for old in ("python kl.py", "python run.py", "python lessons.py",
                            "tools/make_sandbox.py"):
                    self.assertNotIn(old, text, rel)
        agents = (self.tmp / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("`kl init --example <name> <new short folder>`", agents)
        self.assertIn("Bash(kl status)", json.loads(
            (self.tmp / ".claude/settings.json").read_text(encoding="utf-8"))["permissions"]["allow"])
        boot = (self.tmp / "BOOTSTRAP.md").read_text(encoding="utf-8")
        block = boot.split("<!-- BEGIN AGENTS.md (verbatim) -->\n", 1)[1].split(
            "<!-- END AGENTS.md -->", 1)[0]
        self.assertEqual(block.strip(), agents.strip())  # still verbatim after the rewrite

    def test_example_refusals(self):
        out = kl("init", "--example", "marketing-research")
        self.assertEqual(out.returncode, 1)
        self.assertIn("needs a new folder", out.stdout)
        out = kl("init", "--example", "marketing-research", ROOT / "sandbox-out")
        self.assertEqual(out.returncode, 1)
        self.assertIn("inside the keeploop", out.stdout)
        self.assertFalse((ROOT / "sandbox-out").exists())
        self.assertNotEqual(kl("init", "--example", "nope", self.tmp / "x").returncode, 0)

    def test_installed_sandbox_has_no_code_and_says_kl(self):
        root, ws = scaffold.make_sandbox(ROOT / "examples" / "marketing-research",
                                         self.tmp / "mr", with_code=False, src=ROOT)
        self.assertFalse((root / "kl.py").exists() or (root / "holdout.py").exists())
        self.assertEqual((root / "evaluate.py").read_bytes(),
                         (ROOT / "examples/marketing-research/evaluate.py").read_bytes())
        self.assertNotIn("python kl.py", (root / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertTrue((ws / "report.md").is_file() and (ws / ".git").is_dir())


class TestRelease(unittest.TestCase):
    def test_pypi_readme_pins_relative_links_to_the_tag(self):
        text = ('<img src="docs/demo.gif"> [guide](docs/GUIDE.md#faq) [ext](https://x.test/a) '
                '[top](#quick-start) <a href="CHANGELOG.md">c</a> <source srcset="docs/a.png">')
        out = scaffold.pypi_readme(text, "v9.9.9")
        raw = "https://raw.githubusercontent.com/johnha912/keeploop/v9.9.9/"
        blob = "https://github.com/johnha912/keeploop/blob/v9.9.9/"
        self.assertIn(f'src="{raw}docs/demo.gif"', out)
        self.assertIn(f"]({blob}docs/GUIDE.md#faq)", out)
        self.assertIn(f'href="{blob}CHANGELOG.md"', out)
        self.assertIn(f'srcset="{raw}docs/a.png"', out)
        self.assertIn("](https://x.test/a)", out)
        self.assertIn("](#quick-start)", out)

    def test_release_notes_are_the_changelog_section(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import release_notes
        from prepare import __version__
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        notes = release_notes.section(text, __version__)
        self.assertTrue(notes.startswith("### "))
        self.assertNotIn(f"## [{__version__}]", notes)
        self.assertNotIn("## [0.1.0]", notes)  # stops at the next section
        self.assertEqual(release_notes.section(text, "9.9.9"), "")

    def test_publish_workflow_gates_the_upload(self):
        wf = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
        build = wf.index("tools/check_dist.py --dist dist")
        self.assertLess(build, wf.index("pypa/gh-action-pypi-publish"))  # gate before upload
        self.assertIn("id-token: write", wf)  # Trusted Publishing, no token in the repo
        self.assertNotIn("password:", wf)
        self.assertIn('"$GITHUB_REF_NAME" != "v$V"', wf)  # tag must equal the version
        # Windows runners read files as cp1252 unless told: prepare.py is UTF-8
        self.assertIn('PYTHONUTF8: "1"', wf)
        self.assertNotIn("p.read_text())", wf)


if __name__ == "__main__":
    unittest.main()
