"""packs.py — profession packs: how keeploop adapts to any field of work.

The loop is profession-agnostic. Everything domain-specific lives in a
pack under `packs/<name>/`:

    pack.yaml   metadata: profession, what the metric usually is, files
    taste.md    craft standards — the distilled judgment of the field
                (principles, anti-patterns, voice). Read by the Analyst
                and Engineer; enforced by the Auditor. This is the layer
                projects like "taste" skills encode: what good looks like
                when a number alone cannot say it.
    rubric.md   a weighted scoring rubric with anchors and hard gates,
                used by the Auditor for qualitative scoring (the layer
                data-driven design systems like UI/UX skill packs pair
                with searchable reference data).
    data/       optional searchable reference data (CSV) + a search
                script, e.g. packs/ui-design/search.py.

team.yaml selects the pack:  pack: ui-design
"""

import re
from pathlib import Path

from prepare import load_team


class DraftPack(ValueError):
    """The selected pack was imported by `kl pack add` and is not approved yet."""


def discover(root: Path) -> list[str]:
    base = root / "packs"
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir()
                  if p.is_dir() and (p / "pack.yaml").exists())


def load_pack(root: Path, name: str | None) -> dict | None:
    if not name:
        return None
    pack_dir = root / "packs" / name
    meta_path = pack_dir / "pack.yaml"
    if not meta_path.exists():
        print(f"packs: no pack named {name!r} under {root / 'packs'} — "
              f"continuing without a pack")
        return None
    meta = load_team(meta_path)
    if meta.get("status") == "draft":  # imported text is untrusted until a human approves it
        raise DraftPack(f"pack {name!r} is a draft — run `kl pack approve {name}` after review")
    taste = ""
    for candidate in (meta.get("taste_file"), "taste.md", "SKILL.md"):
        if candidate and (pack_dir / candidate).exists():
            taste = (pack_dir / candidate).read_text(encoding="utf-8")
            break
    rubric_path = pack_dir / meta.get("rubric_file", "rubric.md")
    return {
        "name": name,
        "dir": pack_dir,
        "meta": meta,
        "taste": taste,
        "rubric_path": rubric_path if rubric_path.exists() else None,
    }


def _words(value) -> list[str]:
    """`a, b, [c]` -> ['a', 'b', 'c'] (the minimal yaml loader has no lists)."""
    return [w.strip() for w in str(value or "").strip("[] ").split(",") if w.strip()]


def scout_topics(pack: dict | None) -> list[str]:
    """Topics a pack wants the scout to watch (`scout_topics: a, b` in pack.yaml)."""
    return _words(((pack or {}).get("meta") or {}).get("scout_topics"))


def specialists_text(pack: dict | None) -> str:
    """The pack's `roles:` as checklist lines for the ONE heavy-change audit call.
    A role has `checklist: text` or `checklist_file: path` (inside the pack folder)."""
    roles = ((pack or {}).get("meta") or {}).get("roles")
    out = []
    for name, cfg in (roles.items() if isinstance(roles, dict) else ()):
        cfg = cfg if isinstance(cfg, dict) else {}
        text = str(cfg.get("checklist") or "")
        if cfg.get("checklist_file"):
            path = (pack["dir"] / str(cfg["checklist_file"])).resolve()
            if path.is_file() and path.is_relative_to(pack["dir"].resolve()):
                text = path.read_text(encoding="utf-8")
        if " ".join(text.split()):
            out.append(f"- {name}: {' '.join(text.split())}")
    return ("Specialist reviewers (this change is heavy): also check each list below and "
            "prefix every failed item with the reviewer's name.\n" + "\n".join(out)) if out else ""


def slop_rules(pack: dict | None) -> list:
    """pack.yaml `slop:` -> [(name, compiled regex, reason)]. Each line is
    `name: regex => reason`; an invalid regex is skipped with a warning."""
    spec = ((pack or {}).get("meta") or {}).get("slop")
    out = []
    for name, line in (spec.items() if isinstance(spec, dict) else ()):
        pattern, _, reason = str(line).partition(" => ")
        try:
            out.append((name, re.compile(pattern.strip()), reason.strip() or "banned"))
        except re.error:
            print(f"packs: slop rule {name!r} is not a valid regex; skipped")
    return out
