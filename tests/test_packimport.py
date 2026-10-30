"""`kl pack add | approve | list`: importing a pack from a link or a name, as a draft.

Offline: every fetch goes to a fake GitHub (FakeHub), never the network.
Run:  python -X utf8 -m unittest discover -s tests
"""

import io
import contextlib
import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import packimport  # noqa: E402
import packs  # noqa: E402
import scout  # noqa: E402
from test_kl import Project  # noqa: E402

SKILL = """---
name: crisp-writing
description: Short, concrete prose for product docs
---
# Crisp writing

Intro text that is not a principle.

## Principles

- Lead with the answer.
- One idea per sentence.

### Examples

- Bad: "In order to"; good: "To".

## Installation

pip install nothing
"""

COMPLETE_RUBRIC = """# Rubric - demo

| Criterion | Weight | Gate |
|---|---|---|
| Clarity | 60 | yes |
| Brevity | 40 | no |
"""


class FakeHub:
    """Answers the URLs packimport asks for: GitHub contents API, raw files, search."""

    def __init__(self, files: dict, owner="acme", repo="demo-skill", search=None):
        self.files, self.owner, self.repo = files, owner, repo
        self.search = search or []
        self.calls: list[str] = []

    def raw(self, path):
        return f"https://raw.githubusercontent.com/{self.owner}/{self.repo}/main/{path}"

    def __call__(self, url, as_json=True):
        self.calls.append(url)
        parts = urllib.parse.urlsplit(url)
        if parts.path.startswith("/search/repositories"):
            return {"items": self.search}
        prefix = f"/repos/{self.owner}/{self.repo}/contents/"
        if parts.hostname == "api.github.com" and parts.path.startswith(prefix):
            path = urllib.parse.unquote(parts.path[len(prefix):]).strip("/")
            if path in self.files:
                return {"name": path.rsplit("/", 1)[-1], "type": "file"}
            under = [f for f in self.files if not path or f.startswith(path + "/")]
            if not under:
                return None
            entries = {}
            for f in under:
                rest = f[len(path) + 1:] if path else f
                head = rest.split("/", 1)[0]
                full = f"{path}/{head}".strip("/")
                entries[head] = ({"name": head, "type": "dir", "path": full} if "/" in rest else
                                 {"name": head, "type": "file", "path": full,
                                  "download_url": self.raw(full)})
            return list(entries.values())
        if parts.hostname == "raw.githubusercontent.com":
            path = parts.path.split("/", 4)[-1]
            return self.files.get(path)
        return self.files.get(url)  # direct links: keyed by the full URL


def repo(name="demo-skill", stars=10, desc="a skill"):
    return {"name": name, "html_url": f"https://github.com/acme/{name}",
            "stargazers_count": stars, "description": desc}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "packs").mkdir()
        self.state = self.root / ".keeploop"

    def add(self, hub, source="https://github.com/acme/demo-skill", name=None, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            return packimport.add(self.root, self.state, source, name, fetch=hub, **kw)

    def refused(self, hub, *args, **kw) -> str:
        with self.assertRaises(packimport.ImportRefused) as ctx:
            self.add(hub, *args, **kw)
        return str(ctx.exception)


class TestImport(Base):
    def test_skill_md_becomes_a_draft_with_provenance(self):
        hub = FakeHub({"SKILL.md": SKILL, "README.md": "readme"})
        report = self.add(hub)
        d = self.root / "packs" / "demo-skill"
        taste = (d / "taste.md").read_text()
        self.assertIn("source: https://github.com/acme/demo-skill", taste)
        self.assertIn("sha256: ", taste)
        self.assertIn("fetched_at: ", taste)
        self.assertIn("Lead with the answer.", taste)
        self.assertIn("Bad: \"In order to\"", taste)  # a sub-heading stays in the section
        self.assertNotIn("pip install", taste)  # the next same-level heading ends it
        meta = packimport.load_team(d / "pack.yaml")
        self.assertEqual(meta["status"], "draft")
        self.assertEqual(meta["source"]["url"], "https://github.com/acme/demo-skill")
        self.assertEqual(len(str(meta["source"]["sha256"])), 64)
        self.assertEqual(meta["description"], "Short, concrete prose for product docs")
        self.assertTrue(packimport.is_skeleton((d / "rubric.md").read_text()))
        proposals = (self.state / "proposals.md").read_text()
        self.assertEqual(proposals.count("Pack import"), 1)
        self.assertIn("demo-skill (skill)", proposals)
        self.assertIn("(pack demo-skill) What AUTOMATIC metric",
                      (self.state / "questions.md").read_text())
        self.assertTrue(any("SKELETON" in line for line in report))

    def test_a_criteria_table_in_the_source_is_mapped(self):
        text = SKILL + "\n| Criterion | Weight (%) | Gate |\n|---|---|---|\n" \
                       "| Clarity | 70% | yes |\n| Brevity | 30% | no |\n"
        self.add(FakeHub({"SKILL.md": text}))
        rubric_text = (self.root / "packs/demo-skill/rubric.md").read_text()
        self.assertFalse(packimport.is_skeleton(rubric_text))
        self.assertIsNone(packimport.rubric_problem(rubric_text, final=True))

    def test_a_criteria_table_that_does_not_sum_to_100_is_refused(self):
        text = SKILL + "\n| Criterion | Weight |\n|---|---|\n| Clarity | 70 |\n"
        msg = self.refused(FakeHub({"SKILL.md": text}))
        self.assertIn("weights sum to 70", msg)
        self.assertFalse((self.root / "packs/demo-skill").exists())

    def test_readme_is_the_fallback_and_a_metric_mention_skips_the_question(self):
        self.add(FakeHub({"README.md": "# Tool\n\n## Rules\n\n- Track the benchmark score.\n"}))
        self.assertIn("Track the benchmark", (self.root / "packs/demo-skill/taste.md").read_text())
        self.assertFalse((self.state / "questions.md").exists())

    def test_direct_md_link_on_another_host(self):
        url = "https://docs.example.org/guides/voice.md"
        self.add(FakeHub({url: "# Voice\n\n- Plain words.\n"}), url)
        self.assertTrue((self.root / "packs/voice/taste.md").exists())

    def test_existing_pack_folder_is_copied_as_is_and_code_is_not_imported(self):
        taste = "# Taste - ux\n\n- Contrast first.\n"
        hub = FakeHub({"packs/ux/pack.yaml": "name: ux\nstatus: active\nprofession: UI\n"
                                             "taste_file: taste.md\nrubric_file: rubric.md\n",
                       "packs/ux/taste.md": taste,
                       "packs/ux/rubric.md": COMPLETE_RUBRIC,
                       "packs/ux/data/colors.csv": "name,hex\nink,#111\n",
                       "packs/ux/search.py": "import os\nos.system('rm -rf /')\n",
                       "README.md": "readme"})
        report = self.add(hub)
        d = self.root / "packs" / "ux"
        self.assertEqual((d / "taste.md").read_text(), taste)
        self.assertEqual((d / "rubric.md").read_text(), COMPLETE_RUBRIC)
        self.assertEqual((d / "data/colors.csv").read_text(), "name,hex\nink,#111\n")
        self.assertFalse((d / "search.py").exists())
        self.assertFalse(list(d.rglob("*.py")))
        self.assertIn("search.py: not imported — code", "\n".join(report))
        meta = packimport.load_team(d / "pack.yaml")
        self.assertEqual(meta["status"], "draft")  # the source's `status: active` is not trusted
        self.assertIn("rubric: parsed", "\n".join(report))

    def test_a_py_file_next_to_skill_md_is_reported_and_not_written(self):
        report = self.add(FakeHub({"SKILL.md": SKILL, "install.py": "print('x')"}))
        self.assertIn("install.py: not imported — code", "\n".join(report))
        self.assertFalse(list((self.root / "packs").rglob("*.py")))


class TestGates(Base):
    def test_credential_in_the_source_refuses_and_writes_nothing(self):
        key = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2"
        msg = self.refused(FakeHub({"SKILL.md": SKILL + f"\nexport KEY={key}\n"}))
        self.assertIn("OpenAI/Anthropic key", msg)
        self.assertNotIn(key, msg)
        self.assertEqual(list((self.root / "packs").iterdir()), [])
        self.assertFalse(self.state.exists())  # not even proposals.md

    def test_slop_rule_of_the_active_pack_refuses(self):
        slop = packs.slop_rules(packs.load_pack(ROOT, "software"))
        msg = self.refused(FakeHub({"SKILL.md": SKILL + "\nTODO: write more\n"}), slop=slop)
        self.assertIn("slop gate: marker", msg)

    def test_oversized_taste_is_refused(self):
        msg = self.refused(FakeHub({"SKILL.md": SKILL}), cap=100)
        self.assertIn("size gate: taste.md", msg)

    def test_name_collision_with_an_active_pack_is_refused(self):
        (self.root / "packs/demo-skill").mkdir()
        (self.root / "packs/demo-skill/pack.yaml").write_text("name: demo-skill\n")
        self.assertIn("already exists and is active", self.refused(FakeHub({"SKILL.md": SKILL})))

    def test_a_draft_from_another_source_is_not_overwritten(self):
        self.add(FakeHub({"SKILL.md": SKILL}))
        other = FakeHub({"SKILL.md": SKILL}, owner="other")
        msg = self.refused(other, "https://github.com/other/demo-skill")
        self.assertIn("draft from another source", msg)
        self.add(FakeHub({"SKILL.md": SKILL.replace("sentence.", "sentence.\n- New rule.")}))  # re-import
        self.assertIn("New rule", (self.root / "packs/demo-skill/taste.md").read_text())

    def test_bad_names_and_schemes_are_refused(self):
        hub = FakeHub({"SKILL.md": SKILL})
        self.assertIn("lowercase", self.refused(hub, name="../evil"))
        self.assertIn("https", self.refused(hub, "http://github.com/acme/demo-skill"))


class TestNameResolution(Base):
    def test_one_strong_match_is_used(self):
        hub = FakeHub({"SKILL.md": SKILL}, search=[repo("demo-skill"), repo("other-thing")])
        self.add(hub, "demo")
        self.assertTrue((self.root / "packs/demo-skill/pack.yaml").exists())

    def test_several_matches_are_listed_and_refused(self):
        hub = FakeHub({"SKILL.md": SKILL}, search=[repo("taste-skill", 50), repo("taste", 9)])
        msg = self.refused(hub, "taste")
        self.assertIn("https://github.com/acme/taste-skill", msg)
        self.assertIn("https://github.com/acme/taste ", msg)
        self.assertEqual(list((self.root / "packs").iterdir()), [])

    def test_no_match_is_refused(self):
        self.assertIn("no repository matches", self.refused(FakeHub({}, search=[]), "taste"))


class TestLifecycle(Base):
    def test_draft_refuses_to_load_until_approved(self):
        self.add(FakeHub({"SKILL.md": SKILL}))
        with self.assertRaises(packs.DraftPack) as ctx:
            packs.load_pack(self.root, "demo-skill")
        self.assertIn("kl pack approve demo-skill", str(ctx.exception))
        with self.assertRaises(packimport.ImportRefused) as ctx:  # skeleton rubric
            packimport.approve(self.root, self.state, "demo-skill")
        self.assertIn("TODO", str(ctx.exception))
        (self.root / "packs/demo-skill/rubric.md").write_text(COMPLETE_RUBRIC)
        packimport.approve(self.root, self.state, "demo-skill")
        pack = packs.load_pack(self.root, "demo-skill")
        self.assertEqual(pack["meta"]["status"], "active")
        self.assertIn("Lead with the answer", pack["taste"])
        self.assertIn("Pack approved", (self.state / "proposals.md").read_text())

    def test_approve_refuses_a_rubric_without_a_gate_or_weights(self):
        self.add(FakeHub({"SKILL.md": SKILL}))
        r = self.root / "packs/demo-skill/rubric.md"
        for text, why in ((COMPLETE_RUBRIC.replace("| yes |", "| no |"), "no gate criterion"),
                          ("| Criterion | Weight | Gate |\n|---|---|---|\n| A | 50 | yes |\n",
                           "sum to 50"),
                          ("# Rubric\n\nno table\n", "no criteria table")):
            r.write_text(text)
            with self.assertRaises(packimport.ImportRefused) as ctx:
                packimport.approve(self.root, self.state, "demo-skill")
            self.assertIn(why, str(ctx.exception))
        self.assertEqual(packimport.load_team(self.root / "packs/demo-skill/pack.yaml")["status"],
                         "draft")


class TestThroughKl(unittest.TestCase):
    def test_draft_blocks_keep_until_the_human_approves(self):
        """Acceptance: add -> keep refused as draft -> rubric + approve -> a normal keep."""
        hub = FakeHub({"SKILL.md": SKILL})
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(scout, "_fetch", hub):
            p = Project(tmp)
            self.assertEqual(p.kl("begin"), 0, p.out)
            self.assertEqual(p.kl("pack", "add", "https://github.com/acme/demo-skill"), 0, p.out)
            self.assertIn("DRAFT pack 'demo-skill'", p.out)
            self.assertIn("begin --accept-changes", p.out)  # packs/ is fenced
            self.assertEqual(p.kl("pack", "list"), 0)
            self.assertRegex(p.out, r"demo-skill\s+draft\s+https://github.com/acme/demo-skill")
            team = p.work / "team.yaml"
            team.write_text(team.read_text().replace("pack: software", "pack: demo-skill"))
            self.assertEqual(p.kl("keep"), 1)
            self.assertIn("is a draft", p.out)
            self.assertEqual(p.card(), 1)  # no command runs on a draft pack
            self.assertEqual(p.kl("pack", "approve", "demo-skill"), 1)  # skeleton rubric
            self.assertIn("TODO", p.out)
            (p.work / "packs/demo-skill/rubric.md").write_text(COMPLETE_RUBRIC)
            self.assertEqual(p.kl("pack", "approve", "demo-skill"), 0, p.out)
            self.assertEqual(p.kl("check"), 2)  # the fence saw packs/ and team.yaml change
            self.assertEqual(p.kl("begin", "--accept-changes"), 0, p.out)  # the human's step
            self.assertEqual(p.card(), 0, p.out)
            p.edit(learning_rate=0.03)
            self.assertEqual(p.kl("keep"), 0, p.out)
            self.assertIn("KEPT cycle 1", p.out)
            self.assertEqual(p.commits(), 2)

    def test_pack_add_without_a_source_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Project(tmp)
            self.assertEqual(p.kl("pack", "add"), 1)
            self.assertIn("needs a source", p.out)


if __name__ == "__main__":
    unittest.main()
