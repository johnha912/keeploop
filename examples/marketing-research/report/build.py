"""Build the Fieldnote Apparel report: charts/*.png, dashboard.html, report.pdf.

Run: python -X utf8 build.py [--no-pdf]
Needs: plotly, kaleido (PNG export) and Microsoft Edge (PDF). Every charted number is read from
../data/metrics.json; report.md supplies the titles and prose. The last step asserts that every
plotted value equals metrics.json and that the report's own claims match the data.
"""
import base64
import copy
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from datetime import date, timedelta
from pathlib import Path
from statistics import NormalDist
from string import Template

import plotly.graph_objects as go
import plotly.offline
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
EX = HERE.parent
CH = HERE / "charts"
PLOTLY_JS = plotly.offline.get_plotlyjs_version()
KATEX = "0.16.11"


def lp(p):
    """Windows MAX_PATH guard: long-path prefix for deep checkouts."""
    s = str(Path(p).resolve())
    return "\\\\?\\" + s if os.name == "nt" else s


def load():
    return json.load(open(EX / "data" / "metrics.json", encoding="utf8"))


D = load()
M = D["modules"]
CORE = D["meta"]["core_brands"]
WIN = "%s to %s" % (D["meta"]["window"][0],
                    (date.fromisoformat(D["meta"]["window"][1]) - timedelta(1)).isoformat())

INK, MUTE, GRID = "#2B2B2B", "#5C5750", "#E8E2D6"
DARK, MID, LIGHT = "#8D8079", "#B8B6B0", "#D8CAA9"
ACC, ACC_L = "#8F2323", "#F0DCD6"
GOOD, BAD = "#1F493D", "#C36728"   # good/bad pair: differ in hue and lightness
FONT = "Inter, Arial, Helvetica, sans-serif"
TITLE_FONT = "Georgia, serif"
REDDIT = "Reddit (general subreddits) via Arctic Shift"


# ---------------------------------------------------------------- helpers
def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / 2 / n) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / 4 / n / n) / d
    return round(100 * (c - h), 1), round(100 * (c + h), 1)


def ci_txt(m):
    return "%.1f%% (%.1f–%.1f)" % (m["pct"], m["ci95"][0], m["ci95"][1])


def err(ms):
    return dict(type="data", symmetric=False, array=[m["ci95"][1] - m["pct"] for m in ms],
                arrayminus=[m["pct"] - m["ci95"][0] for m in ms], color=INK, thickness=1.3, width=4)


def band(ms):
    """Interval shared by all of ms (max lower bound to min upper bound)."""
    return max(m["ci95"][0] for m in ms), min(m["ci95"][1] for m in ms)


def base_fig(fig, **kw):
    fig.update_layout(font=dict(family=FONT, size=14, color=INK), paper_bgcolor="white",
                      plot_bgcolor="white", showlegend=False,
                      hoverlabel=dict(font=dict(family=FONT, color=INK), bgcolor="white", bordercolor=MID),
                      **kw)
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=MID, ticks="outside", tickcolor=MID)
    fig.update_yaxes(zeroline=False, linecolor=MID, ticks="")
    return fig


def label(fig, x, y, text, xref="x", yref="y", **kw):
    kw.setdefault("font", dict(size=13, color=INK))
    fig.add_annotation(x=x, y=y, xref=xref, yref=yref, text=text, showarrow=False, **kw)


# Simple 24px line icons for the eight attributes, drawn for this report in the style of Lucide (ISC licence).
ATTR_ICON = {
    "price/value": '<circle cx="12" cy="12" r="9"/><path d="M14.5 9.2c-.4-.8-1.4-1.2-2.5-1.2-1.4 0-2.5.7-2.5 1.8s1 1.6 2.5 2 2.5.9 2.5 2-1.1 1.9-2.5 1.9c-1.2 0-2.2-.5-2.6-1.4M12 6.5V8M12 16v1.5"/>',
    "quality/durability": '<path d="M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z"/><path d="M9 12l2 2 4-4"/>',
    "fit/sizing": '<path d="M3 17L17 3l4 4L7 21z"/><path d="M7 13l2 2M10 10l2 2M13 7l2 2"/>',
    "style/trend": '<path d="M11 3l1.8 5.2L18 10l-5.2 1.8L11 17l-1.8-5.2L4 10l5.2-1.8z"/><path d="M19 16v5M16.5 18.5h5"/>',
    "sustainability/ethics": '<path d="M5 19c0-8 5-14 15-14 0 9-5 14-13 14"/><path d="M5 19c3-5 6-8 10-10"/>',
    "shipping/returns": '<path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M3 7l9 4 9-4M12 11v10"/>',
    "customer service": '<path d="M4 14v-2a8 8 0 0 1 16 0v2"/><rect x="3" y="14" width="4" height="6" rx="1.5"/><rect x="17" y="14" width="4" height="6" rx="1.5"/>',
    "store experience": '<path d="M4 9l1.5-5h13L20 9"/><path d="M4 9a2.7 2.7 0 0 0 5.3 0 2.7 2.7 0 0 0 5.4 0A2.7 2.7 0 0 0 20 9"/><path d="M5 12v8h14v-8"/>',
}


def icon_uri(name, color="#5C5750"):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%s" stroke-width="2" '
           'stroke-linecap="round" stroke-linejoin="round">%s</svg>' % (color, ATTR_ICON[name]))
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def panel_title(fig, text, xref, yref="paper"):
    fig.add_annotation(xref=xref + " domain", yref=yref, x=0, y=1, yshift=14, text=text,
                       showarrow=False, xanchor="left", yanchor="bottom", font=dict(size=13, color=MUTE))


def chart(fig, title, sub, h, hh, l, r, table, src, srcnote=REDDIT, t=0, b=40):
    return dict(fig=fig, title=title, sub=sub, h=h, hh=hh, l=l, r=r, table=table, src=src,
                srcnote=srcnote, t=t, b=b)


def footnote(c):
    return "Source: data/metrics.json, %s. %s; collection window %s." % (c["src"], c["srcnote"], WIN)


def render(c, png):
    fig = go.Figure(c["fig"])
    if png:
        sub = "<br>".join(textwrap.wrap(c["sub"], 118))
        tl = textwrap.wrap(c["title"], 66)
        top = 70 + 19 * (sub.count("<br>") + 1) + c["t"] + 27 * (len(tl) - 1)
        fig.update_layout(
            width=1100, height=c["h"], margin=dict(l=c["l"], r=c["r"], t=top, b=c["b"] + 56),
            title=dict(text="<b>%s</b><br><span style='font-family:Inter,Arial,sans-serif;font-weight:400;font-size:13px;color:%s'>%s</span>"
                       % ("<br>".join(tl), MUTE, sub), x=0, xref="container", xanchor="left", y=1,
                       yref="container", yanchor="top", pad=dict(t=24, l=12), font=dict(size=21, family=TITLE_FONT)))
        fig.add_annotation(xref="paper", yref="paper", x=0, y=0, xanchor="left", yanchor="top",
                           xshift=12 - c["l"], yshift=-(c["b"] + 24), showarrow=False,
                           text=footnote(c), font=dict(size=11, color=MUTE))
    else:
        fig.update_layout(height=c["hh"], margin=dict(l=10, r=c["r"], t=c["t"] + 16, b=c["b"]), autosize=True)
        fig.update_yaxes(automargin=True)
    return fig


# ---------------------------------------------------------------- report.md / brief.md parsing
def parse_report():
    txt = (EX / "report.md").read_text(encoding="utf8")
    out = dict(h1=re.search(r"^# (.+)$", txt, re.M).group(1), mods=[])
    secs = {}
    for part in re.split(r"^## ", txt, flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        secs[head.strip()] = body.strip()
    for head, body in secs.items():
        if head.startswith("Summary:"):
            paras = [p.strip() for p in body.split("\n\n") if p.strip()]
            out["sum_title"] = head[len("Summary: "):]
            out["sum_text"] = paras[0]
            out["target"] = [p for p in paras if p.startswith("Target segment:")][0]
        elif re.match(r"\d\. ", head):
            n, rest = re.match(r"(\d)\. (.+)", head).groups()
            kicker, _, title = rest.partition(": ")
            f = {k: re.search(r"^%s: (.+)$" % k, body, re.M).group(1)
                 for k in ("Question", "Decision", "So what", "Recommendation")}
            out["mods"].append(dict(n=int(n), kicker=kicker, title=title, bullets=re.findall(r"^- (.+)$", body, re.M),
                                    quotes=re.findall(r'^> "(.+)" \((.+?), (.+?)\)$', body, re.M),
                                    quote_rule=(re.search(r"^Quote rule: (.+)$", body, re.M) or [None, ""])[1], **f))
        elif head.startswith("Method"):
            paras = [p.strip() for p in body.split("\n\n") if p.strip()]
            out["method"] = paras[0]
            out["limits_intro"] = paras[1]
            out["limits"] = re.findall(r"^- (.+)$", body, re.M)
            out["next"] = [p for p in paras if p.startswith("Next step:")][0]
    return out


def parse_context():
    txt = (EX / "brief.md").read_text(encoding="utf8")
    sec = re.search(r"^## Market context.*?\n(.*?)^## ", txt, re.M | re.S).group(1)
    items = [" ".join(x.split("\n\n")[0].split()) for x in re.split(r"^- ", sec, flags=re.M)[1:]]
    out = []
    for it in items:
        body, _, cite = it.rpartition(" (")
        out.append((body.strip(), cite.rstrip(")")))
    return out


# ---------------------------------------------------------------- charts
def c1():
    t = M["top_of_mind"]
    fm, tm = t["first_mention"], t["total_mention"]
    names = sorted(fm, key=lambda b: (-fm[b]["pct"], b))
    lead = names[0]
    colors = [ACC if b == lead else DARK if b in CORE else LIGHT for b in names]
    ms = [fm[b] for b in names]
    fig = go.Figure(go.Bar(
        y=names, x=[m["pct"] for m in ms], orientation="h", marker_color=colors, width=0.62, error_x=err(ms),
        customdata=[[m["k"], m["base"], m["ci95"][0], m["ci95"][1], tm[b]["pct"]] for b, m in zip(names, ms)],
        hovertemplate="<b>%{y}</b><br>First named: %{x:.1f}% (95% CI %{customdata[2]:.1f} to %{customdata[3]:.1f})"
                      "<br>%{customdata[0]} of %{customdata[1]} replies<br>Named at all: %{customdata[4]:.1f}%<extra></extra>"))
    for b in names:
        if b in CORE:
            label(fig, fm[b]["ci95"][1], b, "<b>%.1f%%</b>" % fm[b]["pct"], xanchor="left", xshift=6)
    base_fig(fig, bargap=0.25)
    fig.update_yaxes(categoryorder="array", categoryarray=names, autorange="reversed", tickvals=names,
                     ticktext=["<b>%s</b>" % b if b in CORE else b for b in names])
    fig.update_xaxes(range=[0, max(m["ci95"][1] for m in ms) * 1.12], ticksuffix="%",
                     title=dict(text="Replies naming the brand first, % of replies naming any brand (95% CI)", font=dict(size=13, color=MUTE)))
    ths = t["threads_by_subreddit"]
    sub = ("n=%d replies that name a brand. %d of the %d threads are menswear (malefashionadvice), so this leans to "
           "menswear-friendly brands. Core set in bold; a proxy for salience, not measured awareness."
           % (t["replies_naming_a_brand"], ths["malefashionadvice"], t["threads_with_replies"]))
    tbl = (["Brand", "First named", "Named at all", "Replies (k of n)"],
           [[b, ci_txt(fm[b]), ci_txt(tm[b]), "%d of %d" % (fm[b]["k"], fm[b]["base"])] for b in names])
    return chart(fig, "First-mention share of brand-naming replies, by brand", sub, 800, 640, 130, 60, tbl,
                 "modules.top_of_mind")


def c2():
    pp = M["penetration_proxy"]["general_subreddits_only"]
    bb, n = pp["by_brand"], pp["base_authors"]
    names = sorted(CORE, key=lambda b: (-bb[b]["pct"], b))
    ms = [bb[b] for b in names]
    lo, hi = band(ms)
    fig = go.Figure(go.Scatter(
        y=names, x=[m["pct"] for m in ms], mode="markers", marker=dict(size=11, color=DARK), error_x=err(ms),
        customdata=[[m["k"], m["base"], m["ci95"][0], m["ci95"][1]] for m in ms],
        hovertemplate="<b>%{y}</b><br>%{x:.1f}% (95% CI %{customdata[2]:.1f} to %{customdata[3]:.1f})"
                      "<br>%{customdata[0]} of %{customdata[1]} authors<extra></extra>"))
    fig.add_vrect(x0=lo, x1=hi, fillcolor=ACC_L, line_width=0, layer="below")
    label(fig, (lo + hi) / 2, 1, "All five intervals overlap:<br>%.1f%% to %.1f%%" % (lo, hi), xref="x", yref="paper",
          yanchor="bottom", font=dict(size=13, color=ACC))
    for b, m in zip(names, ms):
        label(fig, m["ci95"][1], b, ci_txt(m), xanchor="left", xshift=8)
    base_fig(fig)
    fig.update_yaxes(categoryorder="array", categoryarray=names, autorange="reversed", tickvals=names)
    fig.update_xaxes(range=[0, 4.6], ticksuffix="%",
                     title=dict(text="Authors with an ownership or purchase phrase, % of brand-mentioning authors (95% CI)",
                                font=dict(size=13, color=MUTE)))
    sub = ("n=%d authors who mentioned any brand. A proxy: phrase matching, not confirmed buyers; "
           "the shaded band is the range every interval shares." % n)
    tbl = (["Brand", "Share (95% CI)", "Authors (k of n)"],
           [[b, ci_txt(bb[b]), "%d of %d" % (bb[b]["k"], bb[b]["base"])] for b in names])
    return chart(fig, "Penetration proxy: authors with an ownership or purchase phrase", sub, 460, 400, 110, 40, tbl,
                 "modules.penetration_proxy", t=26, b=60)


def c3():
    pf = M["profiling"]
    cov = pf["coverage_brand_mentioning_authors"]["age"]
    cova = pf["coverage_all_authors"]["age"]
    gen = pf["generation_of_brand_mentioning_authors"]
    gk = [k for k in gen if k.startswith("Gen Z")] + [k for k in gen if k.startswith("Millennial")]
    gm = [gen[k] for k in gk]
    n_age = gm[0]["base"]
    fig = make_subplots(rows=1, cols=2, column_widths=[0.42, 0.58], horizontal_spacing=0.2)
    cl = ["Brand-mentioning<br>authors (n=%d)" % cov["base"], "All authors<br>(n=%d)" % cova["base"]]
    cms = [cov, cova]
    fig.add_trace(go.Bar(y=cl, x=[m["pct"] for m in cms], orientation="h", width=0.5, marker_color=[ACC, MID],
                         error_x=err(cms), customdata=[[m["k"], m["base"], m["ci95"][0], m["ci95"][1]] for m in cms],
                         hovertemplate="<b>%{y}</b><br>%{x:.1f}% gave an age (95% CI %{customdata[2]:.1f} to "
                                       "%{customdata[3]:.1f})<br>%{customdata[0]} of %{customdata[1]}<extra></extra>"), 1, 1)
    for y, m in zip(cl, cms):
        label(fig, m["ci95"][1], y, ci_txt(m), "x", "y", xanchor="left", xshift=6)
    fig.add_trace(go.Bar(y=gk, x=[m["pct"] for m in gm], orientation="h", width=0.5, marker_color=DARK,
                         error_x=err(gm), customdata=[[m["k"], m["base"], m["ci95"][0], m["ci95"][1]] for m in gm],
                         hovertemplate="<b>%{y}</b><br>%{x:.1f}% (95% CI %{customdata[2]:.1f} to %{customdata[3]:.1f})"
                                       "<br>%{customdata[0]} of %{customdata[1]} authors<extra></extra>"), 1, 2)
    for y, m in zip(gk, gm):
        label(fig, m["ci95"][1], y, ci_txt(m), "x2", "y2", xanchor="left", xshift=6)
    lo, hi = band(gm)
    fig.add_vrect(x0=lo, x1=hi, fillcolor=ACC_L, line_width=0, layer="below", row=1, col=2)
    panel_title(fig, "Authors who state an age, %", "x")
    panel_title(fig, "Generation, %% of the %d authors who state an age" % n_age, "x2")
    label(fig, (lo + hi) / 2, 1, "Intervals overlap: %.1f%% to %.1f%%" % (lo, hi), "x2", "paper", yanchor="bottom",
          yshift=46, font=dict(size=13, color=ACC))
    base_fig(fig, bargap=0.3)
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(ticksuffix="%")
    fig.update_xaxes(range=[0, 4.8], row=1, col=1)
    fig.update_xaxes(range=[0, 118], tickvals=[0, 20, 40, 60, 80, 100], row=1, col=2)
    older = [k for k in gen if k.startswith("Older")][0]
    sub = ("Median stated age %.0f. %d author (%.1f%%) is 46 or older and is not shown. Gender (%d authors) and country (%d) "
           "have a base too small to chart."
           % (pf["median_age_known"], gen[older]["k"], gen[older]["pct"],
              pf["coverage_brand_mentioning_authors"]["gender"]["k"], pf["coverage_brand_mentioning_authors"]["country"]["k"]))
    tbl = (["Measure", "Share (95% CI)", "k of n"],
           [["Age stated, brand-mentioning authors", ci_txt(cov), "%d of %d" % (cov["k"], cov["base"])],
            ["Age stated, all authors", ci_txt(cova), "%d of %d" % (cova["k"], cova["base"])]] +
           [[k, ci_txt(m), "%d of %d" % (m["k"], m["base"])] for k, m in zip(gk, gm)])
    return chart(fig, "Age self-report coverage and the Gen Z vs Millennial split", sub, 440, 400, 150, 40, tbl,
                 "modules.profiling", t=50, b=44)


CA_POS = {"Aritzia": "bottom right", "Zara": "bottom center", "H&M": "top center", "Shein": "bottom center",
          "Uniqlo": "top center", "Old Navy": "bottom left", "Everlane": "bottom center",
          "price/value": "bottom center", "quality/durability": "top center", "fit/sizing": "middle right",
          "style/trend": "top center", "sustainability/ethics": "top center", "shipping/returns": "bottom center",
          "customer service": "top center", "store experience": "bottom center"}


def c4():
    ca = M["positioning"]["correspondence_analysis"]
    rows, cols, pc = ca["row_coords_dim1_2"], ca["col_coords_dim1_2"], ca["axis_inertia_pct"]
    fig = go.Figure()
    rn, cn = list(rows), list(cols)
    fig.add_trace(go.Scatter(
        x=[rows[b][0] for b in rn], y=[rows[b][1] for b in rn], mode="markers+text", text=["<b>%s</b>" % b for b in rn],
        textposition=[CA_POS.get(b, "top center") for b in rn], textfont=dict(size=14, color=INK),
        marker=dict(size=13, color=[ACC if b in CORE else MID for b in rn], line=dict(width=2, color="white")),
        customdata=rn, hovertemplate="<b>%{customdata}</b> (brand)<br>Dim 1 %{x:.3f}, Dim 2 %{y:.3f}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=[cols[a][0] for a in cn], y=[cols[a][1] for a in cn], mode="markers+text", text=cn,
        textposition=[CA_POS.get(a, "top center") for a in cn], textfont=dict(size=13, color=MUTE),
        marker=dict(size=10, symbol="diamond", color="white", line=dict(width=2, color=DARK)),
        customdata=cn, hovertemplate="<b>%{customdata}</b> (attribute)<br>Dim 1 %{x:.3f}, Dim 2 %{y:.3f}<extra></extra>"))
    base_fig(fig)
    fig.add_hline(y=0, line=dict(color=MID, width=1))
    fig.add_vline(x=0, line=dict(color=MID, width=1))
    fig.update_xaxes(title=dict(text="Dimension 1 (%.1f%% of inertia)" % pc[0], font=dict(size=13, color=MUTE)),
                     range=[-0.8, 0.5], showgrid=False)
    fig.update_yaxes(title=dict(text="Dimension 2 (%.1f%% of inertia)" % pc[1], font=dict(size=13, color=MUTE)),
                     range=[-0.75, 0.35], showgrid=False)
    sub = ("Red dots are brands (grey: not in the core set); open diamonds are attributes. Brands near an attribute are "
           "talked about for it. Total inertia %.4f; dimensions 1 and 2 hold %.1f%%." % (ca["total_inertia"], pc[0] + pc[1]))
    tbl = (["Point", "Type", "Dim 1", "Dim 2"],
           [[b, "brand", "%.3f" % rows[b][0], "%.3f" % rows[b][1]] for b in rn] +
           [[a, "attribute", "%.3f" % cols[a][0], "%.3f" % cols[a][1]] for a in cn])
    return chart(fig, "Perceptual map: brands and attributes (correspondence analysis)", sub,
                 760, 620, 70, 30, tbl, "modules.positioning.correspondence_analysis", t=0, b=50)


def c5():
    p = M["positioning"]
    asr, cnt = p["adjusted_std_residuals"], p["counts"]
    brands, attrs, n, bz = p["brands_in_matrix"], p["attributes"], p["chi_square"]["n"], p["bonferroni_z"]
    rt = {b: sum(cnt[b][a] for a in attrs) for b in brands}
    ct = {a: sum(cnt[b][a] for b in brands) for a in attrs}
    z = [[asr[b][a] for a in attrs] for b in brands]
    txt = [["<b>%.2f</b>" % v if abs(v) > bz else "%.2f" % v for v in r] for r in z]
    cd = [[[cnt[b][a], rt[b] * ct[a] / n] for a in attrs] for b in brands]
    ylab = [b if b in CORE else b + " (non-core)" for b in brands]
    fig = go.Figure(go.Heatmap(
        z=z, x=[a.replace("/", "/<br>").replace(" ", "<br>") for a in attrs], y=ylab, text=txt, texttemplate="%{text}", textfont=dict(size=13),
        customdata=cd, zmid=0, zmin=-7, zmax=7, xgap=2, ygap=2,
        colorscale=[[0, "#5E554F"], [0.5, "#FFFFFF"], [1, ACC]],
        colorbar=dict(title=dict(text="Adj. std. residual", side="right", font=dict(size=12)), thickness=10, len=0.85, outlinewidth=0,
                      tickvals=[-6, -3, 0, 3, 6]),
        hovertemplate="<b>%{y}</b> x %{x}<br>Adjusted standardised residual %{z:.2f}<br>Observed %{customdata[0]}, "
                      "expected %{customdata[1]:.1f}<extra></extra>"))
    for i, b in enumerate(brands):
        for j, a in enumerate(attrs):
            if abs(asr[b][a]) > bz:
                fig.add_shape(type="rect", x0=j - 0.5, x1=j + 0.5, y0=i - 0.5, y1=i + 0.5, xref="x", yref="y",
                              line=dict(color=INK, width=3), fillcolor="rgba(0,0,0,0)")
    for j, a in enumerate(attrs):
        fig.add_layout_image(dict(source=icon_uri(a), xref="x", yref="paper", x=j, y=1.12, sizex=0.62, sizey=0.085,
                                  xanchor="center", yanchor="bottom", layer="above"))
    base_fig(fig)
    fig.update_xaxes(side="top", showgrid=False, ticks="", linecolor="white", tickangle=0)
    fig.update_yaxes(autorange="reversed", showgrid=False, linecolor="white")
    sub = ("Red = more talk than expected, grey = less. Bold, outlined cells survive the Bonferroni correction "
           "(|z| > %.2f, %d cells). Counts are sentences, not authors, so p-values are indicative."
           % (bz, p["chi_square"]["cells"]))
    tbl = (["Brand"] + attrs, [[b] + ["%.2f%s" % (asr[b][a], " *" if abs(asr[b][a]) > bz else "") for a in attrs] for b in brands])
    return chart(fig, "Brand x attribute adjusted standardised residuals", sub, 650, 520, 150, 90, tbl,
                 "modules.positioning.adjusted_std_residuals", t=84, b=20)


def c6():
    bb = M["perception"]["by_brand"]
    names = sorted(CORE, key=lambda b: -bb[b]["net_sentiment"])
    ng = [bb[b]["neg"] for b in names]
    ps = [bb[b]["pos"] for b in names]
    fig = go.Figure()
    neg_err = dict(type="data", symmetric=False, array=[m["pct"] - m["ci95"][0] for m in ng],
                   arrayminus=[m["ci95"][1] - m["pct"] for m in ng], color=INK, thickness=1.3, width=4)
    cd = lambda ms, bs: [[m["k"], m["base"], m["ci95"][0], m["ci95"][1], bb[b]["net_sentiment"]] for b, m in zip(bs, ms)]
    hov = ("<b>%{y}</b><br>@@: %{customdata[0]} of %{customdata[1]} sentences<br>"
           "95% CI %{customdata[2]:.1f} to %{customdata[3]:.1f}%<br>Net sentiment %{customdata[4]:+.3f}<extra></extra>")
    fig.add_trace(go.Bar(y=names, x=[-m["pct"] for m in ng], orientation="h", width=0.55, error_x=neg_err,
                         marker_color=BAD, customdata=cd(ng, names),
                         hovertemplate=hov.replace("@@", "Negative")))
    fig.add_trace(go.Bar(y=names, x=[m["pct"] for m in ps], orientation="h", width=0.55, error_x=err(ps),
                         marker_color=GOOD, customdata=cd(ps, names), hovertemplate=hov.replace("@@", "Positive")))
    for b, m in zip(names, ng):
        label(fig, -m["ci95"][1], b, "<b>%.1f%%</b>" % m["pct"], xanchor="right", xshift=-6)
    for b, m in zip(names, ps):
        label(fig, m["ci95"][1], b, "<b>%.1f%%</b>" % m["pct"], xanchor="left", xshift=6)
    for b in names:
        label(fig, 1, b, "<b>%+.3f</b>" % bb[b]["net_sentiment"], "paper", "y", xanchor="left", xshift=14)
    label(fig, 1, 1, "Net sentiment", "paper", "paper", xanchor="left", xshift=8, yshift=10, yanchor="bottom",
          font=dict(size=13, color=MUTE))
    label(fig, 0.0, 1, "Negative share", "x", "paper", xanchor="right", xshift=-4, yshift=10, yanchor="bottom",
          font=dict(size=13, color=MUTE))
    label(fig, 0.0, 1, "Positive share", "x", "paper", xanchor="left", xshift=4, yshift=10, yanchor="bottom",
          font=dict(size=13, color=MUTE))
    base_fig(fig, barmode="overlay", bargap=0.3)
    fig.update_yaxes(categoryorder="array", categoryarray=names, autorange="reversed", tickvals=names)
    fig.update_xaxes(range=[-42, 70], tickvals=[-40, -30, -20, -10, 0, 10, 20, 30, 40, 50, 60],
                     ticktext=["40", "30", "20", "10", "0", "10", "20", "30", "40", "50", "60"], ticksuffix="%",
                     title=dict(text="% of single-brand sentences, VADER (95% CI)", font=dict(size=13, color=MUTE)))
    vv = M["perception"]["vader_validation"]
    sub = ("Brands sorted by net sentiment = (positive - negative) / all sentences. Green bars are positive share, orange bars negative share. "
           " VADER agreed with hand labels on %d%% of %d sentences, so negativity is likely understated."
           % (round(vv["agreement"] * 100), vv["n"]))
    tbl = (["Brand", "Sentences", "Positive (95% CI)", "Negative (95% CI)", "Net sentiment"],
           [[b, str(bb[b]["base"]), ci_txt(bb[b]["pos"]), ci_txt(bb[b]["neg"]), "%+.3f" % bb[b]["net_sentiment"]] for b in names])
    return chart(fig, "Positive and negative share of single-brand sentences, by brand", sub, 500, 440, 90, 120, tbl,
                 "modules.perception.by_brand", t=30, b=50)


def seg_name(s):
    return s["name"].split(" (rule")[0]


def c7():
    sg = M["segmentation"]
    segs = sg["segments"]
    tgt = int(re.search(r"Segment (\d)", REPORT["target"]).group(1))
    nm = lambda s: seg_name(s).replace(", ", ",<br>", 1)
    lab = ["<b>S%d %s<br>(recommended target)</b>" % (s["segment"], nm(s)) if s["segment"] == tgt
           else "S%d %s" % (s["segment"], nm(s)) for s in segs]
    sz = [s["share_of_eligible"] for s in segs]
    ng = [s["sentiment"]["neg"] for s in segs]
    col = [ACC if s["segment"] == tgt else MID for s in segs]
    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.04)
    for ci_, ms, ttl in ((1, sz, "Segment size"), (2, ng, "Negative share")):
        fig.add_trace(go.Bar(y=lab, x=[m["pct"] for m in ms], orientation="h", width=0.55, marker_color=col,
                             error_x=err(ms), customdata=[[m["k"], m["base"], m["ci95"][0], m["ci95"][1]] for m in ms],
                             hovertemplate="<b>%{y}</b><br>" + ttl + " %{x:.1f}% (95% CI %{customdata[2]:.1f} to "
                                           "%{customdata[3]:.1f})<br>%{customdata[0]} of %{customdata[1]}<extra></extra>"),
                      1, ci_)
        for y, m in zip(lab, ms):
            txt = ci_txt(m) if ci_ == 1 else "%s, n=%d" % ("%.1f%%" % m["pct"], m["base"])
            label(fig, m["ci95"][1], y, txt, "x%s" % ("" if ci_ == 1 else "2"), "y", xanchor="left", xshift=6)
    panel_title(fig, "Segment size, %% of %d eligible authors (95%% CI)" % sz[0]["base"], "x")
    panel_title(fig, "Negative share of the segment's sentences (95% CI)", "x2")
    base_fig(fig, bargap=0.3)
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(ticksuffix="%", range=[0, 46])
    sub = ("Authors with at least two brand-mention sentences, grouped into k=%d segments (silhouette %.3f, weak). "
           "Size intervals overlap, so size alone does not decide the target." % (sg["k"], sg["silhouette_by_k"][str(sg["k"])]))
    tbl = (["Segment", "Authors", "Size (95% CI)", "Negative (95% CI)", "Net sentiment"],
           [["S%d %s" % (s["segment"], seg_name(s)), str(s["authors"]), ci_txt(s["share_of_eligible"]),
             ci_txt(s["sentiment"]["neg"]), "%+.3f" % s["sentiment"]["net_sentiment"]] for s in segs])
    return chart(fig, "Talk segments: size and negative share", sub, 480, 420, 300, 40, tbl,
                 "modules.segmentation", t=26, b=44)


def c8():
    tr = M["trend"]
    mon = tr["months"]
    lab = {m: date.fromisoformat(m + "-01").strftime("%b %y") for m in mon}
    fig = make_subplots(rows=2, cols=3, vertical_spacing=0.2, horizontal_spacing=0.07)
    tbl_rows = []
    for i, b in enumerate(CORE):
        r, c = i // 3 + 1, i % 3 + 1
        v = [tr["wikipedia_monthly_views"][b][m.replace("-", "")] for m in mon]
        fig.add_trace(go.Scatter(x=[lab[m] for m in mon], y=v, mode="lines", line=dict(color=DARK, width=2),
                                 hovertemplate="%{x}: %{y:,} views<extra>" + b + "</extra>"), r, c)
        fig.add_trace(go.Scatter(x=[lab[mon[0]], lab[mon[-1]]], y=[v[0], v[-1]], mode="markers+text",
                                 marker=dict(size=9, color=[DARK, ACC], line=dict(width=2, color="white")),
                                 text=["%.1fk" % (v[0] / 1000), "%.1fk" % (v[-1] / 1000)], textposition=["bottom right" if v[1] > v[0] else "top right", "top left"],
                                 textfont=dict(size=12, color=INK), hoverinfo="skip"), r, c)
        rr = tr["pearson_r_views_vs_mentions"][b]
        panel_title(fig, "<b>%s</b>   r = %+.2f" % (b, rr["r"]), "x%s" % (i + 1 if i else ""),
                    "y%s domain" % (i + 1 if i else ""))
        fig.update_yaxes(range=[0, max(v) * 1.2], row=r, col=c)
        tbl_rows.append([b] + ["{:,}".format(x) for x in v] + ["%+.2f" % rr["r"]])
    label(fig, 0.70, 0.17, "Wikipedia page views per month<br>(English, all-access, user).<br>Descriptive only: r compares views<br>"
          "with the monthly count of brand-<br>mentioning items, n=%d months.<br>Mention counts are capped by the crawl." % len(mon),
          "paper", "paper", xanchor="left", yanchor="middle", align="left", font=dict(size=12, color=MUTE))
    base_fig(fig)
    fig.update_xaxes(tickvals=[lab[mon[0]], lab[mon[4]], lab[mon[8]], lab[mon[-1]]], tickfont=dict(size=11))
    fig.update_yaxes(rangemode="tozero", tickformat="~s", gridcolor=GRID, tickfont=dict(size=11))
    for ax in (fig.update_xaxes, fig.update_yaxes):
        ax(showgrid=False, showline=False, showticklabels=False, ticks="", row=2, col=3)
    sub = "Monthly English Wikipedia page views for the five core brands; each panel has its own scale. Red dot marks the latest month."
    tbl = (["Brand"] + [lab[m] for m in mon] + ["r"], tbl_rows)
    return chart(fig, "Public interest by brand over 12 months (descriptive)", sub, 600, 520, 50, 20, tbl,
                 "modules.trend", srcnote="Wikipedia monthly page views (en, all-access, user)", t=30, b=30)


# ---- supplementary analysis (added after the audited cycle; every number from metrics.json "supplementary")
SUP = D.get("supplementary")
SUPN = REDDIT + "; supplementary analysis, not audited"
IMG_WRAP = {"trendy/fashion-forward": "trendy/<br>fashion-<br>forward", "inconsistent/hit-or-miss": "inconsistent/<br>hit-or-miss",
            "premium/aspirational": "premium/<br>aspirational"}
IMG_ORDER = ["premium/aspirational", "cheap/disposable", "trendy/fashion-forward", "dated/frumpy", "comfortable",
             "uncomfortable", "ethical/responsible", "unethical/exploitative", "reliable/consistent",
             "inconsistent/hit-or-miss", "basic/everyday", "Canadian/local", "fun/young"]


def c9():
    fb = SUP["funnel"]["by_brand"]
    fig = make_subplots(rows=2, cols=3, vertical_spacing=0.3, horizontal_spacing=0.07)
    stages = ["Aware", "Considering", "Bought"]
    tbl = []
    for i, b in enumerate(CORE):
        r, c = i // 3 + 1, i % 3 + 1
        f = fb[b]
        cs, bt = f["considering"]["share_of_aware"], f["bought"]["share_of_aware"]
        ms = [dict(pct=100.0, ci95=[100.0, 100.0]), cs, bt]
        fig.add_trace(go.Bar(
            y=stages, x=[m["pct"] for m in ms], orientation="h", width=0.6, marker_color=[LIGHT, MID, ACC], error_x=err(ms),
            customdata=[[f["aware"]["k"], f["aware"]["k"]], [cs["k"], cs["base"]], [bt["k"], bt["base"]]],
            hovertemplate="<b>" + b + "</b> %{y}: %{x:.1f}% of Aware<br>%{customdata[0]} of %{customdata[1]} authors<extra></extra>"), r, c)
        ax, ay = "x%s" % (i + 1 if i else ""), "y%s" % (i + 1 if i else "")
        label(fig, 100, "Aware", "<b>100%%</b> (n=%d)" % f["aware"]["k"], ax, ay, xanchor="left", xshift=6)
        label(fig, cs["ci95"][1], "Considering", "<b>%s</b>" % ci_txt(cs), ax, ay, xanchor="left", xshift=6)
        label(fig, bt["ci95"][1], "Bought", "<b>%s</b>" % ci_txt(bt), ax, ay, xanchor="left", xshift=6)
        conv = f["bought"]["conversion_from_previous_stage"]
        ctxt = ("Bought / Considering: base too small (n=%d)" % conv["base"] if conv["pct"] is None else
                "Bought / Considering: %.0f%% (%.0f to %.0f), n=%d" % (conv["pct"], conv["ci95"][0], conv["ci95"][1], conv["base"]))
        adv = f["advocate"]
        fig.add_annotation(xref=ax + " domain", yref=ay + " domain", x=0, y=0, yshift=-36, xanchor="left", yanchor="top", showarrow=False,
                           align="left", font=dict(size=12, color=MUTE),
                           text="%s<br>Advocate: %d of %d, not measurable" % (ctxt, adv["k"], f["aware"]["k"]))
        panel_title(fig, "<b>%s</b> (n=%d authors)" % (b, f["aware"]["k"]), ax, ay + " domain")
        tbl.append([b, str(f["aware"]["k"]), ci_txt(cs), ci_txt(bt),
                    "base too small" if conv["pct"] is None else ci_txt(conv), "%d of %d" % (adv["k"], bt["k"])])
    label(fig, 0.70, 0.17, "How to read this<br>Shares are of the authors who<br>mentioned the brand. A proxy from<br>phrases in public posts, not a<br>survey funnel. Advocate is 0 or 1<br>author per brand, so it is not drawn.",
          "paper", "paper", xanchor="left", yanchor="middle", align="left", font=dict(size=12, color=MUTE))
    base_fig(fig)
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(range=[0, 175], tickvals=[0, 50, 100], ticksuffix="%")
    for ax_ in (fig.update_xaxes, fig.update_yaxes):
        ax_(showgrid=False, showline=False, showticklabels=False, ticks="", row=2, col=3)
    sub = ("Brand funnel (proxy). Social-listening proxy, not a survey funnel: shares of the authors who mentioned each brand. Considering is almost the same as Bought, "
           "because most Considering authors qualified through a purchase phrase. Advocate is 0 or 1 author per brand, so it is not measurable.")
    bts = [fb[b]["bought"]["share_of_aware"]["pct"] for b in CORE]
    title = ("Between %d%% and %d%% of the authors who mention each core brand also say they bought it; Advocate is too thin to measure"
             % (round(min(bts)), round(max(bts))))
    return chart(fig, title, sub, 780, 700, 40, 20,
                 (["Brand", "Aware (authors)", "Considering, % of Aware", "Bought, % of Aware", "Bought / Considering", "Advocate (k of Bought)"], tbl),
                 "supplementary.funnel.by_brand", srcnote=SUPN, t=30, b=84)


def c10():
    pm = SUP["positioning_map"]["by_brand"]
    names = list(pm)
    X = [pm[b]["x_price_value_share"] for b in names]
    Y = [pm[b]["y_style_trend_share"] for b in names]
    vol = [pm[b]["bubble_mention_sentences"] for b in names]
    net = [pm[b]["colour_net_sentiment"] for b in names]
    fig = go.Figure(go.Scatter(
        x=[m["pct"] for m in X], y=[m["pct"] for m in Y], mode="markers", text=names,
        error_x=dict(type="data", symmetric=False, array=[m["ci95"][1] - m["pct"] for m in X], arrayminus=[m["pct"] - m["ci95"][0] for m in X],
                     color=MID, thickness=1.3, width=0),
        error_y=dict(type="data", symmetric=False, array=[m["ci95"][1] - m["pct"] for m in Y], arrayminus=[m["pct"] - m["ci95"][0] for m in Y],
                     color=MID, thickness=1.3, width=0),
        marker=dict(size=vol, sizemode="area", sizeref=2.0 * max(vol) / (46.0 ** 2), sizemin=8, color=net,
                    colorscale=[[0, "#EEE0CA"], [1, "#1F493D"]], cmin=min(net) - 0.05, cmax=max(net), line=dict(width=2, color="white"),
                    colorbar=dict(title=dict(text="Net sentiment", side="right", font=dict(size=12)), thickness=10, len=0.7, outlinewidth=0)),
        customdata=[[pm[b]["attribute_hits"], v, n, x["ci95"][0], x["ci95"][1], y["ci95"][0], y["ci95"][1]] for b, v, n, x, y in zip(names, vol, net, X, Y)],
        hovertemplate="<b>%{text}</b><br>Price/value share %{x:.1f}% (CI %{customdata[3]:.1f} to %{customdata[4]:.1f})<br>"
                      "Style/trend share %{y:.1f}% (CI %{customdata[5]:.1f} to %{customdata[6]:.1f})<br>%{customdata[1]} mention sentences, net sentiment %{customdata[2]:+.3f}<extra></extra>"))
    off = {"Aritzia": (60, -50), "Zara": (70, 40), "H&M": (-70, -50), "Old Navy": (20, 110), "Uniqlo": (55, -25),
           "Shein": (-40, 38), "Everlane": (50, -30)}
    for b, x, y in zip(names, X, Y):
        ax_, ay_ = off.get(b, (40, -30))
        fig.add_annotation(x=x["pct"], y=y["pct"], ax=ax_, ay=ay_, xref="x", yref="y", axref="pixel", ayref="pixel", text="<b>%s</b>" % b,
                           showarrow=True, arrowhead=0, arrowwidth=1, arrowcolor=MID, font=dict(size=13, color=INK))
    base_fig(fig)
    fig.update_xaxes(range=[10, 70], ticksuffix="%", title=dict(text="Price/value share of the brand's attribute hits (95% CI)", font=dict(size=13, color=MUTE)))
    fig.update_yaxes(range=[0, 40], ticksuffix="%", gridcolor=GRID, title=dict(text="Style/trend share (95% CI)", font=dict(size=13, color=MUTE)))
    hi_x = max(names, key=lambda b: pm[b]["x_price_value_share"]["pct"])
    lo_core = min(CORE, key=lambda b: pm[b]["x_price_value_share"]["pct"])
    sub = ("Positioning map. Bubble area = mention sentences, colour = net sentiment, cross-hair bars = 95%% CI. Most price-share intervals overlap; %s is furthest out on price "
           "(%.1f%%) and %s is lowest among the core brands on price and on style/trend." % (hi_x, pm[hi_x]["x_price_value_share"]["pct"], lo_core))
    tbl = (["Brand", "Price/value share", "Style/trend share", "Mention sentences", "Net sentiment"],
           [[b, ci_txt(x), ci_txt(y), str(v), "%+.3f" % n] for b, x, y, v, n in zip(names, X, Y, vol, net)])
    top3 = sorted(CORE, key=lambda b: -pm[b]["x_price_value_share"]["pct"])[:3]
    xs3 = [pm[b]["x_price_value_share"]["pct"] for b in top3]
    lead_y = max(CORE, key=lambda b: pm[b]["y_style_trend_share"]["pct"])
    both = lo_core == min(CORE, key=lambda b: pm[b]["y_style_trend_share"]["pct"])
    title = ("%s sit within %.1f points of each other on price/value share; %s leads on style/trend (%.1f%%)%s"
             % (", ".join(top3[:-1]) + " and " + top3[-1], max(xs3) - min(xs3), lead_y, pm[lead_y]["y_style_trend_share"]["pct"],
                " and %s is lowest on both" % lo_core if both else ""))
    return chart(fig, title, sub, 720, 600, 80, 80, tbl,
                 "supplementary.positioning_map", srcnote=SUPN, t=0, b=50)


def c11():
    bi = SUP["brand_image"]
    brands = bi["brands_in_grid"]
    grid, avg = bi["association_grid"], bi["set_average_share_pct"]
    assert set(IMG_ORDER) == set(avg)
    z = [[grid[b][i]["pct"] for i in IMG_ORDER] for b in brands] + [[avg[i] for i in IMG_ORDER]]
    txt = [["%.1f%%<br><span style='font-size:10px'>%.0f to %.0f</span>" % (grid[b][i]["pct"], grid[b][i]["ci95"][0], grid[b][i]["ci95"][1])
            for i in IMG_ORDER] for b in brands] + [["%.1f%%" % avg[i] for i in IMG_ORDER]]
    cd = [[[grid[b][i]["k"], grid[b][i]["base"], grid[b][i]["ci95"][0], grid[b][i]["ci95"][1]] for i in IMG_ORDER] for b in brands] + \
         [[[0, 0, 0, 0] for i in IMG_ORDER]]
    rows = ["%s (n=%d)" % (b, bi["coded_sentences_per_brand"][b]) for b in brands] + ["Set average"]
    fig = go.Figure(go.Heatmap(
        z=z, x=[IMG_WRAP.get(i, i.replace("/", "/<br>")) for i in IMG_ORDER], y=rows, text=txt, texttemplate="%{text}", textfont=dict(size=12), customdata=cd,
        zmin=0, zmax=70, xgap=2, ygap=2, colorscale=[[0, "#FBF7F0"], [1, ACC]],
        colorbar=dict(title=dict(text="Share, %", side="right", font=dict(size=12)), thickness=10, len=0.85, outlinewidth=0),
        hovertemplate="<b>%{y}</b> x %{x}<br>%{z:.1f}% of its image-coded sentences<br>%{customdata[0]} of %{customdata[1]} (CI %{customdata[2]:.1f} to %{customdata[3]:.1f})<extra></extra>"))
    base_fig(fig)
    fig.update_xaxes(side="top", showgrid=False, ticks="", linecolor="white", tickangle=0, tickfont=dict(size=10))
    fig.update_yaxes(autorange="reversed", showgrid=False, linecolor="white")
    small = [b for b in bi["brands_base_too_small"] if b in CORE]
    sub = ("Brand image association grid. Share of each brand's image-coded sentences that carry the image (a sentence can carry several), with the 95%% CI under it. "
           "Brands under 30 image-coded sentences are not shown: %s (%d sentences) and the wider brands." %
           (", ".join(small), bi["coded_sentences_per_brand"][small[0]]))
    tbl = (["Brand"] + IMG_ORDER, [[b] + [ci_txt(grid[b][i]) + " (%d of %d)" % (grid[b][i]["k"], grid[b][i]["base"]) for i in IMG_ORDER] for b in brands]
           + [["Set average"] + ["%.1f%%" % avg[i] for i in IMG_ORDER]])
    tops = {b: max(grid[b], key=lambda k: grid[b][k]["pct"]) for b in brands}
    groups = []
    for b in brands:
        for g in groups:
            if g[0] == tops[b]:
                g[1].append(b)
                break
        else:
            groups.append((tops[b], [b]))
    title = "In image talk the most common image is %s" % ", ".join(
        "%s for %s (%s)" % (img, " and ".join(bs), ", ".join("%.1f%%" % grid[b][img]["pct"] for b in bs)) for img, bs in groups)
    return chart(fig, title, sub, 520, 380, 170, 90, tbl,
                 "supplementary.brand_image.association_grid", srcnote=SUPN, t=40, b=20)


def c12():
    bi = SUP["brand_image"]
    brands = bi["brands_in_grid"]
    asr, bz = bi["adjusted_std_residuals"], bi["bonferroni_z"]
    flagged = {(c["brand"], c["image"]): c for c in bi["strengths_and_weaknesses_bonferroni"]["cells"]}
    fig = make_subplots(rows=2, cols=2, shared_yaxes=True, vertical_spacing=0.14, horizontal_spacing=0.04)
    for k, b in enumerate(brands):
        r, c = k // 2 + 1, k % 2 + 1
        zs = [asr[b][i] for i in IMG_ORDER]
        cols = [(ACC if zz > 0 else DARK) if (b, i) in flagged else LIGHT for i, zz in zip(IMG_ORDER, zs)]
        fig.add_trace(go.Bar(y=IMG_ORDER, x=zs, orientation="h", width=0.7, marker_color=cols,
                             hovertemplate="<b>" + b + "</b> %{y}<br>adjusted residual %{x:+.2f}<extra></extra>"), r, c)
        ax = "x%s" % (k + 1 if k else "")
        ay = "y%s" % (k + 1 if k else "")
        panel_title(fig, "<b>%s</b> (n=%d image-coded sentences)" % (b, bi["coded_sentences_per_brand"][b]), ax, ay + " domain")
        for sgn in (-1, 1):
            fig.add_vline(x=sgn * bz, line=dict(color=MID, width=1, dash="dash"), row=r, col=c)
        for i, zz in zip(IMG_ORDER, zs):
            if (b, i) in flagged:
                f_ = flagged[(b, i)]
                lab = "<b>%+.2f</b> (%d vs %.1f)" % (zz, f_["observed"], f_["expected"])
                if f_["reading"] == "strength":
                    lab += "<br>association, not endorsement"
                if zz > 6:
                    label(fig, 0, i, lab, ax, ay, xanchor="left", xshift=8, font=dict(size=11, color="white"))
                elif zz > 0:
                    label(fig, zz, i, lab, ax, ay, xanchor="left", xshift=6, font=dict(size=11, color=INK))
                else:
                    label(fig, 0, i, lab, ax, ay, xanchor="left", xshift=6, font=dict(size=11, color=INK))
    base_fig(fig)
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=11))
    fig.update_xaxes(range=[-7, 13], tickvals=[-6, -3, 0, 3, 6, 9, 12], gridcolor=GRID, zeroline=True, zerolinecolor=MID)
    sub = ("Image strengths and weaknesses against the set average. Adjusted standardised residual of each brand x image cell; dashed lines mark the Bonferroni threshold (|z| > %.1f). "
           "Coloured bars are flagged. Flagged means more or less talk than average, not praise: keyword association is not endorsement." % bz)
    tbl = (["Brand", "Image", "z", "Observed", "Expected", "Reading"],
           [[c["brand"], c["image"], "%+.2f" % c["z"], str(c["observed"]), "%.1f" % c["expected"],
             "flagged, association not endorsement" if c["reading"] == "strength" else c["reading"]] for c in flagged.values()])
    cells_ = bi["strengths_and_weaknesses_bonferroni"]["cells"]
    parts = []
    for b in brands:
        ov = [c["image"] for c in cells_ if c["brand"] == b and c["direction"] == "over"]
        un = [c["image"] for c in cells_ if c["brand"] == b and c["direction"] == "under"]
        if ov or un:
            parts.append("%s %s" % (b, " and ".join((["over-indexes on " + ", ".join(ov)] if ov else []) + (["under on " + ", ".join(un)] if un else []))))
    title = "; ".join(parts)
    return chart(fig, title, sub, 900, 780, 150, 40, tbl,
                 "supplementary.brand_image.adjusted_std_residuals", srcnote=SUPN, t=24, b=30)


def c13():
    pq = SUP["brand_image"]["priority_quadrant"]["by_brand"]
    placed = [(b, c) for b, v in pq.items() for c in v.get("cells_n_ge_30", [])]
    unplaced = sum(v.get("cells_below_30_not_placed", 0) for v in pq.values())
    small = [b for b, v in pq.items() if v.get("status") == "base too small"]
    fig = go.Figure()
    for (x0, x1, y0, y1, fill, name, how, ax_, ay_) in (
            (1, 3, 0, 1, "#DDE7E1", "Defend", "strong image, positive sentiment", "left", "top"),
            (1, 3, -1, 0, "#F3D9C3", "Fix", "strong image, negative sentiment", "left", "bottom"),
            (0, 1, 0, 1, "#EEE0CA", "Hidden asset", "weak image, positive sentiment", "left", "top"),
            (0, 1, -1, 0, "#E9E6E1", "Low priority", "weak image, negative sentiment", "left", "bottom")):
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, fillcolor=fill, line_width=0, layer="below")
        fig.add_annotation(x=x0, y=y1 if ay_ == "top" else y0, xref="x", yref="y", xanchor="left", yanchor=ay_, xshift=8, yshift=-8 if ay_ == "top" else 8,
                           showarrow=False, align="left", text="<b>%s</b><br><span style='font-size:11px'>%s</span>" % (name, how), font=dict(size=14, color=INK))
    fig.add_trace(go.Scatter(
        x=[c["index_vs_set_average"] for _, c in placed], y=[c["net_sentiment"] for _, c in placed], mode="markers",
        marker=dict(size=18, color=ACC, line=dict(width=2, color="white")),
        customdata=[[b, c["image"], c["n"], c["share_pct"], c["quadrant"]] for b, c in placed],
        hovertemplate="<b>%{customdata[0]}, %{customdata[1]}</b><br>index vs set average %{x:.2f}, net sentiment %{y:+.2f}<br>n=%{customdata[2]}, %{customdata[4]}<extra></extra>"))
    for b, c in placed:
        label(fig, c["index_vs_set_average"], c["net_sentiment"], "<b>%s, %s</b><br>n=%d, %.1f%% of its image-coded sentences<br>%.2fx the set average, net sentiment %+.2f: %s"
              % (b, c["image"], c["n"], c["share_pct"], c["index_vs_set_average"], c["net_sentiment"], c["quadrant"]), "x", "y",
              xanchor="right", xshift=-14, yanchor="middle")
    base_fig(fig)
    fig.update_xaxes(range=[0, 3], title=dict(text="Image strength: the brand's share of the image vs the set average (1.0 = average)", font=dict(size=13, color=MUTE)),
                     gridcolor="rgba(0,0,0,0)")
    fig.update_yaxes(range=[-1, 1], title=dict(text="Net sentiment in the cell", font=dict(size=13, color=MUTE)), gridcolor="rgba(0,0,0,0)")
    sub = ("Image priority quadrant. Only cells with at least 30 sentences are placed: %d cell is placed and %d brand x image cells are not. %s has too few image-coded sentences "
           "(%d) to be placed." % (len(placed), unplaced, ", ".join(small), pq[small[0]]["coded_sentences"]))
    tbl = (["Brand", "Image", "n", "Share", "Index vs set average", "Net sentiment", "Quadrant"],
           [[b, c["image"], str(c["n"]), "%.1f%%" % c["share_pct"], "%.2f" % c["index_vs_set_average"], "%+.2f" % c["net_sentiment"], c["quadrant"]] for b, c in placed])
    c0 = placed[0][1]
    title = ("Only %d cell has enough sentences to place: %s's %s image, at %.1f times the set average with net sentiment %+.2f"
             % (len(placed), placed[0][0], c0["image"], c0["index_vs_set_average"], c0["net_sentiment"]))
    return chart(fig, title, sub, 580, 500, 80, 30, tbl,
                 "supplementary.brand_image.priority_quadrant", srcnote=SUPN, t=0, b=50)


# ---- mobile variants (below 640 px): one column, horizontal bars, direct labels, no legends, text >= 12 px.
# Charts 05, 11 and 12 (heatmaps) are replaced on phones by ranked card lists (see mob_list).
def _mob_fix(fig):
    fig.update_layout(dragmode=False, hovermode="closest", font=dict(family=FONT, size=12, color=INK))
    for a in fig.layout.annotations:
        sz = (a.font.size if a.font and a.font.size else 12)
        a.font = dict(size=max(12, sz), color=(a.font.color if a.font and a.font.color else INK))
    fig.update_xaxes(tickfont=dict(size=12), fixedrange=True)
    fig.update_yaxes(tickfont=dict(size=12), fixedrange=True)
    return fig


def m1():
    c = c1()
    c["hh"], c["r"] = 600, 20
    fig = c["fig"]
    fig.update_xaxes(range=[0, 62], title=dict(text="Named first, % of replies (95% CI)", font=dict(size=12, color=MUTE)))
    _mob_fix(fig)
    return c


def m2():
    c = c2()
    c["hh"], c["r"] = 330, 16
    fig = c["fig"]
    fig.update_xaxes(range=[0, 6.6], dtick=1, title=dict(text="% of brand-mentioning authors (95% CI)", font=dict(size=12, color=MUTE)))
    _mob_fix(fig)
    return c


def m3():
    pf = M["profiling"]
    cov, cova = pf["coverage_brand_mentioning_authors"]["age"], pf["coverage_all_authors"]["age"]
    gen = pf["generation_of_brand_mentioning_authors"]
    gk = [k for k in gen if k.startswith("Gen Z")] + [k for k in gen if k.startswith("Millennial")]
    gm = [gen[k] for k in gk]
    fig = make_subplots(rows=2, cols=1, vertical_spacing=0.3)
    cl = ["Brand-mentioning<br>authors (n=%d)" % cov["base"], "All authors<br>(n=%d)" % cova["base"]]
    cms = [cov, cova]
    fig.add_trace(go.Bar(y=cl, x=[m["pct"] for m in cms], orientation="h", width=0.5, marker_color=[ACC, MID], error_x=err(cms),
                         hovertemplate="<b>%{y}</b><br>%{x:.1f}% gave an age<extra></extra>"), 1, 1)
    for y, m in zip(cl, cms):
        label(fig, m["ci95"][1], y, ci_txt(m), "x", "y", xanchor="left", xshift=6)
    fig.add_trace(go.Bar(y=gk, x=[m["pct"] for m in gm], orientation="h", width=0.5, marker_color=DARK, error_x=err(gm),
                        hovertemplate="<b>%{y}</b><br>%{x:.1f}%<extra></extra>"), 2, 1)
    for y, m in zip(gk, gm):
        label(fig, m["ci95"][1], y, ci_txt(m), "x2", "y2", xanchor="left", xshift=6)
    lo, hi = band(gm)
    fig.add_vrect(x0=lo, x1=hi, fillcolor=ACC_L, line_width=0, layer="below", row=2, col=1)
    panel_title(fig, "Authors who state an age, %", "x", "y domain")
    panel_title(fig, "Generation, %% (n=%d)" % gm[0]["base"], "x2", "y2 domain")
    base_fig(fig, bargap=0.3)
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(ticksuffix="%")
    fig.update_xaxes(range=[0, 7.5], row=1, col=1)
    fig.update_xaxes(range=[0, 190], tickvals=[0, 25, 50, 75, 100], row=2, col=1)
    _mob_fix(fig)
    base = chart(fig, "", "", 0, 560, 10, 16, ([], []), "modules.profiling")
    return base


def m4():
    c = c4()
    fig = c["fig"]
    fig.data[0].marker.size = 17
    fig.data[0].textfont = dict(size=13, color=INK)
    fig.data[1].mode = "markers"
    fig.data[1].text = None
    fig.data[1].marker.size = 12
    fig.update_xaxes(title=dict(text="Axis 1 (%s)" % fig.layout.xaxis.title.text.split("(")[1], font=dict(size=12, color=MUTE)))
    fig.update_yaxes(title=dict(text="Axis 2 (%s)" % fig.layout.yaxis.title.text.split("(")[1], font=dict(size=12, color=MUTE)))
    c["hh"], c["r"] = 440, 12
    _mob_fix(fig)
    return c


def m6():
    bb = M["perception"]["by_brand"]
    names = sorted(CORE, key=lambda b: -bb[b]["net_sentiment"])
    ng = [bb[b]["neg"] for b in names]
    ps = [bb[b]["pos"] for b in names]
    fig = go.Figure()
    neg_err = dict(type="data", symmetric=False, array=[m["pct"] - m["ci95"][0] for m in ng],
                   arrayminus=[m["ci95"][1] - m["pct"] for m in ng], color=INK, thickness=1.3, width=3)
    fig.add_trace(go.Bar(y=names, x=[-m["pct"] for m in ng], orientation="h", width=0.55, error_x=neg_err, marker_color=BAD,
                         hovertemplate="<b>%{y}</b><br>Negative %{x:.1f}%<extra></extra>"))
    fig.add_trace(go.Bar(y=names, x=[m["pct"] for m in ps], orientation="h", width=0.55, error_x=err(ps), marker_color=GOOD,
                         hovertemplate="<b>%{y}</b><br>Positive %{x:.1f}%<extra></extra>"))
    for b, m in zip(names, ng):
        label(fig, -m["ci95"][1], b, "<b>%.1f%%</b>" % m["pct"], xanchor="right", xshift=-4)
    for b, m in zip(names, ps):
        label(fig, m["ci95"][1], b, "<b>%.1f%%</b>" % m["pct"], xanchor="left", xshift=4)
    label(fig, 0, 1, "Negative", "x", "paper", xanchor="right", xshift=-4, yshift=10, yanchor="bottom", font=dict(size=12, color=MUTE))
    label(fig, 0, 1, "Positive", "x", "paper", xanchor="left", xshift=4, yshift=10, yanchor="bottom", font=dict(size=12, color=MUTE))
    base_fig(fig, barmode="overlay", bargap=0.3)
    fig.update_yaxes(categoryorder="array", categoryarray=names, autorange="reversed", tickvals=names,
                     ticktext=["<b>%s</b><br>net %+.3f" % (b, bb[b]["net_sentiment"]) for b in names])
    fig.update_xaxes(range=[-40, 72], tickvals=[-40, -20, 0, 20, 40, 60], ticktext=["40", "20", "0", "20", "40", "60"], ticksuffix="%",
                     title=dict(text="% of single-brand sentences (95% CI)", font=dict(size=12, color=MUTE)))
    _mob_fix(fig)
    return chart(fig, "", "", 0, 420, 10, 14, ([], []), "modules.perception.by_brand", t=20)


def m7():
    sg = M["segmentation"]
    segs = sg["segments"]
    tgt = int(re.search(r"Segment (\d)", REPORT["target"]).group(1))
    lab = ["<b>S%d %s (target)</b>" % (s["segment"], seg_name(s).split(",")[0]) if s["segment"] == tgt
           else "S%d %s" % (s["segment"], seg_name(s).split(",")[0]) for s in segs]
    sz = [s["share_of_eligible"] for s in segs]
    ng = [s["sentiment"]["neg"] for s in segs]
    col = [ACC if s["segment"] == tgt else MID for s in segs]
    fig = make_subplots(rows=2, cols=1, vertical_spacing=0.2)
    for r_, ms, ttl in ((1, sz, "Segment size"), (2, ng, "Negative share")):
        fig.add_trace(go.Bar(y=lab, x=[m["pct"] for m in ms], orientation="h", width=0.55, marker_color=col, error_x=err(ms),
                             hovertemplate="<b>%{y}</b><br>" + ttl + " %{x:.1f}%<extra></extra>"), r_, 1)
        for y, m in zip(lab, ms):
            txt = ci_txt(m) if r_ == 1 else "%.1f%% (n=%d)" % (m["pct"], m["base"])
            label(fig, m["ci95"][1], y, txt, "x%s" % ("" if r_ == 1 else "2"), "y%s" % ("" if r_ == 1 else "2"), xanchor="left", xshift=5)
    panel_title(fig, "Segment size, %% of %d eligible authors (95%% CI)" % sz[0]["base"], "x", "y domain")
    panel_title(fig, "Negative share of the segment's sentences (95% CI)", "x2", "y2 domain")
    base_fig(fig, bargap=0.3)
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(ticksuffix="%", range=[0, 52])
    _mob_fix(fig)
    return chart(fig, "", "", 0, 620, 10, 12, ([], []), "modules.segmentation", t=24)


def m8():
    tr = M["trend"]
    mon = tr["months"]
    lab = {m: date.fromisoformat(m + "-01").strftime("%b %y") for m in mon}
    fig = make_subplots(rows=5, cols=1, vertical_spacing=0.075)
    for i, b in enumerate(CORE):
        v = [tr["wikipedia_monthly_views"][b][m.replace("-", "")] for m in mon]
        fig.add_trace(go.Scatter(x=[lab[m] for m in mon], y=v, mode="lines", line=dict(color=DARK, width=2.5),
                                 hovertemplate="%{x}: %{y:,} views<extra>" + b + "</extra>"), i + 1, 1)
        fig.add_trace(go.Scatter(x=[lab[mon[0]], lab[mon[-1]]], y=[v[0], v[-1]], mode="markers+text",
                                 marker=dict(size=11, color=[DARK, ACC], line=dict(width=2, color="white")),
                                 text=["%.1fk" % (v[0] / 1000), "%.1fk" % (v[-1] / 1000)],
                                 textposition=["top right", "top left"], textfont=dict(size=12, color=INK), hoverinfo="skip"), i + 1, 1)
        rr = tr["pearson_r_views_vs_mentions"][b]
        panel_title(fig, "<b>%s</b>   r = %+.2f" % (b, rr["r"]), "x%s" % (i + 1 if i else ""), "y%s domain" % (i + 1 if i else ""))
        fig.update_yaxes(range=[0, max(v) * 1.25], row=i + 1, col=1)
    base_fig(fig)
    fig.update_xaxes(tickvals=[lab[mon[0]], lab[mon[4]], lab[mon[8]], lab[mon[-1]]])
    fig.update_yaxes(rangemode="tozero", tickformat="~s", gridcolor=GRID, nticks=3)
    _mob_fix(fig)
    return chart(fig, "", "", 0, 820, 40, 14, ([], []), "modules.trend", t=24)


def m9():
    fb = SUP["funnel"]["by_brand"]
    fig = make_subplots(rows=5, cols=1, vertical_spacing=0.1)
    stages = ["Aware", "Considering", "Bought"]
    for i, b in enumerate(CORE):
        f = fb[b]
        cs, bt = f["considering"]["share_of_aware"], f["bought"]["share_of_aware"]
        ms = [dict(pct=100.0, ci95=[100.0, 100.0]), cs, bt]
        fig.add_trace(go.Bar(y=stages, x=[m["pct"] for m in ms], orientation="h", width=0.6, marker_color=[LIGHT, MID, ACC], error_x=err(ms),
                             hovertemplate="<b>" + b + "</b> %{y}: %{x:.1f}% of Aware<extra></extra>"), i + 1, 1)
        ax, ay = "x%s" % (i + 1 if i else ""), "y%s" % (i + 1 if i else "")
        label(fig, 100, "Aware", "<b>100%%</b> (n=%d)" % f["aware"]["k"], ax, ay, xanchor="left", xshift=5)
        label(fig, cs["ci95"][1], "Considering", "<b>%s</b>" % ci_txt(cs), ax, ay, xanchor="left", xshift=5)
        label(fig, bt["ci95"][1], "Bought", "<b>%s</b>" % ci_txt(bt), ax, ay, xanchor="left", xshift=5)
        conv = f["bought"]["conversion_from_previous_stage"]
        ctxt = ("Bought/Considering: base too small (n=%d)" % conv["base"] if conv["pct"] is None else
                "Bought/Considering %.0f%% (%.0f to %.0f), n=%d" % (conv["pct"], conv["ci95"][0], conv["ci95"][1], conv["base"]))
        fig.add_annotation(xref=ax + " domain", yref=ay + " domain", x=0, y=0, yshift=-32, xanchor="left", yanchor="top", showarrow=False,
                           align="left", font=dict(size=12, color=MUTE), text="%s<br>Advocate: %d of %d, not measurable" % (ctxt, f["advocate"]["k"], f["aware"]["k"]))
        panel_title(fig, "<b>%s</b> (n=%d authors)" % (b, f["aware"]["k"]), ax, ay + " domain")
    base_fig(fig)
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(range=[0, 200], tickvals=[0, 50, 100], ticksuffix="%")
    _mob_fix(fig)
    return chart(fig, "", "", 0, 1180, 84, 12, ([], []), "supplementary.funnel.by_brand", t=24, b=40)


def m10():
    pm = SUP["positioning_map"]["by_brand"]
    names = list(pm)
    X = [pm[b]["x_price_value_share"] for b in names]
    Y = [pm[b]["y_style_trend_share"] for b in names]
    vol = [pm[b]["bubble_mention_sentences"] for b in names]
    net = [pm[b]["colour_net_sentiment"] for b in names]
    fig = go.Figure(go.Scatter(
        x=[m["pct"] for m in X], y=[m["pct"] for m in Y], mode="markers", text=names,
        error_x=dict(type="data", symmetric=False, array=[m["ci95"][1] - m["pct"] for m in X], arrayminus=[m["pct"] - m["ci95"][0] for m in X], color=MID, thickness=1.5, width=0),
        error_y=dict(type="data", symmetric=False, array=[m["ci95"][1] - m["pct"] for m in Y], arrayminus=[m["pct"] - m["ci95"][0] for m in Y], color=MID, thickness=1.5, width=0),
        marker=dict(size=vol, sizemode="area", sizeref=2.0 * max(vol) / (38.0 ** 2), sizemin=14, color=net, colorscale=[[0, "#EEE0CA"], [1, "#1F493D"]],
                    cmin=min(net) - 0.05, cmax=max(net), line=dict(width=2, color="white"),
                    colorbar=dict(title=dict(text="Net sentiment", side="top", font=dict(size=12)), orientation="h", thickness=10, len=0.8, x=0.5, y=-0.28,
                                  outlinewidth=0, tickfont=dict(size=12))),
        hovertemplate="<b>%{text}</b><br>Price/value %{x:.1f}%<br>Style/trend %{y:.1f}%<extra></extra>"))
    off = {"Aritzia": (38, -48), "Zara": (46, 40), "H&M": (-40, -50), "Old Navy": (10, 66), "Uniqlo": (42, -30), "Shein": (-34, 40), "Everlane": (-30, -36)}
    for b, x, y in zip(names, X, Y):
        ax_, ay_ = off.get(b, (30, -30))
        fig.add_annotation(x=x["pct"], y=y["pct"], ax=ax_, ay=ay_, xref="x", yref="y", axref="pixel", ayref="pixel", text="<b>%s</b>" % b,
                           showarrow=True, arrowhead=0, arrowwidth=1, arrowcolor=MID, font=dict(size=13, color=INK))
    base_fig(fig)
    fig.update_xaxes(range=[10, 70], ticksuffix="%", title=dict(text="Price/value share (95% CI)", font=dict(size=12, color=MUTE)))
    fig.update_yaxes(range=[0, 40], ticksuffix="%", gridcolor=GRID, title=dict(text="Style/trend share (95% CI)", font=dict(size=12, color=MUTE)))
    _mob_fix(fig)
    return chart(fig, "", "", 0, 560, 56, 14, ([], []), "supplementary.positioning_map", t=10, b=96)


def m13():
    c = c13()
    fig = c["fig"]
    pq = SUP["brand_image"]["priority_quadrant"]["by_brand"]
    placed = [(b, x) for b, v in pq.items() for x in v.get("cells_n_ge_30", [])]
    for a in list(fig.layout.annotations):
        if a.text and "n=" in a.text and a.xref == "x" and a.xanchor == "right":
            b, x = placed[0]
            a.text = "<b>%s, %s</b><br>n=%d, %.2fx set average<br>net sentiment %+.2f" % (b, x["image"], x["n"], x["index_vs_set_average"], x["net_sentiment"])
    fig.update_xaxes(title=dict(text="Share vs set average (1.0 = average)", font=dict(size=12, color=MUTE)))
    fig.update_yaxes(title=dict(text="Net sentiment", font=dict(size=12, color=MUTE)))
    c["hh"], c["r"] = 420, 12
    _mob_fix(fig)
    return c


MOB_BUILDERS = {"01-top-of-mind": m1, "02-penetration-proxy": m2, "03-profiling": m3, "04-perceptual-map": m4, "06-perception": m6,
                "07-segments": m7, "08-interest-trend": m8, "09-brand-funnel": m9, "10-positioning-map": m10, "13-image-priority": m13}
MOB_LIST = ("05-positioning-residuals", "11-brand-image-grid", "12-image-strengths")   # heatmaps: ranked cards on phones


CHARTS = [("01-top-of-mind", c1), ("02-penetration-proxy", c2), ("03-profiling", c3), ("04-perceptual-map", c4),
          ("05-positioning-residuals", c5), ("06-perception", c6), ("07-segments", c7), ("08-interest-trend", c8),
          ("09-brand-funnel", c9), ("10-positioning-map", c10), ("11-brand-image-grid", c11),
          ("12-image-strengths", c12), ("13-image-priority", c13)]


# ---------------------------------------------------------------- HTML (friendly board style)
# Art direction: warm off-white ground, flat colour fields (no gradients, shadows or rules), one friendly
# sans-serif, big numbers, rounded cards separated by tone steps. Inside the charts: grey plus one accent.
CSS = """
:root{--bg:#F3EFE8;--card:#FFFFFF;--ink:#3D3D3D;--head:#1F493D;--mute:#5C5750;--forest:#1F493D;--forest2:#336659;
--burg:#8F2323;--deep:#5D0034;--orange:#C36728;--orange-d:#A7532D;--gold:#BF9B30;--navy:#082351;--sand:#EEE0CA;
--sage:#DDE7E1;--blush:#F0DCD6;--taupe:#8D8079;--serif:"Playfair Display",Georgia,"Times New Roman",serif}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;font:17px/1.55 Inter,"Segoe UI","Helvetica Neue",Arial,sans-serif;color:var(--ink);background:var(--bg);
-webkit-print-color-adjust:exact;print-color-adjust:exact}
main{display:flex;flex-direction:column}
.w{width:100%;max-width:1160px;margin:0 auto;padding-left:20px;padding-right:20px;align-self:center}
a{color:var(--burg)}
h1,h2,h3,p{margin:0}
h1,h2,.num,.v,.bigstat,.kpi b{font-family:var(--serif)}
h2,h3{color:var(--head)}
.note{font-size:14px;color:var(--mute)}
.ic{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;flex:none}
/* storyline tracker */
.track{display:none;flex-wrap:wrap;gap:4px 6px;align-items:center;font-size:13px;color:var(--mute);margin-bottom:18px}
.track span{padding:3px 10px;border-radius:999px}
.track .on{background:var(--burg);color:#fff;font-weight:700}
.track i{font-style:normal;color:var(--taupe)}
/* cover */
.cover{padding-top:20px;padding-bottom:8px}
.cover-grid{display:grid;grid-template-columns:1.45fr 1fr;gap:16px}
.block{background:var(--forest);color:var(--bg);border-radius:28px;padding:40px 38px 34px;display:flex;flex-direction:column;justify-content:space-between;gap:40px;min-height:520px}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{background:var(--gold);color:#1A1A1A;font-weight:700;font-size:14px;border-radius:999px;padding:6px 14px}
.client{font-size:18px;font-weight:600;margin-bottom:12px}
.block h1{font-size:clamp(30px,4.8vw,54px);line-height:1.08;font-weight:800;letter-spacing:-.01em;max-width:16em;color:var(--bg)}
.answer{background:var(--sand);border-radius:28px;padding:34px 32px 28px;display:flex;flex-direction:column;gap:16px;justify-content:center}
.answer .lab{font-size:14px;font-weight:700;color:var(--burg)}
.answer h2{font-size:clamp(22px,2.6vw,30px);line-height:1.2;font-weight:800}
.answer .target{background:#fff;border-radius:16px;padding:12px 16px;font-weight:600;font-size:16px;color:var(--head)}
/* generic */
section.pg{padding-top:56px}
.shead h2{font-size:clamp(26px,3.6vw,40px);line-height:1.15;font-weight:800;letter-spacing:-.01em;max-width:28em}
.shead .lead{margin-top:8px;color:var(--mute);max-width:46em}
.card{background:var(--card);border-radius:22px;padding:22px 24px;display:flex;flex-direction:column;gap:10px}
.card h3{display:flex;align-items:center;gap:10px;font-size:17px;font-weight:800}
.card h3 .dot{display:inline-flex;width:36px;height:36px;border-radius:999px;align-items:center;justify-content:center;background:var(--sand);color:var(--head)}
.card p,.card li{font-size:16px}
.card ol,.card ul{margin:0;padding-left:20px}.card li{margin-bottom:6px}
.k-q{background:var(--sage)}.k-t{background:var(--gold);color:#1A1A1A}.k-t h3,.k-t p{color:#1A1A1A}.k-w{background:var(--blush)}.k-n{background:var(--sand)}
.k-q h3 .dot,.k-t h3 .dot,.k-w h3 .dot,.k-n h3 .dot{background:#fff}
.span2{grid-column:span 2}.span3{grid-column:span 3}
.mini3{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:6px}
.mini3 b{display:block;font-family:var(--serif);font-size:clamp(34px,4.4vw,48px);line-height:1.05;color:var(--burg)}
.mini3 span{display:block;font-weight:700;color:var(--head);line-height:1.3;margin-top:4px}
.mini3 small{display:block;font-size:13px;color:var(--mute);margin-top:4px;line-height:1.4}
@media(max-width:700px){.mini3{grid-template-columns:1fr}}
.bigstat{font-size:56px;line-height:1;font-weight:800;color:inherit}
/* summary */
.scqa{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:20px}
.scqa .card{gap:8px}.scqa .card h3{font-size:15px}
.scqa .a{background:var(--forest);color:var(--bg)}.scqa .a h3,.scqa .a p{color:var(--bg)}
.tks{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:14px}
.tk{background:var(--sand);border-radius:22px;padding:18px 22px}
.tk b{display:block;color:var(--burg);font-size:14px;margin-bottom:4px}.tk p{font-size:16px;color:var(--head);font-weight:600}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(170px,100%),1fr));gap:12px;margin-top:14px}
.kpi{background:var(--card);border-radius:20px;padding:16px 18px}
.kpi .l{display:block;font-size:14px;font-weight:700;color:var(--head)}
.kpi b{display:block;font-size:32px;line-height:1.15;color:var(--burg);margin:4px 0}
.kpi span.s{display:block;font-size:14px;color:var(--mute);line-height:1.4}
.base{font-size:14px;color:var(--mute);margin-top:12px}
.board{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:20px}
.ctxgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));gap:14px;margin-top:20px}
.ctxgrid .card{justify-content:space-between}.ctxgrid .cite{font-size:14px;color:var(--mute)}
.srcgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:20px}
/* chapter band and module heads */
.band{background:var(--forest);color:var(--bg);border-radius:26px;padding:24px 30px;margin-bottom:26px;display:grid;grid-template-columns:auto 1fr;gap:6px 22px;align-items:center}
.band .chip{align-self:start}.band h2{color:var(--bg);font-size:clamp(22px,3vw,30px);line-height:1.2;font-weight:800}
.band p{grid-column:1/-1;font-size:15px;color:var(--bg)}
.mhead{display:grid;grid-template-columns:auto 1fr;gap:6px 20px;align-items:start;margin-bottom:18px}
.num{font-size:clamp(52px,8vw,84px);line-height:.95;font-weight:800;color:var(--burg);letter-spacing:-.03em}
.kick{font-size:15px;font-weight:700;color:var(--mute);margin-bottom:4px}
.mhead h2{font-size:clamp(23px,3vw,32px);line-height:1.2;font-weight:800;max-width:30em}
.supp{display:inline-block;background:var(--gold);color:#1A1A1A;font-size:13px;font-weight:800;border-radius:999px;padding:3px 12px;margin-left:8px}
.mgrid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,2fr);gap:14px;grid-template-areas:"stat q" "chart chart" "so rec"}
.stat{grid-area:stat;background:var(--burg);color:var(--bg);border-radius:24px;padding:24px 26px;display:flex;flex-direction:column;gap:6px;justify-content:center}
.stat .v{font-size:clamp(44px,6.4vw,64px);line-height:1;font-weight:800;color:var(--bg)}
.stat .t{font-size:17px;font-weight:700;line-height:1.3}
.stat .s{font-size:14px;line-height:1.4}
.qcard{grid-area:q;background:var(--sage);border-radius:24px;padding:22px 26px;display:flex;flex-direction:column;gap:10px;justify-content:center}
.chartwrap{grid-area:chart;display:flex;flex-direction:column;gap:14px}
.sowhat{grid-area:so;background:var(--sand);border-radius:24px;padding:22px 26px}
.rec{grid-area:rec;background:var(--forest);color:var(--bg);border-radius:24px;padding:22px 26px}
.rec h3{color:var(--bg)}
.sowhat h3,.rec h3,.qcard h3{font-size:15px;font-weight:800;margin-bottom:6px}
.sowhat p,.rec p{font-size:18px}
.chartcard{background:var(--card);border-radius:24px;padding:18px 20px 14px}
.chartcard figure{margin:0}
.sub{font-size:15px;color:var(--mute);max-width:62em;margin-bottom:6px}
.src{font-size:13px;color:var(--mute);margin-top:6px}
.pimg{display:none}
.pgrid{max-width:360px}
.leg{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:13px;font-weight:700;margin:6px 0 4px}
.leg i{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:5px;vertical-align:-1px}
.hint{display:none;font-size:13px;color:var(--mute)}
@media(max-width:700px){.hint{display:block}}
details{font-size:15px}
.drawer{margin:14px 0 0}
.drawer>summary,.chartcard details>summary{cursor:pointer;list-style:none;display:inline-flex;align-items:center;gap:8px;background:var(--card);color:var(--burg);font-weight:700;border-radius:999px;padding:10px 18px}
.chartcard details>summary{background:var(--sand);color:var(--head);font-size:14px;padding:6px 14px;margin-top:8px}
summary::-webkit-details-marker{display:none}
.drawer>summary:before,.chartcard details>summary:before{content:"+";font-weight:800}
.drawer[open]>summary:before,.chartcard details[open]>summary:before{content:"\\2212"}
.drawer .fgrid{margin-top:12px}
table{border-collapse:collapse;width:100%;font-size:14px;margin-top:8px;display:block;overflow-x:auto}
th,td{padding:5px 12px 5px 0;text-align:left;vertical-align:top;white-space:nowrap}
th{color:var(--mute);font-weight:700}
tr:nth-child(even) td{background:var(--bg)}
.quad{width:100%;height:auto;display:block}
.quad text{font-family:inherit}
/* personas */
.personas{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));gap:14px;margin-top:14px}
.persona{background:var(--card);border-radius:24px;padding:20px 22px;display:flex;flex-direction:column;gap:10px}
.persona.target{background:var(--gold);color:#1A1A1A}
.phead{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:12px;align-items:center}
.badge{flex:none;width:48px;height:48px;border-radius:999px;background:var(--forest);color:var(--bg);font-weight:800;display:flex;align-items:center;justify-content:center;font-size:18px}
.target .badge{background:var(--burg);color:#fff}
.persona h3{font-size:16px;font-weight:800;line-height:1.25;font-family:Inter,"Segoe UI",Arial,sans-serif}
.target h3{color:#1A1A1A}
.pill{display:inline-block;background:#fff;color:#1A1A1A;font-size:13px;font-weight:800;border-radius:999px;padding:3px 10px;margin-top:4px}
.persona dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:14px}
.persona dt{color:var(--mute)}.target dt{color:#1A1A1A}
.persona dd{margin:0;font-weight:700}
.persona dd small{font-weight:400;color:var(--mute)}.target dd small{color:#1A1A1A}
.persona blockquote{margin:0;background:var(--bg);border-radius:14px;padding:10px 14px;font-size:14px}
.persona blockquote cite{display:block;margin-top:4px;font-size:12px;font-style:normal;color:var(--mute)}
.target blockquote{background:#fff}
/* quotes */
.notes{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(250px,100%),1fr));gap:16px;margin:18px 0 12px}
.sticky{border-radius:8px 8px 24px 8px;padding:20px 22px 16px;display:flex;flex-direction:column;justify-content:space-between;gap:14px;min-height:150px;color:#2B2B2B}
.sticky p{font-size:18px;line-height:1.4}
.sticky cite{font-size:13px;font-style:normal;font-weight:700;color:#3D3D3D}
.n0{background:#EBD9A0}.n1{background:var(--blush)}.n2{background:var(--sage)}.n3{background:var(--sand)}.n4{background:#F7F1E3}
/* implications, caveats */
.impl{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:20px}
.impl .card h3{font-size:19px;font-family:var(--serif)}
.impl .from{font-size:13px;font-weight:700;color:var(--burg)}
.caveat{margin-top:14px;background:var(--blush)}
/* formulas, method */
.fgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(310px,100%),1fr));gap:14px}
.fcard{background:var(--card);border-radius:20px;padding:16px 18px 12px;min-width:0}
.fcard h3{font-size:15px;font-weight:800;margin-bottom:4px}
.tex{overflow-x:auto;overflow-y:hidden;padding:2px 0}
.code{font:12px/1.4 Consolas,monospace;color:var(--mute);word-break:break-word}
.fcard p{font-size:14px;margin:6px 0}
.sil{display:grid;grid-template-columns:34px 1fr 50px;gap:4px 8px;align-items:center;font-size:13px;margin:6px 0}
.sil i{display:block;height:10px;border-radius:5px;background:var(--taupe)}.sil i.on{background:var(--burg)}
.twocol{display:grid;grid-template-columns:1.4fr 1fr;gap:14px;margin-top:16px}
.defs{display:grid;grid-template-columns:1fr 1fr;gap:10px 18px;margin-top:12px}.defs p{font-size:14px}
.tbls{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(380px,100%),1fr));gap:14px;margin-top:14px}
.tbls .card h3{font-size:15px}
ul.lim{padding-left:20px;margin:8px 0 0}ul.lim li{margin-bottom:6px}
ul.ctx{padding-left:20px}ul.ctx li{margin-bottom:8px}.cite{color:var(--mute);font-size:14px}
footer{padding-top:28px;padding-bottom:48px;font-size:14px;color:var(--mute)}
@media(max-width:900px){.cover-grid,.twocol,.defs{grid-template-columns:1fr}.board,.srcgrid{grid-template-columns:1fr 1fr}.span3{grid-column:span 2}.scqa{grid-template-columns:1fr 1fr}.impl,.tks{grid-template-columns:1fr}}
@media(max-width:700px){.board,.srcgrid,.scqa{grid-template-columns:1fr}.span2,.span3{grid-column:auto}
.mgrid{grid-template-columns:minmax(0,1fr);grid-template-areas:"stat" "q" "chart" "so" "rec"}.block{min-height:0}.band{grid-template-columns:1fr}}
/* ---- v3: McKinsey-style frame (hero, sticky nav, eyebrows), friendly infographics inside the cards */
.onpage{position:sticky;top:0;z-index:20;background:var(--bg)}
.onpage .w{display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;padding-top:10px;padding-bottom:10px;align-items:center}
.onpage .lab{flex:none;font-size:12px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;color:var(--mute);margin-right:6px}
.onpage a{flex:none;text-decoration:none;color:var(--head);font-size:13px;font-weight:700;padding:6px 12px;border-radius:999px}
.onpage a.on{background:var(--forest);color:var(--bg)}
.hero{background:var(--forest);color:var(--bg);border-radius:28px;padding:44px 40px 34px;display:flex;flex-direction:column;gap:22px}
.hero h1{font-size:clamp(30px,5vw,56px);line-height:1.06;font-weight:800;max-width:17em;color:var(--bg)}
.hero .lede{max-width:44em;font-size:18px;color:var(--bg)}
.hero .ans{background:var(--gold);color:#1A1A1A;border-radius:18px;padding:14px 20px;max-width:48em}
.hero .ans b{display:block;font-size:12.5px;letter-spacing:.07em;text-transform:uppercase}
.hero .ans h2{font-size:clamp(19px,2.2vw,24px);line-height:1.25;font-weight:800;color:#1A1A1A;margin-top:2px}
.hstats{display:grid;grid-template-columns:repeat(3,1fr);margin-top:4px}
.hstat{padding:4px 26px}.hstat:first-child{padding-left:0}.hstat+.hstat{border-left:1px solid var(--gold)}
.hstat .v{font-family:var(--serif);font-size:clamp(34px,5vw,54px);font-weight:800;line-height:1.05;color:var(--bg)}
.hstat .t{font-weight:700;margin-top:6px;line-height:1.3}.hstat .s{font-size:13px;margin-top:2px}
@media(max-width:700px){.hstats{grid-template-columns:1fr}.hstat+.hstat{border-left:0;border-top:1px solid var(--gold);padding:12px 0 0;margin-top:12px}.hero{padding:30px 22px 26px}}
.eyebrow,.kick,.qcard h3,.sowhat h3,.rec h3{text-transform:uppercase;letter-spacing:.07em;font-size:12.5px;font-weight:800}
.eyebrow{color:var(--mute);margin:0 0 6px}
.card h3{background:var(--forest);color:var(--bg);border-radius:999px;padding:4px 16px 4px 4px;width:fit-content;font-size:15px}
.card h3 .dot{width:30px;height:30px;background:var(--bg);color:var(--forest)}
.card h3:not(:has(.dot)){padding-left:16px}
.scqa .a h3{background:var(--gold);color:#1A1A1A}
.k-t h3{background:var(--forest)}
.avs{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(150px,100%),1fr));gap:12px}
.av{background:var(--card);border-radius:22px;padding:16px 12px;display:flex;flex-direction:column;align-items:center;text-align:center;gap:3px}
.avb{width:56px;height:56px;border-radius:999px;background:#6E625B;color:#fff;font-weight:800;display:flex;align-items:center;justify-content:center;font-size:19px}
.av.lead .avb{background:var(--burg)}
.av b{font-size:15px;color:var(--head)}
.av .avp{font-family:var(--serif);font-size:32px;font-weight:800;color:var(--burg);line-height:1.1}
.av small{font-size:12.5px;color:var(--mute);line-height:1.35}
.pics{display:grid;grid-template-columns:1.1fr 1.4fr;gap:14px}
.pics .card p{font-size:14px}
.pic{width:100%;height:auto;display:block}
.pic text{font-family:inherit}
.ring{margin-left:auto;flex:none}
.bigrow{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:20px}
.bnum{background:var(--forest);color:var(--bg);border-radius:22px;padding:18px 22px}
.bnum b{display:block;font-family:var(--serif);font-size:clamp(30px,4vw,44px);line-height:1.1}
.bnum span{font-size:14px}
.supp{display:inline-block;background:var(--gold);color:#1A1A1A;font-size:12.5px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;border-radius:999px;padding:3px 12px;margin-bottom:8px}
.sgrid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
.sgrid .a{background:var(--sand)}.sgrid .b{background:var(--blush)}
.sticky p{font-family:var(--serif);font-weight:500;font-style:italic;font-size:20px;line-height:1.38}
.team{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:16px}
.team .card h3{font-size:14px}
.result{margin-top:14px;background:var(--forest);color:var(--bg);border-radius:22px;padding:16px 22px}
.result a{color:var(--gold)}
@media(max-width:900px){.pics,.sgrid,.team{grid-template-columns:1fr}.bigrow{grid-template-columns:1fr 1fr}}

img{max-width:100%;height:auto}
html{scroll-behavior:smooth}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
.w{padding-left:max(20px,env(safe-area-inset-left));padding-right:max(20px,env(safe-area-inset-right))}
.plot{width:100%;min-height:var(--dh,0)}
.mobonly,.moblist{display:none}
.lc{background:var(--bg);border-radius:14px;padding:10px 14px;margin:0 0 8px;display:grid;grid-template-columns:1fr auto;gap:2px 10px}
.lc.hit{outline:3px solid var(--ink);outline-offset:-3px}
.lc b{color:var(--head);font-size:15px}.lc .z{font-family:var(--serif);font-weight:800;font-size:22px;color:var(--burg)}
.lc small{grid-column:1/-1;color:var(--mute);font-size:13px;line-height:1.4}
.fullimg{display:block;background:var(--sand);border-radius:14px;padding:10px;text-align:center;font-weight:700;font-size:14px;color:var(--head);text-decoration:none;min-height:44px}
.fullimg img{display:block;margin:0 auto 6px;border-radius:8px}
ul.alist{display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;padding:0;margin:4px 0 0;list-style:none;font-size:14px}
ul.alist li{display:flex;gap:6px;align-items:center}
.tex{max-width:100%;position:relative}
.board.two{grid-template-columns:1fr 1fr}
.gloss{font-size:13px;line-height:1.45;color:var(--mute);background:var(--sand);border-radius:12px;padding:8px 12px;margin:8px 0 0}
.gloss b{color:var(--head)}
.card.k-w .gloss,.card.k-q .gloss{background:rgba(255,255,255,.65)}
.lednote{font-size:13px;max-width:44em;opacity:.95;border-left:3px solid var(--gold);padding-left:12px}
.ctxgrid .supp{align-self:flex-start;margin:0 0 4px}
@media(max-width:639px){
 body{font-size:16px}
 .deskonly,.plot.hasl{display:none}.mobonly,.moblist{display:block}
 .plot{min-height:var(--mh,0)}
 .onpage a{min-height:44px;display:inline-flex;align-items:center;padding:0 14px}
 .onpage .w{padding-top:2px;padding-bottom:2px;padding-left:12px;padding-right:12px}
 .drawer>summary,.chartcard details>summary{min-height:44px}
 .chartcard{padding:14px 12px 10px}
 table,thead,tbody,tr,td,th{display:block}
 thead{display:none}
 table{overflow:visible}
 tr{background:var(--bg);border-radius:12px;padding:8px 12px;margin:0 0 8px}
 td{display:flex;justify-content:space-between;gap:12px;white-space:normal;padding:2px 0;background:none!important}
 td::before{content:attr(data-label);color:var(--mute);font-weight:700;flex:none;max-width:45%}
 .katex{font-size:.86em}
 .tex{overflow-x:auto}
 .board.two{grid-template-columns:1fr}
}
@page{size:A4 landscape;margin:0 0 11mm 0;
 @bottom-left{content:"Fieldnote Apparel | Social-listening study | Nov 2025 to Oct 2026";font:7.5pt Inter,"Segoe UI",Arial,sans-serif;color:#5C5750;padding-left:11mm}
 @bottom-right{content:counter(page);font:8pt Inter,"Segoe UI",Arial,sans-serif;color:#5C5750;padding-right:11mm}}
@media print{
 body{font-size:10pt;line-height:1.4}
 main{display:block}
 .w{max-width:none;padding:9mm 11mm 0}
 section.pg,.cover{padding-top:9mm}
 .cover,.pg{break-after:page}
 footer{break-after:auto}
 .plot,details,.src,.sub.screen,.hint,.screenonly{display:none!important}
 .pimg{display:block;max-width:100%;max-height:140mm;width:auto;height:auto;margin:0 auto}
 .track{margin-bottom:3mm;font-size:8pt}
 .cover-grid{gap:4mm}.block{min-height:150mm;padding:10mm;border-radius:7mm}.block h1{font-size:30pt}
 .answer{padding:9mm;border-radius:7mm}.answer h2{font-size:17pt}.client{font-size:12pt}
 .shead h2{font-size:21pt}
 .scqa{gap:4mm;margin-top:4mm}.tks{gap:4mm;margin-top:4mm}.tk{padding:3.5mm 5mm;border-radius:5mm}.tk p{font-size:10pt}
 .kpis{gap:3mm;margin-top:4mm}.kpi{padding:3.5mm 4mm;border-radius:5mm}.kpi b{font-size:19pt}.kpi .l{font-size:9pt}.kpi span.s{font-size:7.5pt}
 .base{font-size:8pt}
 .board,.ctxgrid,.srcgrid,.impl{gap:4mm;margin-top:5mm}.card{padding:5mm 6mm;border-radius:6mm;gap:2mm}.card h3{font-size:11pt}.card p,.card li{font-size:9.5pt}
 .bigstat{font-size:32pt}
 .band{padding:3.5mm 7mm;border-radius:6mm;margin-bottom:3mm;gap:1mm 5mm}.band h2{font-size:14pt}.band p{font-size:8.5pt}
 .mhead{margin-bottom:2mm;gap:2px 5mm}.num{font-size:34pt}.mhead h2{font-size:15pt}.kick{font-size:8.5pt;margin-bottom:0}
 .mgrid{grid-template-columns:1.9fr 1fr;gap:4mm;grid-template-areas:"chart stat" "chart q" "chart so" "chart rec";align-items:start}
 .chartcard{padding:4mm;border-radius:6mm}
 .stat,.qcard,.sowhat,.rec{padding:4mm 5mm;border-radius:6mm}
 .stat .v{font-size:27pt}.stat .t{font-size:10pt}.stat .s{font-size:7.5pt}
 .qcard p{font-size:8.5pt}.sowhat h3,.rec h3,.qcard h3{font-size:8.5pt;margin-bottom:1mm}
 .sowhat p,.rec p{font-size:9pt}
 .pgbreak{break-before:page;padding-top:9mm}
 .personas{grid-template-columns:repeat(3,1fr);gap:4mm}.persona{padding:4.5mm 5mm;border-radius:6mm;gap:2mm;break-inside:avoid}
 .persona dl,.persona blockquote{font-size:8.5pt}.persona h3{font-size:10pt}.badge{width:11mm;height:11mm;font-size:11pt}
 .notes{grid-template-columns:repeat(3,1fr);gap:5mm}.sticky p{font-size:11pt}.sticky{min-height:0;break-inside:avoid}
 .impl .card h3{font-size:13pt}
 .fgrid{display:block;column-count:2;column-gap:4mm}
 .fcard{break-inside:avoid;margin-bottom:4mm;padding:3mm 4mm;border-radius:5mm;font-size:8.5pt}
 .fcard p,.code{font-size:7.5pt;margin:2px 0}
 .tex{overflow:visible}.katex{font-size:.9em}.katex-display{margin:.25em 0!important}
 #formulas,#appx-tables,#sources{break-before:page}
 .twocol{gap:5mm}.defs p{font-size:8pt}
 .tbls{display:block;column-count:2;column-gap:4mm}.tbls .card{break-inside:avoid;margin-bottom:4mm;padding:3mm 4mm}
 table{display:table;font-size:7pt;margin-top:1mm}th,td{padding:1px 6px 1px 0}
 #method p,#method li,#context li,.ctxgrid p{font-size:9.5pt}
 footer{padding:4mm 11mm 0}
 .track{display:flex}
 .board{grid-template-columns:repeat(3,1fr)}.srcgrid{grid-template-columns:repeat(3,1fr)}.bigrow{grid-template-columns:repeat(4,1fr)}
 .scqa{grid-template-columns:repeat(4,1fr)}.tks,.impl,.team{grid-template-columns:repeat(3,1fr)}.pics{grid-template-columns:1.05fr 1.4fr}
 .sgrid{grid-template-columns:1fr 1fr}.twocol{grid-template-columns:1.4fr 1fr}.span2{grid-column:span 2}.span3{grid-column:span 3}
 .mini3{grid-template-columns:repeat(3,1fr)}.mini3 b{font-size:26pt}
 .gloss{font-size:7.5pt;padding:1.5mm 3mm;margin:1.5mm 0 0}.lednote{font-size:8pt}
 footer{display:none}#team{break-after:auto}
 .deskonly{display:block!important}.mobonly,.moblist{display:none!important}.qplot>svg{max-height:122mm}
 .sp .mhead h2{display:none}
 .pgrid{max-width:90mm}
 .onpage{display:none}
 .hero{padding:11mm 12mm 9mm;border-radius:7mm;min-height:178mm;gap:6mm}.hero h1{font-size:31pt}.hero .lede{font-size:11pt}
 .hero .ans{padding:4mm 6mm;border-radius:5mm}.hero .ans h2{font-size:13pt}
 .hstat .v{font-size:30pt}.hstat .t{font-size:10pt}.hstat .s{font-size:8pt}
 .avs{grid-template-columns:repeat(5,1fr);gap:3mm}.av{padding:3mm 2mm;border-radius:5mm}.avb{width:11mm;height:11mm;font-size:12pt}.av b{font-size:9pt}.av .avp{font-size:17pt}.av small{font-size:7pt}
 .pics{gap:4mm}.pics .card p{font-size:8.5pt}
 .bigrow{gap:4mm;margin-top:5mm}.bnum{padding:4mm 5mm;border-radius:5mm}.bnum b{font-size:22pt}.bnum span{font-size:8.5pt}
 .sgrid{gap:4mm}.team{gap:4mm}.result{padding:4mm 6mm;border-radius:5mm}
 .card h3{font-size:10pt}.card h3 .dot{width:7mm;height:7mm}.card h3 .dot .ic{width:4.5mm;height:4.5mm}
 #m1 .pimg{max-height:104mm}#m3 .pimg{max-height:84mm}
 .leg{font-size:8pt;gap:2px 8px;margin:1mm 0}.leg i{width:2.4mm;height:2.4mm}
 #m1 .chartcard,#m3 .chartcard{padding:3mm}
 .eyebrow,.kick,.qcard h3,.sowhat h3,.rec h3{font-size:7.5pt}
 .supp{font-size:7.5pt;padding:1mm 3mm}
 .sticky p{font-size:11.5pt}
}
"""

JS = """
var MQ=window.matchMedia('(max-width:639px)');
var CFG={responsive:true,displayModeBar:false,scrollZoom:false,displaylogo:false,doubleClick:false};
function draw(el){
  if(!el.offsetParent)return;                       // hidden at this width (a phone shows a card list instead of a heatmap)
  var cfg=JSON.parse(document.getElementById('d-'+el.dataset.chart).textContent);
  var m=MQ.matches&&cfg.m, f=m?cfg.m:cfg.d, key=m?'m':'d';
  if(el.dataset.mode===key)return;
  if(el.dataset.mode)Plotly.purge(el);
  el.dataset.mode=key;
  Plotly.newPlot(el,f.data,f.layout,CFG);
}
function drawAll(){[].slice.call(document.querySelectorAll('.plot[data-chart]')).forEach(draw);}
function texAll(){[].slice.call(document.querySelectorAll('.tex')).forEach(function(el){
  try{katex.render(el.dataset.tex,el,{displayMode:true,throwOnError:false});}catch(e){}
});}
drawAll();texAll();
var chg=function(){drawAll();texAll();};
if(MQ.addEventListener)MQ.addEventListener('change',chg);else MQ.addListener(chg);
window.addEventListener('orientationchange',function(){setTimeout(drawAll,250);});
(function(){
  var links=[].slice.call(document.querySelectorAll('.onpage a')),map={};
  links.forEach(function(a){map[a.dataset.ch]=a;});
  if(!('IntersectionObserver' in window))return;
  var io=new IntersectionObserver(function(es){es.forEach(function(e){
    if(e.isIntersecting){links.forEach(function(a){a.classList.remove('on');});var a=map[e.target.dataset.ch];if(a)a.classList.add('on');}
  });},{rootMargin:'-40% 0px -55% 0px'});
  [].slice.call(document.querySelectorAll('[data-ch]')).forEach(function(el){if(!el.matches('.onpage a'))io.observe(el);});
})();
"""


def esc(s):
    return html.escape(s, quote=True)


# minimum chart width in px on a phone; narrower screens scroll the chart sideways instead of crushing the labels
MIN_W = {"01-top-of-mind": 420, "02-penetration-proxy": 560, "03-profiling": 640, "04-perceptual-map": 560,
         "05-positioning-residuals": 660, "06-perception": 640, "07-segments": 760, "08-interest-trend": 640,
         "quadrant": 640, "09-brand-funnel": 700, "10-positioning-map": 600, "11-brand-image-grid": 840,
         "12-image-strengths": 700, "13-image-priority": 560}


def png_wh(slug):
    head = Path(lp(CH / (slug + ".png"))).read_bytes()[:24]
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def table_html(tbl):
    h, rows = tbl
    return ("<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>"
            % ("".join("<th>%s</th>" % esc(x) for x in h),
               "".join("<tr>%s</tr>" % "".join('<td data-label="%s">%s</td>' % (esc(h[i]), esc(x)) for i, x in enumerate(r)) for r in rows)))


def mob_list(slug):
    """Phones get ranked cards instead of a heatmap: the largest or flagged cells, with counts; the full chart opens on tap."""
    cards = []
    if slug == "05-positioning-residuals":
        p = M["positioning"]
        asr, cnt, bz = p["adjusted_std_residuals"], p["counts"], p["bonferroni_z"]
        brands, attrs, n = p["brands_in_matrix"], p["attributes"], p["chi_square"]["n"]
        rt = {b: sum(cnt[b][a] for a in attrs) for b in brands}
        ct = {a: sum(cnt[b][a] for b in brands) for a in attrs}
        cells = sorted(((b, a) for b in brands for a in attrs), key=lambda k: -abs(asr[k[0]][k[1]]))[:8]
        for b, a in cells:
            z = asr[b][a]
            cards.append('<div class="lc%s"><b>%s %s</b><span class="z">%+.2f</span><small>%d sentences observed vs %.1f expected%s</small></div>'
                         % (" hit" if abs(z) > bz else "", esc(b + ("" if b in CORE else " (non-core)")) + " x", attr_icon(a, 16) + " " + esc(a), z,
                            cnt[b][a], rt[b] * ct[a] / n, "; survives Bonferroni" if abs(z) > bz else ""))
        head = "The 8 largest cells, by adjusted residual. Outlined cards survive Bonferroni (|z| > %.2f)." % bz
    elif slug == "11-brand-image-grid":
        bi = SUP["brand_image"]
        gr = bi["association_grid"]
        for b in bi["brands_in_grid"]:
            top = sorted(gr[b], key=lambda k: -gr[b][k]["pct"])[:3]
            cards.append('<div class="lc"><b>%s</b><small>%s</small></div>' % (esc(b), "<br>".join(
                "%s %.1f%% (CI %.0f to %.0f), %d of %d" % (esc(i), gr[b][i]["pct"], gr[b][i]["ci95"][0], gr[b][i]["ci95"][1], gr[b][i]["k"], gr[b][i]["base"]) for i in top)))
        head = "Each brand's three most common images, as a share of its image-coded sentences."
    else:
        bi = SUP["brand_image"]
        for c in bi["strengths_and_weaknesses_bonferroni"]["cells"]:
            rd = "flagged, association not endorsement" if c["reading"] == "strength" else "flagged (association)"
            cards.append('<div class="lc hit"><b>%s x %s</b><span class="z">%+.2f</span><small>%d observed vs %.1f expected; %s</small></div>'
                         % (esc(c["brand"]), esc(c["image"]), c["z"], c["observed"], c["expected"], rd))
        head = "The %d cells above the Bonferroni threshold (|z| > %.1f)." % (len(cards), bi["bonferroni_z"])
    w, h = png_wh(slug)
    return ('<div class="moblist"><p class="note">%s</p>%s<a class="fullimg" href="charts/%s.png"><img loading="lazy" src="charts/%s.png" width="%d" height="%d" '
            'alt="Full chart">Tap to open the full chart</a></div>' % (head, "".join(cards), slug, slug, w, h))


def quadrant_m_svg():
    """Portrait quadrant for phones: larger type, brand chips on leader lines, attribute icons only (names in the list below)."""
    ca = M["positioning"]["correspondence_analysis"]
    rows, cols, pc = ca["row_coords_dim1_2"], ca["col_coords_dim1_2"], ca["axis_inertia_pct"]
    W, H, L, R, T, B = 450, 640, 40, 14, 10, 100
    sx = lambda v: L + (v + 0.8) / 1.3 * (W - L - R)
    sy = lambda v: T + (0.3 - v) / 1.02 * (H - T - B)
    x0, y0 = sx(0), sy(0)
    chip = {"Uniqlo": (395, 100), "Aritzia": (402, 172), "Old Navy": (392, 208), "H&M": (262, 140), "Zara": (252, 222),
            "Shein": (180, 200), "Everlane": (332, 524)}
    out = ['<svg class="quad" viewBox="0 0 %d %d" role="img" aria-label="Positioning quadrant for phones: brands as chips, attributes as icons, listed below.">' % (W, H)]
    for (xa, xb, ya, yb, fill) in ((L, x0, T, y0, "#EFE6D6"), (x0, W - R, T, y0, "#F8F3EA"), (L, x0, y0, H - B, "#F8F3EA"), (x0, W - R, y0, H - B, "#EFE6D6")):
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>' % (xa, ya, xb - xa, yb - ya, fill))
    for a, v in cols.items():
        px, py = sx(v[0]), sy(v[1])
        out.append('<circle cx="%.1f" cy="%.1f" r="14" fill="#fff" stroke="#8D8079" stroke-width="1.5" data-kind="attribute" data-name="%s" data-x="%s" data-y="%s"/>'
                   % (px, py, esc(a), v[0], v[1]))
        out.append('<g transform="translate(%.1f %.1f) scale(.75)" fill="none" stroke="#5C5750" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">%s</g>'
                   % (px - 9, py - 9, ATTR_ICON[a]))
    for b, v in rows.items():
        px, py = sx(v[0]), sy(v[1])
        cx, cy = chip[b]
        fill = "#8F2323" if b in CORE else "#6E625B"
        w = 10 * len(b) + 26
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.5"/>' % (px, py, cx, cy, fill))
        out.append('<circle cx="%.1f" cy="%.1f" r="6" fill="%s" data-kind="brand" data-name="%s" data-x="%s" data-y="%s"/>' % (px, py, fill, esc(b), v[0], v[1]))
        out.append('<rect x="%.1f" y="%.1f" width="%d" height="28" rx="14" fill="%s"/>' % (cx - w / 2, cy - 14, w, fill))
        out.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="15" font-weight="700" fill="#fff">%s</text>' % (cx, cy + 5, esc(b)))
    n1, p1 = axis_ends(cols, 0)
    lab = lambda xs: " and ".join(xs)
    out.append('<text x="%d" y="%d" font-size="14" font-weight="700" fill="#1F493D">%s</text>' % (L, H - 62, "← " + lab(n1)))
    out.append('<text x="%d" y="%d" text-anchor="end" font-size="14" font-weight="700" fill="#1F493D">%s</text>' % (W - R, H - 40, lab(p1) + " →"))
    out.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="14" fill="#5C5750">Axis 1 (%.1f%% of variation)</text>' % ((L + W - R) / 2, H - 14, pc[0]))
    out.append('<text transform="translate(16 %.1f) rotate(-90)" text-anchor="middle" font-size="14" fill="#5C5750">Axis 2 (%.1f%% of variation)</text>' % ((T + H - B) / 2, pc[1]))
    out.append("</svg>")
    al = "".join('<li>%s %s</li>' % (attr_icon(a, 18), esc(a)) for a in sorted(cols, key=lambda a: cols[a][0]))
    return "".join(out) + '<p class="note" style="margin-top:8px">Attributes on the map, from the left to the right of axis 1:</p><ul class="alist">%s</ul>' % al


def fig_html(slug, c, screen_only=False):
    fd = render(c, png=False)
    fd.update_layout(dragmode=False, hovermode="closest")
    mh, fm = c["hh"], None
    mb = MOB_BUILDERS.get(slug)
    if mb:
        cm = mb()
        fm = render(cm, png=False)
        fm.update_layout(dragmode=False, hovermode="closest")
        mh = cm["hh"]
    blob = json.dumps({"d": json.loads(fd.to_json()), "m": json.loads(fm.to_json()) if fm is not None else None}).replace("</", "<\\/")
    lst = mob_list(slug) if slug in MOB_LIST else ""
    w, h = png_wh(slug)
    return ('<div class="chartcard%s"><figure><p class="sub screen"><b>%s.</b> %s</p>'
            '<div class="plot%s" data-chart="%s" role="img" aria-label="%s" style="--dh:%dpx;--mh:%dpx"></div>'
            '<script type="application/json" id="d-%s">%s</script>%s'
            '<img class="pimg" src="charts/%s.png" width="%d" height="%d" loading="lazy" alt="%s">'
            '<p class="src">%s</p><details><summary>Data table</summary>%s</details></figure></div>'
            % (" screenonly deskonly" if screen_only else "", esc(c["title"]), esc(c["sub"]), " hasl" if lst else "", slug, esc(alt_for(c)), c["hh"], mh,
               slug, blob, lst, slug, w, h, esc(alt_for(c)), esc(footnote(c)), table_html(c["table"])))




FKEYS = ["wilson", "net", "share", "pen", "chi", "ca", "kmeans", "kappa", "pearson"]


def tex(s, **kw):
    for k, v in kw.items():
        s = s.replace("<<%s>>" % k, str(v))
    return '<div class="tex" data-tex="%s">%s</div>' % (esc(s), esc(s))


def fcard(title, body, source, formula_key=None):
    code = '<p class="code">metrics.json: %s</p>' % esc(D["formulas"][formula_key]) if formula_key else ""
    return '<div class="fcard"><h3>%s</h3>%s%s<p class="note">Source: %s</p></div>' % (title, body, code, source)


def formulas_html():
    t, pp, pf = M["top_of_mind"], M["penetration_proxy"], M["profiling"]
    pe, pc, sg, tr = M["perception"], M["positioning"], M["segmentation"], M["trend"]
    out = []
    u = t["first_mention"]["Uniqlo"]
    lo, hi = wilson(u["k"], u["base"])
    out.append(fcard("Wilson 95% interval", tex(
        r"\hat p=\frac{k}{n},\qquad \mathrm{CI}_{95}=\frac{\hat p+\frac{z^2}{2n}\pm z\sqrt{\frac{\hat p(1-\hat p)}{n}+\frac{z^2}{4n^2}}}{1+\frac{z^2}{n}},\; z=1.96")
        + "<p>Run value, Uniqlo first mention: k=%d, n=%d, so p=%.3f and the interval is %.1f%% to %.1f%% (matches metrics.json)</p>"
        % (u["k"], u["base"], u["k"] / u["base"], lo, hi),
        "Wilson (1927), J. American Statistical Association 22(158):209-212. Used for every interval in this report; "
        "shown only where the base is at least 30.", "wilson_95"))
    z = pe["by_brand"]["Zara"]
    nneu = z["base"] - z["pos"]["k"] - z["neg"]["k"]
    out.append(fcard("Net sentiment", tex(
        r"\mathrm{net}=\frac{n_{pos}-n_{neg}}{n_{pos}+n_{neg}+n_{neu}}") + tex(
        r"\mathrm{Zara}:\ \frac{<<p>>-<<n>>}{<<p>>+<<n>>+<<u>>}=<<r>>", p=z["pos"]["k"], n=z["neg"]["k"], u=nneu,
        r="%.3f" % z["net_sentiment"]),
        "Hutto and Gilbert (2014), VADER, Proc. ICWSM: compound score; positive at 0.05 or more, negative at -0.05 or less. "
        "The share-difference definition is the one recorded in metrics.json.", "net_sentiment"))
    out.append(fcard("First-mention and total-mention share", tex(
        r"\mathrm{first}_b=\frac{k^{first}_b}{n},\qquad \mathrm{total}_b=\frac{k^{total}_b}{n}")
        + tex(r"\mathrm{Uniqlo}:\ \frac{<<a>>}{<<n>>}=<<pa>>\%,\qquad \frac{<<b>>}{<<n>>}=<<pb>>\%", a=u["k"], n=u["base"],
              pa="%.1f" % u["pct"], b=t["total_mention"]["Uniqlo"]["k"], pb="%.1f" % t["total_mention"]["Uniqlo"]["pct"])
        + "<p>n counts top-level replies that name any brand; total-mention shares can sum to more than 100%.</p>",
        "Standard share of a multiple-response base; definitions in data/README.md (Methods, item 1).", "top_of_mind_first"))
    zp = pp["general_subreddits_only"]["by_brand"]["Zara"]
    out.append(fcard("Penetration proxy", tex(
        r"\mathrm{pen}_b=\frac{\#\text{ authors with an ownership phrase about } b}{\#\text{ authors with any brand mention}}")
        + tex(r"\mathrm{Zara}:\ \frac{<<k>>}{<<n>>}=<<p>>\%", k=zp["k"], n=zp["base"], p="%.1f" % zp["pct"])
        + "<p>A proxy by construction: phrase matching and a base of brand-talkers only.</p>",
        "Proportion with a Wilson interval; the ownership-phrase list is in metrics.json (dictionaries.ownership_phrases).",
        "penetration_proxy"))
    ch = pc["chi_square"]
    sh = "Shein"
    at = "sustainability/ethics"
    cnt = pc["counts"]
    attrs, brands = pc["attributes"], pc["brands_in_matrix"]
    rt = sum(cnt[sh][a] for a in attrs)
    ctt = sum(cnt[b][at] for b in brands)
    e = rt * ctt / ch["n"]
    zz = (cnt[sh][at] - e) / math.sqrt(e * (1 - rt / ch["n"]) * (1 - ctt / ch["n"]))
    out.append(fcard("Chi-square, adjusted residual, Bonferroni", tex(
        r"\chi^2=\sum\frac{(O-E)^2}{E},\quad E=\frac{\mathrm{row}\cdot\mathrm{col}}{n},\quad \mathrm{df}=(R-1)(C-1)")
        + tex(r"\chi^2=<<c>>,\ \mathrm{df}=(<<R>>-1)(<<C>>-1)=<<d>>,\ n=<<n>>", c=ch["chi2"], R=len(brands), C=len(attrs),
              d=ch["df"], n=ch["n"])
        + tex(r"z=\frac{O-E}{\sqrt{E\left(1-\frac{\mathrm{row}}{n}\right)\left(1-\frac{\mathrm{col}}{n}\right)}}")
        + tex(r"\mathrm{Shein,\ sustainability/ethics}:\ O=<<o>>,\ E=<<e>>,\ z=<<z>>", o=cnt[sh][at], e="%.1f" % e,
              z="%.2f" % zz)
        + tex(r"|z|>\Phi^{-1}\!\left(1-\tfrac{0.05/m}{2}\right)=<<b>>,\ \ m=<<m>>\text{ cells}", b="%.2f" % pc["bonferroni_z"],
              m=ch["cells"])
        + "<p>Hits are not independent (one author can add several), so p-values are indicative.</p>",
        "Haberman (1973), Biometrics 29(1):205-220 (adjusted residuals); Agresti (2002), Categorical Data Analysis; "
        "Dunn (1961), J. American Statistical Association 56(293):52-64 (Bonferroni).", "adjusted_std_residual"))
    ca = pc["correspondence_analysis"]
    out.append(fcard("Correspondence analysis", tex(
        r"P=N/n,\quad S=D_r^{-1/2}\,(P-rc^{\top})\,D_c^{-1/2}=UDV^{\top}") + tex(
        r"\lambda_k=d_k^{2},\quad \sum_k\lambda_k=\frac{\chi^2}{n}")
        + tex(r"\frac{\chi^2}{n}=\frac{<<c>>}{<<n>>}=<<t>>,\quad \lambda_1=<<l1>>\ (<<p1>>\%),\ \lambda_2=<<l2>>\ (<<p2>>\%)",
              c=ch["chi2"], n=ch["n"], t=ca["total_inertia"], l1=ca["axis_inertia"][0], p1=ca["axis_inertia_pct"][0],
              l2=ca["axis_inertia"][1], p2=ca["axis_inertia_pct"][1])
        + "<p>Row coordinates are U D / sqrt(r), column coordinates V D / sqrt(c); the axis percentages label the map.</p>",
        "Benzecri (1973), L'analyse des donnees; Greenacre (2017), Correspondence Analysis in Practice, 3rd ed., CRC Press.",
        "correspondence_analysis"))
    sil = sg["silhouette_by_k"]
    bars = "".join('<span>k=%s</span><i class="%s" style="width:%d%%"></i><span>%.3f</span>'
                   % (k, "on" if int(k) == sg["k"] else "", v / max(sil.values()) * 100, v) for k, v in sil.items())
    out.append(fcard("k-means and silhouette", tex(
        r"\min\sum_{j=1}^{k}\sum_{x\in C_j}\lVert x-\mu_j\rVert^{2}") + tex(
        r"s(i)=\frac{b(i)-a(i)}{\max\{a(i),b(i)\}},\quad \bar s=\frac1N\sum_i s(i)")
        + "<p>a(i): mean distance to the author's own group; b(i): mean distance to the nearest other group. "
          "Mean silhouette by number of groups (N=%d authors):</p><div class=\"sil\">%s</div>"
          "<p>k=%d is the highest (%.3f); a value this low means weak separation.</p>"
        % (sg["eligible_authors"], bars, sg["k"], sil[str(sg["k"])]),
        "Lloyd (1982), IEEE Trans. Information Theory 28(2):129-137; Rousseeuw (1987), J. Computational and Applied "
        "Mathematics 20:53-65; scikit-learn (Pedregosa et al., 2011, JMLR 12:2825-2830), 10 starts, seed 0.", "kmeans"))
    vv = pe["vader_validation"]
    cm = vv["confusion_human_rows_vader_cols"]
    labs = ["pos", "neu", "neg"]
    rows_ = [sum(cm[a].values()) for a in labs]
    cols_ = [sum(cm[a][b] for a in labs) for b in labs]
    po = sum(cm[a][a] for a in labs) / vv["n"]
    pe_ = sum(r * c for r, c in zip(rows_, cols_)) / vv["n"] ** 2
    out.append(fcard("Cohen's kappa (VADER check)", tex(
        r"\kappa=\frac{p_o-p_e}{1-p_e},\qquad p_e=\sum_i\frac{r_i\,c_i}{N^{2}}")
        + tex(r"p_o=\tfrac{<<a>>}{<<n>>}=<<po>>,\ \ p_e=<<pe>>,\ \ \kappa=\frac{<<po>>-<<pe>>}{1-<<pe>>}=<<k>>",
              a=sum(cm[a][a] for a in labs), n=vv["n"], po="%.2f" % po, pe="%.3f" % pe_, k="%.2f" % vv["cohens_kappa"])
        + "<p>Agreement %d%% (Wilson 95%% CI %.1f%% to %.1f%%); kappa 0.45 reads as moderate. One labeller, so no "
          "inter-rater reliability.</p>" % (round(vv["agreement"] * 100), vv["agreement_ci95"][0] * 100, vv["agreement_ci95"][1] * 100),
        "Cohen (1960), Educational and Psychological Measurement 20(1):37-46; Landis and Koch (1977), Biometrics 33(1):159-174 "
        "(bands). Not in metrics.json formulas; computed from its confusion matrix.", None))
    rr = tr["pearson_r_views_vs_mentions"]
    out.append(fcard("Pearson r (trend)", tex(
        r"r=\frac{\sum_t(x_t-\bar x)(y_t-\bar y)}{\sqrt{\sum_t(x_t-\bar x)^2\,\sum_t(y_t-\bar y)^2}}")
        + "<p>x: Wikipedia views per month, y: brand-mentioning items per month, t = %d months. Run values: %s. "
          "Descriptive only.</p>" % (len(tr["months"]), "; ".join("%s %+.2f" % (b, rr[b]["r"]) for b in CORE)),
        "Pearson (1895), Proc. Royal Society of London 58:240-242. The formula is not listed in metrics.json; "
        "the r values are, and build.py recomputes them.", None))
    return dict(zip(FKEYS, out))


FONTS_LINK = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
              '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=Playfair+Display:ital,wght@0,700;0,800;1,500&display=swap">')

ICONS = {
    "question": '<circle cx="12" cy="12" r="10"/><path d="M9.5 9.2a2.6 2.6 0 1 1 3.6 2.4c-.8.4-1.1.9-1.1 1.8M12 17v.01"/>',
    "listen": '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
    "star": '<path d="M12 2.5l3 6.6 7 .7-5.3 4.7 1.6 7L12 17.8 5.7 21.5l1.6-7L2 9.8l7-.7z"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "alert": '<path d="M12 3L2 21h20z"/><path d="M12 10v5M12 18v.01"/>',
    "arrow": '<path d="M4 12h16M14 6l6 6-6 6"/>',
}


def icon(name):
    return '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">%s</svg>' % ICONS[name]


def attr_icon(name, size=20):
    return ('<svg class="ic" width="%d" height="%d" viewBox="0 0 24 24" aria-hidden="true">%s</svg>' % (size, size, ATTR_ICON[name]))


def nf(n):
    return format(n, ",")


def win_label():
    a = date.fromisoformat(D["meta"]["window"][0])
    b = date.fromisoformat(D["meta"]["window"][1]) - timedelta(1)
    return "%s to %s" % (a.strftime("%b %Y"), b.strftime("%b %Y"))


# storyline tracker (breadcrumb, shown on every PDF page); the current chapter is highlighted
TRACK = [("S", "Summary"), ("A", "A Brand health"), ("B", "B Who is talking"), ("C", "C Brand image"),
         ("D", "D Segments"), ("I", "Implications")]


def tracker(cur):
    return '<nav class="track" aria-label="Storyline">%s</nav>' % ' <i>&rsaquo;</i> '.join(
        '<span%s>%s</span>' % (' class="on" aria-current="step"' if k == cur else "", esc(t)) for k, t in TRACK)


ONPAGE = [("S", "summary", "Summary"), ("K", "context", "Market"), ("A", "m1", "Brand health"), ("B", "m3", "Who is talking"),
          ("C", "m4", "Image &amp; positioning"), ("D", "m6", "Segments"), ("I", "implications", "Implications"),
          ("X", "appx", "Method"), ("T", "team", "The team")]


def onpage():
    return ('<nav class="onpage" aria-label="On this page"><div class="w"><span class="lab">On this page</span>%s</div></nav>'
            % "".join('<a href="#%s" data-ch="%s">%s</a>' % (i, k, t) for k, i, t in ONPAGE))


def alt_for(c):
    rows = "; ".join(" ".join(str(x) for x in r[:4]) for r in c["table"][1][:8])
    return ("%s. %s Values: %s." % (c["title"], c["sub"], rows))[:900]


def kpis():
    t, pf, sg = M["top_of_mind"], M["profiling"], M["segmentation"]
    bb, vv = M["perception"]["by_brand"], M["perception"]["vader_validation"]
    lead = max(t["first_mention"], key=lambda b: t["first_mention"][b]["pct"])
    age = pf["coverage_brand_mentioning_authors"]["age"]
    s1 = sg["segments"][0]
    items = [
        ("%.1f%%" % t["first_mention"][lead]["pct"], "%s named first" % lead,
         "n=%d brand-naming replies; %d of %d threads menswear" % (t["replies_naming_a_brand"], t["threads_by_subreddit"]["malefashionadvice"], t["threads_with_replies"])),
        ("%.1f%%" % age["pct"], "Authors who state an age", "%d of %s brand-mentioning authors" % (age["k"], nf(age["base"]))),
        ("%.1f%% vs %.1f%%" % (bb["Zara"]["neg"]["pct"], bb["Uniqlo"]["neg"]["pct"]), "Negative sentences, Zara vs Uniqlo",
         "n=%d and n=%d; the tool understates negativity" % (bb["Zara"]["base"], bb["Uniqlo"]["base"])),
        ("%.1f%%" % s1["share_of_eligible"]["pct"], "Segment 1 (Zara-led) share",
         "%d of %d authors; 95%% CI %.1f%% to %.1f%%" % (s1["authors"], s1["share_of_eligible"]["base"], s1["share_of_eligible"]["ci95"][0], s1["share_of_eligible"]["ci95"][1])),
        ("%.3f" % sg["silhouette_by_k"][str(sg["k"])], "Silhouette at k=%d" % sg["k"], "highest of k=2 to 6, still weak"),
        ("%d%%" % round(vv["agreement"] * 100), "VADER agreement with hand labels", "kappa %.2f, n=%d, one labeller" % (vv["cohens_kappa"], vv["n"])),
    ]
    s = D["sample"]
    base = "Base: %s Reddit items from %s authors, %s; %s brand-mentioning authors, %s single-brand sentences." % (
        nf(s["reddit_items"]), nf(s["reddit_authors"]), WIN, nf(s["authors_mentioning_a_brand"]), nf(s["single_brand_sentences"]))
    return ('<div class="kpis">%s</div><p class="base">%s</p>%s'
            % ("".join('<div class="kpi"><span class="l">%s</span><b>%s</b><span class="s">%s</span></div>' % (esc(l), esc(v), esc(n))
                       for v, l, n in items), esc(base), gloss("vader", "kappa", "sil")))


def module_stat(n):
    """(big number, plain label, small print with n and CI) for module n, all from metrics.json."""
    t, pf, sg = M["top_of_mind"], M["profiling"], M["segmentation"]
    ci = lambda m: "95%% CI %.1f%% to %.1f%%" % tuple(m["ci95"])
    if n == 1:
        lead = max(t["first_mention"], key=lambda b: t["first_mention"][b]["pct"])
        m = t["first_mention"][lead]
        return ("%.1f%%" % m["pct"], "of brand-naming replies name %s first" % lead, "n=%d replies; %s" % (m["base"], ci(m)))
    if n == 2:
        bb = M["penetration_proxy"]["general_subreddits_only"]["by_brand"]
        lo, hi = band([bb[b] for b in CORE])
        return ("%.1f%% to %.1f%%" % (lo, hi), "the range all five brands' ownership-talk intervals share",
                "n=%s authors who mentioned a brand; each brand's own 95%% CI is wider" % nf(bb[CORE[0]]["base"]))
    if n == 3:
        m = pf["coverage_brand_mentioning_authors"]["age"]
        return ("%.1f%%" % m["pct"], "of brand-mentioning authors state an age", "%d of %s authors; %s" % (m["k"], nf(m["base"]), ci(m)))
    if n == 4:
        p = M["positioning"]
        cells = [c for c in p["significant_cells"] if c["survives_bonferroni"] and c["brand"] in CORE]
        c = max(cells, key=lambda c: abs(c["z"]))
        return ("%d vs %d" % (c["observed"], round(c["expected"])), "%s talk about %s: sentences found vs about %d expected"
                % (c["brand"], c["attribute"].replace("/ethics", " and ethics"), round(c["expected"])),
                "exact expected count: %.1f" % c["expected"])
    if n == 5:
        bb = M["perception"]["by_brand"]
        w = max(CORE, key=lambda b: bb[b]["neg"]["pct"])
        m = bb[w]["neg"]
        return ("%.1f%%" % m["pct"], "of %s's sentences are negative" % w, "n=%d sentences; %s; VADER understates negativity" % (m["base"], ci(m)))
    s1 = sg["segments"][0]
    m = s1["share_of_eligible"]
    return ("%.1f%%" % m["pct"], "of eligible authors are in Segment 1, the Zara-led group", "%d of %d authors; %s" % (s1["authors"], m["base"], ci(m)))


# ---- Powerslides-style infographics that carry real numbers
def avatar_cards():
    fm = M["top_of_mind"]["first_mention"]
    names = sorted(CORE, key=lambda b: (-fm[b]["pct"], b))
    out = []
    for i, b in enumerate(names):
        m = fm[b]
        out.append('<div class="av%s"><span class="avb" aria-hidden="true">%s</span><b>%s</b><div class="avp">%.1f%%</div>'
                   '<small>named first<br>n=%d, 95%% CI %.1f%% to %.1f%%</small></div>'
                   % (" lead" if i == 0 else "", "H&amp;M" if b == "H&M" else b[0], esc(b), m["pct"], m["base"], m["ci95"][0], m["ci95"][1]))
    return '<div class="avs">%s</div>' % "".join(out)


PERSON = '<symbol id="person" viewBox="0 0 24 24"><circle cx="12" cy="6.5" r="4"/><path d="M4.5 22v-2.5A6 6 0 0 1 10.5 13.5h3a6 6 0 0 1 6 6V22z"/></symbol>'


def pic_grid(n_fill, total=100, cols=20, size=17, gap=4, color="#8F2323", off="#D8CAA9"):
    rows = -(-total // cols)
    W, H = cols * (size + gap), rows * (size + gap)
    us = "".join('<use href="#person" x="%d" y="%d" width="%d" height="%d" fill="%s"/>'
                 % ((i % cols) * (size + gap), (i // cols) * (size + gap), size, size, color if i < n_fill else off) for i in range(total))
    return '<svg class="pic pgrid" viewBox="0 0 %d %d" role="img" aria-label="%d of %d icons filled">%s</svg>' % (W, H, n_fill, total, us)


def pic_row(groups, size=22, gap=5, per_row=17):
    """groups: (count, colour, label). One person icon per author in a wrapped array, with a coloured legend under it."""
    cells = [col for cnt, col, _ in groups for _ in range(cnt)]
    rows = -(-len(cells) // per_row)
    W, H = min(per_row, len(cells)) * (size + gap), rows * (size + gap)
    us = "".join('<use href="#person" x="%d" y="%d" width="%d" height="%d" fill="%s"/>'
                 % ((i % per_row) * (size + gap), (i // per_row) * (size + gap), size, size, col) for i, col in enumerate(cells))
    leg = "".join('<span><i style="background:%s"></i>%s</span>' % (col, esc(lab)) for _, col, lab in groups)
    return ('<svg class="pic" style="max-width:%dpx" viewBox="0 0 %d %d" role="img" aria-label="%s">%s</svg><p class="leg">%s</p>'
            % (W, W, H, esc("; ".join(l for _, _, l in groups)), us, leg))


def pictograms():
    pf = M["profiling"]
    age = pf["coverage_brand_mentioning_authors"]["age"]
    n_fill = round(100 * age["k"] / age["base"])
    gen = pf["generation_of_brand_mentioning_authors"]
    gz = [k for k in gen if k.startswith("Gen Z")][0]
    ml = [k for k in gen if k.startswith("Millennial")][0]
    ol = [k for k in gen if k.startswith("Older")][0]
    gnd = pf["gender_of_brand_mentioning_authors"]
    cty = pf["country_of_brand_mentioning_authors"]
    g_f, g_m = gnd["female"]["k"], gnd["male"]["k"]
    c_us, c_ca = cty["US"]["k"], cty["Canada"]["k"]
    left = ('<div class="card"><h3>Who states an age</h3>%s<p><b>%d of %s</b> brand-mentioning authors state an age: %.2f%%, shown as %d of 100 icons '
            '(rounded to the nearest whole icon).</p></div>' % (pic_grid(n_fill), age["k"], nf(age["base"]), age["pct"] if False else 100 * age["k"] / age["base"], n_fill))
    mid = ('<div class="card"><h3>The %d who do</h3>%s<p>%d Gen Z, %d Millennial, %d aged 46 or older (one icon per author). '
           'The Gen Z and Millennial intervals overlap.</p>'
           '<h3 style="margin-top:6px">Gender and country</h3>%s%s<p class="note">Base too small for percentages: %d authors reported gender, %d reported country.</p></div>'
           % (age["k"], pic_row([(gen[gz]["k"], "#8F2323", "%d Gen Z" % gen[gz]["k"]), (gen[ml]["k"], "#1F493D", "%d Millennial" % gen[ml]["k"]),
                                 (gen[ol]["k"], "#BF9B30", "%d older" % gen[ol]["k"])]),
              gen[gz]["k"], gen[ml]["k"], gen[ol]["k"],
              pic_row([(g_f, "#1F493D", "%d female" % g_f), (g_m, "#8D8079", "%d male" % g_m)], size=18),
              pic_row([(c_us, "#1F493D", "%d US" % c_us), (c_ca, "#8D8079", "%d Canada" % c_ca)], size=18),
              g_f + g_m, c_us + c_ca))
    return ('<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>%s</defs></svg><div class="pics">%s%s</div>' % (PERSON, left, mid))


def ring(pct, size=64, track="#EEE0CA"):
    r = 26
    c = 2 * math.pi * r
    return ('<svg class="ring" width="%d" height="%d" viewBox="0 0 64 64" role="img" aria-label="%.1f%% of eligible authors">'
            '<circle cx="32" cy="32" r="%d" fill="none" stroke="%s" stroke-width="8"/>'
            '<circle cx="32" cy="32" r="%d" fill="none" stroke="#8F2323" stroke-width="8" stroke-dasharray="%.2f %.2f" transform="rotate(-90 32 32)"/>'
            '<text x="32" y="36" text-anchor="middle" font-size="13" font-weight="800" fill="#1F1B16">%.1f%%</text></svg>'
            % (size, size, pct, r, track, r, c * pct / 100, c, pct))


# ---- positioning quadrant (CA coordinates as brand chips and attribute icons)
Q_OFF = {  # (dx, dy, anchor) of each label relative to its dot, in svg px
    "Aritzia": (12, 3, "start"), "Zara": (0, 20, "middle"), "H&M": (0, -16, "middle"), "Shein": (0, 20, "middle"),
    "Uniqlo": (12, -2, "start"), "Old Navy": (12, 12, "start"), "Everlane": (0, 20, "middle"),
    "price/value": (0, 28, "middle"), "quality/durability": (0, -18, "middle"), "fit/sizing": (16, -2, "start"),
    "style/trend": (0, -18, "middle"), "sustainability/ethics": (0, 28, "middle"), "shipping/returns": (0, -18, "middle"),
    "customer service": (0, -18, "middle"), "store experience": (0, 28, "middle"),
}
AX_MIN = 0.25   # an axis end is named only from attributes at least this far out on that side


def axis_ends(cols, k):
    neg = sorted([a for a, v in cols.items() if v[k] <= -AX_MIN], key=lambda a: cols[a][k])[:2]
    pos = sorted([a for a, v in cols.items() if v[k] >= AX_MIN], key=lambda a: -cols[a][k])[:2]
    return neg, pos


def quadrant():
    ca = M["positioning"]["correspondence_analysis"]
    rows, cols, pc = ca["row_coords_dim1_2"], ca["col_coords_dim1_2"], ca["axis_inertia_pct"]
    W, H, L, R, T, B = 900, 560, 50, 14, 10, 52
    xr, yr = (-0.8, 0.5), (-0.72, 0.3)
    sx = lambda v: L + (v - xr[0]) / (xr[1] - xr[0]) * (W - L - R)
    sy = lambda v: T + (yr[1] - v) / (yr[1] - yr[0]) * (H - T - B)
    x0, y0 = sx(0), sy(0)
    out = ['<svg class="quad" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (W, H, "ALTQ")]
    for (xa, xb, ya, yb, fill) in ((L, x0, T, y0, "#EFE6D6"), (x0, W - R, T, y0, "#F8F3EA"),
                                   (L, x0, y0, H - B, "#F8F3EA"), (x0, W - R, y0, H - B, "#EFE6D6")):
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>' % (xa, ya, xb - xa, yb - ya, fill))
    pts = []
    for a, v in cols.items():
        px, py = sx(v[0]), sy(v[1])
        dx, dy, an = Q_OFF[a]
        out.append('<circle cx="%.1f" cy="%.1f" r="12" fill="#fff" stroke="#8D8079" stroke-width="1.5" data-kind="attribute" data-name="%s" data-x="%s" data-y="%s"/>'
                   % (px, py, esc(a), v[0], v[1]))
        out.append('<g transform="translate(%.1f %.1f) scale(.67)" fill="none" stroke="#5C5750" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">%s</g>'
                   % (px - 8, py - 8, ATTR_ICON[a]))
        out.append('<text x="%.1f" y="%.1f" text-anchor="%s" font-size="14" fill="#5C5750">%s</text>' % (px + dx, py + dy + 4, an, esc(a)))
        pts.append(("attribute", a, v[0], v[1]))
    for b, v in rows.items():
        px, py = sx(v[0]), sy(v[1])
        dx, dy, an = Q_OFF[b]
        fill = "#8F2323" if b in CORE else "#6E625B"
        w = 9 * len(b) + 22
        cx = px + dx if an == "start" else px + dx - w / 2
        cy = py + dy - 11
        out.append('<circle cx="%.1f" cy="%.1f" r="5" fill="%s" data-kind="brand" data-name="%s" data-x="%s" data-y="%s"/>' % (px, py, fill, esc(b), v[0], v[1]))
        out.append('<rect x="%.1f" y="%.1f" width="%d" height="24" rx="12" fill="%s"/>' % (cx, cy, w, fill))
        out.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="14" font-weight="700" fill="#fff">%s</text>' % (cx + w / 2, cy + 16, esc(b)))
        pts.append(("brand", b, v[0], v[1]))
    n1, p1 = axis_ends(cols, 0)
    n2, p2 = axis_ends(cols, 1)
    lab = lambda xs: " and ".join(xs)
    yb = H - 14
    out.append('<text x="%d" y="%d" font-size="14" font-weight="700" fill="#1F493D">%s</text>' % (L, yb, ("← " + lab(n1)) if n1 else "←"))
    out.append('<text x="%.1f" y="%d" text-anchor="end" font-size="14" font-weight="700" fill="#1F493D">%s</text>' % (W - R, yb, (lab(p1) + " →") if p1 else "→"))
    out.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="14" fill="#5C5750">Axis 1 (%.1f%% of variation)</text>' % ((L + W - R) / 2, H - 32, pc[0]))
    out.append('<text transform="translate(14 %.1f) rotate(-90)" text-anchor="middle" font-size="14" fill="#5C5750">Axis 2 (%.1f%% of variation)</text>'
               % ((T + H - B) / 2, pc[1]))
    out.append("</svg>")
    alt = ("Positioning quadrant. Brands (red chips) and attributes (icons) at their correspondence-analysis coordinates. Axis 1 (%.1f%% of variation) runs from %s "
           "to %s. Shein sits at the sustainability and shipping end; Uniqlo, Aritzia, H&M, Zara and Old Navy cluster on the fit, style and price side." % (pc[0], lab(n1), lab(p1)))
    svg = "".join(out).replace("ALTQ", esc(alt))
    named = ("Axis 1 ends are named from the attributes sitting furthest out on that side. " + (
        "Axis 2 is not named: no attribute sits clearly out on either side of it (all within %.2f of the centre), and the one brand far out on it is non-core Everlane." % AX_MIN
        if not (n2 or p2) else "Axis 2 ends are named the same way."))
    card = ('<div class="chartcard"><figure><p class="sub"><b>Positioning quadrant: brands and attributes.</b> Each chip is a brand, each icon an attribute; '
            'a brand sits near the attributes it is talked about for. Red chips are core brands, grey is not in the core set.</p>'
            '<div class="qplot deskonly">%s</div><div class="qplot mobonly">%s</div>'
            '<p class="src">%s Source: data/metrics.json, modules.positioning.correspondence_analysis; Reddit (general subreddits) via Arctic Shift; collection window %s. '
            'Icons are simple line drawings in the style of Lucide (ISC licence).</p>'
            '</figure></div>' % (svg, quadrant_m_svg(), esc(named), WIN))
    return card, pts, (n1, p1, n2, p2)


# ---- board, personas
def next_text():
    t = REPORT["next"][len("Next step: "):] if REPORT["next"].startswith("Next step: ") else REPORT["next"]
    return t[0].upper() + t[1:]


def brief_questions():
    txt = (EX / "brief.md").read_text(encoding="utf8")
    sec = re.search(r"^## Business question\n(.*?)^## ", txt, re.M | re.S).group(1)
    return " ".join(sec.strip().split("\n\n")[0].split()), re.findall(r"^\d\. (.+)$", sec, re.M)


def pick_limit(key):
    hit = [x for x in REPORT["limits"] if key in x]
    assert len(hit) == 1, key
    return hit[0]


GL = {
    "z": "<i>z</i> (adjusted standardized residual) is how far above or below the expected count a cell is",
    "bonf": "Bonferroni is a stricter bar for calling a cell unusual, because we test many cells at once",
    "sil": "silhouette is how distinct the groups are, from 0 (not at all) to 1 (clearly separate)",
    "vader": "VADER is an automatic positive/negative word scorer",
    "kappa": "kappa is agreement beyond chance",
    "ca": "correspondence analysis is a map that puts brands and attributes close together when they are often talked about together",
}


def gloss(*keys):
    return '<p class="gloss"><b>In plain words.</b> %s.</p>' % "; ".join(GL[k] for k in keys)


def board_html():
    R = REPORT
    intro, qs = brief_questions()
    s = D["sample"]
    listened = ("Public Reddit posts and comments, %s: %s items from %s authors; %s of those authors mention a brand. "
                "Also App Store store-level ratings (review text could not be collected) and Wikipedia page views. This is social listening, not a survey."
                % (win_label(), nf(s["reddit_items"]), nf(s["reddit_authors"]), nf(s["authors_mentioning_a_brand"])))
    finds = '<div class="mini3">%s</div>' % "".join(
        '<div><b>%s</b><span>%s</span><small>%s</small></div>' % (esc(module_stat(n)[0]), esc(module_stat(n)[1]), esc(module_stat(n)[2])) for n in (4, 5, 3))
    watch = "<ul>%s</ul>%s" % ("".join("<li>%s</li>" % esc(pick_limit(k)) for k in (
        "not a representative", "menswear", "VADER agreement", "Segments are weak")), gloss("vader", "sil"))
    s1 = M["segmentation"]["segments"][0]["share_of_eligible"]
    nxt = next_text()
    return (
        '<div class="board">'
        '<div class="card k-q"><h3><span class="dot">%s</span>Business question</h3><p>%s</p><ol>%s</ol></div>'
        '<div class="card"><h3><span class="dot">%s</span>Who we listened to</h3><p>%s</p></div>'
        '<div class="card k-t"><h3><span class="dot">%s</span>Target segment</h3><div class="bigstat">%.1f%%</div><p>%s</p></div>'
        '<div class="card span3"><h3><span class="dot">%s</span>3 key findings</h3>%s</div>'
        '<div class="card k-w span2"><h3><span class="dot">%s</span>Watch-outs</h3>%s</div>'
        '<div class="card k-n"><h3><span class="dot">%s</span>Next step</h3><p>%s</p></div>'
        '</div>' % (icon("question"), esc(intro), "".join("<li>%s</li>" % esc(q) for q in qs), icon("listen"), esc(listened),
                    icon("target"), s1["pct"], esc(R["target"]), icon("star"), finds, icon("alert"), watch, icon("arrow"), esc(nxt)))


def personas_html():
    sg = M["segmentation"]
    tgt = int(re.search(r"Segment (\d)", REPORT["target"]).group(1))
    cards = []
    for s in sg["segments"]:
        lb = max(s["top_brands_share_of_mentions"], key=s["top_brands_share_of_mentions"].get)
        la = max(s["top_attributes_share_of_mentions"], key=s["top_attributes_share_of_mentions"].get)
        qs = (_qj.get(lb, {}).get(la, {}).get("quotes") or [None])[0]
        sz, ng = s["share_of_eligible"], s["sentiment"]["neg"]
        is_t = s["segment"] == tgt
        quote = ('<blockquote>&ldquo;%s&rdquo;<cite>%s, %s (rule-selected quote)</cite></blockquote>' % (esc(qs["text"]), esc(lb), esc(la))
                 if qs else '<p class="note">No rule-selected quote exists for %s, %s.</p>' % (esc(lb), esc(la)))
        cards.append(
            '<article class="persona%s"><div class="phead"><span class="badge">S%d</span><div><h3>%s</h3>%s</div>%s</div>'
            '<dl><dt>Size</dt><dd>%.1f%% <small>of eligible authors (n=%d, 95%% CI %.1f%% to %.1f%%)</small></dd>'
            '<dt>Lead brand</dt><dd>%s <small>%.1f%% of its brand mentions</small></dd>'
            '<dt>Talks most about</dt><dd>%s %s <small>%.1f%% of its sentences</small></dd>'
            '<dt>Net sentiment</dt><dd>%+.3f</dd>'
            '<dt>Negative share</dt><dd>%.1f%% <small>(n=%d, 95%% CI %.1f%% to %.1f%%)</small></dd></dl>%s</article>'
            % (" target" if is_t else "", s["segment"], esc(seg_name(s)),
               '<span class="pill">Recommended target</span>' if is_t else "", ring(sz["pct"], track="#F5ECCF" if is_t else "#EEE0CA"),
               sz["pct"], sz["base"], sz["ci95"][0], sz["ci95"][1], esc(lb), s["top_brands_share_of_mentions"][lb],
               attr_icon(la, 16), esc(la), s["top_attributes_share_of_mentions"][la], s["sentiment"]["net_sentiment"], ng["pct"], ng["base"],
               ng["ci95"][0], ng["ci95"][1], quote))
    return ('<div class="personas">%s</div><p class="note" style="margin-top:10px">Badges are segment numbers, not people. The ring is the segment\'s share of the %d eligible authors. '
            'No age, gender or country profile is shown for any segment: the base per segment is too small (report.md).</p>'
            % ("".join(cards), sg["eligible_authors"]))


FMODS = {1: ["wilson", "share"], 2: ["pen", "wilson"], 3: ["wilson"], 4: ["chi", "ca"], 5: ["net", "kappa", "wilson"],
         6: ["kmeans", "wilson"]}
CHAPTER = {"A": ("Brand health: who is top of mind and who converts", (1, 2)),
           "B": ("Who is talking", (3,)),
           "C": ("Brand image and positioning: what each brand stands for", (4, 5)),
           "D": ("Segments and target", (6,))}
MOD_CHAPTER = {1: "A", 2: "A", 3: "B", 4: "C", 5: "C", 6: "D"}


def chapter_band(letter):
    title, mods = CHAPTER[letter]
    qs = " ".join(m["Question"] for m in REPORT["mods"] if m["n"] in mods)
    return ('<div class="band"><span class="chip">Chapter %s</span><h2>%s</h2><p><b>This chapter answers:</b> %s</p></div>'
            % (letter, esc(title), esc(qs)))


def mod_block(m, FC, charts, after="", first_of_chapter=False, extra_note="", lead=""):
    n = m["n"]
    cur = MOD_CHAPTER[n]
    v, lbl, small = module_stat(n)
    drawer = ('<details class="drawer"><summary>How we calculated this</summary><div class="fgrid">%s</div></details>'
              % "".join(FC[k] for k in FMODS[n]))
    ev = "".join("<li>%s</li>" % esc(b) for b in m["bullets"])
    return (
        '<section class="mod pg w" id="m%d" data-ch="%s">%s%s<div class="mhead"><div class="num">%02d</div><div><p class="kick">Module %02d &middot; %s</p>'
        '<h2>%s</h2></div></div>'
        '<div class="mgrid"><div class="stat"><div class="v">%s</div><div class="t">%s</div><div class="s">%s</div></div>'
        '<div class="qcard"><div><h3>The question</h3><p>%s</p></div><div><h3>The decision</h3><p>%s</p></div></div>'
        '<div class="chartwrap">%s<p class="eyebrow">What we found</p>%s%s</div>'
        '<div class="sowhat"><h3>So what</h3><p>%s</p></div>'
        '<div class="rec"><h3>What Fieldnote should do</h3><p>%s</p></div></div>%s%s'
        '<details class="drawer"><summary>Evidence as written in the audited report</summary><ul>%s</ul></details></section>'
        % (n, cur, tracker(cur), chapter_band(cur) if first_of_chapter else "", n, n, esc(m["kicker"]), esc(m["title"]), esc(v), esc(lbl),
           esc(small), esc(m["Question"]), esc(m["Decision"]), lead, charts, extra_note, esc(m["So what"]), esc(m["Recommendation"]),
           after, drawer, ev))


def supp_block(sid, cur, title, chart_html, shows, care, drawer_keys=(), FC=None):
    drawer = ""
    if drawer_keys:
        drawer = ('<details class="drawer"><summary>How we calculated this</summary><div class="fgrid">%s</div></details>'
                  % "".join(FC[k] for k in drawer_keys))
    return ('<section class="mod pg w sp" id="%s" data-ch="%s">%s<span class="supp">Supplementary, not audited</span>'
            '<div class="mhead"><div class="num">+</div><div><p class="kick">Added after the audited keeploop cycle; not part of report.md</p><h2>%s</h2></div></div>'
            '<p class="eyebrow">What we found</p><div class="chartwrap">%s</div>'
            '<div class="sgrid"><div class="card a"><h3>What the chart shows</h3><p>%s</p></div>'
            '<div class="card b"><h3>Read with care</h3><p>%s</p></div></div>%s</section>'
            % (sid, cur, tracker(cur), esc(title), chart_html, esc(shows), esc(care), drawer))


def caveats():
    """Known issues in the audited report, found by comparing its claims with the charted intervals."""
    pe = M["perception"]["by_brand"]
    seg = M["segmentation"]["segments"]
    p = M["positioning"]
    z, h = pe["Zara"]["neg"], pe["H&M"]["neg"]
    sh = pe["Shein"]["neg"]
    assert sh["pct"] > z["pct"] and z["ci95"][0] <= h["ci95"][1]
    s1, s4 = seg[0]["sentiment"]["neg"], seg[3]["sentiment"]["neg"]
    u = [c for c in p["significant_cells"] if c["brand"] == "Uniqlo" and c["attribute"] == "style/trend"][0]
    assert z["ci95"][0] <= h["ci95"][1] and s1["ci95"][0] <= s4["ci95"][1]
    return [
        "Module 05's title says Shein and Zara draw more negative sentences than Aritzia, Uniqlo or H&M, but Zara's interval (%.1f%% to %.1f%%) overlaps H&M's (%.1f%% to %.1f%%). Only the gap to Aritzia and Uniqlo is clear of overlap."
        % (z["ci95"][0], z["ci95"][1], h["ci95"][0], h["ci95"][1]),
        "Module 06 says Segment 1 carries a higher negative share than the Uniqlo-led group, but their intervals overlap (%.1f%% to %.1f%% vs %.1f%% to %.1f%%). Only the Aritzia-led group is clearly lower."
        % (s1["ci95"][0], s1["ci95"][1], s4["ci95"][0], s4["ci95"][1]),
        "The Summary says to position on trend and fit, while module 04 ties style/trend to Uniqlo (z=%+.2f, survives Bonferroni). The audit of the report already flagged this as the next card (run/cycle-2/audit.txt)." % u["z"],
        "The Summary says Zara is discussed mostly for price and quality, but module 04 finds that price/value and quality/durability come up for every core brand, so they do not differentiate Zara from the others.",
        "The Summary's phrase \"the most open dissatisfaction\" is an unsupported superlative: Zara's negative share (%.1f%% to %.1f%%) overlaps H&M's, and Shein's (%.1f%%) is higher than Zara's (%.1f%%)."
        % (z["ci95"][0], z["ci95"][1], sh["pct"], z["pct"]),
    ]


IMPL = [("Where to play", "the segment", (6,)), ("How to win", "positioning", (4, 5)), ("What to validate", "in the survey", (1, 2, 3))]


def parse_definitions():
    txt = (EX / "data" / "README.md").read_text(encoding="utf8")
    sec = txt.split("## Methods and formulas")[1].split("## Quotes")[0]
    items = re.findall(r"^(\d)\. \*\*(.+?)\*\*\s+(.+)$", sec, re.M)
    assert len(items) == 7
    return items


def keeploop_result():
    """baseline / best / audit verdict from the cycle-2 transcript, for the credits."""
    t = (EX / "run" / "cycle-2" / "transcript.txt").read_text(encoding="utf8")
    m = re.search(r"baseline:\s*(\S+)\s+best:\s*(\S+)", t)
    assert m and "APPROVED" in t and "KEPT" in t
    return m.group(1), m.group(2)


def supp_texts():
    """Plain descriptions for the three supplementary parts, computed from metrics.json."""
    fb = SUP["funnel"]["by_brand"]
    cs = [fb[b]["considering"]["share_of_aware"]["pct"] for b in CORE]
    bt = [fb[b]["bought"]["share_of_aware"]["pct"] for b in CORE]
    conv = [fb[b]["bought"]["conversion_from_previous_stage"] for b in CORE if fb[b]["bought"]["conversion_from_previous_stage"]["pct"] is not None]
    small = [b for b in CORE if fb[b]["bought"]["conversion_from_previous_stage"]["pct"] is None]
    t9 = ("Among authors who mentioned each core brand, %.1f%% to %.1f%% also used a considering phrase and %.1f%% to %.1f%% a purchase phrase. "
          "Where the step has at least 30 authors, %.0f%% to %.0f%% of Considering authors are also Bought."
          % (min(cs), max(cs), min(bt), max(bt), min(c["pct"] for c in conv), max(c["pct"] for c in conv)))
    c9_ = ("Advocate is 0 or 1 author per brand, so it is not measurable and not drawn. Considering is almost the same as Bought, because most Considering authors "
           "qualified through a purchase phrase. %s's Considering to Bought step is base too small. These are phrase counts in public posts, not survey funnel rates." % ", ".join(small))
    pm = SUP["positioning_map"]["by_brand"]
    t10 = ("Price/value share runs from %.1f%% (%s) to %.1f%% (%s, not a core brand); style/trend share is highest for %s at %.1f%%."
           % (min(pm[b]["x_price_value_share"]["pct"] for b in CORE), min(CORE, key=lambda b: pm[b]["x_price_value_share"]["pct"]),
              max(v["x_price_value_share"]["pct"] for v in pm.values()), max(pm, key=lambda b: pm[b]["x_price_value_share"]["pct"]),
              max(pm, key=lambda b: pm[b]["y_style_trend_share"]["pct"]), max(v["y_style_trend_share"]["pct"] for v in pm.values())))
    c10_ = ("The 95%% intervals are wide and most overlap on price share, so differences between the core brands on price are not clear. Shares are of attribute hits, "
            "not of consumers. Old Navy and Everlane are not in the core set.")
    bi = SUP["brand_image"]
    gr = bi["association_grid"]
    tops = []
    for b in bi["brands_in_grid"]:
        i = max(gr[b], key=lambda k: gr[b][k]["pct"])
        tops.append("%s: %s %.1f%%" % (b, i, gr[b][i]["pct"]))
    t11 = "The image carried by the largest share of each brand's image-coded sentences: %s. The set average for that image differs by brand." % "; ".join(tops)
    c11_ = ("Shares of talk, not of consumers. %s has too few image-coded sentences (%d) and the wider brands are base too small. A keyword can match without praise."
            % ("Aritzia", bi["coded_sentences_per_brand"]["Aritzia"]))
    cells = bi["strengths_and_weaknesses_bonferroni"]["cells"]
    t12 = ("%d cells pass the Bonferroni threshold (|z| > %.1f): %s." % (len(cells), bi["bonferroni_z"], "; ".join(
        "%s %s %s (%+.2f)" % (c["brand"], c["image"], c["direction"], c["z"]) for c in cells)))
    sh = [c for c in cells if c["brand"] == "Shein" and c["image"] == "ethical/responsible"][0]
    c12_ = ("Shein's ethical/responsible flag rests on %d sentences and is mostly critical ethics talk: association, not endorsement. It is not read as a strength. "
            "Cell sentiment is base too small for every flagged cell except Uniqlo basic/everyday." % sh["observed"])
    pq = bi["priority_quadrant"]["by_brand"]
    placed = [(b, c) for b, v in pq.items() for c in v.get("cells_n_ge_30", [])]
    unplaced = sum(v.get("cells_below_30_not_placed", 0) for v in pq.values())
    t13 = ("%d cell is placed: %s, %s (n=%d, %.2f times the set average, net sentiment %+.2f), which the rule puts in the \"%s\" quadrant. %d other brand x image cells have fewer than 30 sentences and are not placed."
           % (len(placed), placed[0][0], placed[0][1]["image"], placed[0][1]["n"], placed[0][1]["index_vs_set_average"], placed[0][1]["net_sentiment"], placed[0][1]["quadrant"], unplaced))
    c13_ = "Aritzia has too few image-coded sentences (%d) to be placed. The quadrant sorts one cell; it does not rank the brands." % bi["coded_sentences_per_brand"]["Aritzia"]
    return {"09": (t9, c9_), "10": (t10, c10_), "11": (t11, c11_), "12": (t12, c12_), "13": (t13, c13_)}


def build_html(figs_cache):
    R = REPORT
    client, _, study = R["h1"].partition(": ")
    FC = formulas_html()
    quad_card, QUAD_PTS, QUAD_AX = quadrant()
    build_html.quad = (QUAD_PTS, QUAD_AX)
    intro, qs = brief_questions()
    mods = {m["n"]: m for m in R["mods"]}
    ctxs = parse_context()
    s = D["sample"]
    cache = figs_cache
    bb = M["perception"]["by_brand"]
    segm = M["segmentation"]["segments"][0]["share_of_eligible"]

    stats = [(nf(s["reddit_items"]), "Reddit items analysed", "from %s authors, %s" % (nf(s["reddit_authors"]), win_label())),
             ("%.1f%%" % bb["Zara"]["neg"]["pct"], "of Zara's sentences are negative", "n=%d, 95%% CI %.1f%% to %.1f%%; Uniqlo %.1f%%" % (
                 bb["Zara"]["base"], bb["Zara"]["neg"]["ci95"][0], bb["Zara"]["neg"]["ci95"][1], bb["Uniqlo"]["neg"]["pct"])),
             ("%.1f%%" % M["top_of_mind"]["first_mention"]["Uniqlo"]["pct"], "of brand-naming replies name Uniqlo first", "n=%d replies, 95%% CI %.1f%% to %.1f%%; %d of %d threads are menswear" % (
                 M["top_of_mind"]["replies_naming_a_brand"], M["top_of_mind"]["first_mention"]["Uniqlo"]["ci95"][0], M["top_of_mind"]["first_mention"]["Uniqlo"]["ci95"][1],
                 M["top_of_mind"]["threads_by_subreddit"]["malefashionadvice"], M["top_of_mind"]["threads_with_replies"]))]
    cover = (
        '<header class="cover" data-ch="S"><div class="w"><div class="hero"><div class="chips"><span class="chip">Consumer insight study</span>'
        '<span class="chip">Social listening, %s</span></div>'
        '<div><p class="client">%s &middot; fictional client</p><h1>%s</h1></div>'
        '<p class="lede">%s</p><p class="lednote">Reader\'s note: two phrases in this summary are not fully backed by the charts, '
        '"mostly for price and quality" and "the most open dissatisfaction"; see Caveats on the evidence.</p>'
        '<div class="ans"><b>The answer in one line</b><h2>%s</h2></div>'
        '<div class="hstats">%s</div></div></div></header>'
        % (win_label(), esc(client), esc(study), esc(R["sum_text"]), esc(R["sum_title"]),
           "".join('<div class="hstat"><div class="v">%s</div><div class="t">%s</div><div class="s">%s</div></div>' % (esc(v), esc(t), esc(sm)) for v, t, sm in stats)))

    cx = "Core competitive set: %s." % ", ".join(CORE)
    comp = ("%s The market is also moving (external context from cited sources, not listening data): store closures, "
            "new US import rules and fast US growth at Aritzia." % cx)
    scqa = (
        '<section class="pg w" id="summary" data-ch="S">%s<div class="shead"><p class="kick">Executive summary</p><h2>%s</h2></div>'
        '<div class="scqa">'
        '<div class="card"><h3>Situation</h3><p>%s</p></div>'
        '<div class="card"><h3>Complication</h3><p>%s</p></div>'
        '<div class="card"><h3>Question</h3><p>%s</p></div>'
        '<div class="card a"><h3>Answer (a hypothesis to validate)</h3><p>%s</p></div></div>'
        '<div class="tks">%s</div>%s</section>'
        % (tracker("S"), esc(R["sum_title"]), esc(intro.split(". ")[0] + "."), esc(comp),
           esc(qs[0].rstrip(".") + ", and " + qs[1][0].lower() + qs[1][1:]), esc(R["target"]),
           "".join('<div class="tk"><b>Takeaway %d, module %02d</b><p>%s</p></div>' % (i + 1, n, esc(mods[n]["title"]))
                   for i, n in enumerate((4, 5, 6))), kpis()))

    board = ('<section class="pg w" id="board" data-ch="S">%s<div class="shead"><p class="kick">Summary</p><h2>The board at a glance</h2></div>%s</section>'
             % (tracker("S"), board_html()))

    context = ('<section class="pg w" id="context" data-ch="K">%s<div class="shead"><p class="kick">Market context</p><h2>What is changing around the five brands</h2>'
               '<p class="lead">External context from the cited sources, for interpretation only. None of these figures comes from the listening data.</p></div>'
               '<div class="ctxgrid">%s</div></section>'
               % (tracker("S"), "".join('<div class="card"><span class="supp">External context, not listening data</span><p>%s</p><p class="cite">Source: %s</p></div>'
                                        % (esc(b), esc(c)) for b, c in ctxs)))

    ap = M["perception"]["appstore"]["store_level_ratings_from_itunes_lookup"]
    nthreads = M["top_of_mind"]["threads_with_replies"]
    listened = (
        '<section class="pg w" id="listened" data-ch="S">%s<div class="shead"><p class="kick">Method in brief</p><h2>Who we listened to</h2>'
        '<p class="lead">Evidence is social listening, not a survey. Full method, definitions and formulas are in the appendix.</p></div>'
        '<div class="bigrow"><div class="bnum"><b>%s</b><span>Reddit items</span></div><div class="bnum"><b>%s</b><span>authors</span></div>'
        '<div class="bnum"><b>%d</b><span>recommendation threads</span></div><div class="bnum"><b>%d</b><span>months, %s</span></div></div>'
        '<div class="srcgrid">'
        '<div class="card k-q"><h3>Reddit</h3><p>%s posts and %s comments, collected through the Arctic Shift archive. %s authors mention a brand; %s single-brand sentences feed sentiment and positioning.</p></div>'
        '<div class="card"><h3>App Store</h3><p>Store-level US ratings only (all-time, not a sample): %s. Review text could not be collected.</p></div>'
        '<div class="card"><h3>Wikipedia</h3><p>Monthly English page views for the five core brands, used only as a descriptive trend.</p></div>'
        '</div><div class="card k-w" style="margin-top:14px"><h3>Main caveats</h3><ul>%s</ul></div></section>'
        % (tracker("S"), nf(s["reddit_items"]), nf(s["reddit_authors"]), nthreads, len(M["trend"]["months"]), win_label(),
           nf(s["reddit_posts"]), nf(s["reddit_comments"]), nf(s["authors_mentioning_a_brand"]), nf(s["single_brand_sentences"]),
           ", ".join("%s %.2f" % (b, ap[b]["avg_rating_us"]) for b in CORE),
           "".join("<li>%s</li>" % esc(pick_limit(k)) for k in ("not a representative", "menswear", "Top-of-mind, penetration", "VADER agreement"))))

    ST = supp_texts()
    # chapter A
    secA = mod_block(mods[1], FC, fig_html("01-top-of-mind", cache["01-top-of-mind"]), first_of_chapter=True, lead=avatar_cards())
    secA += mod_block(mods[2], FC, fig_html("02-penetration-proxy", cache["02-penetration-proxy"]))
    secA += supp_block("s09", "A", cache["09-brand-funnel"]["title"],
                       fig_html("09-brand-funnel", cache["09-brand-funnel"]), ST["09"][0], ST["09"][1], ("wilson",), FC)
    secA += ('<section class="mod pg w" id="m7" data-ch="A">%s<div class="mhead"><div class="num">+</div><div><p class="kick">Supporting view</p>'
             "<h2>Public interest in each core brand over the 12 months</h2></div></div>"
             '<p class="note" style="margin-bottom:12px">Descriptive only. The audited report draws no conclusion from this chart, so there is no so-what or recommendation here.</p>%s</section>'
             % (tracker("A"), fig_html("08-interest-trend", cache["08-interest-trend"])))
    # chapter B
    secB = mod_block(mods[3], FC, fig_html("03-profiling", cache["03-profiling"]), first_of_chapter=True, lead=pictograms())
    # chapter C
    detail = ('<div class="pgbreak"></div><div class="chartwrap" style="margin-top:14px">%s%s</div>'
              % (fig_html("05-positioning-residuals", cache["05-positioning-residuals"]),
                 fig_html("04-perceptual-map", cache["04-perceptual-map"], screen_only=True)))
    secC = mod_block(mods[4], FC, quad_card, after=detail, first_of_chapter=True, extra_note=gloss("z", "bonf", "ca"))
    secC += supp_block("s10", "C", cache["10-positioning-map"]["title"],
                       fig_html("10-positioning-map", cache["10-positioning-map"]), ST["10"][0], ST["10"][1])
    extra5 = ('<p class="note">App Store review text could not be collected. Store-level US averages (all-time, not a sample): %s.</p>'
              % ", ".join("%s %.2f" % (b, ap[b]["avg_rating_us"]) for b in CORE))
    secC += mod_block(mods[5], FC, fig_html("06-perception", cache["06-perception"]), extra_note=extra5 + gloss("vader", "kappa"))
    secC += supp_block("s11", "C", cache["11-brand-image-grid"]["title"],
                       fig_html("11-brand-image-grid", cache["11-brand-image-grid"]), ST["11"][0], ST["11"][1], ("wilson",), FC)
    secC += supp_block("s12", "C", cache["12-image-strengths"]["title"],
                       fig_html("12-image-strengths", cache["12-image-strengths"]), ST["12"][0], ST["12"][1] + " In plain words: " + "; ".join(
                           re.sub("<[^>]+>", "", GL[k]) for k in ("z", "bonf")) + ".", ("chi",), FC)
    secC += supp_block("s13", "C", cache["13-image-priority"]["title"],
                       fig_html("13-image-priority", cache["13-image-priority"]), ST["13"][0], ST["13"][1])
    # chapter D
    secD = mod_block(mods[6], FC, fig_html("07-segments", cache["07-segments"]), first_of_chapter=True, extra_note=gloss("sil"),
                     after='<div class="pgbreak"></div>' + personas_html())

    notes = "".join(
        '<div class="sticky n%d"><p>&ldquo;%s&rdquo;</p><cite>%s, %s &middot; cell of %d sentences</cite></div>'
        % (i % 5, esc(q), esc(b), esc(a), QCELL[(b, a)]) for i, (q, b, a) in enumerate(QUOTES))
    quotes = ('<section class="pg w" id="quotes" data-ch="C">%s<div class="shead"><p class="kick">In their words</p><h2>Quotes, one per brand from the price/value cell</h2></div>'
              '<div class="notes">%s</div><p class="note"><b>Quote rule.</b> %s</p></section>'
              % (tracker("C"), notes, esc(R["mods"][3]["quote_rule"])))

    # implications
    cols = []
    for head, sub, ns in IMPL:
        items = "".join('<p class="from">Module %02d, %s</p><p>%s</p>' % (n, esc(mods[n]["kicker"]), esc(mods[n]["Recommendation"])) for n in ns)
        cols.append('<div class="card"><h3>%s <span style="font-weight:600">(%s)</span></h3>%s</div>' % (head, sub, items))
    cav = "".join("<li>%s</li>" % esc(c) for c in caveats())
    impl = ('<section class="pg w" id="implications" data-ch="I">%s<div class="shead"><p class="kick">What it means for Fieldnote</p>'
            "<h2>What the audited report recommends, grouped by decision</h2>"
            '<p class="lead">These are the report\'s own recommendations, verbatim and unchanged; nothing is added here.</p></div>'
            '<div class="impl">%s</div><div class="card k-w" style="margin-top:14px"><h3><span class="dot">%s</span>Caveats on the evidence</h3><ul>%s</ul>%s</div></section>'
            % (tracker("I"), "".join(cols), icon("alert"), cav, gloss("z", "bonf")))
    nxt = ('<section class="pg w" id="next" data-ch="I">%s<div class="shead"><p class="kick">Next steps</p><h2>Validate with a survey before committing the plan</h2></div>'
           '<div class="board two"><div class="card k-n"><h3><span class="dot">%s</span>The next study</h3><p>%s</p></div>'
           '<div class="card"><h3><span class="dot">%s</span>A draft questionnaire exists</h3>'
           '<p>A draft questionnaire for this brief is in <a href="../run/cycle-1/">../run/cycle-1/</a>; it runs longer than the 10-minute budget and needs shortening before fieldwork.'
           '</p></div></div></section>'
           % (tracker("I"), icon("arrow"), esc(next_text()), icon("question")))

    # appendix
    defs = "".join('<p><b>%s</b> %s</p>' % (esc(t.rstrip(".")), esc(b.replace("`", ""))) for _, t, b in parse_definitions())
    lim = "".join("<li>%s</li>" % esc(x) for x in R["limits"])
    appx = ('<section class="pg w" id="appx" data-ch="X"><div class="shead"><p class="kick">Appendix</p><h2>Methodology and definitions</h2></div>'
            '<div class="twocol"><div class="card"><p>%s</p><p><b>%s</b></p><ul class="lim">%s</ul></div>'
            '<div class="card k-q"><h3>Definitions, including the proxies</h3><div style="display:grid;gap:8px">%s</div></div></div></section>'
            % (esc(R["method"]), esc(R["limits_intro"]), lim, defs))
    formulas = ('<section class="pg w" id="formulas" data-ch="X"><div class="shead"><p class="kick">Appendix</p><h2>How we calculated this</h2>'
                '<p class="lead">Each formula, with this run\'s values plugged in and the source of the formula.</p></div><div style="margin-top:16px"><div class="fgrid">%s</div></div></section>'
                % "".join(FC.values()))
    tbls = "".join('<div class="card"><h3>%s</h3>%s</div>' % (esc(c["title"]), table_html(c["table"])) for c in cache.values())
    tables = ('<section class="pg w" id="appx-tables" data-ch="X"><div class="shead"><p class="kick">Appendix</p><h2>Data tables</h2>'
              '<p class="lead">The numbers behind each chart, as plotted.</p></div><div class="tbls">%s</div></section>' % tbls)
    base_s, best_s = keeploop_result()
    roles = [("Analyst", "Analysis and the report draft."), ("Engineer", "Edits to the report."),
             ("Auditor", "Independent audit of each change."), ("Tech", "Data collection, charts and this report."),
             ("Content", "Report prose."), ("QC", "Final check of the outputs.")]
    sources = (
        '<section class="pg w" id="sources" data-ch="X"><div class="shead"><p class="kick">Appendix</p><h2>Sources and credits</h2></div><div class="twocol">'
        '<div class="card"><h3>Data</h3><ul><li>Reddit posts and comments through the Arctic Shift archive, %s (general subreddits only for cross-brand modules).</li>'
        '<li>App Store store-level ratings from the iTunes lookup API; Wikipedia monthly page views (English, all-access, user).</li>'
        '<li>Files: data/metrics.json, data/quotes.json; method in data/README.md. Analysis run %s (UTC); supplementary run %s (UTC).</li></ul></div>'
        '<div class="card"><h3>Credits</h3><ul><li>Brief and market context: brief.md, with the citations shown on the market-context page.</li>'
        '<li>Sentiment: VADER (Hutto and Gilbert, 2014). Formula sources are listed with each formula.</li>'
        '<li>Charts: Plotly. Formulas: KaTeX. Type: Inter and Playfair Display (Google Fonts, SIL Open Font License). Icons: simple line drawings in the style of Lucide (ISC licence).</li></ul></div></div>'
        '</section>'
        '<section class="pg w" id="team" data-ch="T"><div class="shead"><p class="kick">The team</p><h2>Who made this report</h2>'
        '<p class="lead">These roles were played by AI agents under keeploop.</p></div>'
        '<div class="team">%s</div>'
        '<div class="result"><b>keeploop result:</b> baseline %s, best %s (%+.6f), audit APPROVED, change KEPT (run/cycle-2/transcript.txt). '
        '<a href="../run/LOG.md">How this report was made, including the mistakes</a>.</div>'
        '</section>'
        % (win_label(), D["meta"]["analysis_utc"][:10], SUP["supplementary_analysis_utc"][:10],
           "".join('<div class="card"><h3>%s</h3><p>%s</p></div>' % (r, esc(t)) for r, t in roles),
           base_s, best_s, float(best_s) - float(base_s)))

    body = "".join((cover, scqa, board, context, listened, secA, secB, secC, quotes, secD, impl, nxt, appx, formulas, tables, sources))
    page = Template("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fieldnote Apparel: fast-fashion talk, fall 2026 (dashboard)</title>
${FONTS}
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@${KATEX}/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@${PLOTLY}/plotly.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@${KATEX}/dist/katex.min.js"></script>
<style>${CSS}</style></head><body>${ONPAGE}<main>${BODY}
<footer class="w">Prepared for ${CLIENT}, a fictional client. Data: data/metrics.json and data/quotes.json; method in data/README.md.
How this report was made, including the mistakes: <a href="../run/LOG.md">run/LOG.md</a>.</footer>
</main><script>${JS}</script></body></html>""").substitute(
        FONTS=FONTS_LINK, KATEX=KATEX, PLOTLY=PLOTLY_JS, CSS=CSS, CLIENT=esc(client), ONPAGE=onpage(), BODY=body, JS=JS)
    (HERE / "dashboard.html").write_text(page, encoding="utf8")
    stat = Template("""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>board</title>${FONTS}
<style>${CSS}.w{max-width:1160px}body{width:1200px}.track{display:none}#hh{position:absolute;left:-9999px}</style></head><body><main>${COVER}${BOARD}</main>
<pre id="hh"></pre><script>document.getElementById('hh').textContent='H='+document.documentElement.scrollHeight;</script></body></html>""")
    return stat.substitute(FONTS=FONTS_LINK, CSS=CSS.split("@page")[0], COVER=cover, BOARD=board)


def edge_path():
    return Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe"


def board_png(board_page):
    """Render cover + board to charts/00-board.png, 2400 px wide, using headless Edge (page height is measured first)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        src = Path(tmp) / "board.html"
        src.write_text(board_page, encoding="utf8")
        prof = "--user-data-dir=" + str(Path(tmp) / "profile")
        h = 3400   # tall window; the blank bottom is cropped below (Edge's --dump-dom prints nothing here, so the height cannot be measured)
        shot = Path(tmp) / "board.png"
        subprocess.run([str(edge_path()), "--headless=new", "--no-first-run", prof, "--hide-scrollbars", "--force-device-scale-factor=2",
                        "--virtual-time-budget=6000", "--window-size=1200,%d" % h, "--screenshot=" + str(shot), src.as_uri()],
                       check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            if shot.exists() and shot.stat().st_size > 10000:
                n = shot.stat().st_size
                time.sleep(1)
                if shot.stat().st_size == n:
                    break
            time.sleep(1)
        assert shot.exists(), "board screenshot was not written"
        data = shot.read_bytes()
        try:        # optional: crop the blank bottom with Pillow when it is installed
            import io
            from PIL import Image, ImageChops
            im = Image.open(io.BytesIO(data)).convert("RGB")
            box = ImageChops.difference(im, Image.new("RGB", im.size, im.getpixel((2, im.size[1] - 3)))).getbbox()
            buf = io.BytesIO()
            im.crop((0, 0, im.size[0], min(im.size[1], box[3] + 80))).save(buf, "PNG")
            data = buf.getvalue()
        except ImportError:
            pass
        Path(lp(CH / "00-board.png")).write_bytes(data)


def print_pdf():
    edge = Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe"
    out = HERE / "report.pdf"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        # Print from a short temp copy: Edge cannot read or write MAX_PATH-length paths, and a link to
        # ../run/LOG.md would embed this machine's absolute path in the PDF, so the copy drops that href.
        tmp_pdf = Path(tmp) / "report.pdf"
        work = Path(tmp) / "w"
        (work / "charts").mkdir(parents=True)
        page = (HERE / "dashboard.html").read_text(encoding="utf8")
        (work / "dashboard.html").write_text(re.sub(r'<a href="\.\./run/[^"]*">(.*?)</a>', r"\1", page), encoding="utf8")
        for slug, _ in CHARTS:
            shutil.copyfile(lp(CH / (slug + ".png")), work / "charts" / (slug + ".png"))
        subprocess.run([str(edge), "--headless=new", "--no-pdf-header-footer", "--virtual-time-budget=15000",
                        "--no-first-run", "--user-data-dir=" + str(Path(tmp) / "profile"),
                        "--print-to-pdf=" + str(tmp_pdf), (work / "dashboard.html").as_uri()],
                       check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(90):                     # Edge returns before the file is written: wait for a stable size
            if tmp_pdf.exists() and tmp_pdf.stat().st_size > 10000:
                n = tmp_pdf.stat().st_size
                time.sleep(1)
                if tmp_pdf.stat().st_size == n:
                    break
            time.sleep(1)
        assert tmp_pdf.exists() and tmp_pdf.stat().st_size > 10000, "Edge did not write the PDF"
        Path(lp(out)).write_bytes(tmp_pdf.read_bytes())


# ---------------------------------------------------------------- self-check
def selfcheck(cs):
    m = load()["modules"]          # re-read: the check does not trust the build-time copy
    close = lambda a, b: math.isclose(a, b, abs_tol=1e-9)
    f = {k: v["fig"] for k, v in cs.items()}

    def barmap(fig, i=0):
        t = fig.data[i]
        return dict(zip(t.y, t.x))
    # 01
    fm = m["top_of_mind"]["first_mention"]
    t = f["01-top-of-mind"].data[0]
    assert len(t.y) == len(fm)
    for b, x, plus, minus in zip(t.y, t.x, t.error_x.array, t.error_x.arrayminus):
        assert close(x, fm[b]["pct"]) and close(x + plus, fm[b]["ci95"][1]) and close(x - minus, fm[b]["ci95"][0]), b
    rt = (EX / "report.md").read_text(encoding="utf8")
    assert "n=%d" % m["top_of_mind"]["replies_naming_a_brand"] in rt
    # 02
    bb = m["penetration_proxy"]["general_subreddits_only"]["by_brand"]
    t = f["02-penetration-proxy"].data[0]
    assert sorted(t.y) == sorted(CORE)
    for b, x, plus, minus in zip(t.y, t.x, t.error_x.array, t.error_x.arrayminus):
        assert close(x, bb[b]["pct"]) and close(x + plus, bb[b]["ci95"][1]) and close(x - minus, bb[b]["ci95"][0]), b
    lo, hi = band([bb[b] for b in CORE])
    assert lo < hi, "the five penetration intervals no longer share a range"
    # 03
    pf = m["profiling"]
    fg = f["03-profiling"]
    assert close(fg.data[0].x[0], pf["coverage_brand_mentioning_authors"]["age"]["pct"])
    assert close(fg.data[0].x[1], pf["coverage_all_authors"]["age"]["pct"])
    gen = pf["generation_of_brand_mentioning_authors"]
    for k, x in zip(fg.data[1].y, fg.data[1].x):
        assert close(x, gen[k]["pct"]) and gen[k]["base"] == pf["coverage_brand_mentioning_authors"]["age"]["k"]
    # 04
    ca = m["positioning"]["correspondence_analysis"]
    fg = f["04-perceptual-map"]
    for tr_, co in ((fg.data[0], ca["row_coords_dim1_2"]), (fg.data[1], ca["col_coords_dim1_2"])):
        for lab_, x, y in zip(tr_.customdata, tr_.x, tr_.y):
            assert close(x, co[lab_][0]) and close(y, co[lab_][1]), lab_
    for ax, i in ((fg.layout.xaxis, 0), (fg.layout.yaxis, 1)):
        assert "%.1f%%" % ca["axis_inertia_pct"][i] in ax.title.text
    # 05
    p = m["positioning"]
    fg = f["05-positioning-residuals"]
    hm = fg.data[0]
    for i, b in enumerate(p["brands_in_matrix"]):
        for j, a in enumerate(p["attributes"]):
            assert close(hm.z[i][j], p["adjusted_std_residuals"][b][a])
    surv = [(s["brand"], s["attribute"]) for s in p["significant_cells"] if s["survives_bonferroni"]]
    assert len(fg.layout.shapes) == len(surv) == sum(abs(v) > p["bonferroni_z"] for r in hm.z for v in r)
    core_surv = [s for s in surv if s[0] in CORE]
    assert len(core_surv) == 3 and ("Shein", "sustainability/ethics") in core_surv   # report.md: three core-brand cells
    # 06
    pe = m["perception"]["by_brand"]
    fg = f["06-perception"]
    for b, xn, xp in zip(fg.data[0].y, fg.data[0].x, fg.data[1].x):
        assert close(-xn, pe[b]["neg"]["pct"]) and close(xp, pe[b]["pos"]["pct"]), b
    ann = " ".join(a.text for a in fg.layout.annotations)
    for b in CORE:
        assert "%+.3f" % pe[b]["net_sentiment"] in ann, b
    # 07
    sg = m["segmentation"]
    fg = f["07-segments"]
    for s, xs, xn in zip(sg["segments"], fg.data[0].x, fg.data[1].x):
        assert close(xs, s["share_of_eligible"]["pct"]) and close(xn, s["sentiment"]["neg"]["pct"])
    assert fg.data[0].marker.color[0] == ACC and all(c != ACC for c in fg.data[0].marker.color[1:])
    # 08
    tr = m["trend"]
    fg = f["08-interest-trend"]
    for i, b in enumerate(CORE):
        v = [tr["wikipedia_monthly_views"][b][mo.replace("-", "")] for mo in tr["months"]]
        assert list(fg.data[2 * i].y) == v, b
    # formulas recomputed from raw numbers
    for b in CORE:
        for mod, key in (("top_of_mind", "first_mention"), ("top_of_mind", "total_mention")):
            x = m[mod][key][b]
            assert tuple(x["ci95"]) == wilson(x["k"], x["base"]), (b, key)
        x = bb[b]
        assert tuple(x["ci95"]) == wilson(x["k"], x["base"])
        x = pe[b]
        assert round((x["pos"]["k"] - x["neg"]["k"]) / x["base"], 3) == x["net_sentiment"], b
    assert round(NormalDist().inv_cdf(1 - 0.05 / p["chi_square"]["cells"] / 2), 2) == p["bonferroni_z"]
    assert round(p["chi_square"]["chi2"] / p["chi_square"]["n"], 4) == ca["total_inertia"]
    assert p["chi_square"]["df"] == (len(p["brands_in_matrix"]) - 1) * (len(p["attributes"]) - 1)
    vv = m["perception"]["vader_validation"]
    cmx = vv["confusion_human_rows_vader_cols"]
    L = ["pos", "neu", "neg"]
    po = sum(cmx[a][a] for a in L) / vv["n"]
    pe_ = sum(sum(cmx[a].values()) * sum(cmx[b][a] for b in L) for a in L) / vv["n"] ** 2
    assert close(po, vv["agreement"]) and round((po - pe_) / (1 - pe_), 3) == vv["cohens_kappa"]
    assert tuple(round(100 * v, 1) for v in vv["agreement_ci95"]) == wilson(round(po * vv["n"]), vv["n"])
    for b in CORE:
        x = [tr["wikipedia_monthly_views"][b][mo.replace("-", "")] for mo in tr["months"]]
        y = [tr["mention_items_by_month"][b][mo] for mo in tr["months"]]
        mx, my = sum(x) / len(x), sum(y) / len(y)
        r = sum((a - mx) * (c - my) for a, c in zip(x, y)) / math.sqrt(sum((a - mx) ** 2 for a in x) * sum((c - my) ** 2 for c in y))
        assert round(r, 2) == tr["pearson_r_views_vs_mentions"][b]["r"], b
    assert sg["silhouette_by_k"][str(sg["k"])] == max(sg["silhouette_by_k"].values())
    assert "silhouette %.3f at five groups" % sg["silhouette_by_k"][str(sg["k"])] in rt
    # report.md claims that the charts must agree with
    s1 = sg["segments"][0]
    assert ("%d authors, %.1f%% of eligible authors, n=%d, 95%% CI %.1f%% to %.1f%%"
            % (s1["authors"], s1["share_of_eligible"]["pct"], s1["share_of_eligible"]["base"], *s1["share_of_eligible"]["ci95"])
            in REPORT["target"])
    rt = (EX / "report.md").read_text(encoding="utf8")
    for b in CORE:
        assert "%s: first-named in %.1f%%" % (b, fm[b]["pct"]) in rt, b
        assert "%s: positive %.1f%%" % (b, pe[b]["pos"]["pct"]) in rt and "net sentiment %.3f" % pe[b]["net_sentiment"] in rt, b
    ctext = (EX / "data" / "quotes.json").read_text(encoding="utf8")
    qj = json.loads(ctext)["cells"]
    for q, b, a in QUOTES:       # every quote shown is verbatim in quotes.json under the stated cell
        assert q in [x["text"] for x in qj[b][a]["quotes"]], (b, a)
    # no personal data or local paths in any output
    bad = ("hmn" + "19", "App" + "Data", "User" + "s", "C" + ":", "reddit.com/u", "/user/")
    s = (HERE / "dashboard.html").read_text(encoding="utf8")
    assert not re.search(r"[\w.-]+@[\w-]+\.[a-z]{2,}", s), "email-like text"
    for w in bad:
        assert w not in s, w
    # --- board-style page: palette contrast (WCAG AA), quadrant, personas, implications, board image
    def _lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    def _cr(a, b):
        la, lb = sorted((_lum(a), _lum(b)), reverse=True)
        return (la + 0.05) / (lb + 0.05)
    for fg_, bg_ in (("#3D3D3D", "#F3EFE8"), ("#1F493D", "#F3EFE8"), ("#5C5750", "#F3EFE8"), ("#8F2323", "#F3EFE8"),
                     ("#F3EFE8", "#1F493D"), ("#F3EFE8", "#8F2323"), ("#FFFFFF", "#8F2323"), ("#1A1A1A", "#BF9B30"),
                     ("#3D3D3D", "#EEE0CA"), ("#5C5750", "#EEE0CA"), ("#3D3D3D", "#DDE7E1"), ("#3D3D3D", "#F0DCD6"),
                     ("#5C5750", "#FFFFFF"), ("#3D3D3D", "#FFFFFF"), ("#A7532D", "#F3EFE8"), ("#FFFFFF", "#6E625B"),
                     ("#8F2323", "#EEE0CA"), ("#1F493D", "#EEE0CA")):
        assert _cr(fg_, bg_) >= 4.5, (fg_, bg_, _cr(fg_, bg_))
    pts, (n1_, p1_, n2_, p2_) = build_html.quad
    cmap = {("brand", b): v for b, v in ca["row_coords_dim1_2"].items()}
    cmap.update({("attribute", a): v for a, v in ca["col_coords_dim1_2"].items()})
    assert len(pts) == len(cmap)
    for kind, name, x, y in pts:
        assert close(x, cmap[(kind, name)][0]) and close(y, cmap[(kind, name)][1]), name
    for a_ in n1_ + p1_ + n2_ + p2_:      # an axis end is named only from an attribute that sits clearly out on that side
        assert max(abs(ca["col_coords_dim1_2"][a_][0]), abs(ca["col_coords_dim1_2"][a_][1])) >= AX_MIN
    assert "Axis 1 (%.1f%% of variation)" % ca["axis_inertia_pct"][0] in s
    assert "Axis 2 (%.1f%% of variation)" % ca["axis_inertia_pct"][1] in s
    for sg_ in m["segmentation"]["segments"]:
        assert "%.1f%%" % sg_["share_of_eligible"]["pct"] in s and "%+.3f" % sg_["sentiment"]["net_sentiment"] in s
    for mod_ in REPORT["mods"]:
        for k_ in ("Recommendation", "So what", "title"):
            assert esc(mod_[k_]) in s, (mod_["n"], k_)
    assert s.count('class="persona') == len(m["segmentation"]["segments"]) + 1   # one per segment, plus the target one
    assert esc(next_text()) in s
    png = CH / "00-board.png"
    if Path(lp(png)).exists():
        head = Path(lp(png)).read_bytes()[:24]
        assert int.from_bytes(head[16:20], "big") == 2400, "00-board.png must be 2400 px wide"
    # --- supplementary charts, hero and credits
    sp = load()["supplementary"]
    fg = f["09-brand-funnel"]
    for i_, b_ in enumerate(CORE):
        fb_ = sp["funnel"]["by_brand"][b_]
        assert list(fg.data[i_].x) == [100.0, fb_["considering"]["share_of_aware"]["pct"], fb_["bought"]["share_of_aware"]["pct"]], b_
        assert fb_["advocate"]["k"] <= 1, "advocate is only left undrawn while it stays unmeasurable"
        for st_ in ("considering", "bought"):
            x_ = fb_[st_]["share_of_aware"]
            assert tuple(x_["ci95"]) == wilson(x_["k"], x_["base"]), (b_, st_)
    pm_ = sp["positioning_map"]["by_brand"]
    tr_ = f["10-positioning-map"].data[0]
    for b_, x_, y_, v_ in zip(tr_.text, tr_.x, tr_.y, tr_.marker.size):
        assert close(x_, pm_[b_]["x_price_value_share"]["pct"]) and close(y_, pm_[b_]["y_style_trend_share"]["pct"]), b_
        assert v_ == pm_[b_]["bubble_mention_sentences"], b_
        for k_, ax_ in (("x_price_value_share", tr_.error_x), ("y_style_trend_share", tr_.error_y)):
            pass
    bi_ = sp["brand_image"]
    hm_ = f["11-brand-image-grid"].data[0]
    for i_, b_ in enumerate(bi_["brands_in_grid"]):
        for j_, im_ in enumerate(IMG_ORDER):
            assert close(hm_.z[i_][j_], bi_["association_grid"][b_][im_]["pct"]), (b_, im_)
            x_ = bi_["association_grid"][b_][im_]
            assert tuple(x_["ci95"]) == wilson(x_["k"], x_["base"]), (b_, im_)
    fg = f["12-image-strengths"]
    assert sum(1 for k_ in range(4) for c_ in fg.data[k_].marker.color if c_ != LIGHT) == len(bi_["strengths_and_weaknesses_bonferroni"]["cells"])
    for c_ in bi_["strengths_and_weaknesses_bonferroni"]["cells"]:
        k_ = bi_["brands_in_grid"].index(c_["brand"])
        assert close(dict(zip(fg.data[k_].y, fg.data[k_].x))[c_["image"]], c_["z"]), c_
        assert abs(c_["z"]) > bi_["bonferroni_z"]
    placed_ = [c_ for v_ in bi_["priority_quadrant"]["by_brand"].values() for c_ in v_.get("cells_n_ge_30", [])]
    t13_ = f["13-image-priority"].data[0]
    assert len(t13_.x) == len(placed_) and close(t13_.x[0], placed_[0]["index_vs_set_average"]) and close(t13_.y[0], placed_[0]["net_sentiment"])
    for b_ in CORE:                       # hero and avatar numbers
        assert "%.1f%%" % m["top_of_mind"]["first_mention"][b_]["pct"] in s
    assert nf(load()["sample"]["reddit_items"]) in s and "%.1f%%" % m["perception"]["by_brand"]["Zara"]["neg"]["pct"] in s
    age_ = m["profiling"]["coverage_brand_mentioning_authors"]["age"]
    assert '%d of 100 icons filled' % round(100 * age_["k"] / age_["base"]) in s      # pictogram fill, stated rounding
    b0_, b1_ = keeploop_result()
    assert b0_ in s and b1_ in s and "Supplementary, not audited" in s
    assert s.count('role="img" aria-label=') >= len(CHARTS) - 1 and s.count('class="pimg"') >= len(CHARTS) - 1
    # --- mobile variants: same numbers as the desktop charts
    sg_ = m["segmentation"]["segments"]
    f7 = m7()["fig"]
    for s_, xs_, xn_ in zip(sg_, f7.data[0].x, f7.data[1].x):
        assert close(xs_, s_["share_of_eligible"]["pct"]) and close(xn_, s_["sentiment"]["neg"]["pct"])
    f9 = m9()["fig"]
    for i_, b_ in enumerate(CORE):
        fb_ = sp["funnel"]["by_brand"][b_]
        assert list(f9.data[i_].x) == [100.0, fb_["considering"]["share_of_aware"]["pct"], fb_["bought"]["share_of_aware"]["pct"]]
    t10m = m10()["fig"].data[0]
    for b_, x_, y_ in zip(t10m.text, t10m.x, t10m.y):
        assert close(x_, sp["positioning_map"]["by_brand"][b_]["x_price_value_share"]["pct"]) and close(y_, sp["positioning_map"]["by_brand"][b_]["y_style_trend_share"]["pct"])
    f6 = m6()["fig"]
    for b_, xn_, xp_ in zip(f6.data[0].y, f6.data[0].x, f6.data[1].x):
        assert close(-xn_, pe[b_]["neg"]["pct"]) and close(xp_, pe[b_]["pos"]["pct"])
    assert "overflow-x:auto}.plot>div" not in s and "scrollZoom:false" in s and "displayModeBar:false" in s
    assert 'loading="lazy"' in s and "max-width:100%;height:auto" in s
    print("self-check passed")


def report_gaps():
    """Print places where report.md says more than the charted intervals support."""
    pe = M["perception"]["by_brand"]
    ov = lambda a, b: a["ci95"][0] <= b["ci95"][1] and b["ci95"][0] <= a["ci95"][1]
    for a in ("Zara", "Shein"):
        for b in ("H&M",):
            if ov(pe[a]["neg"], pe[b]["neg"]):
                print("GAP: negative share of %s overlaps %s (%s vs %s)" % (a, b, ci_txt(pe[a]["neg"]), ci_txt(pe[b]["neg"])))
    s = M["segmentation"]["segments"]
    for o in s[1:]:
        if ov(s[0]["sentiment"]["neg"], o["sentiment"]["neg"]):
            print("GAP: Segment 1 negative share overlaps Segment %d (%s vs %s)" % (o["segment"], ci_txt(s[0]["sentiment"]["neg"]), ci_txt(o["sentiment"]["neg"])))


# ---------------------------------------------------------------- main
REPORT = parse_report()
QUOTES = REPORT["mods"][3]["quotes"]
_qj = json.load(open(EX / "data" / "quotes.json", encoding="utf8"))["cells"]
QCELL = {(b, a): _qj[b][a]["cell_n"] for _, b, a in QUOTES}


def main():
    CH.mkdir(exist_ok=True)
    cs = {}
    for slug, fn in CHARTS:
        cs[slug] = fn()
        png = render(cs[slug], png=True).to_image(format="png", scale=2)
        Path(lp(CH / (slug + ".png"))).write_bytes(png)
        print("wrote", slug)
    board_page = build_html(cs)
    if "--no-pdf" not in sys.argv:
        board_png(board_page)
    selfcheck(cs)
    report_gaps()
    if "--no-pdf" not in sys.argv:
        print_pdf()
        print("wrote report.pdf")


if __name__ == "__main__":
    main()
