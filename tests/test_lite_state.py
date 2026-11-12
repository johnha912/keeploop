"""keeploop-lite's state block (0.3.2): the run in about 300 words, in a fixed form, so a
new chat can go on where a long one stopped. The same five fields, the same cap, the same
~6-cycle suggestion and the same `save` in every language, in the full skill and the MINI
one; and each language's EXAMPLE restarts after cycle 3 from the block alone, with every
carried value taken from that same file's cycles 0 to 3.

0.3.3: the languages are DISCOVERED from lite/KEEPLOOP-LITE*.md, not listed here. A
language with a lite file needs all three files (skill, MINI, EXAMPLE), a row of labels
in LANG below, a README that keeps the lite section's structure, and entries in
llms.txt; a LANG row with no files fails too. So a new language cannot ship half-done,
and a dropped one cannot linger in the table.

Run:  python -X utf8 -m unittest discover -s tests
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LITE = ROOT / "lite"
sys.path.insert(0, str(ROOT))

# The words each language uses for the state block and its rules. Only labels live here:
# which languages exist is read from the lite/ folder (discover()).
LANG = {
    "en": {"head": "KEEPLOOP-LITE STATE", "after": "(after cycle {n})",
           "fields": ["Score (locked since cycle 0", "Best so far:", "Best version:", "Discarded:", "Lessons:"],
           "save": "**save**: print the state block", "save_mini": "**save**: the state block only",
           "six": "About every 6 cycles", "cap": "300 words", "best_line": "Best so far: cycle 3,",
           "ledger_head": "KEEPLOOP-LITE LEDGER", "ledger_best": "Best version (cycle 3):",
           "pass": "PASS", "fail": "FAIL"},
    "vi": {"head": "TRẠNG THÁI KEEPLOOP-LITE", "after": "(sau chu kỳ {n})",
           "fields": ["Điểm (khóa từ chu kỳ 0", "Tốt nhất đến giờ:", "Phiên bản tốt nhất:", "Đã bỏ:", "Bài học:"],
           "save": "**lưu**: chỉ in khối trạng thái", "save_mini": "**lưu**: chỉ in khối trạng thái",
           "six": "hoảng mỗi 6 chu kỳ", "cap": "300 từ", "best_line": "Tốt nhất đến giờ: chu kỳ 3,",
           "ledger_head": "SỔ GHI KEEPLOOP-LITE", "ledger_best": "Phiên bản tốt nhất (chu kỳ 3):",
           "pass": "ĐẠT", "fail": "TRƯỢT"},
    "zh-CN": {"head": "KEEPLOOP-LITE 状态", "after": "（第 {n} 轮之后）",
              "fields": ["评分（自第 0 轮起锁定", "目前最佳：", "最佳版本：", "已舍弃：", "经验："],
              "save": "**保存**：只输出状态块", "save_mini": "**保存**：只输出状态块",
              "six": "大约每 6 轮", "cap": "300 词", "best_line": "目前最佳：第 3 轮，",
              "ledger_head": "KEEPLOOP-LITE 记录本", "ledger_best": "最佳版本（第 3 轮）：",
              "pass": "通过", "fail": "不通过"},
    "es": {"head": "ESTADO KEEPLOOP-LITE", "after": "(después del ciclo {n})",
           "fields": ["Puntuación (fija desde el ciclo 0", "Lo mejor hasta ahora:", "Mejor versión:", "Descartados:", "Lecciones:"],
           "save": "**guardar**: imprime el bloque de estado", "save_mini": "**guardar**: solo el bloque de estado",
           "six": "cada 6 ciclos", "cap": "300 palabras", "best_line": "Lo mejor hasta ahora: ciclo 3,",
           "ledger_head": "REGISTRO KEEPLOOP-LITE", "ledger_best": "Mejor versión (ciclo 3):",
           "pass": "PASA", "fail": "NO PASA"},
}


def discover() -> dict[str, str]:
    """{language: file suffix} for every lite/KEEPLOOP-LITE<suffix>.md that is not a MINI.
    English has no suffix."""
    out = {}
    for p in LITE.glob("KEEPLOOP-LITE*.md"):
        m = re.fullmatch(r"KEEPLOOP-LITE(\.[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,4})?)?\.md", p.name)
        if m:
            out[m.group(1)[1:] if m.group(1) else "en"] = m.group(1) or ""
    return out


LANGS = discover()


def fold(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def template(text: str, head: str) -> list[str]:
    """The lines of the state-block template (the code block that starts with head)."""
    m = re.search(r"```\n(" + re.escape(head) + r"[^\n]*\n.*?)```", text, re.S)
    assert m, head
    return m.group(1).splitlines()


def blocks(text: str, head: str, after: str) -> dict[int, str]:
    """{cycle: the state block printed after that cycle} in an EXAMPLE."""
    out = {}
    for n in (3, 4):
        m = re.search(r"```\n(" + re.escape(head + " " + after.format(n=n)) + r".*?)```", text, re.S)
        if m is None and after.startswith("（"):  # Chinese: no space before the full-width paren
            m = re.search(r"```\n(" + re.escape(head + after.format(n=n)) + r".*?)```", text, re.S)
        assert m, (head, n)
        out[n] = m.group(1)
    return out


def row(text: str, n: int) -> tuple[str, int, int]:
    """(change, total, max) of the ledger row for cycle n."""
    m = re.search(rf"^\| {n} \| (.+?) \| (\d+)/(\d+)", text, re.M)
    assert m, n
    return m.group(1), int(m.group(2)), int(m.group(3))


def checker_table(text: str, L: dict) -> tuple[list[tuple[str, int]], list[str], tuple[int, int]]:
    """The one scoring table in text: ([(criterion, score)], [gate verdicts], (total, max))."""
    scores = [(m.group(1), int(m.group(2))) for m in re.finditer(r"^\| ([^|]+?) \| (\d+)/10 \|", text, re.M)]
    gates = re.findall(r"^\| [^|]+? \| \**(" + re.escape(L["fail"]) + "|" + re.escape(L["pass"]) + r")\** \|",
                       text, re.M)
    totals = re.findall(r"^\| [^|]+? \| (\d+)/(\d+) \| \|$", text, re.M)
    assert len(totals) == 1, totals
    return scores, gates, (int(totals[0][0]), int(totals[0][1]))


class TestLanguagesAreDiscovered(unittest.TestCase):
    def test_every_lite_language_is_complete_and_labelled(self):
        self.assertGreaterEqual(len(LANGS), 3)
        self.assertEqual(sorted(set(LANGS) - set(LANG)), [], "lite files with no LANG labels in this test")
        self.assertEqual(sorted(set(LANG) - set(LANGS)), [], "LANG labels with no lite files")
        for lang, sfx in LANGS.items():
            for name in (f"KEEPLOOP-LITE{sfx}.md", f"KEEPLOOP-LITE-MINI{sfx}.md", f"EXAMPLE{sfx}.md"):
                with self.subTest(lang=lang, file=name):
                    self.assertTrue((LITE / name).is_file(), f"{lang}: lite/{name} is missing")

    def test_no_stray_lite_file(self):
        """Every MINI and EXAMPLE belongs to a discovered language."""
        for p in LITE.glob("*.md"):
            m = re.fullmatch(r"(?:KEEPLOOP-LITE-MINI|EXAMPLE)(\.[^.]+)?\.md", p.name)
            if m:
                with self.subTest(file=p.name):
                    self.assertIn(m.group(1) or "", LANGS.values(), f"lite/{p.name} has no KEEPLOOP-LITE file")


class TestStateBlockInEverySkill(unittest.TestCase):
    def test_same_five_fields_cap_suggestion_and_save(self):
        for lang, sfx in LANGS.items():
            L = LANG[lang]
            for name, save in ((f"KEEPLOOP-LITE{sfx}.md", L["save"]),
                               (f"KEEPLOOP-LITE-MINI{sfx}.md", L["save_mini"])):
                with self.subTest(lang=lang, file=name):
                    text = (LITE / name).read_text(encoding="utf-8")
                    lines = template(text, L["head"])
                    starts = [next((i for i, ln in enumerate(lines) if ln.startswith(f)), None)
                              for f in L["fields"]]
                    self.assertNotIn(None, starts, lines)
                    self.assertEqual(starts, sorted(starts))  # the five fields, in order
                    self.assertEqual(len(lines), 1 + 5 + 2)   # header, 5 fields, one example line each list
                    self.assertIn(L["cap"], text)
                    self.assertIn(L["six"], text)
                    self.assertIn(save, text)


class TestExampleRestart(unittest.TestCase):
    def test_the_restart_carries_only_values_from_cycles_0_to_3(self):
        for lang, sfx in LANGS.items():
            L = LANG[lang]
            with self.subTest(lang=lang):
                text = (LITE / f"EXAMPLE{sfx}.md").read_text(encoding="utf-8")
                b = blocks(text, L["head"], L["after"])
                before = text[:text.index(b[3])]  # everything up to the save after cycle 3
                ledger = before[before.rindex(L["ledger_head"]):]  # the full ledger after cycle 3
                lines = b[3].strip().splitlines()
                score, best, version = lines[1], lines[2], lines[3]
                # the locked score: every criterion and the gate, word for word from the ledger
                crits = re.findall(r"^\d\. (.+)$", ledger, re.M)
                self.assertTrue(3 <= len(crits) <= 5, crits)
                for crit in crits:
                    self.assertIn(crit, score)
                self.assertTrue(best.startswith(L["best_line"]))
                self.assertIn(best, ledger)
                best_text = ledger.split(L["ledger_best"], 1)[1].strip().split("\n```")[0]
                self.assertTrue(version.endswith(fold(best_text)), (version, best_text))
                # discarded (cycle 2): its change and its score, as in the ledger row for cycle 2
                disc = [ln for ln in lines if ln.startswith("- ") and "L1" not in ln]
                self.assertEqual(len(disc), 1)
                change, total, mx = row(ledger, 2)
                self.assertIn(change, disc[0])
                self.assertIn(f"{total}/{mx}", disc[0])
                l1 = next(ln for ln in lines if "L1" in ln)
                body = l1.split("：", 1)[-1] if lang == "zh-CN" else l1.split("): ", 1)[1]
                self.assertIn(fold(body), fold(ledger))
                for n in re.findall(r"\d+", b[3]):
                    self.assertIn(n, before, f"{lang}: {n} in the cycle-3 block is not in cycles 0-3")
                words = len(b[3].split()) if lang != "zh-CN" else len(re.sub(r"\s", "", b[3]))
                self.assertLessEqual(words, 300 if lang != "zh-CN" else 500)
                # after cycle 4 (in the new chat): the same block plus cycle 4 and L2 only
                kept = [ln for ln in b[3].strip().splitlines()[1:]]
                after4 = b[4].strip().splitlines()[1:]
                self.assertEqual([ln for ln in after4 if ln in kept], kept)
                self.assertEqual(len(after4) - len(kept), 2)

    def test_cycle_4_obeys_the_block_it_started_from(self):
        """The new chat sees only the state block, scores on the locked scorecard, cannot
        beat the best without passing the gate, and does not retry the discarded idea."""
        for lang, sfx in LANGS.items():
            L = LANG[lang]
            with self.subTest(lang=lang):
                text = (LITE / f"EXAMPLE{sfx}.md").read_text(encoding="utf-8")
                b = blocks(text, L["head"], L["after"])
                ledger3 = text[:text.index(b[3])]
                ledger3 = ledger3[ledger3.rindex(L["ledger_head"]):]
                restart = text[text.index(b[3]) + len(b[3]):text.index(b[4])]
                self.assertNotIn(L["ledger_head"], restart, "the new chat must start from the block alone")
                locked = [re.split(r"[:：]", c, maxsplit=1)[0] for c in re.findall(r"^\d\. (.+)$", ledger3, re.M)]
                scores, gates, (total, mx) = checker_table(restart, L)
                self.assertEqual([c for c, _ in scores], locked)  # the locked criteria, in order
                self.assertEqual(sum(s for _, s in scores), total)
                best_total, best_max = map(int, re.search(r"(\d+)/(\d+)", b[3].splitlines()[2]).groups())
                self.assertEqual(mx, best_max)
                self.assertTrue(gates, "the gate is scored in cycle 4")
                change4, row_total, _ = row(restart, 4)
                self.assertEqual(row_total, total)
                # the block after cycle 4 keeps the best, so cycle 4 must not beat it with a passing gate
                self.assertTrue(total <= best_total or L["fail"] in gates, (total, best_total, gates))
                self.assertNotEqual(change4, row(ledger3, 2)[0], "cycle 4 retried the discarded idea")
                new = [ln for ln in b[4].strip().splitlines() if ln not in b[3].strip().splitlines()]
                self.assertTrue(any(change4 in ln and f"{total}/{mx}" in ln for ln in new), new)
                for n in re.findall(r"\d+", b[4]):
                    self.assertIn(n, ledger3 + b[3] + restart, f"{lang}: {n} in the cycle-4 block comes from nowhere")


def readmes() -> dict[str, Path]:
    """{language: README} for every README*.md at the root; README.md is English."""
    out = {}
    for p in ROOT.glob("README*.md"):
        m = re.fullmatch(r"README(\.[^.]+)?\.md", p.name)
        if m:
            out[m.group(1)[1:] if m.group(1) else "en"] = p
    return out


def number(s: str) -> int:
    return int(re.sub(r"[.,\s ]", "", s))


class TestEveryReadmeNamesEveryLanguage(unittest.TestCase):
    """The discovery surface: each README's language bar and lite section, and llms.txt."""

    def test_one_readme_per_lite_language(self):
        self.assertEqual(sorted(readmes()), sorted(LANGS))

    def test_the_lite_section_keeps_its_structure(self):
        for lang, path in readmes().items():
            sfx = LANGS.get(lang, "")
            text = path.read_text(encoding="utf-8")
            with self.subTest(readme=path.name):
                bar = re.search(r'<p align="center">\s*<!--.*?-->\s*(.*?)</p>', text, re.S).group(1)
                for other, p in readmes().items():
                    if other == lang:
                        self.assertNotIn(f'href="{p.name}"', bar)
                        self.assertRegex(bar, r"<b>[^<]+</b>")
                    else:
                        self.assertIn(f'<a href="{p.name}">', bar, f"{path.name}: the language bar misses {p.name}")
                # the note for AI assistants: its own raw lite URL, every other lite file, its own MINI
                ai = re.search(r"<details>\s*<summary>.*?</details>", text, re.S).group(0)
                self.assertIn(f"https://raw.githubusercontent.com/johnha912/keeploop/main/lite/KEEPLOOP-LITE{sfx}.md", ai)
                for other in LANGS.values():
                    self.assertIn(f"KEEPLOOP-LITE{other}.md", ai)
                mini = LITE / f"KEEPLOOP-LITE-MINI{sfx}.md"
                at = ai.index(f"lite/KEEPLOOP-LITE-MINI{sfx}.md")
                words = len(mini.read_text(encoding="utf-8").split())
                if words >= 1000:  # a space-separated language: the stated size is measured
                    claim = re.search(r"\d{1,3}(?:[.,  ]\d{3})+|\d{3,}", ai[at:at + 200])
                    self.assertIsNotNone(claim, f"{path.name}: no word count for the MINI")
                    self.assertLessEqual(abs(number(claim.group(0)) - words), words * 0.05,
                                         f"{path.name}: says {claim.group(0)} words, the MINI has {words}")
                # the lite box: every lite language, its own example and MINI, then the chat guide
                box = text[text.index("](lite/KEEPLOOP-LITE"):]
                box = box[:box.index("keeploop-guide-chat.gif")]
                for other in LANGS.values():
                    self.assertIn(f"(lite/KEEPLOOP-LITE{other}.md)", box, f"{path.name}: lite box misses {other or 'en'}")
                self.assertIn(f"(lite/EXAMPLE{sfx}.md)", box)
                self.assertIn(f"(lite/KEEPLOOP-LITE-MINI{sfx}.md)", box)
                # and the order of the top: language bar, AI note, lite box and guide, quick start
                marks = [text.index(bar), text.index(ai), text.index("keeploop-guide-chat.gif"),
                         text.index("\n## ")]
                self.assertEqual(marks, sorted(marks))

    def test_llms_txt_lists_every_language(self):
        text = (ROOT / "llms.txt").read_text(encoding="utf-8")
        raw = "https://raw.githubusercontent.com/johnha912/keeploop/main/"
        for lang, sfx in LANGS.items():
            with self.subTest(lang=lang):
                for f in (f"lite/KEEPLOOP-LITE{sfx}.md", f"lite/KEEPLOOP-LITE-MINI{sfx}.md", f"lite/EXAMPLE{sfx}.md"):
                    self.assertIn(f"({raw}{f})", text)
                if sfx:
                    self.assertIn(f"({raw}README{sfx}.md)", text)


if __name__ == "__main__":
    unittest.main()
