"""Render keeploop's two animated user guides. Build-time only.

    python tools/render_guides.py [--only chat|code] [--out docs/assets]
    python tools/render_guides.py --only chat --stills 3.1,9.5 --out /tmp/x   # PNGs at those times

Not a keeploop dependency: needs Node with Playwright's Chromium (require('playwright'))
and ffmpeg.

- chat: tools/figure/guide-chat.html -> keeploop-guide-chat.mp4 / .gif / .png.
  keeploop-lite in a chat app, six steps, illustrated with lite/EXAMPLE.md.
- code: tools/figure/guide-code.html -> keeploop-guide-code.mp4 / .gif / .png.
  keeploop with a coding AI, five steps, from README.md "Quick start", AGENTS.md and
  team.yaml.

Each page exposes window.render(t), a pure function of time, and window.TOTAL (seconds).
Before any frame is rendered, two checks run on the page:
- every element with data-src="FILE" (its data-quote, or else its text) must appear word
  for word in FILE (whitespace folded), so a quoted line or score cannot drift from the
  committed example;
- every `kl SUBCOMMAND` an element with class "kl" shows must be a subcommand of kl.py.
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
FIG = REPO / "tools" / "figure"
PAGES = {"chat": "guide-chat.html", "code": "guide-code.html"}
POSTER_AT = {"chat": 23.0, "code": 18.5}  # seconds: a busy, finished frame of a middle step

DRIVER = r"""
const { chromium } = require('playwright');
(async () => {
  const [html, out, fps, w, h, stills] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: +w, height: +h }, deviceScaleFactor: 1 });
  await p.goto('file://' + html);
  await p.evaluate(() => document.fonts.ready);
  const total = await p.evaluate(() => window.TOTAL);
  // the facts each page claims, for the Python side to check
  const facts = await p.evaluate(() => {
    const T = window.TOTAL, q = [], cmds = [];
    for (let t = 0; t < T; t += 0.1) {  // a typed line only shows its full text once typed
      window.render(t);
      document.querySelectorAll('[data-src]').forEach(e => q.push([e.dataset.src, e.dataset.quote || e.textContent]));
      document.querySelectorAll('.kl').forEach(e => cmds.push(e.dataset.full || e.textContent));
    }
    return { q, cmds };
  });
  require('fs').writeFileSync(`${out}/facts.json`, JSON.stringify({ total, ...facts }));
  // warm-up: walk the whole timeline once, so every lazily loaded font is in before frame 0
  for (let t = 0; t <= total; t += 0.5) {
    await p.evaluate(t => window.render(t), t);
    await p.screenshot({ path: `${out}/warmup.png` });
  }
  await p.evaluate(() => document.fonts.ready);
  if (stills) {
    for (const s of stills.split(',')) {
      await p.evaluate(t => window.render(t), +s);
      await p.screenshot({ path: `${out}/still-${(+s).toFixed(2)}.png` });
    }
  } else {
    const n = Math.round(total * +fps);
    for (let i = 0; i < n; i++) {
      await p.evaluate(t => window.render(t), i / +fps);
      await p.screenshot({ path: `${out}/f${String(i).padStart(5, '0')}.png` });
    }
  }
  await b.close();
})();
"""


def fold(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def kl_subcommands() -> set[str]:
    out = subprocess.run([sys.executable, str(REPO / "kl.py"), "--help"], capture_output=True, text=True,
                         check=True, cwd=REPO).stdout
    m = re.search(r"\{([a-z,\-]+)\}", out)
    return set(m.group(1).split(","))


def check(facts: dict, page: str) -> None:
    bad, seen = [], set()
    for src, text in facts["q"]:
        text = fold(text)
        if not text or (src, text) in seen:
            continue
        seen.add((src, text))
        body = fold((REPO / src).read_text(encoding="utf-8"))
        if text not in body:
            bad.append(f"{page}: not in {src}: {text!r}")
    subs = kl_subcommands()
    for cmd in {fold(c) for c in facts["cmds"]}:
        m = re.match(r"(?:\$\s*)?kl\s+([a-z\-]+)", cmd)
        if not m or m.group(1) not in subs:
            bad.append(f"{page}: not a kl subcommand: {cmd!r}")
    if bad:
        raise SystemExit("\n".join(bad))
    print(f"{page}: {len(seen)} quoted lines match their files; "
          f"{len({fold(c) for c in facts['cmds']})} kl commands exist")


def frames(name: str, tmp: Path, fps: int, stills: str = "") -> dict:
    (tmp / "driver.js").write_text(DRIVER, encoding="utf-8")
    subprocess.run(["node", str(tmp / "driver.js"), str(FIG / PAGES[name]), str(tmp), str(fps), "1920", "1080",
                    stills], check=True)
    (tmp / "warmup.png").unlink(missing_ok=True)
    facts = json.loads((tmp / "facts.json").read_text(encoding="utf-8"))
    check(facts, PAGES[name])
    return facts


def encode(name: str, tmp: Path, out: Path, fps: int, total: float) -> None:
    stem = f"keeploop-guide-{name}"
    mp4, gif, png = out / f"{stem}.mp4", out / f"{stem}.gif", out / f"{stem}.png"
    pat = str(tmp / "f%05d.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", pat,
                    "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(mp4)], check=True)
    poster = tmp / f"f{round(POSTER_AT[name] * fps):05d}.png"
    shutil.copyfile(poster, png)
    # the GIF: 1280 wide, 12 fps, one shared palette; the flat light design keeps it small
    for gfps, colors in ((12, 96), (10, 64), (8, 48)):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", pat,
                        "-vf", f"fps={gfps},scale=1280:-1:flags=lanczos,split[a][b];"
                        f"[a]palettegen=max_colors={colors}:stats_mode=full[p];"
                        "[b][p]paletteuse=dither=none:diff_mode=rectangle",
                        "-loop", "0", str(gif)], check=True)
        if gif.stat().st_size < 4e6:
            break
    for f in (mp4, gif, png):
        print(f"wrote {f.relative_to(REPO) if f.is_relative_to(REPO) else f} ({f.stat().st_size / 1e6:.2f} MB)")
    print(f"{stem}: {total:.1f} s, {fps} fps; GIF at {gfps} fps, {colors} colours")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", choices=sorted(PAGES))
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "assets")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--stills", default="", help="comma-separated times: write PNGs there instead of a video")
    a = ap.parse_args(argv)
    for tool in ("node", "ffmpeg"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} not found (build-time only)")
    a.out.mkdir(parents=True, exist_ok=True)
    for name in [a.only] if a.only else sorted(PAGES):
        with tempfile.TemporaryDirectory(prefix=f"kl-guide-{name}-") as d:
            tmp = Path(d)
            facts = frames(name, tmp, a.fps, a.stills)
            if a.stills:
                for p in sorted(tmp.glob("still-*.png")):
                    shutil.copyfile(p, a.out / f"{name}-{p.name}")
                print(f"wrote {len(a.stills.split(','))} stills of {name} to {a.out}")
            else:
                encode(name, tmp, a.out, a.fps, facts["total"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
