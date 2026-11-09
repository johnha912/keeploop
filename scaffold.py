"""scaffold.py - the files a keeploop project needs, and where they come from.

`kl init [DIR]` writes keeploop's editable files (AGENTS.md, program.md,
team.yaml, a demo evaluate.py, packs/, the Claude accelerators) into DIR. They
are meant to be edited there by the human, so they are copies, never read from
the install folder. Existing files are never overwritten.

`kl init --example NAME DEST` (and `tools/make_sandbox.py`) builds a worked
example's sandbox: DEST/kl is a control folder with the example's files on top,
DEST/<workspace> a fresh git repo. What goes where is declared in the example's
team.yaml header:

    # sandbox root: evaluate.py, holdout.py, team.yaml, data/holdout.jsonl
    # sandbox workspace: prompt.md, data/dev.jsonl
    # sandbox requires: claude (why; optional, warns when not on PATH)

Source of the files: a clone reads them from the repo; a pip install reads the
copy setup.py packed into `_assets/` next to the modules (all inside the wheel's
`keeploop/` folder). A pip-installed `kl` has no kl.py to run, so its copies say
`kl ...` instead of `python kl.py ...`. Stdlib only.
"""

import re
import shutil
from pathlib import Path

from prepare import GIT_AUTHOR, git

HERE = Path(__file__).resolve().parent
BUNDLE = HERE / "_assets"  # present only in a pip install (setup.py)

# The engine: the modules the wheel installs, inside its `keeploop/` folder (never
# top-level, where names like `run` or `prepare` would clash with other packages).
ENGINE = ["bm25", "codemap", "kl", "ledger", "lessons", "packs", "prepare", "quickstart", "report", "rubric",
          "run", "scaffold", "scout", "vendors"]
REPO_URL = "https://github.com/johnha912/keeploop"

# What `kl init` writes, relative to the source; globs allowed.
FRAMEWORK = ["AGENTS.md", "CLAUDE.md", "GEMINI.md", "BOOTSTRAP.md", "program.md",
             "team.yaml", "evaluate.py", ".claude/settings.json", ".claude/agents/*.md",
             ".claude/skills/*/SKILL.md", "packs/**/*"]
# The ones a project cannot run without (kl init refuses a source that lacks one).
REQUIRED = ["AGENTS.md", "program.md", "team.yaml", "evaluate.py", "packs/software/pack.yaml"]
GITIGNORE = ".keeploop/\n__pycache__/\n"

# Command spellings in the copied text, for a pip-installed `kl`. Order matters.
REWRITES = [("python tools/make_sandbox.py examples/<name>", "kl init --example <name>"),
            (" (docs/GUIDE.md).", " (docs/GUIDE.md in the keeploop source)."),
            ("python kl.py", "kl"), ("python run.py", "kl run"),
            ("python lessons.py", "kl lesson")]
TEXT = {".md", ".json"}

# Copied from a clone into a sandbox's control folder that runs `python kl.py`.
SKIP = {".git", ".keeploop", "__pycache__", ".venv", "venv", "dist", "build",
        ".playwright-mcp", "examples", "tests", "tools"}


def source() -> Path:
    return BUNDLE if BUNDLE.is_dir() else HERE


def _expand(src: Path, patterns: list[str]) -> list[str]:
    out = []
    for pat in patterns:
        for p in sorted(src.glob(pat)):
            rel = p.relative_to(src)
            if p.is_file() and "__pycache__" not in rel.parts and p.suffix != ".pyc":
                out.append(rel.as_posix())
    return list(dict.fromkeys(out))


def framework_files(src: Path) -> list[str]:
    return _expand(src, FRAMEWORK)


def example_names(src: Path) -> list[str]:
    base = src / "examples"
    return sorted(d.name for d in base.iterdir() if (d / "team.yaml").is_file()) \
        if base.is_dir() else []


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


def bundle_files(src: Path) -> list[str]:
    """Every file setup.py packs into keeploop_assets/: the framework files and,
    per example, its team.yaml and the files its sandbox lines name."""
    files = framework_files(src)
    if missing := [r for r in REQUIRED if r not in files]:
        raise SystemExit(f"{src}: missing {missing}")
    for name in example_names(src):
        found = manifest(src / "examples" / name)
        files += [f"examples/{name}/{p}" for p in ["team.yaml", *found["root"], *found["workspace"]]]
    return list(dict.fromkeys(files))


def _put(src: Path, rel: str, dest: Path, *, rewrite: bool, overwrite: bool = False) -> bool:
    """Copy src/rel to dest/rel; False (and nothing written) if it exists and not overwrite."""
    target = dest / rel
    if target.exists() and not overwrite:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if rewrite and target.suffix in TEXT:
        text = (src / rel).read_bytes().decode("utf-8")
        for old, new in REWRITES:
            text = text.replace(old, new)
        target.write_bytes(text.encode("utf-8"))
    else:
        shutil.copy2(src / rel, target)
    return True


def init(dest: Path, *, rewrite: bool, src: Path | None = None) -> tuple[list[str], list[str]]:
    """Write the framework files into dest -> (written, kept: already there, untouched)."""
    src = src or source()
    files = framework_files(src)
    if missing := [r for r in REQUIRED if r not in files]:
        raise SystemExit(f"refused: the keeploop files are incomplete in {src}: {missing}")
    dest.mkdir(parents=True, exist_ok=True)
    written, kept = [], []
    for rel in files:
        (written if _put(src, rel, dest, rewrite=rewrite) else kept).append(rel)
    if not (dest / ".gitignore").exists():
        (dest / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
        written.append(".gitignore")
    return written, kept


def make_sandbox(example: Path, dest: Path, *, with_code: bool,
                 src: Path | None = None) -> tuple[Path, Path]:
    """Build an example's sandbox -> (control folder, workspace). with_code copies the
    clone's code too (for `python kl.py`); without it the control folder holds only
    the editable files, for a pip-installed `kl`."""
    from run import project_config  # lazy: setup.py imports this module to list files
    src = (src or source()).resolve()
    example, dest = example.resolve(), dest.resolve()
    files = manifest(example)
    if dest == HERE or HERE in dest.parents or dest == src or src in dest.parents:
        raise SystemExit(f"refused: {dest} is inside the keeploop {'repo' if with_code else 'install'}")
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"refused: {dest} is not empty")
    root = dest / "kl"
    if with_code:
        def ignore(d, names):
            if Path(d) == src:
                return {n for n in names if n in SKIP or n.endswith(".egg-info")}
            return {n for n in names if n == "__pycache__"}
        shutil.copytree(src, root, ignore=ignore)
    else:
        init(root, rewrite=True, src=src)
    (root / "holdout.py").unlink(missing_ok=True)  # demo holdout scores the demo config (L-001)
    for rel in files["root"]:
        _put(example, rel, root, rewrite=not with_code, overwrite=True)
    ws = project_config(root)["workspace"]
    if dest not in ws.parents:
        raise SystemExit(f"refused: team.yaml workspace {ws} is outside {dest}")
    for rel in files["workspace"]:
        _put(example, rel, ws, rewrite=False, overwrite=True)
    git(ws, "init", "-q")
    git(ws, "add", "-A")
    git(ws, *GIT_AUTHOR, "commit", "-qm", "keeploop: initial workspace")
    return root, ws


def pypi_readme(text: str, ref: str) -> str:
    """README.md for the PyPI page: relative links and images become absolute URLs
    pinned to `ref` (the release tag), since PyPI cannot resolve repo paths."""
    def absolute(path: str) -> str:
        if re.match(r"[a-z][a-z0-9+.-]*:|#|/", path, re.I):
            return path  # already absolute, an anchor, or site-relative
        kind = "raw" if re.search(r"\.(png|gif|jpe?g|svg|webp)(#|$)", path, re.I) else "blob"
        if kind == "raw":
            return f"{REPO_URL.replace('github.com', 'raw.githubusercontent.com')}/{ref}/{path}"
        return f"{REPO_URL}/blob/{ref}/{path}"
    text = re.sub(r"(\]\()([^)\s]+)", lambda m: m.group(1) + absolute(m.group(2)), text)
    return re.sub(r'((?:src|href|srcset)=")([^"]+)"', lambda m: m.group(1) + absolute(m.group(2)) + '"', text)
