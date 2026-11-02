"""evaluate.py - consumer-insight report quality score. Humans only.

The report writer must never see this file; they get FORMAT.md only.

Workspace = brief.md, report.md, data/metrics.json, data/quotes.json.
Prints ONE float in 0..1 (higher is better); the per-check breakdown goes to
stderr. Exit 2 (invalid workspace, no score) when a file is missing, when
report.md holds a number that cannot be traced to data/metrics.json (see
traceable() for the exact rule), or when a quote is not verbatim in
data/quotes.json.

Score = sum(weight * share_of_items_passing) / 100. Each check serves one
criterion of packs/marketing-research/rubric.md. A check with nothing to test
scores 0 (the old questionnaire scorer gave full credit and was gameable).
The one exception is U1 (unsupported skew claims): no such claim is the good case.
Rule-based, so NOT validated against client decisions (see pack.yaml).

Usage:  python evaluate.py <workspace-dir>
        python evaluate.py --self-check
"""

import bisect
import json
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
FILES = ("brief.md", "report.md", "data/metrics.json", "data/quotes.json")
# Funnel order from brief.md: (heading keyword, comparative module?)
MODULES = [(r"top.of.mind", 1), (r"penetration", 1), (r"profil", 0),
           (r"position", 1), (r"perception", 1), (r"segment", 0)]

NUM = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?")
ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
CI95 = re.compile(r"95\s*%\s*(?=CI|interval)", re.I)
HAS_CI = re.compile(r"95\s*%\s*(CI|interval)", re.I)
PCT = re.compile(r"\d\s*%")
BASE_N = re.compile(r"\bn\s*=\s*(\d[\d,]*)")
QUOTE = re.compile(r"^>\s*[“\"](.+?)[”\"]\s*(?:\(([^()]*)\))?\s*$")
SEG = re.compile(r"\bSegment\s+(\d+)", re.I)
# Comparative wording: a number on such a line may belong to a second brand, so B1 skips the line.
BROAD = re.compile(r"\b(other|others|rest|remaining|each|both|versus|vs)\b", re.I)
# Demographic or platform skew claims (U1). A sentence matching needs a traced number or a (Source, year).
SKEW = re.compile(r"\bskew(?:s|ed)?\b|\bpredominantly\b|\bmostly\s+(?:men|women|male|female|young|older)\b|"
                  r"\b(?:users|audience|shoppers)\s+(?:are|is)\s+(?:mostly|largely)\b", re.I)
SOURCE = re.compile(r"\([^()]*[A-Za-z][^()]*\b(?:19|20)\d{2}\b[^()]*\)")
QUOTE_START =re.compile(r"^>\s*[“\"]")
LABELS = r"(Question|Decision|So what|Recommendation|Quote rule|Target segment)"


class Invalid(Exception):
    pass


def norm(s):
    return " ".join(s.split())


def sections(text):
    out = []
    for line in text.splitlines():
        if line.startswith("## "):
            out.append({"head": line[3:].strip(), "lines": []})
        elif out:
            out[-1]["lines"].append(line)
    return out


def field(lines, label):
    for line in lines:
        m = re.match(rf"{label}\s*:\s*(\S.*)", line.replace("**", "").lstrip("-* \t"), re.I)
        if m:
            return m[1].strip()
    return ""


def chunks(lines):
    """Evidence units: a bullet with its continuation, a table row, a labelled line, or a paragraph."""
    out, cur = [], []
    for raw in lines:
        s = raw.replace("**", "").strip()
        if not s or s.startswith(">"):
            if cur:
                out.append(" ".join(cur))
            cur = []
            continue
        if cur and (re.match(r"([-*]|\d+\.)\s|\|", s) or re.match(LABELS + r"\s*:", s, re.I)):
            out.append(" ".join(cur))
            cur = []
        cur.append(s)
    if cur:
        out.append(" ".join(cur))
    return out


def load_slop():
    for base in (HERE, HERE.parent.parent):
        p = base / "packs" / "marketing-research" / "pack.yaml"
        if p.exists():
            break
    else:
        raise Invalid("packs/marketing-research/pack.yaml not found")
    out, on = [], False
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("slop:"):
            on = True
        elif on and line and not line.startswith(" "):
            break
        elif on and ":" in line:
            out.append(re.compile(line.split(":", 1)[1].split(" => ")[0].strip()))
    return out


def number_index(metrics):
    """-> (sorted abs numeric values, sorted 100x values). Numbers in dict keys count (e.g. 'Gen Z (14-29)')."""
    vals = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                vals.update(float(x.replace(",", "")) for x in re.findall(r"\d+(?:\.\d+)?", k))
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            vals.add(abs(float(o)))
    walk(metrics)
    return sorted(vals), sorted(v * 100 for v in vals)


def traceable(tok, idx):
    """tok is a numeric token as shown. True if some metrics value, or 100x some value, rounds to it at the decimals shown (sign ignored)."""
    t = float(tok.replace(",", ""))
    tol = 0.5 * 10 ** -(len(tok.split(".")[1]) if "." in tok else 0) + 1e-9
    for arr in idx:
        i = bisect.bisect_left(arr, t - tol)
        if i < len(arr) and arr[i] <= t + tol:
            return True
    return False


def find_quotes(lines):
    """-> [(text, attribution or None)]; raises Invalid on a malformed quote line."""
    out = []
    for line in lines:
        if QUOTE_START.match(line):
            m = QUOTE.match(line.strip())
            if not m:
                raise Invalid(f"malformed quote line: {line[:70]!r}")
            out.append((norm(m[1]), m[2]))
    return out


def untraceable(lines, brief, idx):
    """-> list of 'line N: token' for tokens with no source. Exemptions are listed in FORMAT.md."""
    sec = brief.split("## Market context", 1)[-1].split("\n## ", 1)[0]
    brief_tokens = {re.sub(r"[,]", "", m.group(0)) for m in NUM.finditer(sec)}
    bad, market = [], False
    for n, line in enumerate(lines, 1):
        if line.startswith("## "):
            market = bool(re.search(r"market context", line, re.I))
            line = re.sub(r"^##\s+\d+\.", "##", line)
        q = QUOTE.match(line.strip())
        if q:
            line = line[:line.index(q[1])] + line[line.index(q[1]) + len(q[1]):]
        for s in tokens(line):
            if not (s.replace(",", "") in brief_tokens if market else traceable(s, idx)):
                bad.append(f"line {n}: {s}")
    return bad


def tokens(line):
    """Numeric tokens of a line that are not exempt (years, dates, '95%' in 95% CI, 30/0.05 on rule lines)."""
    line = CI95.sub(" ", ISO.sub(" ", line))
    if re.search(r"\b(rule|threshold)\b", line, re.I):
        line = re.sub(r"(?<![\d.])(30|0\.05)(?![\d.])", " ", line)
    return [m.group(0) for m in NUM.finditer(line) if m.group(0) not in ("2025", "2026")]


def claim_index(metrics):
    """-> {context: (sorted values, sorted 100x values)}. A value's contexts are the lowercased keys on its path plus 'segment N' for values inside a segment object."""
    ctx = defaultdict(set)

    def add(v, keys, tags):
        for c in {k.lower() for k in keys} | tags:
            ctx[c].add(v)

    def walk(o, keys, tags):
        if isinstance(o, dict):
            if isinstance(o.get("segment"), int) and isinstance(o.get("name"), str):
                tags = tags | {f"segment {o['segment']}"}
            for k, v in o.items():
                for x in re.findall(r"\d+(?:\.\d+)?", k):
                    add(float(x), keys + [k], tags)
                walk(v, keys + [k], tags)
        elif isinstance(o, list):
            for v in o:
                walk(v, keys, tags)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            add(abs(float(o)), keys, tags)
    walk(metrics, [], set())
    return {c: (sorted(s), sorted(v * 100 for v in s)) for c, s in ctx.items()}


def _flag(items):
    return sum(map(bool, items)), len(items)


def _modules(c, f):
    return _flag([f(i, s) for i, s in enumerate(c.mods)])


def _order(c):
    pos = [s["i"] if s else -1 for s in c.mods]
    return _flag([p >= 0 and (i == 0 or p > pos[i - 1]) for i, p in enumerate(pos)])


def _method(c):
    ms = [s["i"] for s in c.secs if re.search(r"method|limit", s["head"], re.I)]
    return _flag([bool(ms) and all(c.mods) and ms[-1] > c.mods[-1]["i"]])


def _target(c):
    v = field(c.secs[0]["lines"], "Target segment") if c.secs else ""
    n = re.search(r"segment\s*(\d+)", v, re.I)
    return _flag([bool(v) and (bool(n and 1 <= int(n[1]) <= len(c.segs)) or any(s.lower() in v.lower() for s in c.segs))])


def _quote_cell(c):
    def ok(text, attr):
        if not attr or "," not in attr:
            return False
        b, a = (x.strip() for x in attr.split(",", 1))
        return text in c.cells.get(b, {}).get(a, set())
    return _flag([ok(t, a) for t, a in c.quotes])


def _bound(c):
    """B1: every number on a one-brand or one-segment line must match a value filed under that brand or segment."""
    items = []
    for _, ch in c.chunks:
        brands = [b for b in c.brands if re.search(re.escape(b), ch, re.I)]
        segs = {int(n) for n in SEG.findall(ch)}
        if BROAD.search(ch):
            continue
        if len(segs) == 1:  # a segment line may also name the brand in the segment's name, nothing else
            n = next(iter(segs))
            if any(b.lower() not in c.segmap.get(n, "").lower() for b in brands):
                continue
            keys = [f"segment {n}"]
        elif not segs and len(brands) == 1:
            b = brands[0].lower()  # "Aritzia-led segment" without an id also accepts that segment's values
            keys = [b] + ([f"segment {n}" for n, s in c.segmap.items() if s.lower().startswith(b)] if re.search("segment", ch, re.I) else [])
        else:
            continue
        items += [any(traceable(t, c.claim[k]) for k in keys if k in c.claim) for t in tokens(SEG.sub(" ", ch))]
    return _flag(items)


def _skew(c):
    """U1: skew claims need a traced number or a (Source, year). No claim at all = compliant (the one full-credit case)."""
    flagged = [s for u in c.units for s in re.split(r"(?<=[.!?])\s+", u) if SKEW.search(s)]
    ok = [bool(SOURCE.search(s)) or any(traceable(t, c.idx) for t in tokens(s)) for s in flagged]
    return _flag(ok) if ok else (1, 1)


def _pct(c, test, only=None):
    return _flag([test(ch) for si, ch in c.chunks if PCT.search(CI95.sub("", ch)) and (only is None or only(si, ch))])


def _small_base(c):
    items = []
    for si, ch in c.chunks:
        ns = [int(x.replace(",", "")) for x in BASE_N.findall(ch)]
        if ns and PCT.search(CI95.sub("", ch)):
            items.append(min(ns) >= 30)
    return _flag(items)


O, E, M, F, D = ("Clear research objectives", "Non-leading, unbiased evidence", "Correct measure choice",
                 "Logical flow", "Decision-ready insight output")
# (id, criterion, weight, what it measures, fn(ctx) -> (passed, total))
CHECKS = [
    ("O1", O, 10, "each of the 6 modules has a Question line",
     lambda c: _modules(c, lambda i, s: s and field(s["lines"], "Question"))),
    ("O2", O, 10, "each of the 6 modules has a Decision line",
     lambda c: _modules(c, lambda i, s: s and field(s["lines"], "Decision"))),
    ("E1", E, 5, "no slop pattern in headings or So what lines",
     lambda c: _flag([not any(r.search(t) for r in c.slop) for t in c.slop_text])),
    ("E2", E, 5, "each comparative module names all 5 core brands",
     lambda c: _flag([bool(s) and all(b.lower() in "\n".join(s["lines"]).lower() for b in c.brands)
                      for (kw, comp), s in zip(MODULES, c.mods) if comp])),
    ("E3", E, 4, "each quote is attributed to the cell it came from", _quote_cell),
    ("E4", E, 3, "a Quote rule line states how quotes were chosen",
     lambda c: _flag([len(field(c.lines, "Quote rule").split()) >= 5])),
    ("B1", E, 5, "each number on a one-brand or one-segment line is filed under that brand or segment", _bound),
    ("U1", E, 3, "skew claims carry a traced number or a (Source, year); none = full credit", _skew),
    ("M1", M, 8, "every percentage has n= and a 95% interval in the same line or bullet",
     lambda c: _pct(c, lambda ch: bool(BASE_N.search(ch) and HAS_CI.search(ch)))),
    ("M2", M, 6, "no percentage on a base under 30", _small_base),
    ("M3", M, 6, "penetration and top-of-mind percentages say proxy",
     lambda c: _pct(c, lambda ch: "proxy" in ch.lower(),
                    lambda si, ch: si in [s["i"] for s in c.mods[:2] if s]
                    or re.search(r"penetration|top.of.mind", ch, re.I))),
    ("F1", F, 5, "answer-first summary is the first section",
     lambda c: _flag([bool(c.secs) and re.search(r"summary|answer", c.secs[0]["head"], re.I)])),
    ("F2", F, 5, "modules appear in brief order", _order),
    ("F3", F, 5, "Method and limits come after the modules", _method),
    ("D1", D, 8, "each module has a So what line",
     lambda c: _modules(c, lambda i, s: s and field(s["lines"], "So what"))),
    ("D2", D, 8, "each module has a Recommendation line naming Fieldnote",
     lambda c: _modules(c, lambda i, s: s and "fieldnote" in field(s["lines"], "Recommendation").lower())),
    ("D3", D, 4, "the summary names the target segment", _target),
]
assert sum(c[2] for c in CHECKS) == 100


def evaluate(ws):
    """-> (score 0..1, rows). Raises Invalid (exit 2)."""
    ws = Path(ws)
    for f in FILES:
        if not (ws / f).is_file():
            raise Invalid(f"missing workspace file: {ws / f}")
    try:
        brief, report = ((ws / f).read_text(encoding="utf-8") for f in FILES[:2])
        metrics, quotes = (json.loads((ws / f).read_text(encoding="utf-8")) for f in FILES[2:])
        cells = {b: {a: {norm(q["text"]) for q in v.get("quotes", [])} for a, v in cs.items()}
                 for b, cs in quotes["cells"].items()}
        brands, segs = metrics["meta"]["core_brands"], [s["name"].split(" (")[0] for s in metrics["modules"]["segmentation"]["segments"]]
    except (ValueError, KeyError, TypeError) as e:
        raise Invalid(f"unreadable workspace file: {e!r}")
    lines = report.splitlines()
    found = find_quotes(lines)
    allq = {t for cs in cells.values() for ts in cs.values() for t in ts}
    for t, _ in found:
        if t not in allq:
            raise Invalid(f"quote not verbatim in data/quotes.json: {t[:70]!r}")
    idx = number_index(metrics)
    bad = untraceable(lines, brief, idx)
    if bad:
        raise Invalid("untraceable numbers (not in data/metrics.json):\n  " + "\n  ".join(bad))
    secs = [dict(s, i=i) for i, s in enumerate(sections(report))]
    mods = [next((s for s in secs if re.match(rf"{i + 1}\.", s["head"]) and re.search(kw, s["head"], re.I)), None)
            for i, (kw, _) in enumerate(MODULES)]
    live = [s for s in secs if not re.search(r"market context", s["head"], re.I)]
    cks = [(s["i"], ch) for s in live for ch in chunks(s["lines"])]
    ctx = SimpleNamespace(
        secs=secs, mods=mods, lines=lines, brands=brands, segs=segs, cells=cells, quotes=found, slop=load_slop(),
        slop_text=[l for l in lines if l.startswith("#")] + [field([l], "So what") for l in lines if field([l], "So what")],
        chunks=cks, idx=idx, claim=claim_index(metrics), units=[s["head"] for s in live] + [ch for _, ch in cks],
        segmap={s["segment"]: s["name"].split(" (")[0] for s in metrics["modules"]["segmentation"]["segments"]})
    rows, got = [], 0.0
    for cid, crit, w, what, fn in CHECKS:
        p, t = fn(ctx)
        got += w * (p / t if t else 0)  # nothing to test = 0, not full credit (U1 returns 1/1 itself)
        rows.append((cid, crit, w, p, t, what))
    return got / 100, rows


def run(ws):
    try:
        value, rows = evaluate(ws)
    except Invalid as e:
        print(f"INVALID WORKSPACE: {e}", file=sys.stderr)
        return 2
    for cid, crit, w, p, t, what in rows:
        print(f"{cid} {w:>2}  {p}/{t}  {crit}: {what}", file=sys.stderr)
    print(f"{value:.6f}")
    return 0


def self_check():
    src = HERE if (HERE / "brief.md").exists() else HERE / "examples" / "marketing-research"
    read = lambda n: (src / "samples" / f"{n}.md").read_text(encoding="utf-8")
    quote = re.search(r"^> [“\"](.+?)[”\"]", read("good"), re.M)[1]

    def code(report):  # real exit code of run() on a scratch workspace
        with tempfile.TemporaryDirectory() as d:
            for f in FILES[:1] + FILES[2:]:
                (Path(d) / f).parent.mkdir(exist_ok=True)
                shutil.copy(src / f, Path(d) / f)
            if report is not None:
                (Path(d) / "report.md").write_text(report, encoding="utf-8")
            rc = run(d)
            if rc:
                return rc, None, {}
            s, rows = evaluate(d)
            return rc, s, {r[0]: (r[3], r[4]) for r in rows}

    (c_good, good, g), (c_bad, bad, _) = code(read("good")), code(read("bad"))
    print({"good": good, "bad": bad}, file=sys.stderr)
    assert c_good == c_bad == 0 and good >= 0.9 and bad <= 0.5 and good - bad >= 0.4, (good, bad)
    # B1: a real number filed under another brand (Zara's 18.4 on a Shein line) fails exactly one more item
    mis = code(read("good").replace("Shein: 23.6% negative", "Shein: 18.4% negative"))[2]
    assert mis["B1"][0] == g["B1"][0] - 1 and mis["B1"][1] == g["B1"][1] > 0, (mis["B1"], g["B1"])
    # U1: no skew claim = 1/1; an unsourced one = 0/1; with (Source, year) = 1/1; with a traced number = 1/1
    skew = "\n- Reddit users skew young%s.\n"
    assert g["U1"] == (1, 1) and code(read("good") + skew % "")[2]["U1"] == (0, 1)
    assert code(read("good") + skew % " (Pew Research Center, 2025)")[2]["U1"] == (1, 1)
    assert code(read("good") + (skew % "").replace("young", "young (42.4% name Uniqlo first)"))[2]["U1"] == (1, 1)
    assert code(read("good") + "\n- Shein: 99.9% of authors (n=1453, 95% CI 1.0 to 2.0).\n")[0] == 2, "untraceable number accepted"
    assert code(read("bad") + "\n- Shein: 99.9% of authors (n=1453, 95% CI 1.0 to 2.0).\n")[0] == 2, "untraceable number accepted"
    assert code(read("good").replace(quote, quote + " really"))[0] == 2, "altered quote accepted"
    assert code(None)[0] == 2, "missing report accepted"
    print("self-check ok")
    return 0


def main():
    if sys.argv[1:] == ["--self-check"]:
        return self_check()
    if len(sys.argv) != 2:
        print("usage: evaluate.py <workspace-dir> | --self-check", file=sys.stderr)
        return 2
    return run(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
