"""evaluate.py - questionnaire design-quality score. Humans only.

Reads <workspace>/questionnaire.md (format: FORMAT.md next to this file) and
prints ONE float in 0..1, higher is better. The per-check breakdown goes to
stderr. Exit 2 with a message when the file is missing or cannot be parsed.

Score = sum(weight * share_of_items_passing) / sum(weight). Every check below
serves exactly one criterion of packs/marketing-research/rubric.md. The
checks are rule-based heuristics, so the score is NOT validated against real
survey outcomes (see metric_validation in pack.yaml).

Usage:  python evaluate.py <workspace-dir>
        python evaluate.py --self-check    (good vs bad sample must score differently)
"""

import re
import sys
from collections import Counter
from pathlib import Path

LENGTH_BUDGET_S = 600  # 10 minutes
SECONDS = {"single": 15, "multi": 25, "open": 45, "scale": 15}  # grid: 10 + 8 per row
TYPES = ("single", "multi", "open", "scale", "grid")

LEADING = re.compile(
    r"don't you (agree|think)|wouldn't you agree|isn't it true|do you agree that|you would agree|"
    r"\b(obviously|of course|everyone knows|as you know|surely|unfortunately)\b|"
    r"\bhow (amazing|great|wonderful|terrible|awful)\b|"
    r"\bour (excellent|best|amazing|award-winning|innovative|superior|wonderful)\b", re.I)
CUE = re.compile(r"\b(satisf\w*|rate|agree|likely|important|easy|happy|pleased|trust|recommend\w*|"
                 r"like|enjoy|prefer\w*|know|use|buy|purchase|visit)\b", re.I)
AND = re.compile(r"\b(and|as well as|and/or)\b", re.I)
NEUTRAL = re.compile(r"neither|neutral|undecided|unsure|average|about right|sometimes|"
                     r"occasionally|moderate|don't know", re.I)
NEG = re.compile(r"\b(dis\w+|un\w+|not|poor|bad|never|rarely|low|none|no)\b", re.I)
MULTI_WORDS = re.compile(r"select all|check all|choose all|all that apply|any that apply", re.I)
SINGLE_WORDS = re.compile(r"which one|one only|select one|choose one|pick one", re.I)


def parse(text: str) -> tuple[list, list]:
    """-> (modules, questions). Raises ValueError('line N: why')."""
    modules, qs = [], []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("# ", ">", "<!--")):
            continue
        key, _, val = line.partition(":")
        key, val = key.strip().lower(), val.strip()
        if line.startswith("## "):
            modules.append({"name": line[3:].strip(), "objective": "", "decision": "", "analysis": ""})
        elif m := re.fullmatch(r"(\d+)\.\s+\[(\w+)\]\s+(.+)", line):
            if m[2] not in TYPES:
                raise ValueError(f"line {n}: type must be one of {', '.join(TYPES)}")
            if any(q["id"] == m[1] for q in qs):
                raise ValueError(f"line {n}: duplicate question number {m[1]}")
            qs.append({"id": m[1], "type": m[2], "stem": m[3], "options": [], "scale": None,
                       "unipolar": False, "awareness": "", "module": len(modules) - 1})
        elif key in ("objective", "decision", "analysis") and modules and not (
                qs and qs[-1]["module"] == len(modules) - 1):  # only before the module's questions
            modules[-1][key] = val
        elif qs and key == "scale":
            qs[-1]["unipolar"] = val.lower().startswith("unipolar:")
            val = val.split(":", 1)[1] if qs[-1]["unipolar"] else val
            qs[-1]["scale"] = [x.strip() for x in val.split("|")]
        elif qs and key == "awareness" and val.lower() in ("aided", "unaided"):
            qs[-1]["awareness"] = val.lower()
        elif qs and line.startswith("- "):
            qs[-1]["options"].append(line[2:].strip())
        else:
            raise ValueError(f"line {n}: cannot parse {line[:60]!r}")
    if not modules or not qs:
        raise ValueError("need at least one '## ' module and one numbered question")
    for q in qs:
        if q["type"] in ("scale", "grid") and not q["scale"]:
            raise ValueError(f"question {q['id']}: {q['type']} needs a 'Scale:' line")
        if q["type"] in ("single", "multi", "grid") and len(q["options"]) < (1 if q["type"] == "grid" else 2):
            raise ValueError(f"question {q['id']}: needs '- ' option lines")
    return modules, qs


def polarity(label: str) -> int:
    """+1 positive, -1 negative, 0 neutral (small word lists; see FORMAT.md)."""
    return 0 if NEUTRAL.search(label) else -1 if NEG.search(label) else 1


def scales(qs):
    return [q for q in qs if q["scale"]]


def direction(q) -> str:
    return "down" if polarity(q["scale"][0]) > polarity(q["scale"][-1]) else "up"


def ranges(options):
    """Numeric bands in an option list -> [(lo, hi)]; non-numeric options are skipped."""
    out = []
    for o in options:
        o = re.sub(r"[$,%]", "", o.lower()).strip()
        if m := re.fullmatch(r"(\d+)\s*(?:-|to)\s*(\d+)", o):
            out.append((int(m[1]), int(m[2])))
        elif m := re.fullmatch(r"(\d+)\s*(\+|or more|and over|and above)", o):
            out.append((int(m[1]), 10**9))
        elif m := re.fullmatch(r"(?:under|less than|below)\s+(\d+)", o):
            out.append((0, int(m[1]) - 1))
        elif m := re.fullmatch(r"(?:over|more than)\s+(\d+)", o):
            out.append((int(m[1]) + 1, 10**9))
    return out


def seconds(q) -> int:
    return 10 + 8 * len(q["options"]) if q["type"] == "grid" else SECONDS[q["type"]]


# Each check: (id, criterion, weight, what it measures, fn(modules, qs) -> (passed, total))
def _flag(items):  # [bool] -> (passed, total)
    return sum(items), len(items)


def _unaided_first(ms, qs):
    seen, res = False, []
    for q in qs:
        if q["awareness"] == "unaided":
            seen = True
        elif q["awareness"] == "aided":
            res.append(seen)
    return _flag(res)


def _brand_lists(ms, qs):
    n = lambda q, rx: any(re.search(rx, o, re.I) for o in q["options"])
    aided = [q for q in qs if q["awareness"] == "aided"]
    return (sum(n(q, r"none of (these|the above)") + n(q, r"other \(specify\)") for q in aided),
            2 * len(aided))


def _ranges_ok(ms, qs):
    res = []
    for q in qs:
        r = sorted(ranges(q["options"]))
        if len(r) >= 2:
            res.append(all(b[0] > a[1] for a, b in zip(r, r[1:])))
    return _flag(res)


def _length(ms, qs):
    est = sum(seconds(q) for q in qs)
    return min(1.0, LENGTH_BUDGET_S / est), 1


def _direction(ms, qs):
    d = Counter(direction(q) for q in scales(qs))
    return (max(d.values()), sum(d.values())) if d else (0, 0)


CHECKS = [
    ("O1", "Clear research objectives", 10, "every module has an Objective line",
     lambda ms, qs: _flag([bool(m["objective"]) for m in ms])),
    ("O2", "Clear research objectives", 10, "every question sits under a module",
     lambda ms, qs: _flag([q["module"] >= 0 for q in qs])),
    ("N1", "Non-leading wording", 15, "no leading or loaded phrase in a stem or option",
     lambda ms, qs: _flag([not LEADING.search(" ".join([q["stem"]] + q["options"])) for q in qs])),
    ("N2", "Non-leading wording", 10, "no double-barreled stem (cue word joined by 'and')",
     lambda ms, qs: _flag([not (CUE.search(q["stem"]) and AND.search(q["stem"])) for q in qs])),
    ("S1", "Correct scale choice", 4, "every scale point has a word label",
     lambda ms, qs: _flag([all(l and not re.fullmatch(r"[\d\s.-]+", l) for l in q["scale"]) for q in scales(qs)])),
    ("S2", "Correct scale choice", 4, "scale is balanced (equal positive and negative points)",
     lambda ms, qs: _flag([q["unipolar"] or sum(map(polarity, q["scale"])) == 0 for q in scales(qs)])),
    ("S3", "Correct scale choice", 3, "same direction in every scale", _direction),
    ("S4", "Correct scale choice", 2, "4 to 7 points",
     lambda ms, qs: _flag([4 <= len(q["scale"]) <= 7 for q in scales(qs)])),
    ("S5", "Correct scale choice", 2, "question type matches 'select all' / 'select one' wording",
     lambda ms, qs: _flag([not (MULTI_WORDS.search(q["stem"]) if q["type"] == "single"
                                else SINGLE_WORDS.search(q["stem"]))
                           for q in qs if q["type"] in ("single", "multi")])),
    ("F1", "Logical question flow", 4, "first module is the screener",
     lambda ms, qs: _flag(["screen" in ms[0]["name"].lower()])),
    ("F2", "Logical question flow", 4, "last module is demographics",
     lambda ms, qs: _flag(["demograph" in ms[-1]["name"].lower()])),
    ("F3", "Logical question flow", 4, "an unaided question precedes every aided one", _unaided_first),
    ("F4", "Logical question flow", 3, f"estimated length within {LENGTH_BUDGET_S // 60} min", _length),
    ("D1", "Decision-ready output", 10, "every module has a Decision line",
     lambda ms, qs: _flag([bool(m["decision"]) for m in ms])),
    ("D2", "Decision-ready output", 10, "every module has an Analysis line",
     lambda ms, qs: _flag([bool(m["analysis"]) for m in ms])),
    ("L1", "Correct scale choice", 3, "aided lists offer None of these and Other (specify)", _brand_lists),
    ("L2", "Correct scale choice", 2, "numeric ranges do not overlap", _ranges_ok),
]
assert sum(c[2] for c in CHECKS) == 100


def score(modules, qs) -> tuple[float, list]:
    """-> (0..1, [(id, criterion, weight, passed, total, what)]). No items = not applicable = full credit."""
    rows, got = [], 0.0
    for cid, crit, w, what, fn in CHECKS:
        p, t = fn(modules, qs)
        got += w * (p / t if t else 1)
        rows.append((cid, crit, w, p, t, what))
    return got / 100, rows


def main() -> int:
    if sys.argv[1:] == ["--self-check"]:
        return self_check()
    if len(sys.argv) != 2:
        print("usage: evaluate.py <workspace-dir> | --self-check", file=sys.stderr)
        return 2
    path = Path(sys.argv[1]) / "questionnaire.md"
    if not path.exists():
        print(f"MISSING WORKSPACE FILE: {path}", file=sys.stderr)
        return 2
    try:
        modules, qs = parse(path.read_text(encoding="utf-8"))
    except ValueError as e:
        print(f"INVALID WORKSPACE: {e}", file=sys.stderr)
        return 2
    value, rows = score(modules, qs)
    for cid, crit, w, p, t, what in rows:
        print(f"{cid} {w:>2}  {p:g}/{t}  {crit}: {what}", file=sys.stderr)
    print(f"{value:.6f}")
    return 0


def self_check() -> int:
    here = Path(__file__).parent / "samples"
    s = {n: score(*parse((here / f"{n}.md").read_text(encoding="utf-8")))[0] for n in ("good", "bad")}
    print(s, file=sys.stderr)
    assert s["good"] >= 0.95, s
    assert s["bad"] <= 0.5, s
    assert s["good"] - s["bad"] >= 0.4, s
    for broken in ("", "## M\n1. [bogus] x", "## M\n1. [scale] no scale line"):
        try:
            parse(broken)
        except ValueError:
            continue
        raise AssertionError(f"parse accepted {broken!r}")
    print("self-check ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
