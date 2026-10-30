"""codemap.py - cached code index of a git workspace (stdlib). Per tracked file:
its defs/classes and imports; a reverse "imported by" index is derived on read.
Incremental: the cache keeps each file's content hash; only changed files are
reparsed. Python uses ast; JS/TS/Go/Rust/Java use short regexes (names only)."""

import ast
import hashlib
import json
import re
from pathlib import Path

from prepare import git

_JS = (r"\b(?:function\*?|class|interface|enum|type)\s+(\w+)|\b(?:const|let|var)\s+(\w+)\s*="
       r"\s*(?:async\s*)?(?:function|\()",
       r"""(?:from|require\(|import)\s*['"]([^'"\n]+)['"]""")
LANGS = {
    **dict.fromkeys((".js", ".jsx", ".ts", ".tsx", ".mjs"), _JS),
    ".go": (r"^func\s+(?:\([^)]*\)\s*)?(\w+)|^type\s+(\w+)\s+(?:struct|interface)",
            r'^\s*(?:import\s+)?(?:[\w.]+\s+)?"([\w./-]+)"\s*$'),
    ".rs": (r"\b(?:fn|struct|enum|trait)\s+(\w+)", r"^\s*(?:use|mod)\s+([\w:]+)"),
    ".java": (r"\b(?:class|interface|enum|record)\s+(\w+)", r"^import\s+(?:static\s+)?([\w.]+)"),
}
MAX_BYTES = 200_000


def _py(text: str) -> tuple[list, list, list]:
    tree = ast.parse(text)
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    label = lambda n: ("class " if isinstance(n, ast.ClassDef) else "def ") + n.name  # noqa: E731
    imps = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imps += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            imps += [n.module or ""] + [a.name for a in n.names]
    return ([label(n) for n in ast.walk(tree) if isinstance(n, kinds)], imps,
            [label(n) for n in tree.body if isinstance(n, kinds)])


def _parse(path: str, text: str) -> dict:
    """{defs, top, imports}; unparseable -> empty (never raises)."""
    ext = Path(path).suffix.lower()
    try:
        if ext == ".py":
            defs, imps, top = _py(text)
        elif ext in LANGS:
            d_rx, i_rx = LANGS[ext]
            defs = sorted({n for m in re.findall(d_rx, text, re.M)
                           for n in (m if isinstance(m, tuple) else (m,)) if n})
            imps = [m for m in re.findall(i_rx, text, re.M) if m]
            top = defs
        else:
            return {}
    except (SyntaxError, ValueError, RecursionError):
        return {}
    return {"defs": defs, "top": top, "imports": sorted({i for i in imps if i})}


def build(workspace: Path, cache: Path | None = None) -> dict:
    """{file: {sha, defs, top, imports}}; reparses only files whose hash changed."""
    old = {}
    if cache and cache.exists():
        try:
            old = json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
    new = {}
    base = workspace.resolve()
    for f in git(workspace, "-c", "core.quotepath=off", "ls-files").splitlines():
        p = workspace / f
        try:  # a tracked symlink (or a path through one) must not read outside the workspace
            if p.is_symlink() or not p.resolve().is_relative_to(base):
                continue
            raw = p.read_bytes()[:MAX_BYTES + 1]
        except (OSError, ValueError):
            continue
        sha = hashlib.sha256(raw).hexdigest()
        if old.get(f, {}).get("sha") == sha:
            new[f] = old[f]
        else:
            new[f] = {"sha": sha, **(_parse(f, raw.decode("utf-8", "replace"))
                                     if len(raw) <= MAX_BYTES else {})}
    if cache and new != old:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(new), encoding="utf-8")
    return new


def render(m: dict, max_chars: int) -> str:
    """The Analyst's repo map: file plus top-level def/class names, capped."""
    lines = [f"{f}: {', '.join(e['top'])}" if e.get("top") else f for f, e in m.items()]
    out, used = [], 0
    for i, line in enumerate(lines):
        if used + len(line) + 1 > max_chars - 40:  # room for the omitted note
            out.append(f"... {len(lines) - i} more files omitted")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def _tail(name: str) -> str:
    return re.split(r"[./:\\]+", name.strip("./"))[-1]


def importers(m: dict, f: str) -> list[str]:
    """Files whose imports end in f's stem (name-based, so approximate)."""
    stem = Path(f).stem
    return sorted(g for g, e in m.items() if g != f
                  and any(_tail(i) == stem for i in e.get("imports", [])))


def query(m: dict, name: str) -> str:
    """Where NAME is defined (or which file is NAME) and who imports that file."""
    want = name.lower()
    hits = [(f, d) for f, e in m.items() for d in e.get("defs", [])
            if d.split()[-1].lower() == want]
    files = [f for f, _ in hits] + [f for f in m if Path(f).stem.lower() == want
                                    and f not in [h for h, _ in hits]]
    out = [f"defined: {f} ({d})" for f, d in hits]
    out += [f"module: {f}" for f in files[len(hits):]]
    for f in dict.fromkeys(files):
        out.append(f"imported by {f}: " + (", ".join(importers(m, f)) or "none"))
    return "\n".join(out) or f"no definition or module named {name!r}"
