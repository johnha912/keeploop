"""User-facing text states what works now; it promises nothing for a future version.

0.3.0 shipped "API vendors land in v0.2" in vendors.py and team.yaml. CHANGELOG.md is
history and is not checked.

Run:  python -X utf8 -m unittest discover -s tests
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import vendors  # noqa: E402

PROMISE = re.compile(r"\b(lands?|ships?|arrives?|coming|planned|will (land|ship|arrive|be added))\b[^.\n]{0,40}"
                     r"\bv?\d+\.\d+\b|\(v\d+\.\d+\)|not implemented in \d+\.\d+", re.I)


class TestNoVersionPromises(unittest.TestCase):
    def test_the_api_vendor_refusal_says_what_works(self):
        with self.assertRaises(vendors.VendorUnavailable) as cm:
            vendors.get_vendor("api:anthropic")
        msg = str(cm.exception)
        self.assertNotRegex(msg, r"v?\d+\.\d+")
        for works in ("claude-cli", "vendors:", "mock"):
            self.assertIn(works, msg)

    def test_no_shipped_text_promises_a_version(self):
        files = [p for p in ROOT.rglob("*") if p.is_file() and p.suffix in {".py", ".md", ".yaml", ".yml", ".toml", ".txt"}
                 and not ({".git", ".claude", "node_modules", "proof", "run", "tests"} & set(p.relative_to(ROOT).parts))
                 and p.name != "CHANGELOG.md"]
        self.assertGreater(len(files), 30)
        bad = [f"{p.relative_to(ROOT)}:{i}: {line.strip()}" for p in files
               for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
               if PROMISE.search(line)]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
