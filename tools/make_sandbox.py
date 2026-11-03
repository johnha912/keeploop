"""Build a ready-to-run sandbox for a worked example, in one command.

    python tools/make_sandbox.py examples/prompt-optimization DEST

DEST/kl is a control copy of keeploop (code, packs, docs, .claude) with the
example's files on top; the demo holdout.py is always removed first, so it
can never score the wrong thing (lesson L-001). The workspace is a fresh git
repo at the path the example's team.yaml names (e.g. DEST/ws), one commit.

What goes where is declared in the example's team.yaml header:

    # sandbox root: evaluate.py, holdout.py, team.yaml, data/holdout.jsonl
    # sandbox workspace: prompt.md, data/dev.jsonl

An optional third line names a command the example needs on PATH; the next
command is printed with a warning when it is missing:

    # sandbox requires: claude (the scorer calls Claude CLI; install it and log in first)

Paths are relative to the example folder and keep their relative path in the
destination. A file named holdout* is refused for the workspace. DEST must be
new (or empty) and outside the keeploop repo; keep it short on Windows.

The same sandbox, without the code copy, is `kl init --example NAME DEST` for
a pip-installed kl (scaffold.py holds the logic for both).
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import scaffold  # noqa: E402
from scaffold import manifest, missing_requirements, requirements  # noqa: E402,F401


def make(example: Path, dest: Path) -> tuple[Path, Path]:
    return scaffold.make_sandbox(example, dest, with_code=True, src=REPO)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    root, ws = make(Path(argv[0]), Path(argv[1]))
    print(f"sandbox ready: workspace {ws}")
    for line in missing_requirements(Path(argv[0])):
        print(line)
    print(f"next: cd {root} && python kl.py begin   (headless: python run.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
