"""Render the README hero figure (GIF, MP4, poster PNG) from the committed run files.

    python tools/render_figure.py [--out docs/assets]

Build-time only, not a keeploop dependency: needs Node with Playwright's Chromium
(require('playwright')), ffmpeg and Pillow (the seamless-loop check).

The figure is tools/figure/figure.html: a one-page technical note in a dark paper
style (abstract, Fig. 1 naive vs keeploop, Algorithm 1, Fig. 2 a real run drawn cycle
by cycle, Table 1 the 25-seed proof, the price, Fig. 3 the keep bar, takeaway). A
highlight walks through it sentence by sentence, box by box, row by row. Every number
on it is read here from committed files, never typed into the template:

- docs/proof/proof.json: version-independent proof summary, panel (c) and the price line;
- docs/assets/demo-run/keeploop/: the seed-2 run that tools/render_demo.py re-runs and
  checks against proof.json (results.tsv, best.json, holdout.json, stdout.txt). The two
  cycles called out are render_demo.select()'s: an in-band discard of a change with no
  true gain, then a keep.

Outputs: keeploop-figure.gif (1200x1600, loops), keeploop-figure.mp4 (1800x2400,
3:4, H.264, for X), keeploop-figure.png (the finished page: the first and last frame).
"""

import argparse
import csv
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
import render_demo  # noqa: E402

FPS = 12
DRIVER = r"""
const { chromium } = require('playwright');
(async () => {
  const [html, out, fps, total] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1800, height: 2400 }, deviceScaleFactor: 1 });
  await p.goto('file://' + html);
  await p.evaluate(() => document.fonts.ready);
  const n = Math.round(parseFloat(total) * parseFloat(fps));
  // warm-up: walk the whole timeline once so every lazily loaded font (the ▶ pointer,
  // italic labels) is in before frame 0; otherwise frame 0 and the last frame differ
  for (let w = 0; w <= parseFloat(total); w += 0.5) {
    await p.evaluate(t => window.render(t), w);
    await p.screenshot({ path: `${out}/warmup.png` });
  }
  await p.evaluate(() => document.fonts.ready);
  for (let i = 0; i <= n; i++) {
    await p.evaluate(t => window.render(t), i / parseFloat(fps));
    await p.screenshot({ path: `${out}/f${String(i).padStart(5, '0')}.png` });
  }
  await b.close();
})();
"""


def data() -> dict:
    from prepare import __version__
    proof = json.loads((REPO / "docs" / "proof" / "proof.json").read_text(encoding="utf-8"))
    seed, a, b = render_demo.select(proof)
    run_dir = REPO / "docs" / "assets" / "demo-run" / "keeploop"
    with (run_dir / "results.tsv").open(encoding="utf-8") as f:
        rows = [{"cycle": int(r["cycle"]), "metric": float(r["metric"]), "best": float(r["best_metric"]),
                 "status": r["status"]} for r in csv.DictReader(f, delimiter="\t") if r["metric"]]
    # the ledger's best_metric is the best AFTER a row; the chart wants the bar each
    # cycle was judged against, i.e. the best BEFORE it
    before = []
    prev = rows[0]["best"]
    for r in rows:
        before.append({**r, "best": prev if r["cycle"] else r["best"]})
        prev = r["best"]
    best = json.loads((run_dir / "best.json").read_text(encoding="utf-8"))
    hold = json.loads((run_dir / "holdout.json").read_text(encoding="utf-8"))
    stdout = (run_dir / "stdout.txt").read_text(encoding="utf-8")
    _, cyc, _ = render_demo.blocks(stdout)
    first = float(re.search(r"evaluate\s+(\d\.\d+)", "\n".join(cyc[b])).group(1))
    rerun = float(re.search(r"re-run (\d\.\d+)", "\n".join(cyc[b])).group(1))
    by = {(r["seed"], r["mode"]): r for r in proof["sweep"]}
    seeds = sorted({r["seed"] for r in proof["sweep"]})
    lower = sum(by[s, "keeploop"]["holdout_gain"] < by[s, "naive"]["holdout_gain"] for s in seeds)
    # timeline (seconds): the finished page, then reset and walk: abstract (5 sentences),
    # Fig. 1 + Algorithm 1 (8 steps), Fig. 2 cycle by cycle, Table 1 (7 rows), the price
    # with Fig. 3 (3 points), the takeaway, and back to the finished page
    t = {"reset": 1.0, "abs": 1.1}
    t["fig1"] = round(t["abs"] + 5 * 0.9, 3)
    t["run"] = round(t["fig1"] + 8 * 0.55, 3)
    sched, at = [], t["run"] + 0.1
    for r in before:
        sched.append([r["cycle"], round(at, 3)])
        at += 0.22 + (1.0 if r["cycle"] in (a, b) else 0)
    t["table"] = round(at + 0.3, 3)
    t["price"] = round(t["table"] + 7 * 0.5, 3)
    t["take"] = round(t["price"] + 3 * 0.8, 3)
    t["end"] = round(t["take"] + 1.3, 3)
    total = round(t["end"] + 0.8, 3)
    return {"version": __version__, "timeline": t, "total": total,
            "run": {"seed": seed, "a": a, "b": b, "rows": before, "sigma": best["sigma"],
                    "hold0": hold["baseline"], "hold1": hold["final"], "b_first": first, "b_rerun": rerun,
                    "schedule": sched},
            "p": {"n": proof["summary"]["naive"], "k": proof["summary"]["keeploop"],
                  "lower": lower, "seeds": len(seeds)}}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "assets")
    a = ap.parse_args(argv)
    for tool in ("node", "ffmpeg"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} not found (build-time only)")
    d = data()
    html = (REPO / "tools" / "figure" / "figure.html").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="kl-fig-") as tmp:
        tmp = Path(tmp)
        page = tmp / "figure.html"
        page.write_text(html.replace("__DATA__", json.dumps(d)), encoding="utf-8")
        (tmp / "driver.js").write_text(DRIVER, encoding="utf-8")
        frames = tmp / "frames"
        frames.mkdir()
        subprocess.run(["node", str(tmp / "driver.js"), str(page), str(frames), str(FPS), str(d["total"])],
                       check=True)
        a.out.mkdir(parents=True, exist_ok=True)
        gif, mp4, png = (a.out / "keeploop-figure.gif", a.out / "keeploop-figure.mp4",
                         a.out / "keeploop-figure.png")
        (frames / "warmup.png").unlink()
        from PIL import Image, ImageChops  # build-time only
        last = sorted(frames.glob("f*.png"))[-1]
        if ImageChops.difference(Image.open(frames / "f00000.png").convert("RGB"),
                                 Image.open(last).convert("RGB")).getbbox():
            raise SystemExit("the first and last frames differ: the loop would jump")
        shutil.copyfile(frames / "f00000.png", png)
        src = ["-framerate", str(FPS), "-i", str(frames / "f%05d.png")]
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src, "-c:v", "libx264", "-preset", "slow",
                        "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src, "-vf",
                        "scale=1200:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=full[p];"
                        "[b][p]paletteuse=dither=none:diff_mode=rectangle", "-loop", "0", str(gif)], check=True)
    print(f"wrote {gif} ({gif.stat().st_size / 1e6:.2f} MB), {mp4} ({mp4.stat().st_size / 1e6:.2f} MB), {png}")
    print(f"{d['total']} s at {FPS} fps; seed {d['run']['seed']}, cycles {d['run']['a']} and {d['run']['b']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
