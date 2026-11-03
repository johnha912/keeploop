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
"""

import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from prepare import GIT_AUTHOR, git  # noqa: E402
from run import project_config  # noqa: E402

SKIP = {".git", ".keeploop", "__pycache__", ".venv", "venv", "dist",
        ".playwright-mcp", "examples", "tests", "tools"}


def manifest(example: Path) -> dict[str, list[str]]:
    text = (example / "team.yaml").read_text(encoding="utf-8")
    found = {k: [p.strip() for p in v.split(",") if p.strip()]
             for k, v in re.findall(r"^# sandbox (root|workspace):(.*)$", text, re.M)}
    if set(found) != {"root", "workspace"}:
        raise SystemExit(f"{example / 'team.yaml'}: needs '# sandbox root:' and "
                         f"'# sandbox workspace:' lines in its header")
    if bad := [p for p in found["workspace"] if Path(p).name.lower().startswith("holdout")]:
        raise SystemExit(f"refused: holdout files must never go in the workspace: {bad}")
    if missing := [p for p in found["root"] + found["workspace"] if not (example / p).is_file()]:
        raise SystemExit(f"missing in {example}: {missing}")
    return found


def requirements(example: Path) -> list[tuple[str, str]]:
    """'# sandbox requires: cmd (why)' lines -> [(cmd, why)]."""
    text = (example / "team.yaml").read_text(encoding="utf-8")
    return [(cmd, why.strip()) for cmd, why in
            re.findall(r"^# sandbox requires:\s*(\S+)\s*(?:\((.*)\))?\s*$", text, re.M)]


def missing_requirements(example: Path, which=shutil.which) -> list[str]:
    """One warning line per required command that is not on PATH."""
    return [f"warning: this example needs `{cmd}` on PATH and it was not found"
            + (f": {why}" if why else "") + f". `kl begin` will fail until `{cmd}` works."
            for cmd, why in requirements(example) if not which(cmd)]


def copy(example: Path, rel: str, dest: Path) -> None:
    (dest / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(example / rel, dest / rel)


def make(example: Path, dest: Path) -> tuple[Path, Path]:
    example, dest = example.resolve(), dest.resolve()
    files = manifest(example)
    if dest == REPO or REPO in dest.parents:
        raise SystemExit(f"refused: {dest} is inside the keeploop repo")
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"refused: {dest} is not empty")
    root = dest / "kl"
    shutil.copytree(REPO, root, ignore=lambda d, names: set(names) & (
        SKIP if Path(d) == REPO else {"__pycache__"}))
    (root / "holdout.py").unlink(missing_ok=True)  # demo holdout scores the demo config
    for rel in files["root"]:
        copy(example, rel, root)
    ws = project_config(root)["workspace"]
    if dest not in ws.parents:
        raise SystemExit(f"refused: team.yaml workspace {ws} is outside {dest}")
    for rel in files["workspace"]:
        copy(example, rel, ws)
    git(ws, "init", "-q")
    git(ws, "add", "-A")
    git(ws, *GIT_AUTHOR, "commit", "-qm", "keeploop: initial workspace")
    return root, ws


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
