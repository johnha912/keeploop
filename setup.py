"""Packs keeploop's project files into the wheel and the sdist.

pyproject.toml holds the metadata; this file only adds the assets that `kl init`
copies into a project (AGENTS.md, program.md, team.yaml, the demo evaluate.py,
packs/, .claude/, and each worked example's sandbox files). scaffold.py is the
single list of them. In the wheel they land in keeploop_assets/ next to the
modules; in the sdist at their repo paths, so a wheel built from it finds them.

    python -m build                  sdist + wheel in dist/
    python tools/check_dist.py       build, list, install in a clean venv, smoke test
"""

import shutil
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scaffold  # noqa: E402


def _copy(files: list[str], dest: Path) -> None:
    for rel in files:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / rel, dest / rel)


class BuildPy(build_py):
    def run(self):
        super().run()
        if not self.dry_run:
            _copy(scaffold.bundle_files(HERE), Path(self.build_lib) / "keeploop_assets")


class Sdist(sdist):
    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        _copy([f for f in scaffold.bundle_files(HERE) if not (Path(base_dir) / f).exists()],
              Path(base_dir))


setup(cmdclass={"build_py": BuildPy, "sdist": Sdist})
