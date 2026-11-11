"""The fast path: `kl next`, `kl try`, `kl handoff`, `kl apply`. Same gates, fence,
keep bar, confirm re-run and audit rule as the step-by-step commands, in fewer commands.

Run:  python -X utf8 -m unittest discover -s tests
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import kl  # noqa: E402
import run as run_mod  # noqa: E402
from test_kl import Project, card  # noqa: E402

LR = "A learning rate near 0.03 scores higher than 0.01."


def card_text(hyp=LR, reject="metric <= the keep bar", extra=""):
    return card(hyp=hyp, reject=reject) + extra


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.cards = Path(tempfile.mkdtemp())  # outside the project: a card file never trips the fence
        self.addCleanup(shutil.rmtree, self.cards, True)

    def started(self, **kw):
        (self.tmp / "p").mkdir()
        p = Project(str(self.tmp / "p"), **kw)
        self.assertEqual(p.kl("begin"), 0, p.out)
        return p

    def write(self, name, text):
        path = self.cards / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def hyps(self, p):
        return [json.loads(l) for l in (p.state / "hypotheses.jsonl").read_text().splitlines()]

    def clean(self, p):
        return not run_mod.git(p.ws, "status", "--porcelain").strip()


class TestNext(Base):
    def test_brief_is_short_and_has_a_card_skeleton(self):
        p = self.started()
        self.assertEqual(p.kl("next"), 0)
        lines = p.out.strip().splitlines()
        self.assertLessEqual(len(lines), 16, p.out)
        self.assertIn("bar 0.828178", lines[0])
        self.assertIn("workspace: .keeploop/workspace", p.out)
        self.assertIn(f"next hypothesis: {LR}", p.out)
        self.assertIn(f"HYPOTHESIS: {LR}", p.out)
        self.assertIn("REJECT IF: metric <= 0.828178", p.out)
        parsed = run_mod.parse_card("\n".join(lines[-6:]))
        self.assertIsNotNone(parsed)  # the skeleton is a card once its ? are filled
        self.assertTrue(run_mod.falsifiable(parsed["reject_if"]))

    def test_memory_hits_are_rejected_hypotheses_and_lessons(self):
        p = self.started()
        p.edit(learning_rate=0.003)
        self.assertEqual(p.kl("try", self.write("c.md", card_text())), kl.EXIT_DISCARDED, p.out)
        self.assertEqual(p.kl("next"), 0)
        self.assertIn("memory (do not repeat):", p.out)
        self.assertIn("hypothesis cycle 1", p.out)
        self.assertIn("[rejected]", p.out)

    def test_stop_line_and_no_skeleton_when_the_target_is_reached(self):
        p = self.started(team_extra="loop:\n  target: 0.5")
        self.assertEqual(p.kl("next"), 0)
        self.assertIn("STOP: target reached", p.out)
        self.assertIn("report", p.out)
        self.assertNotIn("HYPOTHESIS", p.out)

    def test_pending_card_is_shown_with_how_to_finish_it(self):
        p = self.started()
        self.assertEqual(p.card(), 0, p.out)
        p.kl("next")
        self.assertIn("pending card 1", p.out)
        self.assertNotIn("HYPOTHESIS:", p.out)


class TestTry(Base):
    def test_decisive_light_gain_is_kept_in_one_command_with_one_evaluation(self):
        p = self.started()
        before = p.commits()
        p.edit(learning_rate=0.03)
        calls = []
        real = kl._evaluate
        with mock.patch.object(kl, "_evaluate", lambda c, s="evaluate.py": calls.append(s) or real(c, s)):
            rc = p.kl("try", self.write("c.md", card_text()))
        self.assertEqual(rc, 0, p.out)
        self.assertEqual(len(calls), 1)  # light and sigma 0: no confirm re-run, as in run.py
        lines = p.out.strip().splitlines()
        self.assertEqual(len(lines), 4, p.out)  # one line per step
        self.assertTrue(lines[-1].startswith("KEPT cycle 1"))
        self.assertEqual(p.commits(), before + 1)
        self.assertEqual(p.rows()[-1]["status"], "keep")
        self.assertEqual(self.hyps(p)[-1]["verdict"], "supported")
        self.assertFalse((p.state / "cycle.json").exists())

    def test_a_loser_is_discarded_with_a_verdict(self):
        p = self.started()
        p.edit(learning_rate=0.003)
        self.assertEqual(p.kl("try", self.write("c.md", card_text())), kl.EXIT_DISCARDED, p.out)
        self.assertIn("does not beat the bar", p.out)
        self.assertIn("discarded cycle 1", p.out)
        self.assertEqual(p.rows()[-1]["status"], "discard")
        self.assertEqual(self.hyps(p)[-1]["verdict"], "rejected")
        self.assertTrue(self.clean(p))

    def test_a_failed_gate_is_discarded_with_a_lesson_and_no_evaluation(self):
        p = self.started()
        (p.ws / ".env").write_text("API_KEY=abc\n")
        with mock.patch.object(kl, "_evaluate", side_effect=AssertionError("evaluated")):
            rc = p.kl("try", self.write("c.md", card_text()))
        self.assertEqual(rc, kl.EXIT_DISCARDED, p.out)
        self.assertIn("FAIL gate: secret blocked", p.out)
        self.assertEqual(p.rows()[-1]["status"], "crash")
        self.assertTrue(p.rows()[-1]["lesson_id"])
        self.assertEqual(self.hyps(p)[-1]["verdict"], "untested")
        self.assertTrue(self.clean(p))

    def test_evaluation_crash_saves_the_full_stderr_and_discards(self):
        p = self.started()
        p.edit(batch_size=7)
        self.assertEqual(p.kl("try", self.write("c.md", card_text())), kl.EXIT_DISCARDED, p.out)
        self.assertIn("FAIL evaluation crashed", p.out)
        self.assertIn("eval-stderr.txt", p.out)
        self.assertIn("INVALID WORKSPACE", (p.state / "eval-stderr.txt").read_text())
        self.assertEqual(p.rows()[-1]["status"], "crash")

    def test_gain_that_is_not_decisive_waits_for_an_audit(self):
        p = self.started()
        p.edit(dropout=0.15)  # +0.006: beats the bar, under 1% of best
        cardf = self.write("c.md", card_text(hyp="Dropout 0.15 beats 0.1"))
        self.assertEqual(p.kl("try", cardf), kl.EXIT_WAIT, p.out)
        self.assertIn("WAIT audit required (the gain is not decisive)", p.out)
        tag = p.out.split("`DIFF: ")[1][:12]
        self.assertTrue((p.state / "cycle.json").exists())  # the cycle stays open
        self.assertFalse(self.clean(p))
        # a verdict for another diff is refused and the cycle stays open
        bad = self.write("bad.txt", "APPROVED\nDIFF: 000000000000\n")
        self.assertEqual(p.kl("try", "--audit-verdict", bad), 1, p.out)
        self.assertIn("different diff", p.out)
        self.assertTrue((p.state / "cycle.json").exists())
        good = self.write("ok.txt", f"APPROVED\nDIFF: {tag}\n")
        self.assertEqual(p.kl("try", cardf, "--audit-verdict", good), 0, p.out)
        self.assertIn("KEPT cycle 1", p.out)

    def test_audit_changes_requested_discards_with_a_lesson(self):
        p = self.started()
        p.edit(dropout=0.15)
        self.assertEqual(p.kl("try", self.write("c.md", card_text(hyp="Dropout 0.15"))), kl.EXIT_WAIT)
        tag = p.out.split("`DIFF: ")[1][:12]
        v = self.write("v.txt", f"CHANGES REQUESTED\nscope: unrelated edit\nDIFF: {tag}\n")
        self.assertEqual(p.kl("try", "--audit-verdict", v), kl.EXIT_DISCARDED, p.out)
        self.assertIn("keep refused: audit", p.out)
        self.assertEqual(p.rows()[-1]["status"], "discard")
        self.assertTrue(p.rows()[-1]["lesson_id"])
        self.assertEqual(self.hyps(p)[-1]["verdict"], "inconclusive")

    def test_heavy_change_needs_an_audit_and_the_confirm_rerun(self):
        p = self.started(team_extra="loop:\n  heavy_diff_lines: 0")
        p.edit(learning_rate=0.03)
        cardf = self.write("c.md", card_text())
        self.assertEqual(p.kl("try", cardf), kl.EXIT_WAIT, p.out)
        self.assertIn("audit required (heavy change)", p.out)
        tag = p.out.split("`DIFF: ")[1][:12]
        calls = []
        real = kl._evaluate
        v = self.write("v.txt", f"APPROVED\nDIFF: {tag}\n")
        with mock.patch.object(kl, "_evaluate", lambda c, s="evaluate.py": calls.append(s) or real(c, s)):
            self.assertEqual(p.kl("try", "--audit-verdict", v), 0, p.out)
        self.assertEqual(len(calls), 2)  # the evaluation and the confirm re-run
        self.assertIn("tier: heavy", p.rows()[-1]["description"])

    def test_unconfirmed_rerun_is_discarded(self):
        p = self.started(team_extra="loop:\n  heavy_diff_lines: 0")
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("try", self.write("c.md", card_text())), kl.EXIT_WAIT)
        tag = p.out.split("`DIFF: ")[1][:12]
        v = self.write("v.txt", f"APPROVED\nDIFF: {tag}\n")
        scores = iter([(0.94, ""), (0.5, "")])
        with mock.patch.object(kl, "_evaluate", lambda c, s="evaluate.py": next(scores)):
            self.assertEqual(p.kl("try", "--audit-verdict", v), kl.EXIT_DISCARDED, p.out)
        self.assertIn("unconfirmed", p.out)
        self.assertIn("unconfirmed", p.rows()[-1]["description"])

    def test_declared_heavy_card_waits_for_the_critic_first(self):
        p = self.started()
        p.edit(learning_rate=0.03)
        cardf = self.write("c.md", card_text(extra="TIER: heavy\n"))
        with mock.patch.object(kl, "_evaluate", side_effect=AssertionError("evaluated")):
            self.assertEqual(p.kl("try", cardf), kl.EXIT_WAIT, p.out)
        self.assertIn("WAIT heavy card 1", p.out)
        self.assertIn("debate 1 --critic", p.out)
        crit = self.write("crit.txt", "OBJECTIONS: none\nSTRONGEST ALTERNATIVE: none\n"
                                      "REJECT-IF CHECK: fine\nVERDICT: proceed\n")
        self.assertEqual(p.kl("debate", "1", "--critic", crit), 0, p.out)
        # then the gates decide the tier, as in `kl keep`: a 2-line decisive change is light
        self.assertEqual(p.kl("try"), 0, p.out)
        self.assertIn("KEPT cycle 1", p.out)

    def test_card_refusals_keep_the_edit_and_a_fixed_card_goes_through(self):
        p = self.started()
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("try", self.write("v.md", card_text(reject="it feels worse"))), 1)
        self.assertIn("REJECT IF must be checkable", p.out)
        self.assertFalse(self.clean(p))  # the edit is still there
        self.assertEqual(p.kl("try", self.write("c.md", card_text())), 0, p.out)

    def test_open_card_with_another_text_is_refused(self):
        p = self.started()
        p.edit(dropout=0.15)
        self.assertEqual(p.kl("try", self.write("c.md", card_text(hyp="Dropout 0.15"))), kl.EXIT_WAIT)
        self.assertEqual(p.kl("try", self.write("d.md", card_text(hyp="something else"))), 1)
        self.assertIn("still open with another text", p.out)
        self.assertEqual(p.kl("try"), kl.EXIT_WAIT)  # no FILE: continues the open card
        self.assertEqual(p.kl("discard", "--reason", "x"), 0)
        self.assertEqual(p.kl("try"), 1)
        self.assertIn("no open card", p.out)

    def test_brake_and_fence_still_hold(self):
        p = self.started(team_extra="loop:\n  target: 0.5")
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("try", self.write("c.md", card_text())), 1)
        self.assertIn("target reached", p.out)
        (self.tmp / "q").mkdir()
        q = Project(str(self.tmp / "q"))
        self.assertEqual(q.kl("begin"), 0)
        (q.work / "evaluate.py").write_text("print(1.0)\n")
        q.edit(learning_rate=0.03)
        self.assertEqual(q.kl("try", self.write("c2.md", card_text())), 2, q.out)
        self.assertIn("fence was broken", q.out)

    def test_measurement_card_is_recorded_refuted(self):
        p = self.started()
        cardf = self.write("m.md", card_text(extra="MEASUREMENT: yes\n"))
        self.assertEqual(p.kl("try", cardf), kl.EXIT_DISCARDED, p.out)
        self.assertIn("PASS measurement card", p.out)
        self.assertEqual(self.hyps(p)[-1]["verdict"], "refuted")

    def test_long_lines_are_cut_and_archived(self):
        p = self.started()
        p.edit(learning_rate=0.003)
        with mock.patch.object(kl, "LINE_CAP", 40):
            p.kl("try", self.write("c.md", card_text()))
        self.assertIn("[full: ", p.out)
        self.assertIn("does not beat the bar", (p.state / "last-try.txt").read_text())

    def test_cycle_time_counts_from_kl_next(self):
        p = self.started()
        p.kl("next")
        mark = json.loads((p.state / "next.json").read_text())["t0"]
        (p.state / "next.json").write_text(json.dumps({"t0": mark - 120}))  # 2 minutes of editing
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("try", self.write("c.md", card_text())), 0, p.out)
        row = [json.loads(l) for l in (p.state / "timing.jsonl").read_text().splitlines()][-1]
        self.assertGreaterEqual(row["agent"], 115)
        self.assertFalse((p.state / "next.json").exists())

    def test_decisive_rule(self):
        self.assertTrue(kl._decisive(0.8, 0.8, 0.81))
        self.assertFalse(kl._decisive(0.8, 0.8, 0.805))   # under 1% of best
        self.assertFalse(kl._decisive(0.8, 0.82, 0.83))   # under the bar's own margin again
        self.assertTrue(kl._decisive(0.8, 0.82, 0.84))
        self.assertTrue(kl._decisive(0.0, 0.0, 0.001))


REPLY = """Here is my card.
HYPOTHESIS: A learning rate near 0.03 scores higher than 0.01.
ALTERNATIVES: any change helps
CHANGE: learning_rate 0.01 -> 0.03 in config.json
EXPECT: metric rises
REJECT IF: metric <= the keep bar
MISSING: none
```file:config.json
{
  "learning_rate": 0.03,
  "batch_size": 32,
  "dropout": 0.1,
  "optimizer": "adam"
}
```
"""


class TestHandoffApply(Base):
    def test_packet_holds_everything_and_the_round_trip_keeps(self):
        (self.tmp / "p").mkdir()
        p = Project(str(self.tmp / "p"))
        p.kl("status")  # creates the demo workspace; files committed before `kl begin` are its best
        (p.ws / "notes.md").write_bytes(b"x" * 5000 + b"\n")  # bytes: no CRLF on Windows
        (p.ws / ".npmrc").write_text("//registry/:_authToken=abc\n")
        run_mod.git(p.ws, "add", "-A")
        run_mod.git(p.ws, *run_mod.GIT_AUTHOR, "commit", "-qm", "more")
        self.assertEqual(p.kl("begin"), 0, p.out)
        self.assertEqual(p.kl("handoff", "--max-chars", "2000"), 0, p.out)
        for part in ("## Mission", "measured ONLY by the metric", "keep bar 0.828178",
                     "## Rejected hypotheses", "## Open lessons", "```file:config.json",
                     '"learning_rate": 0.01', "notes.md (5001 chars, over --max-chars)",
                     ".npmrc (looks like it holds a secret)", "REJECT IF: metric <= 0.828178",
                     "learning rate near 0.03"):
            self.assertIn(part, p.out)
        self.assertNotIn("_authToken", p.out)
        rc = p.kl("apply", self.write("reply.md", REPLY))
        self.assertEqual(rc, 0, p.out)
        self.assertIn("applied 1 file(s): config.json", p.out)
        self.assertIn("KEPT cycle 1", p.out)

    def test_handoff_files_glob_and_refusals(self):
        p = self.started()
        self.assertEqual(p.kl("handoff", "--files", "*.md"), 0)
        self.assertNotIn("```file:config.json", p.out)
        p.edit(learning_rate=0.03)
        self.assertEqual(p.kl("handoff"), 1)
        self.assertIn("uncommitted changes", p.out)

    def test_apply_refuses_bad_paths_and_writes_nothing(self):
        p = self.started(team_extra="protect: tests")
        p.kl("handoff")
        outside = self.tmp / "evil.txt"
        (p.ws / "real").mkdir()
        link = p.ws / "linkdir"
        try:
            os.symlink(self.tmp, link, target_is_directory=True)
            run_mod.git(p.ws, "add", "-A")
            run_mod.git(p.ws, *run_mod.GIT_AUTHOR, "commit", "-qm", "link")
        except OSError:
            link = None
        bad = ["../evil.txt", "/etc/passwd", "a\\b.txt", "C:/x.txt", ".git/config", "x/.git/hooks/p",
               "tests/test_x.py", "./config.json", "a//b", "~/x", ".gitattributes", "real",
               "x:stream", "trail. /x"]
        if link:
            bad.append("linkdir/evil.txt")
        for path in bad:
            reply = REPLY.replace("```file:config.json", f"```file:{path}")
            rc = p.kl("apply", self.write("r.md", reply))
            self.assertEqual(rc, 1, (path, p.out))
            self.assertIn("refused path", p.out, path)
        self.assertFalse(outside.exists())
        self.assertFalse((p.state / "cycle.json").exists())
        self.assertEqual(len(p.rows()), 1)  # only the baseline: no card was registered

    def test_apply_refuses_a_file_the_packet_did_not_show_whole(self):
        p = self.started()
        p.kl("handoff", "--files", "*.md")  # config.json not shown
        self.assertEqual(p.kl("apply", self.write("r.md", REPLY)), 1)
        self.assertIn("did not show this file whole", p.out)
        p.kl("handoff")
        new = REPLY + "```file:docs/new.md\nhello\n```\n"
        self.assertEqual(p.kl("apply", self.write("r.md", new)), 0, p.out)
        self.assertEqual((p.ws / "docs" / "new.md").read_text(), "hello\n")

    def test_card_is_registered_before_any_file_is_written(self):
        p = self.started()
        p.kl("handoff")
        reply = REPLY.replace("REJECT IF: metric <= the keep bar", "REJECT IF: it feels off")
        self.assertEqual(p.kl("apply", self.write("r.md", reply)), 1)
        self.assertIn("REJECT IF must be checkable", p.out)
        self.assertTrue(self.clean(p))

    def test_reply_parser(self):
        card_, files = kl.parse_reply("HYPOTHESIS: h\n````file:a.md\n```py\nx\n```\n````\ntail\n")
        self.assertEqual(files, [("a.md", "```py\nx\n```\n")])
        self.assertNotIn("tail", card_)
        with self.assertRaises(kl.Refuse):
            kl.parse_reply("HYPOTHESIS: h\n```file:a.md\nnever closed\n")
        _, files = kl.parse_reply("x\r\n```file:b.txt\r\none\r\n```\r\n")
        self.assertEqual(files, [("b.txt", "one\n")])

    def test_audit_and_critic_packets(self):
        p = self.started()
        self.assertEqual(p.kl("handoff", "--audit"), 1)
        p.kl("handoff")
        reply = REPLY.replace('"dropout": 0.1', '"dropout": 0.15').replace('"learning_rate": 0.03', '"learning_rate": 0.01')
        self.assertEqual(p.kl("apply", self.write("r.md", reply)), kl.EXIT_WAIT, p.out)
        tag = p.out.split("`DIFF: ")[1][:12]
        self.assertEqual(p.kl("handoff", "--audit"), 0, p.out)
        self.assertIn("NEW chat", p.out)
        self.assertIn("You are the Auditor", p.out)
        self.assertIn(f"DIFF: {tag}", p.out)
        self.assertEqual(p.kl("handoff", "--critic"), 0)
        self.assertIn("You are the Critic", p.out)
        self.assertIn("debate 1 --critic", p.out)


class TestRotateNudge(Base):
    """0.3.2: `kl next` prints one line suggesting a fresh session when the completed-cycle
    count (results.tsv rows with cycle >= 1) is a multiple of 5, and nothing at other
    counts. It says it counts cycles: kl cannot see sessions."""

    def test_the_nudge_at_multiples_of_5_only(self):
        import ledger
        p = self.started()
        seen = {}
        for done in range(0, 12):
            if done:  # one more completed cycle, in the ledger's own format
                ledger.append_row(p.state, {"cycle": done, "ts": "t", "role_vendors": "mock",
                                            "metric": "0.8", "best_metric": "0.828178",
                                            "status": "discard", "tokens": 0, "lesson_id": "",
                                            "description": f"cycle {done}"})
            self.assertEqual(p.kl("next"), 0, p.out)
            self.assertIn(f"| cycles {done} ", p.out)
            seen[done] = [ln for ln in p.out.splitlines() if ln.startswith("session:")]
        self.assertEqual([n for n, lines in seen.items() if lines], [5, 10])
        for n in (5, 10):
            self.assertEqual(len(seen[n]), 1)  # one line, no more
            line = seen[n][0]
            self.assertIn(f"{n} cycles are done", line)
            self.assertIn("cannot see sessions", line)  # never claims to detect a session
            self.assertIn("kl.py next", line)

    def test_no_nudge_mid_cycle_or_after_a_stop(self):
        import ledger
        p = self.started(team_extra="loop:\n  stall_cycles: 5")
        for done in range(1, 6):
            ledger.append_row(p.state, {"cycle": done, "ts": "t", "role_vendors": "mock",
                                        "metric": "0.8", "best_metric": "0.828178",
                                        "status": "discard", "tokens": 0, "lesson_id": "",
                                        "description": f"cycle {done}"})
        self.assertEqual(p.kl("next"), 0, p.out)
        self.assertIn("STOP:", p.out)  # the brake speaks; no new cycle, no rotation line
        self.assertNotIn("session:", p.out)


class TestDocs(unittest.TestCase):
    def test_fast_path_is_near_the_top_and_names_the_new_commands(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        fast = agents.index("## Fast path")
        self.assertLess(fast, agents.index("## Pointing keeploop"))
        for cmd in ("python kl.py next", "python kl.py try CARD", "python kl.py handoff",
                    "python kl.py apply FILE", "--audit-verdict"):
            self.assertIn(cmd, agents)
        skill = (ROOT / ".claude/skills/keeploop/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("python kl.py try FILE", skill)
        boot = (ROOT / "BOOTSTRAP.md").read_text(encoding="utf-8")
        self.assertIn("python kl.py apply FILE", boot.split("<!-- END AGENTS.md -->")[1])

    def test_every_driving_surface_says_to_rotate_sessions(self):
        """0.3.2: a long driving session drifts silently; every shipped surface that
        instructs the driving agent says to start fresh about every 5 cycles, and the
        user guide says why."""
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("**Start a fresh session every ~5 cycles.**", agents)
        self.assertLess(agents.index("Start a fresh session"), agents.index("## Fast path"))
        skill = (ROOT / ".claude/skills/keeploop/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("After about 5 cycles in this session", skill)
        boot = (ROOT / "BOOTSTRAP.md").read_text(encoding="utf-8").split("<!-- END AGENTS.md -->")[1]
        self.assertIn("**A new chat every ~5 cycles.**", boot)
        guide = (ROOT / "docs" / "GUIDE.md").read_text(encoding="utf-8")
        self.assertIn("### Long runs: a fresh session every ~5 cycles", guide)
        for text in (agents, skill, boot, guide):
            self.assertIn("kl next" if text is not boot else "kl.py handoff", text)

    def test_every_command_the_docs_name_exists(self):
        names = set(kl.parser()._subparsers._group_actions[0].choices)
        for cmd in ("next", "try", "handoff", "apply"):
            self.assertIn(cmd, names)
            self.assertIn(cmd, kl.COMMANDS)


if __name__ == "__main__":
    unittest.main()
