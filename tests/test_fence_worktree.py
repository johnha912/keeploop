"""The fence over a workspace that is a git worktree (the setup AGENTS.md recommends).

In a worktree, <workspace>/.git is a file that points at the real git dir, and the
config, hooks and info that git runs from live in the main repository's .git. A
change there (core.hooksPath, an alias, a filter) can make keeploop's own git calls
run commands, so the fence must cover it.

Run:  python -X utf8 -m unittest discover -s tests
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import kl  # noqa: E402
import run as run_mod  # noqa: E402
from prepare import INITIAL_WORKSPACE  # noqa: E402
from test_core import make_project  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def git_keys(snap):
    """The fence entries that cover git's own files (config, hooks, info)."""
    return {k: v[:12] for k, v in snap.items() if k.startswith("<")}


class TestWorktreeFence(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        # the user's own repository, and a worktree of it for the loop
        self.main = base / "app"
        self.main.mkdir()
        git(self.main, "init", "-q")
        git(self.main, "config", "user.email", "t@example.com")
        git(self.main, "config", "user.name", "t")
        (self.main / "config.json").write_text(json.dumps(INITIAL_WORKSPACE, indent=2), encoding="utf-8")
        git(self.main, "add", "config.json")
        git(self.main, "commit", "-q", "-m", "app")
        self.ws = base / "app-keeploop"
        git(self.main, "worktree", "add", "-q", str(self.ws), "-b", "keeploop")
        self.ws = self.ws.resolve()  # kl reports resolved paths (macOS /private/var, Windows 8.3 names)
        self.assertTrue((self.ws / ".git").is_file())  # a gitdir pointer, not a directory
        # the keeploop project beside it, pointed at the worktree
        self.work = base / "ctl"
        self.work.mkdir()
        make_project(str(self.work))
        team = self.work / "team.yaml"
        text = team.read_text(encoding="utf-8")
        self.assertIn("workspace: .keeploop/workspace\n", text)
        team.write_text(text.replace("workspace: .keeploop/workspace\n", f"workspace: {self.ws.as_posix()}\n"),
                        encoding="utf-8")

    def kl(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                rc = kl.main(["--root", str(self.work), *args])
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue()

    def test_a_change_to_the_main_repos_git_config_breaks_the_fence(self):
        rc, out = self.kl("begin")
        self.assertEqual(rc, 0, out)  # baseline measured, fence sealed
        self.assertIn(f"workspace: {self.ws}", out)  # the loop runs in the worktree
        before = run_mod.fence_files(self.work, self.ws)
        # after the seal: the shared config gains a hooks path (git would run its hooks)
        git(self.main, "config", "core.hooksPath", str(self.work / "evil-hooks"))
        after = run_mod.fence_files(self.work, self.ws)
        self.assertNotEqual(before, after, f"the fence does not cover the main repo's .git/config: {git_keys(after)}")
        rc, out = self.kl("begin")  # a resumed session checks the fence first
        self.assertNotEqual(rc, 0, out)
        self.assertIn("config", out)

    def test_the_git_dirs_are_the_ones_git_reports(self):
        gitdir, common = run_mod.git_dirs(self.ws)
        want = git(self.ws, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir").split()
        self.assertEqual([gitdir, common], [Path(p).resolve() for p in want])
        self.assertEqual(common, (self.main / ".git").resolve())

    def test_a_new_hook_in_the_main_repo_breaks_the_fence(self):
        rc, out = self.kl("begin")
        self.assertEqual(rc, 0, out)
        before = run_mod.fence_files(self.work, self.ws)
        common = Path(git(self.ws, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
        (common / "hooks" / "post-checkout").write_text("#!/bin/sh\necho owned\n", encoding="utf-8")
        after = run_mod.fence_files(self.work, self.ws)
        self.assertNotEqual(before, after, f"the fence does not cover the main repo's hooks: {git_keys(after)}")

    def test_a_plain_repo_workspace_is_covered_as_before(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = make_project(tmp.name)  # the default workspace: .keeploop/workspace, its own .git dir
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(kl.main(["--root", str(work), "begin"]), 0, out.getvalue())
        ws = work / ".keeploop" / "workspace"
        self.assertTrue((ws / ".git").is_dir())
        before = run_mod.fence_files(work, ws)
        git(ws, "config", "alias.st", "!echo owned")
        (ws / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\necho owned\n", encoding="utf-8")
        after = run_mod.fence_files(work, ws)
        changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        self.assertTrue(any(k.endswith("config") for k in changed), changed)
        self.assertTrue(any(k.endswith("pre-commit") for k in changed), changed)


if __name__ == "__main__":
    unittest.main()
