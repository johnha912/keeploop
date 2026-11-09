"""Render keeploop's two animations from the committed run files. Build-time only.

    python tools/render_figure.py [--only readme|talk] [--out docs/assets]

Not a keeploop dependency: needs Node with Playwright's Chromium (require('playwright')),
ffmpeg, and Pillow (the seamless-loop check).

- readme: tools/figure/readme.html -> keeploop-gate.gif (1280x620, loops) + .png. "The
  keep gate": one number line; three real changes from the seed-2 keeploop run drop onto
  it. Cycle 7 lands inside the noise band and is reset; cycle 8 clears the bar on the
  first run and on its re-run and is committed, which moves the bar; a later cycle then
  scores more than cycle 8 did and is still reset. That third cycle is the first one that
  beats cycle 8's score, lands inside the new band and had no true gain, so the README's
  "a gain inside the noise is not a gain" stays true of what it shows.
- talk: tools/figure/talk.html -> keeploop-talk.mp4 (1920x1080, H.264, for X) + .png. An
  eight-slide talk: title, same code / different score (a measured noise sample), keep-if-
  better keeps luck (the seed-2 naive and keeploop runs with their true effects), the
  commit law, the 25-seed numbers, the price, the fast path, the end card.

Every number either page shows is read here from committed files, never typed into a
template:
- docs/proof/proof.json (the sweep, the summary, each cycle's true effect);
- docs/assets/demo-run/keeploop/ (seed 2, re-run by tools/render_demo.py, which checks it
  against proof.json): stdout.txt for cycle 8's first score and re-run, best.json for sigma;
- docs/assets/demo-run/noise-sample.json, written here: examples/noisy-eval/evaluate.py
  run 10 times on its initial config with KEEPLOOP_DEMO_SEED=2 (the same draws every time).
"""

import argparse
import json
import os
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

DRIVER = r"""
const { chromium } = require('playwright');
(async () => {
  const [html, out, fps, total, w, h] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: +w, height: +h }, deviceScaleFactor: 1 });
  await p.goto('file://' + html);
  // warm-up: walk the whole timeline once, so every lazily loaded font is in before
  // frame 0 (otherwise frame 0 and the last frame differ and the loop jumps)
  for (let t = 0; t <= +total; t += 0.5) {
    await p.evaluate(t => window.render(t), t);
    await p.screenshot({ path: `${out}/warmup.png` });
  }
  await p.evaluate(() => document.fonts.ready);
  const n = Math.round(+total * +fps);
  for (let i = 0; i <= n; i++) {
    await p.evaluate(t => window.render(t), i / +fps);
    await p.screenshot({ path: `${out}/f${String(i).padStart(5, '0')}.png` });
  }
  await b.close();
})();
"""
EXAMPLE = REPO / "examples" / "noisy-eval"
RUN_DIR = REPO / "docs" / "assets" / "demo-run"
TALK_SECONDS = 4.2 + 6.2 + 8.0 + 7.0 + 6.0 + 6.0 + 5.6 + 4.8  # talk.html's DUR


def noise_sample(n: int = 10, seed: str = "2") -> list[float]:
    """evaluate.py on the example's initial config, n times, reproducible draws."""
    out = []
    with tempfile.TemporaryDirectory(prefix="kl-noise-") as d:
        ws = Path(d) / "ws"
        ws.mkdir()
        shutil.copyfile(EXAMPLE / "config.json", ws / "config.json")
        env = {**os.environ, "KEEPLOOP_DEMO_SEED": seed, "KEEPLOOP_DEMO_STATE": str(Path(d) / "state.json"),
               "PYTHONDONTWRITEBYTECODE": "1"}
        for _ in range(n):
            p = subprocess.run([sys.executable, str(EXAMPLE / "evaluate.py"), str(ws)], env=env,
                               capture_output=True, text=True, check=True)
            out.append(float(p.stdout.strip().splitlines()[-1]))
    return out


def label(change: dict) -> str:
    return ", ".join(f"{k} → {json.dumps(v)}" for k, v in change.items())


def data(write: bool = False) -> dict:
    from prepare import __version__
    proof = json.loads((REPO / "docs" / "proof" / "proof.json").read_text(encoding="utf-8"))
    seed, a, b = render_demo.select(proof)
    by = {(r["seed"], r["mode"]): r for r in proof["sweep"]}
    keep, naive = by[seed, "keeploop"], by[seed, "naive"]
    sigma = json.loads((RUN_DIR / "keeploop" / "best.json").read_text(encoding="utf-8"))["sigma"]
    _, cyc, _ = render_demo.blocks((RUN_DIR / "keeploop" / "stdout.txt").read_text(encoding="utf-8"))
    first = float(re.search(r"evaluate\s+(\d\.\d+)", "\n".join(cyc[b])).group(1))
    rerun = float(re.search(r"re-run (\d\.\d+)", "\n".join(cyc[b])).group(1))
    c = {x["cycle"]: x for x in keep["cycles"]}
    new_best = c[b]["metric"]
    third = next(x for x in keep["cycles"] if x["cycle"] > b and x["status"] == "discard"
                 and x["metric"] > first and x["metric"] <= new_best + 2 * sigma and x["true_effect"] <= 0)
    beats = [
        {"cycle": a, "change": label(c[a]["set"]), "score": c[a]["metric"], "rerun": None, "verdict": "discard",
         "best": c[a]["best_before"], "score_label": f"scored {c[a]['metric']:.3f}",
         "say1": f"Cycle {a} beats the best by +{c[a]['metric'] - c[a]['best_before']:.3f}.",
         "say2": "That is inside the noise. Reset."},
        {"cycle": b, "change": label(c[b]["set"]), "score": first, "rerun": rerun, "verdict": "keep",
         "best": c[a]["best_before"], "score_new_best": new_best, "score_label": f"scored {first:.3f}",
         "say1": f"Cycle {b} clears best + 2σ, then again on a re-run.",
         "say2": "Committed. The bar moves up with the best."},
        {"cycle": third["cycle"], "change": label(third["set"]), "score": third["metric"], "rerun": None,
         "verdict": "discard", "best": new_best, "score_label": f"scored {third['metric']:.3f}",
         "say1": f"Cycle {third['cycle']} scores {third['metric']:.3f}, more than cycle {b} did.",
         "say2": "Inside the new band. Reset."},
    ]
    t, starts = 0.9, []
    for bt in beats:
        starts.append(round(t, 3))
        t += 4.6 if bt["rerun"] is not None else 3.9
    scores = [x["score"] for x in beats] + [rerun, c[a]["best_before"], new_best + 2 * sigma]
    seeds = sorted({r["seed"] for r in proof["sweep"]})
    lower = sum(by[s, "keeploop"]["holdout_gain"] < by[s, "naive"]["holdout_gain"] for s in seeds)
    noise = noise_sample()
    if write:
        (RUN_DIR / "noise-sample.json").write_text(json.dumps({
            "what": "examples/noisy-eval/evaluate.py on its initial config.json, 10 calls, KEEPLOOP_DEMO_SEED=2",
            "scores": noise}, indent=2) + "\n", encoding="utf-8")

    def slim(cycles):
        return [{k: x[k] for k in ("cycle", "status", "true_effect")} for x in cycles]
    return {
        "version": __version__,
        "run": {"seed": seed, "sigma": sigma},
        "readme": {"beats": beats, "lo": round(min(scores) - 0.012, 3), "hi": round(max(scores) + 0.008, 3),
                   "idle": ["Keep only what beats the noise.", ""],
                   "timeline": {"beats": starts, "rewind": round(t, 3)}, "total": round(t + 1.2, 3)},
        "talk": {"noise": noise, "naive": slim(naive["cycles"]), "keep": slim(keep["cycles"])},
        "p": {"n": proof["summary"]["naive"], "k": proof["summary"]["keeploop"], "lower": lower, "seeds": len(seeds)},
    }


def frames_of(page: str, d: dict, size: tuple[int, int], fps: int, total: float, tmp: Path) -> Path:
    html = (REPO / "tools" / "figure" / page).read_text(encoding="utf-8").replace("__DATA__", json.dumps(d))
    (tmp / page).write_text(html, encoding="utf-8")
    (tmp / "driver.js").write_text(DRIVER, encoding="utf-8")
    frames = tmp / "frames"
    frames.mkdir()
    subprocess.run(["node", str(tmp / "driver.js"), str(tmp / page), str(frames), str(fps), str(total),
                    str(size[0]), str(size[1])], check=True)
    (frames / "warmup.png").unlink()
    return frames


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", choices=["readme", "talk"])
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "assets")
    a = ap.parse_args(argv)
    for tool in ("node", "ffmpeg"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} not found (build-time only)")
    from PIL import Image, ImageChops  # build-time only
    d = data(write=True)
    a.out.mkdir(parents=True, exist_ok=True)
    if a.only in (None, "readme"):
        with tempfile.TemporaryDirectory(prefix="kl-fig-") as tmp:
            frames = frames_of("readme.html", d, (1280, 620), 15, d["readme"]["total"], Path(tmp))
            last = sorted(frames.glob("f*.png"))[-1]
            if ImageChops.difference(Image.open(frames / "f00000.png").convert("RGB"),
                                     Image.open(last).convert("RGB")).getbbox():
                raise SystemExit("readme: the first and last frames differ: the loop would jump")
            gif = a.out / "keeploop-gate.gif"
            shutil.copyfile(frames / "f00000.png", a.out / "keeploop-gate.png")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "15", "-i", str(frames / "f%05d.png"),
                            "-vf", "split[a][b];[a]palettegen=max_colors=64:stats_mode=full[p];"
                            "[b][p]paletteuse=dither=none:diff_mode=rectangle", "-loop", "0", str(gif)], check=True)
            print(f"wrote {gif} ({gif.stat().st_size / 1e6:.2f} MB, {d['readme']['total']} s)")
    if a.only in (None, "talk"):
        with tempfile.TemporaryDirectory(prefix="kl-talk-") as tmp:
            frames = frames_of("talk.html", d, (1920, 1080), 30, TALK_SECONDS, Path(tmp))
            mp4 = a.out / "keeploop-talk.mp4"
            shutil.copyfile(frames / "f00075.png", a.out / "keeploop-talk.png")  # the title, at 2.5 s
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "30", "-i", str(frames / "f%05d.png"),
                            "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(mp4)], check=True)
            print(f"wrote {mp4} ({mp4.stat().st_size / 1e6:.2f} MB, {TALK_SECONDS} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
