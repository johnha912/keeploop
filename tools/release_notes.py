"""Print one CHANGELOG.md section: the GitHub release notes for a tag.

    python tools/release_notes.py 0.2.0 > notes.md

Exits 1 if the section is missing or empty, so a tag never ships without notes.
"""

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def section(text: str, version: str) -> str:
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    notes = section(CHANGELOG.read_text(encoding="utf-8"), argv[0].removeprefix("v"))
    if not notes:
        print(f"release_notes: no [{argv[0]}] section with content in {CHANGELOG}", file=sys.stderr)
        return 1
    print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
