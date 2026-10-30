"""Fix round 7: fence laundering, env scrub, redirects, packaging, symlinks, loop overrides,
best_before, critic timing, revised-card validation, reserved pack names.

Run:  python -X utf8 -m unittest discover -s tests
"""

import ast
import contextlib
import datetime
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import codemap  # noqa: E402
import kl  # noqa: E402
import lessons  # noqa: E402
import run as run_mod  # noqa: E402
import scout  # noqa: E402
import vendors  # noqa: E402
from test_core import make_project  # noqa: E402
from test_kl import Project, card  # noqa: E402

STAFFING = "\nstaffing:\n  allow_models: m-small, m-big\n  max_tokens_per_role: 40000\n"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def started(self, **kw):
        p = Project(self.tmp, **kw)
        self.assertEqual(p.kl("begin"), 0, p.out)
        self.side = Path(tempfile.mkdtemp())  # scratch files must stay outside the fenced project
        self.addCleanup(lambda: __import__("shutil").rmtree(self.side, ignore_errors=True))
        return p


class TestB1StaffCannotLaunderTamper(Base):
    def test_pre_tampered_team_yaml_is_refused_and_the_fence_stays(self):
        p = self.started(edit_team=lambda t: t)  # sealed WITHOUT a staffing allowlist
        team = p.work / "team.yaml"
        team.write_text(team.read_text(encoding="utf-8") + "protect: nothing-evil\n" + STAFFING,
                        encoding="utf-8")
        self.assertEqual(p.kl("eval"), 2, p.out)
        fence, tampered = (p.state / "fence.json").read_bytes(), team.read_bytes()
        self.assertEqual(p.kl("staff", "--apply"), 2, p.out)
        self.assertNotIn("applied", p.out)
        self.assertEqual((p.state / "fence.json").read_bytes(), fence)  # not re-sealed
        self.assertEqual(team.read_bytes(), tampered)  # nothing rewritten
        self.assertEqual(p.kl("eval"), 2, p.out)  # still broken

    def test_allowlist_added_after_the_seal_is_refused_even_alone(self):
        p = self.started(edit_team=lambda t: t)
        team = p.work / "team.yaml"
        team.write_text(team.read_text(encoding="utf-8") + STAFFING, encoding="utf-8")
        fence = (p.state / "fence.json").read_bytes()
        self.assertEqual(p.kl("staff", "--apply"), 2, p.out)
        self.assertEqual((p.state / "fence.json").read_bytes(), fence)


class TestS1CustomEnv(unittest.TestCase):
    SECRETS = {"NODE_AUTH_TOKEN": "a", "SLACK_BOT_TOKEN": "b", "STRIPE_SECRET_KEY": "c",
               "OPENAI_API_KEY": "d", "GOOGLE_APPLICATION_CREDENTIALS": "e", "NODE_ENV": "ok"}
    KEEP = "NODE_,SLACK_,STRIPE_,OPENAI_,GOOGLE_"

    def env(self, **spec):
        with mock.patch.dict(os.environ, self.SECRETS):
            v = vendors.custom_vendor("v", {"cmd": "x -p", "env_keep": self.KEEP, **spec}, 5, None)
            return vendors.safe_env(v.env_keep, v.env_allow)

    def test_kept_prefix_does_not_let_other_services_secrets_through(self):
        env = self.env()
        for name in self.SECRETS:
            self.assertEqual(name in env, name == "NODE_ENV", name)

    def test_only_an_exact_env_allow_name_passes(self):
        env = self.env(env_allow="OPENAI_API_KEY")
        self.assertIn("OPENAI_API_KEY", env)
        for name in ("NODE_AUTH_TOKEN", "SLACK_BOT_TOKEN", "STRIPE_SECRET_KEY",
                     "GOOGLE_APPLICATION_CREDENTIALS"):
            self.assertNotIn(name, env)

    def test_env_allow_must_sit_under_a_kept_prefix(self):
        for bad in ("GITHUB_TOKEN", "lower_key"):
            with self.assertRaises(vendors.VendorUnavailable, msg=bad):
                vendors.custom_vendor("v", {"cmd": "x", "env_keep": "MYV_", "env_allow": bad}, 5, None)

    def test_presets_keep_their_own_keys(self):
        env = {"ANTHROPIC_API_KEY": "1", "OPENAI_API_KEY": "2", "GEMINI_API_KEY": "3",
               "GOOGLE_API_KEY": "4", "GITHUB_TOKEN": "5"}
        with mock.patch.dict(os.environ, env):
            for cli, name in (("claude-cli", "ANTHROPIC_API_KEY"), ("codex-cli", "OPENAI_API_KEY"),
                              ("gemini-cli", "GEMINI_API_KEY"), ("gemini-cli", "GOOGLE_API_KEY")):
                got = vendors.safe_env(vendors.ENV_KEEP[cli])
                self.assertIn(name, got, (cli, name))
                self.assertNotIn("GITHUB_TOKEN", got)


class TestS2Fetch(unittest.TestCase):
    def resolve(self, ip):
        return mock.patch.object(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (ip, 443))])

    def test_private_loopback_linklocal_reserved_hosts_are_refused(self):
        for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "0.0.0.0",
                   "240.0.0.1", "::1", "fe80::1", "::ffff:127.0.0.1"):
            with self.resolve(ip), self.assertRaises(ValueError, msg=ip):
                scout._check_url("https://example.test/")
        with self.resolve("93.184.216.34"):
            scout._check_url("https://example.test/")  # public: fine
        with self.assertRaises(ValueError):
            scout._check_url("http://example.test/")

    def test_fetch_never_opens_a_private_host(self):
        def boom(*a, **k):
            raise AssertionError("opened")
        with self.resolve("127.0.0.1"), mock.patch.object(scout, "_open", boom), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(scout._fetch("https://internal.test/x"))

    def test_redirects_must_stay_https_and_public(self):
        h = scout._HttpsOnly()
        req = urllib.request.Request("https://a.test/")
        args = (req, io.BytesIO(b""), 302, "Found", {})
        with self.resolve("93.184.216.34"):
            self.assertIsNotNone(h.redirect_request(*args, "https://b.test/ok"))
            with self.assertRaises(ValueError):
                h.redirect_request(*args, "http://b.test/plain")
        with self.resolve("10.1.2.3"), self.assertRaises(ValueError):
            h.redirect_request(*args, "https://b.test/private")
        self.assertIn(scout._HttpsOnly, [type(x) for x in scout._OPENER.handlers])


class TestS3Packaging(unittest.TestCase):
    def test_every_local_import_is_packaged_and_kl_is_a_script(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs Python 3.11+")
        cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        mods = set(cfg["tool"]["setuptools"]["py-modules"])
        self.assertEqual(cfg["project"]["scripts"]["kl"], "kl:main")
        local = {p.stem for p in ROOT.glob("*.py")}
        need = set()
        for name in sorted(mods) + ["kl", "run"]:
            for node in ast.walk(ast.parse((ROOT / f"{name}.py").read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    need |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    need.add(node.module.split(".")[0])
        self.assertEqual(sorted((need & local) - mods), [])
        self.assertTrue({"kl", "bm25", "codemap", "holdout"} <= mods)
        self.assertTrue(callable(kl.main))


class TestS4CodemapSymlinks(Base):
    def repo(self):
        ws = Path(self.tmp) / "ws"
        ws.mkdir()
        (ws / "a.py").write_text("def real(): pass\n", encoding="utf-8")
        (ws / "link.py").write_text("def leaked(): pass\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
        subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
        return ws

    def test_a_tracked_symlink_is_not_followed(self):
        ws = self.repo()
        real = Path.is_symlink
        with mock.patch.object(Path, "is_symlink", lambda self: self.name == "link.py" or real(self)):
            m = codemap.build(ws)
        self.assertIn("a.py", m)
        self.assertNotIn("link.py", m)

    def test_a_path_resolving_outside_the_workspace_is_skipped(self):
        ws = self.repo()
        real = Path.resolve

        def resolve(self, *a, **k):
            return Path(self.anchor) / "elsewhere" / self.name if self.name == "link.py" else real(self, *a, **k)
        with mock.patch.object(Path, "resolve", resolve):
            m = codemap.build(ws)
        self.assertNotIn("link.py", m)
        self.assertIn("a.py", m)


class TestC1LoopOverrides(Base):
    OVERRIDES = {"eval_timeout_s": 7, "token_budget_per_role": 12000, "vendor_timeout_s": 11,
                 "guardrail_max_chars": 200, "lesson_retire_after_days": 3,
                 "lesson_effective_after": 0, "repo_map_max_chars": 120}

    def edit(self, t):
        loop = "loop:\n" + "".join(f"  {k}: {v}\n" for k, v in self.OVERRIDES.items())
        for n in ("30000", "50000"):  # roles fall back to token_budget_per_role
            t = t.replace(f"    token_budget: {n}\n", "")
        return t.replace("loop:\n", loop, 1)

    def test_every_overridable_key_takes_effect(self):
        p = self.started(edit_team=self.edit)
        c = kl.load(p.work)
        for k, v in self.OVERRIDES.items():
            self.assertEqual(c.loop_cfg[k], v, k)
        # eval_timeout_s (kl eval) and lesson replay
        seen = []
        real = subprocess.run

        def spy(*a, **k):
            seen.append(k.get("timeout"))
            return real(*a, **k)
        p.card()
        p.edit(learning_rate=0.03)
        with mock.patch.object(subprocess, "run", spy):
            self.assertEqual(p.kl("eval"), 0, p.out)
        self.assertIn(7, seen)
        self.assertEqual(p.kl("lesson", "add", "w", "c", "rule zero", "--", sys.executable, "-c", "pass"), 0)
        seen.clear()
        with mock.patch.object(subprocess, "run", spy):
            self.assertEqual(lessons.replay(p.state, p.ws, c.loop_cfg), [])
        self.assertEqual(seen, [7])
        # token_budget_per_role (kl staff) and repo_map_max_chars (kl map)
        self.assertEqual(kl.staff_proposal(c)[0]["analyst"]["token_budget"], 12000)
        self.assertEqual(p.kl("map"), 0)
        self.assertLessEqual(len(p.out.strip()), 120)
        # vendor_timeout_s (kl audit)
        got = {}

        def fake_vendor(name, timeout_s=0, **kw):
            got["t"] = timeout_s
            raise vendors.VendorUnavailable("stop")
        with mock.patch.object(vendors, "get_vendor", fake_vendor):
            self.assertEqual(p.kl("audit", "--vendor", "x"), 1)
        self.assertEqual(got["t"], 11)
        # guardrail_max_chars, lesson_retire_after_days, lesson_effective_after (kl lesson ...)
        for i, rule in enumerate(("keep every cycle small and focused on one idea, always",
                                  "never skip running the whole test suite before a keep",
                                  "always read the complete diff before you keep a change")):
            self.assertEqual(p.kl("lesson", "add", f"w{i}", "c", rule), 0)
        self.assertEqual((p.state / "guardrails.md").read_text(encoding="utf-8").count("- **L-"), 1)
        path = p.state / "lessons.jsonl"
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5)).isoformat()
        rows[1]["ts"] = old  # L-002 (the "rule zero" check lesson is L-001)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        self.assertEqual(p.kl("lesson", "review"), 0)
        self.assertNotIn("L-002", p.out)  # retired after 3 days
        self.assertIn("L-004  [effective]", p.out)  # effective after 0 clean cycles

    def test_headless_run_reads_the_merged_config(self):
        p = Project(self.tmp, edit_team=self.edit)
        got = {"budget": set(), "vt": set(), "et": set()}

        class Spy(vendors.MockVendor):
            def complete(self, prompt, *, role, max_tokens, cwd=None):
                got["budget"].add(max_tokens)
                return super().complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)

        gv, ew = vendors.get_vendor, run_mod.evaluate_workspace
        with mock.patch.object(vendors, "MockVendor", Spy), \
                mock.patch.object(vendors, "get_vendor", lambda n, timeout_s=0, **k: (
                    got["vt"].add(timeout_s), gv(n, timeout_s=timeout_s, **k))[1]), \
                mock.patch.object(run_mod, "evaluate_workspace", lambda r, w, s="evaluate.py", t=None: (
                    got["et"].add(t), ew(r, w, s, t))[1]), \
                contextlib.redirect_stdout(io.StringIO()):
            run_mod.run(p.work, mock=True, iterations=1)
        self.assertEqual((got["budget"], got["vt"], got["et"]), ({12000}, {11}, {7}))


class TestC2C3Timing(Base):
    def test_best_before_is_the_best_before_the_keep(self):
        p = self.started()
        before = json.loads((p.state / "best.json").read_text())["metric"]
        p.card()
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("keep"), 0, p.out)
        after = json.loads((p.state / "best.json").read_text())["metric"]
        h = [json.loads(l) for l in (p.state / "hypotheses.jsonl").read_text().splitlines()][-1]
        self.assertGreater(after, before)
        self.assertEqual((h["best_before"], h["metric"]), (before, after))

    def test_critic_time_is_recorded_and_not_counted_as_agent_time(self):
        p = self.started()
        p.card()
        cy = json.loads((p.state / "cycle.json").read_text())
        cy["t0"] = time.time() - 50
        (p.state / "cycle.json").write_text(json.dumps(cy), encoding="utf-8")
        f = self.side / "critique.md"
        f.write_text("Looks fine.\nVERDICT: proceed\n", encoding="utf-8")
        self.assertEqual(p.kl("debate", "1", "--critic", str(f)), 0, p.out)
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("keep"), 0, p.out)
        row = json.loads((p.state / "timing.jsonl").read_text().splitlines()[-1])
        self.assertGreaterEqual(row["critic"], 49)
        self.assertLess(row["agent"], 10)  # wall ~50s minus the 50s critic phase


class TestN1RevisedCard(Base):
    def critic(self, p):
        f = self.side / "critique.md"
        f.write_text("Weak.\nVERDICT: revise\n", encoding="utf-8")
        self.assertEqual(p.kl("debate", "2", "--critic", str(f)), 0, p.out)

    def reply(self, p, text):
        f = self.side / "reply.md"
        f.write_text(text, encoding="utf-8")
        return p.kl("debate", "2", "--reply", str(f))

    def two_cycles(self):
        p = self.started()
        p.card(hyp="Setting optimizer to sgd helps")
        p.edit(optimizer="sgd")
        self.assertEqual(p.kl("eval"), 0)  # a measured, worse metric -> verdict rejected
        self.assertEqual(p.kl("discard"), 0)
        self.assertEqual(p.card(hyp="Setting batch_size to 64 helps"), 0)
        self.critic(p)
        return p

    def test_revised_card_that_repeats_a_rejected_one_is_refused(self):
        p = self.two_cycles()
        self.assertEqual(self.reply(p, card(hyp="Setting optimizer to sgd helps")), 1)
        self.assertIn("duplicate of cycle 1", p.out)
        parsed = json.loads((p.state / "cycle.json").read_text())["parsed"]
        self.assertIn("batch_size", parsed["hypothesis"])  # the open card is unchanged
        self.assertNotIn("## Reply", (p.state / "debate" / "2.md").read_text(encoding="utf-8"))

    def test_revised_card_missing_goes_to_questions_and_vague_reject_is_refused(self):
        p = self.two_cycles()
        self.assertEqual(self.reply(p, card(hyp="Setting batch_size to 64 helps",
                                            reject="it does not work out")), 1)
        text = card(hyp="Setting batch_size to 64 helps").replace(
            "MISSING: none", "MISSING: the real dataset path")
        self.assertEqual(self.reply(p, text), 0, p.out)
        self.assertIn("the real dataset path", (p.state / "questions.md").read_text(encoding="utf-8"))


class TestN2ReservedPackNames(Base):
    def test_windows_device_names_are_refused(self):
        p = Project(self.tmp)
        for name in ("con", "nul", "aux", "prn", "com1", "lpt9", "con.txt", "CON", "Nul.md", "../x"):
            self.assertEqual(p.kl("pack", "new", name), 1, name)
        self.assertEqual(p.kl("pack", "new", "console"), 0)  # only the exact device names


if __name__ == "__main__":
    unittest.main()
