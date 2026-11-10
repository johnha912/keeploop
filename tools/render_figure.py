"""Render keeploop's animations from committed files. Build-time only.

    python tools/render_figure.py [--only hero|readme|x] [--out docs/assets]

Not a keeploop dependency: needs Node with Playwright's Chromium (require('playwright')),
ffmpeg, and Pillow (the seamless-loop check). Every page uses tools/figure/kl.css, the
light design system: your AI as a team, each role in its own colour.

- hero: tools/figure/hero.html -> keeploop-team.gif (1280x720, loops) + .png, the README
  hero. You and the CEO (your AI): it asks the first-time questions of AGENTS.md, staffs
  the team (Analyst on a cheap model, Engineer on your main model, Auditor on the
  strongest), and a cycle runs in two commands. The session lines are real output of
  `kl next` / `kl try` on the offline demo, re-run here (docs/assets/demo-run/fastpath.txt);
  the speed strip reads docs/proof/bench-latency-{default,fast}.json.
- readme: tools/figure/readme.html -> keeploop-gate.gif (1280x620) + .png, "the keep
  gate", shown in the README's "Why trust the keeps": three real changes from the seed-2
  keeploop run land on one number line; the third is chosen by rule (a later reset that
  beats cycle 8's score inside the new band with no true gain).
- x: tools/figure/x.html -> keeploop-x.mp4 (1920x1080, H.264) + .png, the video for X:
  give your AI a team, it asks first (the illustrative lite/EXAMPLE.md interview), it
  staffs the team, two commands a cycle (the real fast-path output), it keeps only what
  clears the noise (docs/proof/proof.json, with the price), fewer calls and tokens (the
  benches), where it works.

No number is typed into a template: every one is read here from those files.
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
  // no partial raster: otherwise Chromium repaints a few anti-aliased edge pixels a
  // couple of frames after a change, and a still scene shows a flicker
  const b = await chromium.launch({ args: ['--disable-partial-raster'] });
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


CARD = """HYPOTHESIS: {h}
ALTERNATIVES: the gain is noise; the evaluation is deterministic, so a re-run tells them apart.
CHANGE: {c}
EXPECT: the metric rises.
REJECT IF: the metric does not beat the keep bar.
MISSING: none
"""


def fastpath_lines() -> list[str]:
    """Two real `kl try` cycles on the offline demo (one kept, one discarded), the
    commands and their output, written to docs/assets/demo-run/fastpath.txt."""
    out = []
    with tempfile.TemporaryDirectory(prefix="kl-fast-") as d:
        proj, card = Path(d) / "demo", Path(d) / "card.md"
        kl = [sys.executable, str(REPO / "kl.py"), "--root", str(proj)]
        run = lambda *a: subprocess.run([*kl, *a], capture_output=True, text=True, encoding="utf-8")  # noqa: E731
        subprocess.run([sys.executable, str(REPO / "kl.py"), "init", str(proj)], capture_output=True, check=True)
        run("begin")
        for h, c, key, val in (("A learning rate near 0.03 scores higher than 0.01.",
                                "set learning_rate to 0.03 in config.json.", "learning_rate", 0.03),
                               ("The sgd optimizer scores higher than adam.", "set optimizer to sgd.",
                                "optimizer", "sgd")):
            out.append("$ kl next")
            run("next")
            card.write_text(CARD.format(h=h, c=c), encoding="utf-8")
            cfg_path = proj / ".keeploop" / "workspace" / "config.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg[key] = val
            cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            out.append("$ kl try card.md")
            out += run("try", str(card)).stdout.strip().splitlines()
    (RUN_DIR / "fastpath.txt").write_text(
        "# two real `kl try` cycles on the offline demo, written by tools/render_figure.py\n"
        + "\n".join(out) + "\n", encoding="utf-8")
    return out


def bench(name: str) -> dict:
    return json.loads((REPO / "docs" / "proof" / f"bench-{name}.json").read_text(encoding="utf-8"))


def hero_data() -> dict:
    lines = fastpath_lines()
    kept = next(x for x in lines if x.startswith("KEPT"))
    metric = next(x for x in lines if "does not beat the bar" in x)
    dropped = next(x for x in lines if x.startswith("discarded"))
    slow, fast = bench("latency-default"), bench("latency-fast")
    tok = 1 - fast["tokens_per_cycle_median"] / slow["tokens_per_cycle_median"]
    wall = 1 - fast["wall_s_per_cycle_median"] / slow["wall_s_per_cycle_median"]
    calls = lambda b: sum(b["calls_per_cycle_median"].values())  # noqa: E731
    # Fig. 1's one motion: a glow steps through the stages, then the whole board rests.
    # Every hold is at least 1.2 s; the first and last frames are the resting board.
    lead, rest = 0.5, 2.0
    steps = [["analyst", 1.2], ["engineer", 1.2], ["evaluate", 1.2], ["gate", 1.6], ["commit", 1.6]]
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
    log = ["<b>$ kl try card.md</b> · " + esc(kept), "<b>$ kl try card.md</b> · " + esc(dropped)]
    assert "does not beat the bar" in metric  # the discarded line is the gate's verdict
    return {
        # the CEO's first-time questions (AGENTS.md: what "better" means, how to measure
        # it, what score is good enough, what a wrong change would cost), asked in one message
        "questions": ["What should get better, in your words?", "How do we measure it?",
                      "What score is good enough?", "What would a wrong change cost you?"],
        "headline": "With a CEO beside you.",
        "log": log,  # two real cycles of the fast path: one kept, one discarded
        "ceo_note": f"cycle {len(log) + 1} · 2 commands each",
        "stats": [
            {"x": 40, "html": "<b>2</b> commands a cycle"},
            {"x": 262, "html": f"profile: fast · <b>−{tok:.0%}</b> tokens"},
            {"x": 560, "html": f"<b>−{wall:.0%}</b> time per cycle"},
            {"x": 800, "html": f"AI calls <b>{calls(slow):.1f} → {calls(fast):.1f}</b> per cycle"},
        ],
        "measured": {"tokens": [slow["tokens_per_cycle_median"], fast["tokens_per_cycle_median"]],
                     "wall": [slow["wall_s_per_cycle_median"], fast["wall_s_per_cycle_median"]]},
        "lead": lead, "steps": steps, "rest": rest,
        "total": round(lead + sum(s for _, s in steps) + rest, 2),
    }


def x_data(d: dict) -> dict:
    """The X video: the lite example's interview and team (lite/EXAMPLE.md, illustrative),
    the real fast-path run, the proof summary and the measured benches."""
    import html as H
    ex = (REPO / "lite" / "EXAMPLE.md").read_text(encoding="utf-8")
    msgs = re.findall(r"^\*\*(AI|Mai):\*\* (.+?)(?=\n\n|\n```)", ex, re.M | re.S)[:4]
    chat = [{"who": w, "text": H.escape(" ".join(s.split()))} for w, s in msgs]
    team_line = " ".join(re.search(r"^Team: (.+?)\.\n", ex, re.M | re.S).group(1).split())
    chat_team = [{"name": n.strip(), "job": j, "kind": k} for (n, j), k in zip(
        re.findall(r"([^,(]+?) \((propose|make|check)\)", team_line), ("analyst", "engineer", "auditor"))]
    for m in chat_team:
        m["job"] = {"propose": "proposes the change", "make": "writes it", "check": "reads it like the buyer"}[m["job"]]
    code_team = [{"name": "Analyst", "job": "one hypothesis card", "kind": "analyst", "model": "cheap, fast model"},
                 {"name": "Engineer", "job": "one small change", "kind": "engineer", "model": "your main model"},
                 {"name": "Auditor", "job": "reads the real diff", "kind": "auditor", "model": "strongest model"}]
    lines = (RUN_DIR / "fastpath.txt").read_text(encoding="utf-8").splitlines()[1:]
    def term(s):
        s = H.escape(s)
        if s.startswith("$"):
            return f"<b>{s}</b>"
        if s.startswith("KEPT"):
            return f'<span class="k">{s}</span>'
        if s.startswith("discarded"):
            return f'<span class="r">{s}</span>'
        return s
    slow, fast = bench("latency-default"), bench("latency-fast")
    calls = lambda b: sum(b["calls_per_cycle_median"].values())  # noqa: E731
    pn, pk = d["p"]["n"], d["p"]["k"]
    return {
        "durations": [5.5, 8.0, 7.5, 8.5, 7.0, 7.0, 5.5, 5.0],
        "chat": chat, "chat_source": "illustrative transcript: lite/EXAMPLE.md (keeploop-lite, fast mode)",
        "teams": [chat_team, code_team],
        "term": [term(s) for s in lines if not s.startswith(("card ", "PASS"))][:8],
        "price": (f"The price: it also discards more real gains ({pk['discarded_true_gain_mean']:.2f} vs "
                  f"{pn['discarded_true_gain_mean']:.2f} per run) and ended lower on {d['p']['lower']} of "
                  f"{d['p']['seeds']} seeds. kl doctor measures the noise first."),
        "proof_source": f"same 20 proposals, same noise, {d['p']['seeds']} seeds: docs/proof/PROOF.md",
        "stats": [{"big": f"−{1 - fast['tokens_per_cycle_median'] / slow['tokens_per_cycle_median']:.0%}", "lab": "tokens per cycle"},
                  {"big": f"−{1 - fast['wall_s_per_cycle_median'] / slow['wall_s_per_cycle_median']:.0%}", "lab": "time per cycle"},
                  {"big": f"{calls(slow):.1f}→{calls(fast):.1f}", "lab": "AI calls per cycle"}],
        "bench_source": (f"offline demo, mock with {slow.get('latency', '')} s per call, median of {slow['reps']} reps: "
                         "docs/proof/bench-latency-*.json"),
    }


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
         "best": c[a]["best_before"], "score_label": f"scored {c[a]['metric']:.3f}"},
        {"cycle": b, "change": label(c[b]["set"]), "score": first, "rerun": rerun, "verdict": "keep",
         "best": c[a]["best_before"], "score_new_best": new_best, "score_label": f"scored {first:.3f}"},
        {"cycle": third["cycle"], "change": label(third["set"]), "score": third["metric"], "rerun": None,
         "verdict": "discard", "best": new_best, "score_label": f"scored {third['metric']:.3f}"},
    ]
    # Fig. 2: one settled scene per beat, joined by instant cuts; the bare figure opens
    # the loop and rests at its end (>= 2 s), so the first and last frames are the same.
    lead, rest = 1.0, 2.0
    t, scenes = lead, []
    for bt in beats:
        hold = 3.6 if bt["rerun"] is not None else 3.0  # the re-run scene has one more thing to read
        scenes.append([round(t, 3), round(t + hold, 3)])
        t += hold
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
                   "headline": "Keep only what beats the noise.",
                   "timeline": {"lead": lead, "scenes": scenes, "rest": rest}, "total": round(t + rest, 3)},
        "talk": {"noise": noise, "naive": slim(naive["cycles"]), "keep": slim(keep["cycles"])},
        "p": {"n": proof["summary"]["naive"], "k": proof["summary"]["keeploop"], "lower": lower, "seeds": len(seeds)},
    }


def loops(first: Path, last: Path) -> bool:
    """True when the last frame looks the same as the first: at most 200 pixels (of about
    a million) may differ, by at most 16 levels of 255 (anti-aliasing at element edges after
    an animation); a moved element or changed text, anything a viewer could see as a
    jump, fails."""
    from PIL import Image, ImageChops
    diff = ImageChops.difference(Image.open(first).convert("RGB"), Image.open(last).convert("RGB"))
    bad = [px for px in diff.get_flattened_data() if max(px) > 0]
    if bad:
        print(f"first vs last frame: {len(bad)} pixels differ, by up to {max(max(px) for px in bad)}; "
              f"box {diff.getbbox()}")
    return all(max(px) <= 2 for px in bad) or (len(bad) <= 200 and all(max(px) <= 16 for px in bad))


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
    ap.add_argument("--only", choices=["hero", "readme", "x"])
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "assets")
    a = ap.parse_args(argv)
    for tool in ("node", "ffmpeg"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} not found (build-time only)")
    from PIL import Image, ImageChops  # build-time only
    d = data(write=True)
    a.out.mkdir(parents=True, exist_ok=True)
    if a.only in (None, "hero"):
        d["hero"] = hero_data()
        with tempfile.TemporaryDirectory(prefix="kl-hero-") as tmp:
            shutil.copyfile(REPO / "tools" / "figure" / "kl.css", Path(tmp) / "kl.css")
            frames = frames_of("hero.html", d, (1280, 720), 15, d["hero"]["total"], Path(tmp))
            last = sorted(frames.glob("f*.png"))[-1]
            if not loops(frames / "f00000.png", last):
                raise SystemExit("hero: the first and last frames differ: the loop would jump")
            gif = a.out / "keeploop-team.gif"
            shutil.copyfile(frames / "f00000.png", a.out / "keeploop-team.png")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "15", "-i", str(frames / "f%05d.png"),
                            "-vf", "split[a][b];[a]palettegen=max_colors=96:stats_mode=full[p];"
                            "[b][p]paletteuse=dither=none:diff_mode=rectangle", "-loop", "0", str(gif)], check=True)
            print(f"wrote {gif} ({gif.stat().st_size / 1e6:.2f} MB, {d['hero']['total']} s)")
    if a.only in (None, "readme"):
        with tempfile.TemporaryDirectory(prefix="kl-fig-") as tmp:
            frames = frames_of("readme.html", d, (1280, 620), 15, d["readme"]["total"], Path(tmp))
            last = sorted(frames.glob("f*.png"))[-1]
            if not loops(frames / "f00000.png", last):
                raise SystemExit("readme: the first and last frames differ: the loop would jump")
            gif = a.out / "keeploop-gate.gif"
            shutil.copyfile(frames / "f00000.png", a.out / "keeploop-gate.png")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "15", "-i", str(frames / "f%05d.png"),
                            "-vf", "split[a][b];[a]palettegen=max_colors=64:stats_mode=full[p];"
                            "[b][p]paletteuse=dither=none:diff_mode=rectangle", "-loop", "0", str(gif)], check=True)
            print(f"wrote {gif} ({gif.stat().st_size / 1e6:.2f} MB, {d['readme']['total']} s)")
    if a.only in (None, "x"):
        d.setdefault("hero", hero_data())
        d["x"] = x_data(d)
        total = sum(d["x"]["durations"])
        with tempfile.TemporaryDirectory(prefix="kl-x-") as tmp:
            shutil.copyfile(REPO / "tools" / "figure" / "kl.css", Path(tmp) / "kl.css")
            frames = frames_of("x.html", d, (1920, 1080), 30, total, Path(tmp))
            mp4 = a.out / "keeploop-x.mp4"
            shutil.copyfile(frames / "f00090.png", a.out / "keeploop-x.png")  # the opening line, at 3 s
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "30", "-i", str(frames / "f%05d.png"),
                            "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(mp4)], check=True)
            print(f"wrote {mp4} ({mp4.stat().st_size / 1e6:.2f} MB, {total} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
