"""The release gate: build the dist, check what is in it, install it in a clean
venv and run the first-run path on the installed `kl`. Run it before any upload.

    python tools/check_dist.py [--dist DIR] [--keep]

1. `python -m build` -> sdist + wheel (needs the `build` package), unless --dist
   names a folder that already holds them.
2. Lists the wheel and the sdist, and fails if an engine module, the CLI entry
   point or any asset scaffold.bundle_files() names is missing, or if evaluate.py
   or holdout.py would install as a top-level module.
3. A new venv (no access to this repo), `pip install --no-index` of the wheel.
4. Smoke test with the installed `kl`, all in a temp folder outside the repo:
   `kl init` in an empty git repo -> `kl begin` (demo baseline) -> `kl status`
   -> `kl run --mock` (headless, offline);
   `kl init --example marketing-research` -> `kl begin` (baseline 1.000000 plus
   the ceiling warning) -> `kl status` (this study's hypothesis, nothing from the
   demo charter, `kl` spelled for a pip install).

Exit 0 only if every step passed. Prints every command it runs.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import scaffold  # noqa: E402

MODULES = ["bm25", "codemap", "kl", "ledger", "lessons", "packs", "prepare", "rubric",
           "run", "scaffold", "scout", "vendors"]
FAILS: list[str] = []


def sh(argv, cwd=None, env=None, ok=True) -> str:
    print("$ " + " ".join(str(a) for a in argv) + (f"   (in {cwd})" if cwd else ""), flush=True)
    p = subprocess.run([str(a) for a in argv], cwd=cwd, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    out = p.stdout + p.stderr
    print(out.rstrip())
    if ok and p.returncode != 0:
        raise SystemExit(f"FAILED (exit {p.returncode}): {argv}")
    return out


def expect(cond: bool, what: str) -> None:
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        FAILS.append(what)


def check_contents(wheel: Path, sdist: Path) -> None:
    names = set(zipfile.ZipFile(wheel).namelist())
    print(f"\n{wheel.name}: {len(names)} entries")
    for n in sorted(names):
        print("  " + n)
    for m in MODULES:
        expect(f"{m}.py" in names, f"wheel has module {m}.py")
    for m in ("evaluate.py", "holdout.py"):
        expect(m not in names, f"wheel does not install {m} as a top-level module")
    assets = scaffold.bundle_files(REPO)
    missing = [a for a in assets if f"keeploop_assets/{a}" not in names]
    expect(not missing, f"wheel has all {len(assets)} assets" + (f"; missing {missing}" if missing else ""))
    ep = next((n for n in names if n.endswith(".dist-info/entry_points.txt")), None)
    expect(ep is not None and "kl = kl:main" in zipfile.ZipFile(wheel).read(ep).decode(),
           "entry point kl = kl:main")
    with tarfile.open(sdist) as tf:
        snames = {n.split("/", 1)[1] for n in tf.getnames() if "/" in n}
    print(f"\n{sdist.name}: {len(snames)} entries")
    missing = [a for a in assets + ["setup.py", "scaffold.py", "pyproject.toml", "README.md"]
               if a not in snames]
    expect(not missing, "sdist has the assets, setup.py and the metadata"
           + (f"; missing {missing}" if missing else ""))


def smoke(wheel: Path, tmp: Path) -> None:
    venv = tmp / "venv"
    sh([sys.executable, "-m", "venv", venv])
    bindir = venv / ("Scripts" if os.name == "nt" else "bin")
    py = bindir / ("python.exe" if os.name == "nt" else "python")
    sh([py, "-m", "pip", "install", "-q", "--no-index", wheel])
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    env["PYTHONUTF8"] = "1"
    kl = shutil.which("kl", path=str(bindir))
    expect(kl is not None, "the venv has a `kl` command")
    if kl is None:
        return
    out = sh([kl, "run", "--version"], env=env)
    expect(f"keeploop {scaffold_version()}" in out, "kl run --version prints this version")

    proj = tmp / "proj"
    proj.mkdir()
    sh(["git", "init", "-q"], cwd=proj)
    out = sh([kl, "init"], cwd=proj, env=env)
    expect("kl init: wrote" in out and "kept" not in out, "kl init writes into an empty repo")
    for rel in scaffold.REQUIRED + [".gitignore", ".claude/agents/keeploop-analyst.md"]:
        expect((proj / rel).is_file(), f"kl init wrote {rel}")
    agents = (proj / "AGENTS.md").read_text(encoding="utf-8")
    expect("python kl.py" not in agents and "`kl begin`" in agents,
           "AGENTS.md says `kl ...`, not `python kl.py`")
    out = sh([kl, "init"], cwd=proj, env=env)
    expect("wrote 0 files" in out, "a second kl init overwrites nothing")
    out = sh([kl, "begin"], cwd=proj, env=env)
    expect("baseline metric =" in out and "best " in out, "kl begin takes the demo baseline")
    out = sh([kl, "status"], cwd=proj, env=env)
    expect(out.startswith("best ") and "next hypothesis to test:" in out, "kl status prints the state")
    out = sh([kl, "run", "--mock", "--iterations", "2"], cwd=proj, env=env)
    expect("Traceback" not in out and (proj / ".keeploop" / "results.tsv").read_text(
        encoding="utf-8").count("\n") >= 3, "kl run --mock runs the headless loop")

    dest = tmp / "mr"
    out = sh([kl, "init", "--example", "marketing-research", dest], cwd=tmp, env=env)
    expect("sandbox ready" in out and f"&& kl begin" in out, "kl init --example builds the sandbox")
    root = dest / "kl"
    expect(not (root / "kl.py").exists() and not (root / "holdout.py").exists(),
           "the sandbox holds no code copy and no demo holdout.py")
    out = sh([kl, "begin"], cwd=root, env=env)
    expect("baseline metric = 1.000000" in out, "kl begin: baseline 1.000000 on the kept report")
    expect("baseline at ceiling" in out, "kl begin warns that the baseline is at the ceiling")
    out = sh([kl, "status"], cwd=root, env=env)
    expect("next hypothesis to test: Dropping or sourcing" in out
           and "learning rate" not in out.lower(), "kl status: this study's hypothesis")


def scaffold_version() -> str:
    from prepare import __version__
    return __version__


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dist", type=Path, help="use the sdist + wheel already in this folder")
    ap.add_argument("--keep", action="store_true", help="keep the temp folder")
    a = ap.parse_args(argv)
    tmp = Path(tempfile.mkdtemp(prefix="kl-dist-"))
    try:
        dist = a.dist or tmp / "dist"
        if not a.dist:
            sh([sys.executable, "-m", "build", "--outdir", dist, REPO])
        v = scaffold_version()
        wheel, sdist = dist / f"keeploop-{v}-py3-none-any.whl", dist / f"keeploop-{v}.tar.gz"
        expect(wheel.is_file() and sdist.is_file(), f"dist has {wheel.name} and {sdist.name}")
        if wheel.is_file() and sdist.is_file():
            check_contents(wheel, sdist)
            smoke(wheel, tmp)
    finally:
        if a.keep:
            print(f"kept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\ncheck_dist: {'FAIL: ' + '; '.join(FAILS) if FAILS else 'PASS'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
