"""Builds keeploop's wheel and sdist. pyproject.toml holds the static metadata;
this file adds what has to be computed:

- the engine modules go into the wheel's `keeploop/` folder, not top-level, so
  names like `run` or `prepare` never clash with other installed packages; the
  `kl` command is `keeploop:main`, which puts that folder on sys.path and runs kl;
- the project files `kl init` copies (scaffold.bundle_files) go into
  `keeploop/_assets/`, and into the sdist at their repo paths;
- the version comes from prepare.__version__ (the single source);
- the PyPI page gets README.md with every relative link pinned to the release tag.

    python -m build                  sdist + wheel in dist/
    python tools/check_dist.py       build, list, install in a clean venv, smoke test
"""

import shutil
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist
from setuptools.dist import Distribution

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scaffold  # noqa: E402
from prepare import __version__  # noqa: E402

INIT = '''"""keeploop: the `kl` engine. Its modules live in this folder and import each
other by plain name, so the folder goes on sys.path only while kl runs."""

import sys
from pathlib import Path

__version__ = "{version}"
_HERE = str(Path(__file__).resolve().parent)


def main() -> int:
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)
    import kl
    return kl.main()
'''


def _copy(files: list[str], dest: Path) -> None:
    for rel in files:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / rel, dest / rel)


class BuildPy(build_py):
    def run(self):
        super().run()
        if self.dry_run:
            return
        pkg = Path(self.build_lib) / "keeploop"
        _copy([f"{m}.py" for m in scaffold.ENGINE], pkg)
        (pkg / "__init__.py").write_text(INIT.format(version=__version__), encoding="utf-8")
        _copy(scaffold.bundle_files(HERE), pkg / "_assets")


class Sdist(sdist):
    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        need = ["README.md"] + [f"{m}.py" for m in scaffold.ENGINE] + scaffold.bundle_files(HERE)
        _copy([f for f in need if not (Path(base_dir) / f).exists()], Path(base_dir))


class Dist(Distribution):
    """No module is declared (they go in keeploop/ by hand), so setuptools would skip
    build_py altogether; this keeps it running."""
    def has_pure_modules(self):
        return True


setup(
    distclass=Dist,
    version=__version__,
    long_description=scaffold.pypi_readme((HERE / "README.md").read_text(encoding="utf-8"),
                                          f"v{__version__}"),
    long_description_content_type="text/markdown",
    cmdclass={"build_py": BuildPy, "sdist": Sdist},
)
