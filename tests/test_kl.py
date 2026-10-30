"""kl.py (interactive tools), pack specialists, slop gate, generic vendor, pointer files.

Run:  python -X utf8 -m unittest discover -s tests
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import kl  # noqa: E402
import ledger  # noqa: E402
import lessons  # noqa: E402
import packs  # noqa: E402
import run as run_mod  # noqa: E402
import scout  # noqa: E402
import vendors  # noqa: E402
from prepare import load_team  # noqa: E402
from test_core import AuditorCount, make_project, run_with  # noqa: E402


def card(hyp="Setting learning_rate to 0.03 helps", reject="metric does not beat the best so far"):
    return (f"HYPOTHESIS: {hyp}\nALTERNATIVES: the gain is noise\nCHANGE: edit config.json\n"
            f"EXPECT: the metric rises\nREJECT IF: {reject}\nMISSING: none\n")


class Project:
    """A throwaway keeploop project driven through kl.main, like an AI would."""

    def __init__(self, tmp, team_extra="", edit_team=None):
        self.work = make_project(tmp, team_extra)
        if edit_team:
            t = self.work / "team.yaml"
            t.write_text(edit_team(t.read_text(encoding="utf-8")), encoding="utf-8")
        self.ws = self.work / ".keeploop" / "workspace"
        self.state = self.work / ".keeploop"

    def kl(self, *args, stdin=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(sys, "stdin", io.StringIO(stdin or "")):
            rc = kl.main(["--root", str(self.work), *args])
        self.out = out.getvalue()
        return rc

    def card(self, **kw):
        return self.kl("card", "-", stdin=card(**kw))

    def edit(self, **patch):
        p = self.ws / "config.json"
        p.write_text(json.dumps({**json.loads(p.read_text()), **patch}, indent=2) + "\n")

    def commits(self):
        return len(subprocess.run(["git", "-C", str(self.ws), "log", "--oneline"],
                                  capture_output=True, text=True).stdout.splitlines())

    def rows(self):
        return ledger.read_rows(self.state)


class TestKl(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def started(self, **kw):
        p = Project(self.tmp, **kw)
        self.assertEqual(p.kl("begin"), 0, p.out)
        return p

    def test_end_to_end_begin_card_edit_check_eval_keep_report(self):
        p = self.started()
        self.assertIn("best 0.", p.out)
        self.assertEqual(p.card(), 0)
        self.assertIn("card 1 registered", p.out)
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("check"), 0)
        self.assertIn("PASS tier=light", p.out)
        self.assertEqual(p.kl("eval"), 0)
        self.assertIn("beats the bar", p.out)
        self.assertEqual(p.kl("keep"), 0, p.out)
        self.assertEqual(p.commits(), 2)
        self.assertEqual([r["status"] for r in p.rows()], ["keep", "keep"])
        hyp = [json.loads(l) for l in (p.state / "hypotheses.jsonl").read_text().splitlines()]
        self.assertEqual(hyp[0]["verdict"], "supported")
        best = json.loads((p.state / "best.json").read_text())
        # the report quotes the ledger, nothing else
        self.assertEqual(p.kl("report"), 0)
        rows = p.rows()
        self.assertIn("cycles: 1  keeps: 1  discards: 0  crashes: 0", p.out)
        self.assertIn(f"baseline: {rows[0]['metric']}  best: {best['metric']:.6f}", p.out)
        self.assertIn(f"gain over baseline: {best['metric'] - float(rows[0]['metric']):+.6f}", p.out)
        # a keep survives the next cycle's cleanup, and a no-op keep is refused
        self.assertEqual(p.card(hyp="Setting batch_size to 64 helps"), 0)
        self.assertEqual(p.kl("keep"), 1)
        self.assertIn("no files were changed", p.out)
        self.assertEqual(p.kl("discard"), 0)
        self.assertEqual(p.commits(), 2)

    def test_everything_but_audit_runs_with_no_ai_cli(self):
        real = shutil.which

        def boom(*a, **k):
            raise AssertionError("kl called a vendor")
        with mock.patch.object(vendors, "get_vendor", boom), mock.patch.object(
                shutil, "which", lambda n, *a, **k: None if n in ("claude", "codex", "gemini")
                else real(n, *a, **k)):
            p = self.started()
            self.assertEqual(p.kl("status"), 0)
            self.assertEqual(p.card(), 0)
            p.edit(learning_rate=0.03)
            for cmd in ("check", "eval", "keep", "report", "staff", "status"):
                self.assertEqual(p.kl(cmd), 0, (cmd, p.out))
            self.assertEqual(p.kl("lesson", "list"), 0)
            self.assertEqual(p.kl("pack", "new", "demo-pack"), 0)

    def test_keep_refuses_when_a_gate_fails(self):
        p = self.started(team_extra="protect: config.json")
        p.card()
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("check"), 1)
        self.assertIn("protected path", p.out)
        self.assertEqual(p.kl("keep"), 1)
        self.assertIn("protected path", p.out)
        self.assertEqual(p.commits(), 1)
        self.assertEqual(p.kl("discard", "--reason", "gate"), 0)
        self.assertEqual(p.rows()[-1]["status"], "crash")  # the gate crash is on the ledger
        self.assertTrue(p.rows()[-1]["lesson_id"])  # ...and became a lesson

    def test_secret_in_the_diff_is_refused(self):
        p = self.started()
        p.card()
        p.edit(learning_rate=0.03)
        (p.ws / "notes.txt").write_text("key AKIA" + "ABCDEFGHIJKLMNOP\n")
        self.assertEqual(p.kl("keep"), 1)
        self.assertIn("secret", p.out)
        self.assertEqual(p.commits(), 1)

    def test_slop_gate_crashes_on_added_marker_only(self):
        p = self.started()
        p.card()
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("check"), 0)  # clean diff passes
        (p.ws / "notes.txt").write_text("fix later: TODO make this real\n")
        self.assertEqual(p.kl("check"), 1)
        self.assertIn("slop: marker", p.out)
        self.assertEqual(p.kl("keep"), 1)
        self.assertEqual(p.commits(), 1)
        rules = packs.slop_rules(packs.load_pack(ROOT, "marketing-content"))
        self.assertTrue(run_mod.slop_hits("+Let us Delve in\n", rules))
        self.assertFalse(run_mod.slop_hits("-delve removed\n+plain text\n", rules))

    def test_keep_refuses_when_the_metric_is_within_noise(self):
        p = self.started(edit_team=lambda t: t.replace("keep_threshold: 0.0", "keep_threshold: 0.5"))
        p.card()
        p.edit(learning_rate=0.03)  # a real gain of about 0.1, bar is best*0.5
        self.assertEqual(p.kl("keep"), 1)
        self.assertIn("does not beat the keep bar", p.out)
        self.assertEqual(p.commits(), 1)

    def test_discard_resets_to_best_and_records(self):
        p = self.started()
        before = (p.ws / "config.json").read_text()
        p.card(hyp="Setting optimizer to sgd helps")
        p.edit(optimizer="sgd")
        (p.ws / "junk.txt").write_text("x")
        self.assertEqual(p.kl("eval"), 0)
        self.assertIn("does not beat", p.out)
        self.assertEqual(p.kl("discard", "--reason", "worse"), 0)
        self.assertEqual((p.ws / "config.json").read_text(), before)
        self.assertFalse((p.ws / "junk.txt").exists())
        self.assertEqual(p.rows()[-1]["status"], "discard")
        self.assertIn("verdict: rejected", p.rows()[-1]["description"])
        # the rejected hypothesis is remembered: repeating it is a duplicate
        self.assertEqual(p.card(hyp="Setting optimizer to sgd helps"), 1)
        self.assertIn("duplicate of cycle 1", p.out)

    def test_card_rejects_missing_label_and_vague_reject_if(self):
        p = self.started()
        bad = card().replace("MISSING: none\n", "")
        self.assertEqual(p.kl("card", "-", stdin=bad), 1)
        self.assertIn("needs HYPOTHESIS", p.out)
        self.assertEqual(p.card(reject="it does not work out"), 1)
        self.assertIn("REJECT IF must be checkable", p.out)
        self.assertEqual(p.card(reject="score drops below 0.8"), 0)  # numeric comparison passes
        self.assertTrue(lessons.load_lessons(p.state))
        self.assertTrue(run_mod.falsifiable("metric not above best"))
        self.assertFalse(run_mod.falsifiable("it fails"))
        self.assertFalse(run_mod.falsifiable("3 failures"))

    def test_tampering_is_refused(self):
        p = self.started()
        p.card()
        p.edit(learning_rate=0.03)
        (p.work / "evaluate.py").write_text("print(1.0)\n")
        self.assertEqual(p.kl("eval"), 2)
        self.assertEqual(p.kl("keep"), 2)
        self.assertEqual(p.commits(), 1)
        shutil.copy(ROOT / "evaluate.py", p.work / "evaluate.py")
        best = json.loads((p.state / "best.json").read_text())
        best["metric"] = -5.0  # lowering the bar by hand
        (p.state / "best.json").write_text(json.dumps(best))
        self.assertEqual(p.kl("keep"), 1)
        self.assertIn("best.json changed outside kl", p.out)

    def test_heavy_change_needs_a_matching_audit_verdict(self):
        p = self.started(team_extra="heavy: config.json")
        p.card()
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("keep"), 1)
        self.assertIn("needs --audit-verdict", p.out)
        self.assertEqual(p.kl("check"), 0)
        tag = p.out.split("diff=")[1].strip()
        v = Path(tempfile.mkdtemp()) / "verdict.txt"  # outside the repo: a stray file would trip the fence
        v.write_text("APPROVED: fine\n")
        self.assertEqual(p.kl("keep", "--audit-verdict", str(v)), 1)  # no DIFF line
        v.write_text(f"CHANGES REQUESTED: no\nDIFF: {tag}\n")
        self.assertEqual(p.kl("keep", "--audit-verdict", str(v)), 1)
        v.write_text(f"APPROVED: fine\nDIFF: {tag}\n")
        self.assertEqual(p.kl("keep", "--audit-verdict", str(v)), 0, p.out)
        self.assertEqual(p.commits(), 2)

    def test_audit_through_the_mock_vendor_feeds_keep(self):
        p = self.started(team_extra="heavy: config.json")
        p.card()
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("audit", "--vendor", "mock"), 0, p.out)
        self.assertTrue(p.out.startswith("APPROVED"))
        v = Path(tempfile.mkdtemp()) / "verdict.txt"  # outside the repo: a stray file would trip the fence
        v.write_text(p.out)
        self.assertEqual(p.kl("keep", "--audit-verdict", str(v)), 0, p.out)

    def test_cite_finds_dead_links_and_missing_quotes(self):
        pages = {"https://ok.example/a": "<p>The  sky is\nBLUE today</p>"}
        f = Path(self.tmp) / "doc.md"
        f.write_text('A "the sky is blue" (https://ok.example/a) and "mars is green" '
                     '(https://ok.example/a) and https://dead.example/x\n', encoding="utf-8")
        p = Project(self.tmp)
        with mock.patch.object(scout, "_fetch", lambda u, as_json=True: pages.get(u)):
            self.assertEqual(p.kl("cite", str(f)), 1)
        self.assertIn("DEAD https://dead.example/x", p.out)
        self.assertIn("QUOTE NOT FOUND in https://ok.example/a: mars is green", p.out)
        self.assertNotIn("sky is blue", p.out)


class TestStaff(unittest.TestCase):
    LOOP = "loop:\n  max_run_tokens: 777\n"

    def project(self, tmp, staffing):
        p = Project(tmp, edit_team=lambda t: t.replace("loop:\n", self.LOOP, 1) + staffing)
        assert p.kl("begin") == 0, p.out  # seals team.yaml (and its `staffing:` block) in the fence
        ledger.append_row(p.state, {"cycle": 0, "status": "keep", "metric": "0.5", "best_metric": "0.5"})
        for i in range(1, 7):
            ledger.append_row(p.state, {"cycle": i, "status": "crash" if i < 5 else "discard",
                                        "tokens": 1000, "description": "tier: heavy"})
        return p

    def test_apply_stays_inside_the_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.project(tmp, "\nstaffing:\n  allow_models: m-small, m-big\n"
                                  "  max_tokens_per_role: 40000\n")
            self.assertEqual(p.kl("staff", "--apply"), 0, p.out)
            text = (p.work / "team.yaml").read_text()
            team = load_team(p.work / "team.yaml")
            self.assertEqual(team["roles"]["engineer"]["model"], "m-big")
            self.assertEqual(team["roles"]["auditor"]["heavy_model"], "m-big")
            for cfg in team["roles"].values():
                self.assertLessEqual(cfg["token_budget"], 40000)
                self.assertIn(cfg.get("model", "m-small"), ("m-small", "m-big"))
            self.assertIn("  max_run_tokens: 777\n", text)  # never touched
            self.assertEqual(team["loop"]["max_iterations"], 20)
            self.assertIn("engineer:", (p.state / "staffing.md").read_text())

    def test_without_an_allowlist_nothing_is_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.project(tmp, "")
            before = (p.work / "team.yaml").read_bytes()
            self.assertEqual(p.kl("staff", "--apply"), 1)
            self.assertEqual((p.work / "team.yaml").read_bytes(), before)
            self.assertTrue((p.state / "staffing.md").exists())  # the proposal is still written


class TestPacks(unittest.TestCase):
    def test_pack_new_scaffolds_valid_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Project(tmp)
            self.assertEqual(p.kl("pack", "new", "cooking"), 0)
            pack = packs.load_pack(p.work, "cooking")
            self.assertEqual(pack["meta"]["status"], "experimental")
            self.assertIn("TODO", pack["meta"]["metric"])
            self.assertIn("metric_validation", pack["meta"])
            self.assertTrue(packs.scout_topics(pack))
            self.assertIn("reviewer-one", packs.specialists_text(pack))
            self.assertTrue(run_mod.rubric_mod.load_rubric(pack["rubric_path"]))
            self.assertIn("AUTOMATIC metric", (p.work / "packs/cooking/pack.yaml").read_text())
            self.assertEqual(p.kl("pack", "new", "cooking"), 1)  # never overwrites
            self.assertEqual(p.kl("pack", "new", "../evil"), 1)

    def test_shipped_software_pack_declares_specialists_and_topics(self):
        pack = packs.load_pack(ROOT, "software")
        text = packs.specialists_text(pack)
        self.assertIn("- security:", text)
        self.assertIn("- performance:", text)
        self.assertTrue(packs.scout_topics(pack))

    def test_specialist_checklist_file_cannot_escape_the_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "pack"
            d.mkdir()
            (Path(tmp) / "secret.txt").write_text("LEAK")
            (d / "ok.md").write_text("check\nthis")
            pack = {"dir": d, "meta": {"roles": {"a": {"checklist_file": "ok.md"},
                                                 "b": {"checklist_file": "../secret.txt"}}}}
            text = packs.specialists_text(pack)
            self.assertIn("- a: check this", text)
            self.assertNotIn("LEAK", text)

    def test_specialists_reach_the_audit_prompt_of_heavy_changes_only(self):
        for extra, heavy in (("heavy: config.json", True), ("", False)):
            with tempfile.TemporaryDirectory() as tmp:
                AuditorCount.prompts = []
                run_with(AuditorCount, tmp, 1, team_extra=extra)
                self.assertEqual(len(AuditorCount.prompts), 1)
                self.assertEqual("Specialist reviewers" in AuditorCount.prompts[0], heavy)
                self.assertEqual("- security:" in AuditorCount.prompts[0], heavy)

    def test_scout_uses_pack_topics(self):
        seen = {}
        with tempfile.TemporaryDirectory() as tmp:
            work = make_project(tmp)
            with mock.patch.object(scout, "fetch_hn", lambda q=None: seen.setdefault("hn", q) and []), \
                    mock.patch.object(scout, "fetch_arxiv", lambda: []), \
                    mock.patch.object(scout, "fetch_github", lambda t=None: seen.setdefault("gh", t) and []), \
                    contextlib.redirect_stdout(io.StringIO()):
                scout.main(["--dry-run", "--state-dir", str(Path(tmp) / "s")], work)
        self.assertIn("secure coding", seen["hn"])
        self.assertIn("secure-coding", seen["gh"])


class TestVendorAgnostic(unittest.TestCase):
    def test_pointer_files_reference_agents_md(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("python kl.py keep", agents)
        for rel in ("CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("AGENTS.md", text, rel)
            self.assertLess(len(text), 400, rel)  # a pointer, not a second source of truth
        self.assertFalse((ROOT / ".cursorrules").exists())

    def test_generic_cli_vendor_gets_stdin_and_a_scrubbed_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake_cli.py"
            fake.write_text(
                "import os, sys\nprompt = sys.stdin.read()\n"
                "print('GOT:' + prompt)\nprint('ARGV:' + ' '.join(sys.argv[1:]))\n"
                "print('SEEN:' + ','.join(k for k in ('GITHUB_TOKEN', 'MYSECRET_TOKEN', "
                "'FAKEV_API_KEY') if k in os.environ))\n", encoding="utf-8")
            exe = sys.executable.replace("\\", "/")
            spec = {"fakev": {"cmd": f'"{exe}" {fake.as_posix()} -p', "edit_args": "--edit",
                              "model_flag": "--mdl", "env_keep": "FAKEV_",
                              "env_allow": "FAKEV_API_KEY"}}
            env = {"GITHUB_TOKEN": "x", "MYSECRET_TOKEN": "y", "FAKEV_API_KEY": "z"}
            with mock.patch.dict(os.environ, env):
                v = vendors.get_vendor("fakev", custom=spec, model="m1")
                self.assertTrue(v.available())
                eng = v.complete("hello prompt", role="engineer", max_tokens=1, cwd=tmp).text
                aud = v.complete("hello prompt", role="auditor", max_tokens=1, cwd=tmp).text
        self.assertIn("GOT:hello prompt", eng)
        self.assertIn("ARGV:-p --edit --mdl m1", eng)  # edit rights for the engineer only
        self.assertIn("ARGV:-p --mdl m1", aud)
        self.assertIn("SEEN:FAKEV_API_KEY", eng)  # its own key survives, the others do not
        self.assertNotIn("GITHUB_TOKEN", eng.split("SEEN:")[1])
        self.assertNotIn("MYSECRET_TOKEN", eng.split("SEEN:")[1])

    def test_generic_vendor_refuses_dangerous_declarations(self):
        for keep in ("GITHUB_", "AWS_", "A_", "TOKEN_", "lower_", "GITHUB_TOKEN"):
            with self.assertRaises(vendors.VendorUnavailable, msg=keep):
                vendors.get_vendor("v", custom={"v": {"cmd": "x -p", "env_keep": keep}})
        for name, spec in (("claude-cli", {"cmd": "x"}), ("v", {"cmd": ""}), ("Bad Name", {"cmd": "x"})):
            with self.assertRaises(vendors.VendorUnavailable, msg=name):
                vendors.get_vendor(name, custom={name: spec})

    def test_team_yaml_vendors_block_and_headless_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake.py"
            fake.write_text("import sys\nsys.stdin.read()\nprint('APPROVED')\n")
            exe = sys.executable.replace("\\", "/")
            extra = f"vendors:\n  fakev:\n    cmd: {exe} {fake.as_posix()}\n"
            work = make_project(tempfile.mkdtemp(), extra)
            team = load_team(work / "team.yaml")
            self.assertEqual(team["vendors"]["fakev"]["cmd"].split()[0], exe)
            vendors.get_vendor("fakev", custom=team["vendors"])  # resolves from the block
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
