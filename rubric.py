"""rubric.py — qualitative scoring: the second signal next to the metric.

Some of what a team produces cannot be reduced to one float from a test
suite: design quality, writing voice, analysis depth. Packs ship a
`rubric.md` — criteria, weights, anchors, and hard gates — and the Auditor
(a different vendor than the Engineer, per the standing rule) scores the
work against it.

rubric.md format (a markdown table; prose anchors may follow):

    | Criterion        | Weight | Gate |
    |------------------|--------|------|
    | Visual hierarchy | 25     | yes  |
    | Typography       | 20     | no   |

Rules (docs/SPEC.md):
- Total = weighted mean of criterion scores (0–100).
- A gate criterion scored < 50 caps the total at 49 — a hard fail,
  however pretty the average looks.
- The loop keeps a change only if the metric improves AND the rubric does
  not regress by more than REGRESSION_TOLERANCE points.
"""

import hashlib
import re
from pathlib import Path

REGRESSION_TOLERANCE = 5.0
GATE_MINIMUM = 50.0
GATE_CAP = 49.0


def load_rubric(path: Path | None) -> list[dict] | None:
    if path is None or not Path(path).exists():
        return None
    criteria = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not cells[1].isdigit():
            continue
        criteria.append({"name": cells[0], "weight": int(cells[1]),
                         "gate": cells[2].lower() in ("yes", "true", "gate")})
    return criteria or None


def _mock_scores(criteria: list[dict]) -> dict[str, float]:
    """Fixed 70..90 per criterion name: the demo's rubric never regresses."""
    return {c["name"]: 70 + int(hashlib.sha1(c["name"].encode()).hexdigest()[:6], 16) % 21
            for c in criteria}


def ask_text(criteria: list[dict]) -> str:
    """The instruction run.py appends to the audit prompt: one `Criterion: NN` line each."""
    return ("Then score the work 0-100 per criterion, one line each, exactly "
            "'Criterion: NN':\n" + "\n".join(f"- {c['name']}" for c in criteria))


def parse_scores(text: str, criteria: list[dict]) -> dict[str, float] | None:
    """{criterion: score} found in a reply, or None when none was given."""
    scores = {}
    for criterion in criteria:
        match = re.search(rf"{re.escape(criterion['name'])}\s*[:=]\s*(\d+(?:\.\d+)?)",
                          text, re.IGNORECASE)
        if match:
            scores[criterion["name"]] = float(match.group(1))
    return scores or None


def total(per_criterion: dict[str, float], criteria: list[dict]) -> float:
    """Weighted mean; a failed gate criterion caps it at GATE_CAP."""
    value = sum(per_criterion.get(c["name"], 0.0) * c["weight"]
                for c in criteria) / sum(c["weight"] for c in criteria)
    if any(c["gate"] and per_criterion.get(c["name"], 0.0) < GATE_MINIMUM for c in criteria):
        return min(value, GATE_CAP)
    return value


def reply_score(vendor, criteria: list[dict] | None, text: str) -> float | None:
    """Rubric total from an audit reply (the mock's fixed scores need no text)."""
    if not criteria:
        return None
    per = _mock_scores(criteria) if getattr(vendor, "is_mock", False) \
        else parse_scores(text, criteria)
    return None if per is None else total(per, criteria)


def score(vendor, criteria: list[dict] | None, *, subject: str, cwd=None) -> float | None:
    """Standalone rubric total for `subject` (its own vendor call), or None.
    The loop does not use this: it reads the scores from its one audit reply."""
    if not criteria:
        return None
    prompt = f"Work:\n{subject}\n\n{ask_text(criteria)}"
    try:
        text = "" if getattr(vendor, "is_mock", False) else vendor.complete(
            prompt, role="auditor", max_tokens=4000, cwd=cwd).text
    except Exception:
        return None
    return reply_score(vendor, criteria, text)
