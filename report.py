"""report.py - a run's ledger as one shareable chart. Stdlib only, no model call.

`kl report --html FILE` (or `--svg FILE`) turns .keeploop/results.tsv, best.json,
holdout.json, hypotheses.jsonl and lessons.jsonl into one self-contained page:

- a summary line: N experiments, K kept, best a -> b, holdout if there is one;
- a chart: experiments on x, score on y. Kept = filled marker, discarded = hollow,
  crash = x on the floor. The running best is a line; the noise band around it
  (best +- noise_z * sigma, sigma measured at the baseline) is shaded, and its upper
  edge is the keep bar a change had to clear.

Also runs on any folder holding those files (a copied run, docs/proof/keeploop):

    python report.py STATE_DIR --html out.html [--noise-z 2.0] [--title TEXT]
"""

import argparse
import csv
import html
import json
import math
from pathlib import Path

W, H = 960, 440
PAD_L, PAD_R, PAD_T, PAD_B = 72, 28, 24, 52

STYLE = """
.kl-chart { --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #8a8984;
  --grid: #e6e5e1; --series: #2a78d6; --band: rgba(42, 120, 214, 0.13); --crash: #52514e; }
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .kl-chart, .kl-chart.kl-auto {
    --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #8f8e88;
    --grid: #33332f; --series: #3987e5; --band: rgba(57, 135, 229, 0.20); --crash: #c3c2b7; }
}
:root[data-theme="dark"] .kl-chart {
  --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #8f8e88;
  --grid: #33332f; --series: #3987e5; --band: rgba(57, 135, 229, 0.20); --crash: #c3c2b7; }
.kl-chart text { font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  fill: var(--ink-2); font-size: 13px; }
.kl-chart .bg { fill: var(--surface); }
.kl-chart .grid { stroke: var(--grid); stroke-width: 1; }
.kl-chart .axis { stroke: var(--muted); stroke-width: 1; }
.kl-chart .band { fill: var(--band); }
.kl-chart .bar { stroke: var(--series); stroke-width: 1.5; stroke-dasharray: 5 4; fill: none; }
.kl-chart .best { stroke: var(--ink); stroke-width: 2; fill: none; }
.kl-chart .kept { fill: var(--series); stroke: var(--surface); stroke-width: 2; }
.kl-chart .disc { fill: var(--surface); stroke: var(--series); stroke-width: 2; }
.kl-chart .crash { stroke: var(--crash); stroke-width: 2; }
.kl-chart .hit { fill: transparent; }
.kl-chart .hit:hover + .dot, .kl-chart .dot:hover { stroke-width: 3.5; }
.kl-chart .lbl { fill: var(--ink); font-weight: 600; }
"""


def read_run(state: Path) -> dict:
    """Everything the chart needs, from a state folder."""
    def js(name, default):
        p = state / name
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default

    def jsonl(name):
        p = state / name
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] \
            if p.is_file() else []
    with (state / "results.tsv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return {"rows": rows, "best": js("best.json", {}), "holdout": js("holdout.json", None),
            "hyps": {int(h["cycle"]): h for h in jsonl("hypotheses.jsonl")},
            "lessons": jsonl("lessons.jsonl")}


def _f(x) -> float | None:
    try:
        return float(x) if x not in (None, "") else None
    except ValueError:
        return None


def summary(run: dict) -> str:
    rows = run["rows"]
    base = next((r for r in rows if int(r["cycle"]) == 0), None)
    cyc = [r for r in rows if int(r["cycle"]) >= 1]
    kept = sum(r["status"] == "keep" for r in cyc)
    best = _f(run["best"].get("metric"))
    parts = [f"{len(cyc)} experiments", f"{kept} kept"]
    if base and best is not None:
        b0 = float(base["metric"])
        parts.append(f"best {b0:.6f} -> {best:.6f} ({best - b0:+.6f})")
    if (s := _f(run["best"].get("sigma"))) is not None:
        parts.append(f"noise sigma {s:.6f}")
    h = run["holdout"]
    if h and "final" in h:
        parts.append(f"holdout {h['baseline']:.6f} -> {h['final']:.6f} ({h['final'] - h['baseline']:+.6f})")
    elif h:
        parts.append("holdout: final not scored yet")
    if run["lessons"]:
        parts.append(f"{len(run['lessons'])} lessons")
    return ", ".join(parts)


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    span = hi - lo or 1.0
    step = 10 ** math.floor(math.log10(span / n))
    for m in (1, 2, 2.5, 5, 10):
        if span / (step * m) <= n:
            step *= m
            break
    first = math.ceil(lo / step) * step
    return [round(first + i * step, 10) for i in range(int((hi - first) / step + 1e-9) + 1)]


def chart_svg(run: dict, noise_z: float = 2.0, title: str = "", auto_dark: bool = False) -> str:
    """The chart as one standalone SVG (its own <style>, light and dark)."""
    rows = sorted(run["rows"], key=lambda r: int(r["cycle"]))
    if not rows:
        raise ValueError("the ledger has no rows: run `kl begin` first")
    sigma = _f(run["best"].get("sigma")) or 0.0
    z = noise_z if noise_z > 0 else 2.0
    xs = [int(r["cycle"]) for r in rows]
    best_line = [(int(r["cycle"]), float(r["best_metric"])) for r in rows if _f(r["best_metric"]) is not None]
    pts = [(int(r["cycle"]), _f(r["metric"]), r) for r in rows if int(r["cycle"]) >= 1]
    vals = [v for _, v, _ in pts if v is not None] + [b for _, b in best_line]
    lo, hi = min(vals + [b - z * sigma for _, b in best_line]), max(vals + [b + z * sigma for _, b in best_line])
    pad = (hi - lo) * 0.08 or 0.01
    lo, hi = lo - pad, hi + pad
    x0, x1 = min(xs), max(max(xs), 1)
    pw, ph = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    def X(c):
        return PAD_L + (c - x0) / (x1 - x0 or 1) * pw

    def Y(v):
        return PAD_T + (hi - v) / (hi - lo) * ph
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'class="kl-chart{" kl-auto" if auto_dark else ""}" role="img" '
         f'aria-label="{html.escape(title or "keeploop run")}: {html.escape(summary(run))}">',
         f"<style>{STYLE}</style>", f'<rect class="bg" width="{W}" height="{H}" rx="8"/>']
    for t in _ticks(lo, hi):
        o.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"/>')
        o.append(f'<text x="{PAD_L - 10}" y="{Y(t) + 4:.1f}" text-anchor="end">{t:.3f}</text>')
    for t in _ticks(x0, x1, 10):
        if float(t).is_integer():
            o.append(f'<text x="{X(t):.1f}" y="{H - PAD_B + 20}" text-anchor="middle">{int(t)}</text>')
    o.append(f'<line class="axis" x1="{PAD_L}" x2="{W - PAD_R}" y1="{H - PAD_B}" y2="{H - PAD_B}"/>')
    o.append(f'<text x="{PAD_L + pw / 2:.1f}" y="{H - 10}" text-anchor="middle">experiment (cycle; 0 = baseline)</text>')
    o.append(f'<text transform="translate(18 {PAD_T + ph / 2:.1f}) rotate(-90)" text-anchor="middle">score</text>')
    # the running best as a step line, with its noise band
    steps = []
    for i, (c, b) in enumerate(best_line):
        nxt = best_line[i + 1][0] if i + 1 < len(best_line) else c
        steps.append((c, nxt, b))
    if sigma > 0:
        up = " ".join(f"{X(a):.1f},{Y(b + z * sigma):.1f} {X(e):.1f},{Y(b + z * sigma):.1f}" for a, e, b in steps)
        dn = " ".join(f"{X(e):.1f},{Y(b - z * sigma):.1f} {X(a):.1f},{Y(b - z * sigma):.1f}" for a, e, b in reversed(steps))
        o.append(f'<polygon class="band" points="{up} {dn}"><title>noise band: best ± {z:g}σ '
                 f'(sigma {sigma:.6f})</title></polygon>')
        if noise_z > 0:
            o.append(f'<polyline class="bar" points="{up}"><title>keep bar: best + {noise_z:g} sigma</title></polyline>')
    o.append('<polyline class="best" points="' + " ".join(
        f"{X(a):.1f},{Y(b):.1f} {X(e):.1f},{Y(b):.1f}" for a, e, b in steps) + '"/>')
    for c, v, r in pts:
        h = run["hyps"].get(c, {})
        tip = html.escape(f"cycle {c}: {r['status']}" + (f", score {v:.6f}" if v is not None else "")
                          + f", best {float(r['best_metric']):.6f}"
                          + (f"\n{h['hypothesis']}" if h.get("hypothesis") else ""))
        if v is None:
            y = H - PAD_B - 8
            o.append(f'<g><title>{tip}</title><path class="crash" d="M{X(c) - 5:.1f},{y - 5} l10,10 m0,-10 l-10,10"/></g>')
            continue
        cls = "kept" if r["status"] == "keep" else "disc"
        o.append(f'<g><title>{tip}</title><circle class="hit" cx="{X(c):.1f}" cy="{Y(v):.1f}" r="12"/>'
                 f'<circle class="dot {cls}" cx="{X(c):.1f}" cy="{Y(v):.1f}" r="{6 if cls == "kept" else 5}"/></g>')
    # legend, one row, top left inside the plot
    lx, ly = PAD_L + 14, PAD_T + 16
    items = [("kept", "kept"), ("disc", "discarded"), (None, "running best")]
    if sigma > 0:
        items.append(("band", f"noise band ±{z:g}σ" + (" (top = keep bar)" if noise_z > 0 else "")))
    for cls, label in items:
        if cls in ("kept", "disc"):
            o.append(f'<circle class="{cls}" cx="{lx}" cy="{ly}" r="5.5"/>')
        elif cls == "band":
            o.append(f'<rect class="band" x="{lx - 7}" y="{ly - 7}" width="14" height="14" rx="2"/>')
        else:
            o.append(f'<line class="best" x1="{lx - 8}" x2="{lx + 8}" y1="{ly}" y2="{ly}"/>')
        o.append(f'<text x="{lx + 12}" y="{ly + 4.5}">{html.escape(label)}</text>')
        lx += 26 + 7.2 * len(label)
    o.append("</svg>")
    return "\n".join(o)


def table_rows(run: dict) -> str:
    out = []
    for r in sorted(run["rows"], key=lambda r: int(r["cycle"])):
        h = run["hyps"].get(int(r["cycle"]), {})
        out.append("<tr>" + "".join(f"<td>{html.escape(str(x))}</td>" for x in (
            r["cycle"], r["status"], r["metric"], r["best_metric"],
            h.get("hypothesis") or r["description"][:120])) + "</tr>")
    return "\n".join(out)


def html_page(run: dict, noise_z: float = 2.0, title: str = "keeploop run") -> str:
    s = html.escape(summary(run))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ --page: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --line: #e6e5e1; color-scheme: light; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --page: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --line: #33332f; color-scheme: dark; }} }}
:root[data-theme="dark"] {{ --page: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --line: #33332f; color-scheme: dark; }}
body {{ margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 1000px; margin: 0 auto; padding: 24px 16px 48px; }}
h1 {{ font-size: 22px; margin: 0 0 4px; }}
.sum {{ color: var(--ink-2); margin: 0 0 16px; font-variant-numeric: tabular-nums; }}
svg {{ width: 100%; height: auto; display: block; }}
details {{ margin-top: 16px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; font-variant-numeric: tabular-nums; }}
td, th {{ text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }}
.foot {{ color: var(--ink-2); font-size: 13px; margin-top: 16px; }}
</style></head>
<body><main>
<h1>{html.escape(title)}</h1>
<p class="sum">{s}</p>
{chart_svg(run, noise_z, title)}
<details><summary>Every experiment (table)</summary>
<table><thead><tr><th>cycle</th><th>status</th><th>score</th><th>best after</th><th>hypothesis</th></tr></thead>
<tbody>
{table_rows(run)}
</tbody></table></details>
<p class="foot">Made by <code>kl report --html</code> from the run's ledger (.keeploop/results.tsv),
no model call. keeploop keeps a change only when it beats the best by more than the
evaluation's own measured noise.</p>
</main></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("state", type=Path, help="a folder with results.tsv (e.g. .keeploop)")
    ap.add_argument("--html", type=Path)
    ap.add_argument("--svg", type=Path)
    ap.add_argument("--noise-z", type=float, default=2.0, help="the run's loop.noise_z (0 = naive)")
    ap.add_argument("--title", default="keeploop run")
    a = ap.parse_args(argv)
    run = read_run(a.state)
    print(summary(run))
    if a.html:
        a.html.write_text(html_page(run, a.noise_z, a.title), encoding="utf-8")
        print(f"wrote {a.html}")
    if a.svg:
        a.svg.write_text(chart_svg(run, a.noise_z, a.title, auto_dark=True), encoding="utf-8")
        print(f"wrote {a.svg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
