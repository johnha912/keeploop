"""Render the launch demo (GIF, MP4, poster) from a REAL noisy-eval run. Build-time only.

    python tools/render_demo.py [--font PATH] [--out docs/assets]

Not a keeploop dependency: it needs Pillow (frames) and ffmpeg (GIF palette, H.264).
keeploop itself stays stdlib only.

What it shows, and why these cycles: the selection rule is fixed in select() before
looking at any frame. It takes the first seed of the proof sweep (docs/proof/proof.json,
seeds in order) whose keeploop run (1) DISCARDS, inside the noise band, a change whose
true effect is <= 0 that still beat the best score, and (2) later KEEPS a change with a
true gain. The demo shows those two cycles in full. The cycles in between and after are
folded into one dim line each, with their counts taken from that run's results.tsv.
The headline seed of PROOF.md (seed 1) does not qualify: its in-band discards were
real gains.

Every line in the frames is the run's own stdout (`run.py --mock --narrate`), re-run
here deterministically, with two exceptions. The window title and the opening `#`
comment carry no numbers. The fold lines are marked with ⋯. The run's files go to
<out>/demo-run/keeploop/ (results.tsv, stdout.txt, ...), and the script fails if any
number on screen is missing from that stdout or if the run differs from proof.json.
Playback is paced for reading: a mock cycle really takes about 0.15 s.

Outputs:
- keeploop-demo.gif: loops, 1280x720, at most 15 MB;
- keeploop-demo.mp4: H.264, yuv420p, the same loop;
- keeploop-demo-poster.png: the first frame, which is also the last (the finished screen).
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO))
import proof_run  # noqa: E402

W, H, FPS = 1280, 720, 25
MARGIN, TITLE_H, FONT_PX, LINE_H = 28, 44, 26, 37
COLS = int((W - 2 * MARGIN) // (FONT_PX * 0.6))  # monospace cell: 0.6 em
BG, FG, DIM, TITLE_BG = (13, 17, 23), (230, 237, 243), (125, 133, 144), (33, 38, 45)
AMBER, GREEN, BLUE, PROMPT = (240, 180, 41), (63, 185, 80), (121, 192, 255), (63, 185, 80)
FONTS = ["/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
         "/Library/Fonts/JetBrainsMono-Regular.ttf", "C:/Windows/Fonts/consola.ttf"]


def select(proof: dict) -> tuple[int, int, int]:
    """(seed, discard cycle, keep cycle) by the rule in the module docstring."""
    for r in proof["sweep"]:
        if r["mode"] != "keeploop":
            continue
        for a in r["cycles"]:
            in_band = (a["status"] == "discard" and a["metric"] is not None
                       and a["best_before"] < a["metric"] <= a["best_before"] + 2 * r["sigma"])
            if in_band and a["true_effect"] <= 0:
                b = next((x for x in r["cycles"] if x["cycle"] > a["cycle"]
                          and x["status"] == "keep" and x["true_effect"] > 0), None)
                if b:
                    return r["seed"], a["cycle"], b["cycle"]
    raise SystemExit("no seed in proof.json matches the demo rule")


def blocks(stdout: str) -> tuple[list[str], dict[int, list[str]], list[str]]:
    """stdout -> (lines before cycle 1, {cycle: its narrated lines}, closing lines)."""
    head, cyc, tail, cur = [], {}, [], None
    for ln in stdout.splitlines():
        if m := re.fullmatch(r"cycle (\d+)", ln):
            cur = int(m.group(1))
            cyc[cur] = []
        elif re.match(r"cycle \d+: ", ln):  # the one-line summary after the narration
            cur = None
        elif ln.startswith(("holdout:", "run complete:")):
            tail.append(ln)
        elif cur is not None and ln.strip():
            cyc[cur].append(ln)
        elif cur is None and not cyc and ln.startswith("run: baseline"):
            head.append(ln)
    return head, cyc, tail


def color_of(ln: str):
    s = ln.strip()
    if s.startswith("DISCARD"):
        return AMBER
    if s.startswith("KEEP"):
        return GREEN
    if s.startswith("⋯") or s.startswith("#"):
        return DIM
    if re.fullmatch(r"cycle \d+", s):
        return BLUE
    return FG


def wrap(ln: str) -> list[str]:
    out = []
    while len(ln) > COLS:
        cut = ln.rfind(" ", 0, COLS)
        cut = cut if cut > COLS // 2 else COLS
        out.append(ln[:cut])
        ln = "            " + ln[cut:].lstrip()  # continuation, indented under the text
    return out + [ln]


def script(seed: int, a: int, b: int, stdout: str, rows: list[dict]) -> list[tuple[float, str]]:
    """(seconds after the previous event, line) pairs; '\\x00' + text = typed."""
    head, cyc, tail = blocks(stdout)

    def fold(lo, hi):
        mine = [r for r in rows if lo <= int(r["cycle"]) <= hi]
        if not mine:
            return []
        k = sum(r["status"] == "keep" for r in mine)
        rng = f"cycle {lo}" if lo == hi else f"cycles {lo}-{hi}"
        return [f"⋯ {rng}: {k} kept, {len(mine) - k} discarded (results.tsv) ⋯"]
    ev = [(0.2, "\x00# keeploop on a noisy eval: keep a change only if it beats best + 2σ"),
          (0.2, "\x00$ kl run --mock --narrate")]
    ev += [(0.35, ln) for ln in head]
    ev += [(0.3, ln) for ln in fold(1, a - 1)]
    for c, pause_end in ((a, 1.4), (b, 0.9)):
        ev.append((0.3, f"cycle {c}"))
        for ln in cyc[c]:
            step = ln.split()[0]
            ev.append(({"analyst": 0.3, "engineer": 0.2, "evaluate": 0.45, "audit": 0.25,
                        "confirm": 0.45}.get(step, 0.6), ln))
        ev.append((pause_end, ""))
    ev += [(0.15, ln) for ln in fold(b + 1, max(int(r["cycle"]) for r in rows))]
    ev += [(0.35, ln) for ln in tail if ln.startswith("run complete:")]
    return ev


def screens(ev: list[tuple[float, str]]) -> list[tuple[float, list[str], int]]:
    """Timed screens: (duration, visible lines, index of the line being typed or -1)."""
    out, lines, rows_max = [], [], (H - TITLE_H - 2 * MARGIN) // LINE_H
    for delay, text in ev:
        if text.startswith("\x00"):
            text = text[1:]
            out.append((delay, list(lines[-rows_max:]), -1))
            for n in list(range(4, len(text), 4)) + [len(text)]:  # typed, four characters a frame
                out.append((1 / FPS, (lines + [text[:n]])[-rows_max:], 1))
            lines.append(text)
            continue
        out.append((delay, list(lines[-rows_max:]), -1))
        lines += wrap(text) if text else [""]
    out.append((1.6, list(lines[-rows_max:]), -1))
    return out


def render(screens_: list, font_path: str, out: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont  # build-time only
    font = ImageFont.truetype(font_path, FONT_PX)
    bold = ImageFont.truetype(font_path.replace("Regular", "Bold"), FONT_PX) \
        if "Regular" in font_path and Path(font_path.replace("Regular", "Bold")).exists() else font
    final = screens_[-1][1]

    def frame(lines, path):
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, W, TITLE_H], fill=TITLE_BG)
        for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse([18 + i * 24, 15, 32 + i * 24, 29], fill=col)
        t = "keeploop  ·  examples/noisy-eval"
        d.text((W / 2 - d.textlength(t, font=font) * 0.75 / 2, 11), t, fill=DIM,
               font=ImageFont.truetype(font_path, 18))
        cont = None
        for i, ln in enumerate(lines):
            y = TITLE_H + MARGIN + i * LINE_H
            c = color_of(ln) if not ln.startswith("            ") else (cont or FG)
            cont = c
            f = bold if c in (AMBER, GREEN) else font
            if ln.startswith("$ "):
                d.text((MARGIN, y), "$", fill=PROMPT, font=bold)
                d.text((MARGIN + d.textlength("$ ", font=font), y), ln[2:], fill=FG, font=font)
            else:
                d.text((MARGIN, y), ln, fill=c, font=f)
        im.save(path)
    n = 0
    seq = [(0.8, final, -1), (0.12, [], -1)] + screens_  # starts on the finished screen
    for dur, lines, _ in seq:
        reps = max(1, round(dur * FPS))
        frame(lines, out / f"f{n:05d}.png")
        for _ in range(reps - 1):
            n += 1
            shutil.copyfile(out / f"f{n - 1:05d}.png", out / f"f{n:05d}.png")
        n += 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--font", default=next((f for f in FONTS if Path(f).exists()), None))
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "assets")
    a = ap.parse_args(argv)
    if not a.font:
        raise SystemExit("no monospace font found: pass --font PATH")
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found (build-time only)")
    proof = json.loads((REPO / "docs" / "proof" / "proof.json").read_text(encoding="utf-8"))
    seed, ca, cb = select(proof)
    print(f"demo: seed {seed}, in-band discard at cycle {ca}, keep at cycle {cb}")
    run_dir = a.out / "demo-run"
    with tempfile.TemporaryDirectory(prefix="kl-demo-") as d:
        tmp = Path(d)
        got = proof_run.one("keeploop", seed, proof["cycles"], tmp, run_dir)
        want = next(r for r in proof["sweep"] if r["seed"] == seed and r["mode"] == "keeploop")
        if got != want:
            raise SystemExit("the re-run differs from proof.json: refusing to render")
        stdout = (run_dir / "keeploop" / "stdout.txt").read_text(encoding="utf-8")
        import csv
        with (run_dir / "keeploop" / "results.tsv").open(encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f, delimiter="\t") if int(r["cycle"]) >= 1]
        ev = script(seed, ca, cb, stdout, rows)
        shown = " ".join(t for _, t in ev)
        for num in re.findall(r"\d+\.\d+", shown):
            if num not in stdout and num not in {"2"}:
                raise SystemExit(f"{num} is on screen but not in the run's stdout")
        frames = tmp / "frames"
        frames.mkdir()
        render(screens(ev), a.font, frames)
        a.out.mkdir(parents=True, exist_ok=True)
        gif, mp4, poster = (a.out / "keeploop-demo.gif", a.out / "keeploop-demo.mp4",
                            a.out / "keeploop-demo-poster.png")
        shutil.copyfile(frames / "f00000.png", poster)
        src = ["-framerate", str(FPS), "-i", str(frames / "f%05d.png")]
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src, "-c:v", "libx264", "-preset", "slow",
                        "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src, "-vf",
                        "fps=12.5,split[a][b];[a]palettegen=max_colors=64:stats_mode=full[p];"
                        "[b][p]paletteuse=dither=none", "-loop", "0", str(gif)], check=True)
        (a.out / "demo-run" / "SOURCE.md").write_text(
            f"# Source of keeploop-demo.gif / .mp4 / -poster.png\n\n"
            f"Rendered by `python tools/render_demo.py` from the keeploop-mode run of seed {seed} of "
            f"the proof sweep (`docs/proof/proof.json`), re-run here: `keeploop/stdout.txt` is its "
            f"output, `keeploop/results.tsv` its ledger. Shown in full: cycle {ca} (a change that "
            f"beat the best but landed inside the noise band, discarded) and cycle {cb} (kept). "
            f"Other cycles are folded into the lines marked ⋯. The selection rule is in "
            f"`tools/render_demo.py` (select()). Playback is paced for reading.\n", encoding="utf-8")
    print(f"wrote {gif} ({gif.stat().st_size / 1e6:.2f} MB), {mp4}, {poster}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
