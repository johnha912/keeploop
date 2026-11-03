"""Draws run/score-by-cycle.png from run/results.tsv, run/holdout.json and run/posthoc.json only.
Usage: python chart.py   (run from anywhere; paths are relative to this file)"""
import csv, json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
ACCENT, GREY, DARK, LIGHT = "#1f493d", "#9a9a9a", "#444444", "#cfcfcf"
SIGMA = 0.004714          # from run.log: "sigma = 0.004714 (3 runs)"
THRESH = 0.01             # keep_threshold in team.yaml

with open(HERE / "results.tsv", encoding="utf-8", newline="") as fh:
    rows = [(int(r["cycle"]), float(r["metric"]), float(r["best_metric"]), r["status"])
            for r in csv.DictReader(fh, delimiter="\t")]
rows.sort()
hold = json.loads((HERE / "holdout.json").read_text(encoding="utf-8"))
post = json.loads((HERE / "posthoc.json").read_text(encoding="utf-8"))["scores"]
c4_dev = [s["score"] for s in post if s["prompt"] == "cycle4_candidate" and s["split"] == "dev"]
assert c4_dev, "posthoc.json has no cycle4_candidate dev scores"

cyc = [r[0] for r in rows]
best = [r[2] for r in rows]
bar = {c: best[i - 1] + max(best[i - 1] * THRESH, 2 * SIGMA) for i, c in enumerate(cyc) if i}  # bar vs best before the cycle

plt.rcParams.update({"font.family": "Segoe UI", "font.size": 15})
fig = plt.figure(figsize=(16, 9), dpi=100)
ax = fig.add_axes([0.06, 0.15, 0.62, 0.64])
side = fig.add_axes([0.76, 0.15, 0.20, 0.64])

ax.step(cyc, best, where="post", color=ACCENT, lw=3, zorder=2)
ax.step([cyc[0]] + cyc[1:], [bar.get(c, best[0]) for c in cyc], where="post", color=DARK, lw=1.5, ls="--", zorder=1)
for c, m, b, s in rows:
    if c == 0:
        ax.scatter(c, m, s=110, facecolor="white", edgecolor=DARK, lw=2, zorder=3)
    elif s == "keep":
        ax.scatter(c, m, s=170, color=ACCENT, zorder=3)
    else:
        ax.scatter(c, m, s=110, color=GREY, zorder=3)
    off = {1: (-24, 8), 3: (0, -26), 5: (0, -26), 7: (12, -5)}.get(c, (0, 14))
    ax.annotate(f"{m:.3f}", (c, m), textcoords="offset points", xytext=off,
                ha="left" if c == 7 else "center", va="center" if c == 7 else "baseline", fontsize=13, color=ACCENT if s == "keep" and c else DARK)
c4 = next(r for r in rows if r[0] == 4)
ax.annotate("cycle 4: 0.915, approved,\nnot confirmed on re-run\n(re-measured after the run: " + ", ".join(f"{s:.3f}" for s in c4_dev) + ")",
            (4, c4[1]), xytext=(4.6, 0.927),
            fontsize=15, color=DARK, fontweight="bold", arrowprops=dict(arrowstyle="-", color=DARK, lw=1))
ax.text(8.15, best[-1] - 0.001, "best so far", color=ACCENT, fontsize=14, va="top", ha="right")
ax.text(8.15, bar[8] + 0.001, "keep bar (best + 2 sigma or 1%)", color=DARK, fontsize=14, va="bottom", ha="right")
ax.set_xlim(-0.4, 8.4)
ax.set_ylim(0.85, 0.94)
ax.set_xticks(cyc)
ax.set_xlabel("cycle (0 = baseline)", color=DARK)
ax.set_ylabel("dev accuracy", color=DARK)
ax.text(0.2, 0.855, "green = kept, grey = discarded", fontsize=13, color=DARK)

side.plot([0, 1], [hold["eval_baseline"], hold["eval_final"]], color=GREY, lw=3, marker="o", ms=10)
side.plot([0, 1], [hold["baseline"], hold["final"]], color=ACCENT, lw=3, marker="o", ms=10)
for y, t, col, ha, dx in [(hold["eval_baseline"], f"{hold['eval_baseline']:.3f}", DARK, "right", -0.06),
                          (hold["eval_final"], f"{hold['eval_final']:.3f}", DARK, "left", 0.09),
                          (hold["baseline"], f"{hold['baseline']:.3f}", ACCENT, "right", -0.06),
                          (hold["final"], f"{hold['final']:.3f}", ACCENT, "left", 0.09)]:
    side.text(0 if dx < 0 else 1, y, t, ha=ha, va="center", color=col, fontsize=14,
              transform=side.transData).set_x((0 if dx < 0 else 1) + dx)
side.text(0.1, hold["eval_final"] + 0.004, "dev (what the loop saw)",
          color=DARK, ha="center", fontsize=14)
side.text(0.5, hold["baseline"] + (hold["final"] - hold["baseline"]) / 2 - 0.02, "holdout (unseen)",
          color=ACCENT, ha="center", fontsize=14, fontweight="bold")
side.set_xlim(-0.5, 1.6)
side.set_ylim(0.82, 0.92)
side.set_xticks([0, 1], ["baseline", "final"])
side.set_yticks([])
side.set_title(f"Holdout gain +{hold['final'] - hold['baseline']:.3f}\nvs dev +{hold['eval_final'] - hold['eval_baseline']:.3f}",
               fontsize=15, color=DARK, loc="left")

for a in (ax, side):
    for s in ("top", "right"):
        a.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        a.spines[s].set_color(LIGHT)
    a.tick_params(colors=DARK, length=0)
side.spines["left"].set_visible(False)

fig.text(0.06, 0.93, "Two prompt changes kept; a 0.915 that did not confirm was refused", fontsize=27, fontweight="bold", color=ACCENT)
fig.text(0.06, 0.875, "Prompt-optimization example, 8 cycles: 6 of 8 candidates discarded; holdout rose too, by less (one run each, see README)",
         fontsize=16, color=DARK)
fig.text(0.06, 0.025, "Source: keeploop prompt-optimization example run (run/results.tsv, run/holdout.json; cycle 4 re-measures from run/posthoc.json);\n"
         "sigma 0.004714 from 3 baseline runs; 200 dev items, bar = best + max(1% of best, 2 sigma).", fontsize=11.5, color=GREY)
fig.savefig(HERE / "score-by-cycle.png", dpi=100, facecolor="white")
print("wrote", HERE / "score-by-cycle.png")
