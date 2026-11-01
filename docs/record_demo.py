"""Record the README demo: docs/demo.cast (asciicast v2) and docs/demo.gif.

    python docs/record_demo.py [--agg PATH] [--font-size N]

Runs the real mock demo (`prepare.py`, then `run.py --mock --iterations 5`, then
`kl.py lesson list`) in a throwaway copy of the tracked files, so the repo is never
touched. Stdlib only; the GIF needs the `agg` binary (https://github.com/asciinema/agg).
asciinema itself is not needed: the cast is written here from real, timestamped output.

Rewrites of real output (the only two; run.py's own leading `prepare:` line is left off):
  1. the temp copy's absolute path prefix is removed, so paths read `.keeploop\\...`;
  2. the `lesson list` lines are word-wrapped to the screen width (they are longer).
Everything else is shown byte for byte. The story is asserted before anything is written.
"""
import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
IDLE_CAP = 1.5  # longest silent gap kept on screen, seconds
TYPE_DELAY = 0.04
STORY = [("1", "keep", "0.942"), ("2", "keep", "0.992"), ("3", "discard", "0.942"),
         ("4", "crash", "None"), ("5", "keep", "1.0")]
COLOR = {"keep": "32", "discard": "33", "crash": "31"}  # ANSI: green, yellow, red


def run_demo() -> tuple[list[tuple[float, str]], str]:
    """Return ([(seconds_since_start, line)] from run.py, `lesson list` text)."""
    tmp = Path(tempfile.mkdtemp(prefix="kl"))
    try:
        tar = subprocess.run(["git", "archive", "HEAD"], cwd=ROOT, check=True,
                             capture_output=True).stdout
        tarfile.open(fileobj=io.BytesIO(tar)).extractall(tmp)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
        py = [sys.executable, "-u"]
        subprocess.run([*py, "prepare.py"], cwd=tmp, env=env, check=True, capture_output=True)
        t0 = time.monotonic()
        p = subprocess.Popen([*py, "run.py", "--mock", "--iterations", "5"], cwd=tmp, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        lines = [(time.monotonic() - t0, raw.decode("utf-8").rstrip("\r\n")) for raw in p.stdout]
        if p.wait():
            sys.exit("record_demo: run.py exited non-zero")
        les = subprocess.run([*py, "kl.py", "lesson", "list"], cwd=tmp, env=env, check=True,
                             capture_output=True).stdout.decode("utf-8")
        prefix = str(tmp) + os.sep  # rewrite 1
        # run.py echoes one `prepare:` line first; the screen opens at the baseline instead
        lines = [(t, s.replace(prefix, "")) for t, s in lines if not s.startswith("prepare:")]
        return lines, les.replace(prefix, "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_story(lines: list[tuple[float, str]], lesson: str) -> None:
    text = [s for _, s in lines]
    cycles = [re.match(r"cycle (\d): (\w+)\s+metric=(\S+)", s) for s in text if s.startswith("cycle ")]
    got = [m.groups() for m in cycles if m]
    problems = []
    if got != STORY:
        problems.append(f"cycles {got} != {STORY}")
    if not text or not text[0].startswith("run: baseline metric = 0.828178"):
        problems.append("first line is not the 0.828178 baseline")
    if not any(s.startswith("cycle 4: crash") and "lesson=L-001" in s for s in text):
        problems.append("cycle 4 did not record lesson L-001")
    if not any(s.startswith("run complete: 3 keeps, 1 discards, 1 crashes, 1 lessons") for s in text):
        problems.append("final summary changed")
    if "L-001" not in lesson:
        problems.append("lesson list has no L-001")
    if re.search(r"Users|AppData|Temp|[A-Za-z]:\\","\n".join(text) + lesson):
        problems.append("a real path leaked")
    if problems:
        sys.exit("record_demo: demo drifted, nothing written:\n  " + "\n  ".join(problems))


def build_cast(lines: list[tuple[float, str]], lesson: str) -> str:
    cols = max(len(s) for _, s in lines)
    wrapped = []
    for ln in lesson.splitlines():  # rewrite 2
        indent = " " * (len(ln) - len(ln.lstrip()))
        wrapped += textwrap.wrap(ln, cols, subsequent_indent=indent + "  ", break_long_words=False) or [""]
    assert all(len(s) <= cols for s in wrapped)
    events, t = [], 0.0

    def out(text: str) -> None:
        events.append([round(t, 3), "o", text])

    def prompt(cmd: str) -> None:
        nonlocal t
        out("\x1b[1;36m$\x1b[0m ")
        for ch in cmd:
            t += TYPE_DELAY
            out(ch)
        t += 0.4
        out("\r\n")

    def show(s: str) -> None:
        m = re.match(r"cycle \d: (\w+)", s)
        c = COLOR.get(m.group(1)) if m else None
        out(f"\x1b[{c}m{s}\x1b[0m\r\n" if c else s + "\r\n")

    t = 0.5
    prompt("python run.py --mock --iterations 5")
    prev = 0.0
    for ts, s in lines:
        t += min(ts - prev, IDLE_CAP)
        prev = ts
        show(s)
    t += 1.2
    out("\r\n")
    prompt("python kl.py lesson list")
    for s in wrapped:
        out(("\x1b[1;35m" + s + "\x1b[0m" if s.startswith("L-") else s) + "\r\n")
        t += 0.15
    t += 1.0
    out("\x1b[1;36m$\x1b[0m ")
    height = len(lines) + len(wrapped) + 4
    head = {"version": 2, "width": cols, "height": height}
    return "\n".join(json.dumps(x, ensure_ascii=False) for x in [head, *events]) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--agg", help="path to the agg binary (default: agg on PATH)")
    ap.add_argument("--font-size", type=int, default=16)  # 95 cols -> 853 px wide
    a = ap.parse_args()
    lines, lesson = run_demo()
    check_story(lines, lesson)
    cast = DOCS / "demo.cast"
    cast.write_text(build_cast(lines, lesson), encoding="utf-8", newline="\n")
    print(f"wrote {cast}")
    agg = a.agg or shutil.which("agg")
    if not agg:
        sys.exit("record_demo: agg not found. Install it from https://github.com/asciinema/agg "
                 "(or pass --agg PATH) to render docs/demo.gif; docs/demo.cast is written.")
    cmd = [agg, "-q", "--font-size", str(a.font_size), "--idle-time-limit", str(IDLE_CAP),
           "--last-frame-duration", "3", "--theme", "github-dark", str(cast), str(DOCS / "demo.gif")]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"wrote {DOCS / 'demo.gif'}")


if __name__ == "__main__":
    main()
