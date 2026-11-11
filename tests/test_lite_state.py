"""keeploop-lite's state block (0.3.2): the run in about 300 words, in a fixed form, so a
new chat can go on where a long one stopped. The same five fields, the same cap, the same
~6-cycle suggestion and the same `save` in every language (en, vi, zh-CN), in the full
skill and the MINI one; and each language's EXAMPLE restarts after cycle 3 from the
block alone, with every carried value taken from that same file's cycles 0 to 3.

Run:  python -X utf8 -m unittest discover -s tests
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LITE = ROOT / "lite"
sys.path.insert(0, str(ROOT))

LANG = {
    "en": {"suffix": "", "head": "KEEPLOOP-LITE STATE", "after": "(after cycle {n})",
           "fields": ["Score (locked since cycle 0", "Best so far:", "Best version:", "Discarded:", "Lessons:"],
           "save": "**save**: print the state block", "save_mini": "**save**: the state block only",
           "six": "About every 6 cycles", "cap": "300 words", "best_line": "Best so far: cycle 3,",
           "ledger_head": "KEEPLOOP-LITE LEDGER", "ledger_best": "Best version (cycle 3):"},
    "vi": {"suffix": ".vi", "head": "TRẠNG THÁI KEEPLOOP-LITE", "after": "(sau chu kỳ {n})",
           "fields": ["Điểm (khóa từ chu kỳ 0", "Tốt nhất đến giờ:", "Phiên bản tốt nhất:", "Đã bỏ:", "Bài học:"],
           "save": "**lưu**: chỉ in khối trạng thái", "save_mini": "**lưu**: chỉ in khối trạng thái",
           "six": "hoảng mỗi 6 chu kỳ", "cap": "300 từ", "best_line": "Tốt nhất đến giờ: chu kỳ 3,",
           "ledger_head": "SỔ GHI KEEPLOOP-LITE", "ledger_best": "Phiên bản tốt nhất (chu kỳ 3):"},
    "zh-CN": {"suffix": ".zh-CN", "head": "KEEPLOOP-LITE 状态", "after": "（第 {n} 轮之后）",
              "fields": ["评分（自第 0 轮起锁定", "目前最佳：", "最佳版本：", "已舍弃：", "经验："],
              "save": "**保存**：只输出状态块", "save_mini": "**保存**：只输出状态块",
              "six": "大约每 6 轮", "cap": "300 词", "best_line": "目前最佳：第 3 轮，",
              "ledger_head": "KEEPLOOP-LITE 记录本", "ledger_best": "最佳版本（第 3 轮）："},
}


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


class TestStateBlockInEverySkill(unittest.TestCase):
    def test_same_five_fields_cap_suggestion_and_save(self):
        for lang, L in LANG.items():
            for name, save in ((f"KEEPLOOP-LITE{L['suffix']}.md", L["save"]),
                               (f"KEEPLOOP-LITE-MINI{L['suffix']}.md", L["save_mini"])):
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
        for lang, L in LANG.items():
            with self.subTest(lang=lang):
                text = (LITE / f"EXAMPLE{L['suffix']}.md").read_text(encoding="utf-8")
                b = blocks(text, L["head"], L["after"])
                before = text[:text.index(b[3])]  # everything up to the save after cycle 3
                ledger = before[before.rindex(L["ledger_head"]):]  # the full ledger after cycle 3
                lines = b[3].strip().splitlines()
                score, best, version = lines[1], lines[2], lines[3]
                # the locked score: every criterion and the gate, word for word from the ledger
                crits = re.findall(r"^\d\. (.+)$", ledger, re.M)
                self.assertEqual(len(crits), 3)
                for crit in crits:
                    self.assertIn(crit, score)
                self.assertTrue(best.startswith(L["best_line"]))
                self.assertIn(best, ledger)
                best_text = ledger.split(L["ledger_best"], 1)[1].strip().split("\n```")[0]
                self.assertTrue(version.endswith(fold(best_text)), (version, best_text))
                # discarded (cycle 2) and lesson L1: from cycles 0 to 3
                disc = [ln for ln in lines if ln.startswith("- ") and "L1" not in ln]
                self.assertEqual(len(disc), 1)
                self.assertTrue(re.search(r"20/30", disc[0]) and "20/30" in ledger)
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


if __name__ == "__main__":
    unittest.main()
