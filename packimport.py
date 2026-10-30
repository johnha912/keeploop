"""packimport.py — `kl pack add | approve | list`: learn a profession pack
from a link or a name, as a gated DRAFT, never as instant trust.

    kl pack add <source> [--name NAME]   source = https URL or a bare name
    kl pack approve <name>               human-only: draft -> active
    kl pack list                         name, status, source

Accepted sources, tried in this order for a GitHub repository URL
(`https://github.com/OWNER/REPO`, optionally `/tree/REF/PATH`):
  1. a keeploop pack (a folder with pack.yaml at PATH, or under PATH/packs/)
     -> its .md/.yaml/.csv files are copied as they are;
  2. SKILL.md -> its principles section becomes a taste.md draft;
  3. README.md -> the same, as a fallback.
A direct link to a .md file is read like 2/3. A bare name is looked up with
GitHub repository search: one strong match is used, several are listed and
refused (never a silent pick), none is refused.

Everything is fetched through scout._fetch (https only, public addresses only
on every redirect, 2 MB cap, fixed User-Agent, 10 s timeout). Fetched text is
untrusted: no code is ever imported (a .py or other file is reported as "not
imported"), and an import is refused, with nothing written, when a gate fails:
  1. rubric: parses with rubric.py and its weights sum to 100 (±1). A skeleton
     (no criteria, or TODO markers) is allowed for a draft; approve refuses it.
  2. secret scan (run.SECRET_PATTERNS, kind only, never the value) over all
     fetched text; slop scan (the active pack's rules) over the prose files.
  3. size: taste and rubric files within guardrail_max_chars.
  4. name collision: an existing active pack, or a draft from another source.
A draft is refused by packs.load_pack until `kl pack approve`, which re-runs
gates 1-3 with a complete rubric (weights sum to 100, at least one gate).
"""

import fnmatch
import hashlib
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import packs
import rubric as rubric_mod
import run as R
import scout
from prepare import CONFIG, load_team, parse_team

ALLOWED = (".md", ".yaml", ".csv")
CODE = (".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash", ".ps1", ".bat", ".cmd",
        ".rb", ".pl", ".php", ".exe", ".dll", ".so", ".jar")
MAX_FILES = 40           # files copied from one source pack
MAX_DEPTH = 2            # folders below the pack folder (data/ ...)
SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,99}")
NAME_RX = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
BARE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
METRIC_RX = re.compile(r"\b(metric|benchmark)s?\b", re.I)
PRINCIPLES = re.compile(r"^(#{1,4})[ \t]+[^\n]*?\b(principles?|rules?|guidelines?|standards?|"
                        r"best practices?|taste|checklist|do'?s and don'?ts)\b", re.I | re.M)
UNSAFE_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f‎‏‪-‮⁦-⁩]")

SKELETON_RUBRIC = """# Rubric - {name}

Skeleton from `kl pack add`: the source states no criteria or weights. Fill every
TODO (weights sum to 100, at least one gate); `kl pack approve` refuses a skeleton.

| Criterion | Weight | Gate |
|---|---|---|
| TODO criterion that must never fail | TODO | yes |
| TODO quality criterion | TODO | no |

Anchors: TODO 90+ = ..., 70 = ..., 50 = ..., below 50 on a gate = hard fail.
"""


class ImportRefused(ValueError):
    pass


# --- small helpers ------------------------------------------------------------

def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:41].strip("-")


def check_name(name: str) -> None:
    if not NAME_RX.fullmatch(name or ""):
        raise ImportRefused("pack name: lowercase letters, digits and - only")
    if re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", name, re.I):
        raise ImportRefused(f"{name!r} is a reserved device name on Windows")


def clean(text: str) -> str:
    """Untrusted text: CRLF to LF, controls (except tab and newline) and bidi overrides out."""
    return UNSAFE_CHARS.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))


def _one_line(text: str, cap: int = 200) -> str:
    """A safe value for the minimal yaml loader: one line, no comment marker."""
    return " ".join(clean(text).replace("#", "").split())[:cap]


def _get(fetch, url: str, as_json: bool, what: str):
    data = fetch(url, as_json=as_json)
    if data is None:
        raise ImportRefused(f"could not fetch {what} ({url}); the line above says why")
    return data


# --- where the source lives -----------------------------------------------------

def parse_github(url: str) -> dict | None:
    """github.com/OWNER/REPO[/tree|blob/REF/PATH] -> parts, else None."""
    parts = urllib.parse.urlsplit(url)
    if (parts.hostname or "").lower() not in ("github.com", "www.github.com"):
        return None
    seg = [s for s in parts.path.split("/") if s]
    if len(seg) < 2:
        return None
    owner, repo = seg[0], seg[1].removesuffix(".git")
    kind, ref, path = "repo", "", ""
    if len(seg) >= 4 and seg[2] in ("tree", "blob"):
        kind, ref, path = seg[2], seg[3], "/".join(seg[4:])
    if not all(SEGMENT.fullmatch(s) for s in [owner, repo] + ([ref] if ref else [])
               + [s for s in path.split("/") if s]):
        raise ImportRefused("unsupported characters in the GitHub URL")
    return {"owner": owner, "repo": repo, "kind": kind, "ref": ref, "path": path}


def _contents_url(gh: dict, path: str) -> str:
    q = f"?ref={urllib.parse.quote(gh['ref'])}" if gh["ref"] else ""
    return (f"https://api.github.com/repos/{gh['owner']}/{gh['repo']}/contents/"
            f"{urllib.parse.quote(path)}{q}")


def resolve_name(name: str, fetch) -> str:
    """A bare name -> exactly one repository URL, or a refusal that lists the options."""
    if not BARE_NAME.fullmatch(name):
        raise ImportRefused("a source is an https URL or a bare name (letters, digits, . _ -)")
    url = ("https://api.github.com/search/repositories?q="
           f"{urllib.parse.quote(name + ' skill')}&sort=stars&order=desc&per_page=10")
    items = (_get(fetch, url, True, "GitHub search") or {}).get("items") or []
    want = slug(name)

    def core(repo_name: str) -> str:
        s = slug(repo_name)
        for affix in ("claude-", "agent-"):
            s = s.removeprefix(affix)
        for affix in ("-skills", "-skill", "-pack"):
            s = s.removesuffix(affix)
        return s

    repos = [i for i in items if isinstance(i, dict) and scout.safe_url(str(i.get("html_url", "")))]
    strong = [i for i in repos if core(str(i.get("name", ""))) == want]
    plausible = [i for i in repos if want in slug(str(i.get("name", "")))
                 or want in str(i.get("description") or "").lower()]
    if len(strong) == 1:
        return strong[0]["html_url"]
    options = (strong or plausible)[:5]
    if not options:
        raise ImportRefused(f"no repository matches {name!r}; give the URL instead")
    listing = "\n  ".join(f"{i['html_url']} ({i.get('stargazers_count', 0)} stars) "
                          f"{scout.clean_title(str(i.get('description') or ''))[:80]}"
                          for i in options)
    raise ImportRefused(f"{len(options)} repositories could be {name!r}; pick one and run "
                        f"`kl pack add URL`:\n  {listing}")


# --- collecting the source ----------------------------------------------------------

def _not_imported(name: str) -> str:
    kind = "code" if Path(name).suffix.lower() in CODE else "not .md/.yaml/.csv"
    return f"{name}: not imported — {kind}"


def _walk_pack(gh: dict, path: str, fetch, out: dict, notes: list, rel: str = "",
               depth: int = 0) -> None:
    listing = _get(fetch, _contents_url(gh, path), True, "the pack folder")
    if not isinstance(listing, list):
        raise ImportRefused(f"{path or '/'} is not a folder")
    for e in listing:
        name, typ = str(e.get("name", "")), e.get("type")
        rel_name = f"{rel}{name}"
        if not SEGMENT.fullmatch(name) or name.startswith("."):
            notes.append(f"{rel_name}: not imported — unsafe or hidden name")
        elif typ == "dir":
            if depth >= MAX_DEPTH:
                notes.append(f"{rel_name}/: not imported — folder too deep")
            else:
                _walk_pack(gh, f"{path}/{name}", fetch, out, notes, rel_name + "/", depth + 1)
        elif typ != "file":
            notes.append(f"{rel_name}: not imported — {typ}")
        elif Path(name).suffix.lower() not in ALLOWED:
            notes.append(_not_imported(rel_name))
        else:
            if len(out) >= MAX_FILES:
                raise ImportRefused(f"the source pack has more than {MAX_FILES} files")
            url = str(e.get("download_url") or "")
            if not scout.safe_url(url):
                raise ImportRefused(f"{rel_name}: no https download link")
            out[rel_name] = clean(_get(fetch, url, False, rel_name))


def _find_pack(gh: dict, fetch, wanted: str | None) -> tuple[str, list] | None:
    """(path of a keeploop pack folder, top-level listing) or (None, listing)."""
    top = _get(fetch, _contents_url(gh, gh["path"]), True, "the repository")
    if not isinstance(top, list):
        raise ImportRefused("the GitHub path is not a folder; link a .md file or a repo/folder")
    names = {str(e.get("name", "")): e for e in top}
    if "pack.yaml" in names:
        return gh["path"], top
    if names.get("packs", {}).get("type") != "dir":
        return None, top
    base = f"{gh['path']}/packs".strip("/")
    found = []
    for e in _get(fetch, _contents_url(gh, base), True, "packs/")[:20]:
        if e.get("type") == "dir" and SEGMENT.fullmatch(str(e.get("name", ""))):
            sub = _get(fetch, _contents_url(gh, f"{base}/{e['name']}"), True, f"packs/{e['name']}")
            if isinstance(sub, list) and any(s.get("name") == "pack.yaml" for s in sub):
                found.append(str(e["name"]))
    if not found:
        return None, top
    if len(found) == 1:
        return f"{base}/{found[0]}", top
    if wanted in found:
        return f"{base}/{wanted}", top
    raise ImportRefused(f"the repository has {len(found)} packs ({', '.join(found)}); "
                        "pick one with --name")


def collect(source_url: str, fetch, wanted: str | None) -> dict:
    """Fetch the source -> {kind, url, files {rel: text}, text, notes, default}."""
    url = urllib.parse.urlsplit(source_url)._replace(fragment="").geturl()
    if not scout.safe_url(url):
        raise ImportRefused("only https URLs (no spaces or control characters)")
    gh = parse_github(url)
    notes: list[str] = []
    if gh and gh["kind"] == "blob" or (not gh and url.lower().split("?")[0].endswith(".md")):
        if gh:
            if not gh["path"].lower().endswith(".md"):
                raise ImportRefused("only .md files can be imported from a file link")
            raw = (f"https://raw.githubusercontent.com/{gh['owner']}/{gh['repo']}/"
                   f"{gh['ref']}/{gh['path']}")
        else:
            raw = url
        text = clean(_get(fetch, raw, False, "the .md file"))
        stem = Path(urllib.parse.urlsplit(raw).path).stem
        parent = Path(urllib.parse.urlsplit(raw).path).parent.name
        default = (gh["repo"] if gh else parent) if stem.lower() in ("skill", "readme") else stem
        return {"kind": "skill" if stem.lower() == "skill" else "markdown", "url": url,
                "files": {Path(urllib.parse.urlsplit(raw).path).name: text}, "text": text,
                "notes": notes,
                "default": default}
    if not gh:
        raise ImportRefused("unsupported source: give a GitHub repository URL or a direct .md link")
    pack_path, top = _find_pack(gh, fetch, wanted)
    if pack_path is not None:
        files: dict = {}
        _walk_pack(gh, pack_path, fetch, files, notes)
        blob = "".join(f"{k}\0{files[k]}\0" for k in sorted(files))
        return {"kind": "pack", "url": url, "files": files, "text": blob, "notes": notes,
                "default": pack_path.rsplit("/", 1)[-1] or gh["repo"]}
    entries = {str(e.get("name", "")).lower(): e for e in top if e.get("type") == "file"}
    notes += [_not_imported(n) for n in sorted(str(e.get("name", "")) for e in top
                                               if e.get("type") == "file")
              if Path(n).suffix.lower() in CODE]
    for wanted_file, kind in (("skill.md", "skill"), ("readme.md", "readme")):
        if wanted_file in entries:
            dl = str(entries[wanted_file].get("download_url") or "")
            if not scout.safe_url(dl):
                raise ImportRefused(f"{wanted_file}: no https download link")
            text = clean(_get(fetch, dl, False, wanted_file))
            return {"kind": kind, "url": url, "files": {entries[wanted_file]["name"]: text},
                    "text": text, "notes": notes,
                    "default": gh["path"].rsplit("/", 1)[-1] if gh["path"] else gh["repo"]}
    raise ImportRefused("the source has no keeploop pack, SKILL.md or README.md")


# --- turning text into a draft pack ------------------------------------------------

def split_frontmatter(text: str) -> tuple[str, str]:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            return text[4:end], text[end + 4:].lstrip("-").lstrip("\n")
    return "", text


def principles(body: str) -> str:
    """The principles/rules/guidelines section (up to the next heading of its level),
    or the whole body when the source has none."""
    m = PRINCIPLES.search(body)
    if not m:
        return body.strip()
    level, section = len(m.group(1)), body[m.start():]
    first = section.find("\n")
    if first == -1:
        return section.strip()
    nxt = re.compile(r"^#{1,%d}[ \t]" % level, re.M).search(section, first + 1)
    return (section[:nxt.start()] if nxt else section).strip()


def rubric_rows(text: str) -> list[tuple[str, int, bool]] | None:
    """Criteria from the first markdown table whose header names a weight."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "|" not in line or not re.search(r"\bweights?\b", line, re.I):
            continue
        head = [c.strip().lower() for c in line.strip().strip("|").split("|")]
        wi = next(k for k, c in enumerate(head) if re.search(r"\bweights?\b", c))
        gi = next((k for k, c in enumerate(head) if "gate" in c), None)
        rows = []
        for row in lines[i + 1:]:
            if "|" not in row:
                break
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if not "".join(cells).strip("-: ") or wi >= len(cells):
                continue
            weight = re.sub(r"\D", "", cells[wi])
            name = _one_line(cells[0], 80).replace("|", "")
            if weight and name and wi != 0:
                gate = gi is not None and gi < len(cells) and \
                    cells[gi].lower() in ("yes", "y", "true", "gate", "x", "✓")
                rows.append((name, int(weight), gate))
        if rows:
            return rows
    return None


def render_rubric(name: str, rows: list[tuple[str, int, bool]]) -> str:
    table = "\n".join(f"| {n} | {w} | {'yes' if g else 'no'} |" for n, w, g in rows)
    return (f"# Rubric - {name}\n\nMapped by `kl pack add` from the source's own criteria "
            f"table.\n\n| Criterion | Weight | Gate |\n|---|---|---|\n{table}\n\n"
            "Anchors: 90+ = would ship as is · 70 = minor notes · 50 = rework the weak "
            "criterion · <50 on a gate criterion = hard fail.\n")


def is_skeleton(text: str) -> bool:
    return "TODO" in text or rubric_mod.parse_rubric(text) is None


def rubric_problem(text: str, final: bool) -> str | None:
    """Gate 1. `final` (approve) also wants a gate criterion and no TODO markers."""
    if final and "TODO" in text:
        return "rubric still has TODO markers"
    criteria = rubric_mod.parse_rubric(text)
    if not criteria:
        return "rubric has no criteria table (| Criterion | Weight | Gate |)"
    total = sum(c["weight"] for c in criteria)
    if abs(total - 100) > 1:
        return f"rubric weights sum to {total}, not 100"
    if final and not any(c["gate"] for c in criteria):
        return "rubric has no gate criterion (Gate = yes)"
    return None


def scan(texts: dict, slop: list) -> None:
    """Gate 2: secrets in every text (and file name), slop in the prose files only
    (a pack.yaml's own slop regexes would match themselves). Never prints a value."""
    for label, text in texts.items():
        bare = text.replace("\0", "")
        if any(fnmatch.fnmatchcase(Path(label).name.casefold(), g) for g in R.SECRET_FILES):
            raise ImportRefused(f"secret gate: secret file name ({label})")
        for kind, rx in R.SECRET_PATTERNS.items():
            if rx.search(bare):
                raise ImportRefused(f"secret gate: {kind} in {label} (value not shown)")
        if not label.endswith(".yaml"):
            for rule, rx, reason in slop:
                if rx.search(bare):
                    raise ImportRefused(f"slop gate: {rule} ({reason}) in {label}")


def check_sizes(texts: dict, cap: int) -> None:
    """Gate 3: taste and rubric files within the guardrail size limit."""
    for label, text in texts.items():
        if len(text) > cap:
            raise ImportRefused(f"size gate: {label} is {len(text)} chars, over the "
                                f"{cap} limit; link a shorter file or the principles section")


def _strip_keys(yaml_text: str, keys: tuple) -> str:
    """Drop top-level `key:` lines (and their indented block) for the given keys."""
    out, skipping = [], False
    for line in yaml_text.splitlines():
        top = line[:1] not in (" ", "\t", "") and not line.startswith("#")
        if top:
            skipping = line.split(":", 1)[0].strip() in keys
        if not skipping:
            out.append(line)
    return "\n".join(out).rstrip() + "\n"


def _source_block(url: str, sha: str, stamp: str) -> str:
    return (f"status: draft\nsource:\n  url: {url}\n  sha256: {sha}\n"
            f"  imported_at: {stamp}\n")


def build(name: str, src: dict, stamp: str) -> tuple[dict, list, dict, str, bool]:
    """-> ({relpath: text} to write, report notes, {file: text} under the size gate,
    the rubric text, whether the source names a metric)."""
    sha = _sha(src["text"])
    notes = list(src["notes"])
    if src["kind"] == "pack":
        files = dict(src["files"])
        if "pack.yaml" not in files:
            raise ImportRefused("the source pack has no pack.yaml")
        try:
            meta = parse_team(files["pack.yaml"])
        except ValueError as exc:
            raise ImportRefused(f"source pack.yaml: {exc}")
        for key in ("taste_file", "rubric_file"):
            v = meta.get(key)
            if v is not None and not (isinstance(v, str) and SEGMENT.fullmatch(v)):
                raise ImportRefused(f"source pack.yaml: {key} must be a file name in the pack")
        rubric_name = meta.get("rubric_file") or "rubric.md"
        if rubric_name not in files:
            files[rubric_name] = SKELETON_RUBRIC.format(name=name)
            notes.append(f"{rubric_name}: the source has none; skeleton written")
        taste_name = next((t for t in (meta.get("taste_file"), "taste.md", "SKILL.md")
                           if t and t in files), None)
        files["pack.yaml"] = _strip_keys(files["pack.yaml"], ("status", "source")) + \
            _source_block(src["url"], sha, stamp)
        for key in ("roles", "slop"):
            if isinstance(meta.get(key), dict) and meta[key]:
                notes.append(f"pack.yaml defines {len(meta[key])} {key} "
                             f"(they join audits / gates once active): review them")
        metric = meta.get("metric") or meta.get("metric_examples")
        has_metric = bool(metric) and not str(metric).startswith("TODO")
        sized = {k: files[k] for k in (taste_name, rubric_name) if k}
        rubric_text = files[rubric_name]
    else:
        front, body = split_frontmatter(src["text"])
        desc = re.search(r"^description:\s*(.+)$", front, re.M)
        section = principles(body)
        taste = (f"> Imported by `kl pack add` — DRAFT, untrusted until `kl pack approve`.\n"
                 f"> source: {src['url']}\n> fetched_at: {stamp}\n> sha256: {sha}\n\n"
                 f"# Taste - {name}\n\n{section}\n")
        rows = rubric_rows(body)
        rubric_text = render_rubric(name, rows) if rows else SKELETON_RUBRIC.format(name=name)
        has_metric = bool(METRIC_RX.search(body))
        description = _one_line(desc.group(1) if desc else "") or f"Imported from {src['url']}"
        meta_yaml = (f"name: {name}\n"
                     f"profession: {_one_line(name.replace('-', ' '), 80)}\n"
                     f"description: {description}\n"
                     f"metric: {'see the source; confirm it for evaluate.py' if has_metric else 'not stated by the source; see .keeploop/questions.md'}\n"
                     f"taste_file: taste.md\nrubric_file: rubric.md\n"
                     + _source_block(src["url"], sha, stamp))
        files = {"taste.md": taste, "rubric.md": rubric_text, "pack.yaml": meta_yaml}
        sized = {"taste.md": taste, "rubric.md": rubric_text}
        if desc is None:
            notes.append("the source has no frontmatter description; pack.yaml description "
                         "points at the source")
    try:
        parse_team(files["pack.yaml"])
    except ValueError as exc:
        raise ImportRefused(f"generated pack.yaml does not parse: {exc}")
    return files, notes, sized, rubric_text, has_metric


# --- commands -----------------------------------------------------------------------

def _meta(pack_dir: Path) -> dict:
    try:
        return load_team(pack_dir / "pack.yaml")
    except ValueError as exc:
        raise ImportRefused(f"{pack_dir / 'pack.yaml'}: {exc}")


def _append(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def add(root: Path, state: Path, source: str, name: str | None = None, *, slop=(),
        cap: int = CONFIG["guardrail_max_chars"], fetch=None) -> list[str]:
    """Import `source` as packs/<name>/ in draft state. Every gate runs before any
    write; a refusal (ImportRefused) leaves the disk untouched."""
    fetch = fetch or scout._fetch
    if name is not None:
        check_name(name)
    if "://" in source:
        url = source
    else:
        url = resolve_name(source, fetch)
    src = collect(url, fetch, name)
    name = name or slug(src["default"])
    check_name(name)

    pack_dir = root / "packs" / name  # gate 4 first: cheapest, and decides overwrite
    if pack_dir.exists():
        if not (pack_dir / "pack.yaml").exists():
            raise ImportRefused(f"{pack_dir} exists and is not a pack")
        meta = _meta(pack_dir)
        if meta.get("status") != "draft":
            raise ImportRefused(f"pack {name!r} already exists and is active; use --name")
        old = (meta.get("source") or {}).get("url") if isinstance(meta.get("source"), dict) else None
        if old != src["url"]:
            raise ImportRefused(f"pack {name!r} is a draft from another source ({old}); "
                                "use --name")

    stamp = _stamp()
    files, notes, sized, rubric_text, has_metric = build(name, src, stamp)
    skeleton = is_skeleton(rubric_text)
    if not skeleton and (problem := rubric_problem(rubric_text, final=False)):
        raise ImportRefused(f"rubric gate: {problem}")
    scan(src["files"], slop)  # all fetched text, before anything is written
    check_sizes(sized, cap)

    for rel, text in files.items():  # every gate passed: now, and only now, write
        p = pack_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    sha = _sha(src["text"])
    _append(state / "proposals.md",
            f"\n## Pack import — {stamp}: {name} ({src['kind']}) from {src['url']}, sha256 "
            f"{sha[:12]}, status: draft — a human reviews packs/{name}/ then runs "
            f"`kl pack approve {name}`\n")
    asked = False
    if not has_metric:
        q = (f"- (pack {name}) What AUTOMATIC metric (a number evaluate.py prints, higher is "
             f"better) judges this pack's work? The source names none.\n")
        qs = state / "questions.md"
        if q not in (qs.read_text(encoding="utf-8") if qs.exists() else ""):
            _append(qs, q)
        asked = True

    report = [f"DRAFT pack {name!r} imported ({src['kind']}) from {src['url']}",
              f"  sha256 {sha}",
              f"  wrote packs/{name}/: {', '.join(sorted(files))}"]
    report += [f"  {n}" for n in notes]
    report.append("  rubric: SKELETON — fill it before approval (weights sum 100, a gate)"
                  if skeleton else "  rubric: parsed, weights sum to 100")
    if asked:
        report.append("  metric: none named; the question is in .keeploop/questions.md")
    report.append(f"Next: the human reviews packs/{name}/ and runs `kl pack approve {name}`. "
                  "Until then the pack refuses to load.")
    if (state / "fence.json").exists():
        report.append("Note: packs/ is inside the fence; after add/approve the human runs "
                      "`kl begin --accept-changes` between cycles (it needs a clean workspace).")
    return report


def approve(root: Path, state: Path, name: str, *, slop=(),
            cap: int = CONFIG["guardrail_max_chars"]) -> list[str]:
    """Human-only: re-run gates 1-3 with a complete rubric, then draft -> active."""
    check_name(name)
    pack_dir = root / "packs" / name
    if not (pack_dir / "pack.yaml").exists():
        raise ImportRefused(f"no pack named {name!r}")
    meta = _meta(pack_dir)
    if meta.get("status") != "draft":
        raise ImportRefused(f"pack {name!r} is not a draft (status: {meta.get('status') or 'active'})")
    rubric_name = str(meta.get("rubric_file") or "rubric.md")
    taste_name = str(meta.get("taste_file") or "taste.md")
    for n in (rubric_name, taste_name):
        if not SEGMENT.fullmatch(n):
            raise ImportRefused(f"pack.yaml: {n!r} must be a file name in the pack")
    rubric_path = pack_dir / rubric_name
    if not rubric_path.exists():
        raise ImportRefused(f"{rubric_name} is missing")
    rubric_text = rubric_path.read_text(encoding="utf-8")
    if problem := rubric_problem(rubric_text, final=True):
        raise ImportRefused(f"rubric gate: {problem}")
    texts = {p.relative_to(pack_dir).as_posix(): p.read_text(encoding="utf-8", errors="replace")
             for p in sorted(pack_dir.rglob("*")) if p.is_file() and not p.is_symlink()
             and p.suffix.lower() in ALLOWED}
    code = [p.relative_to(pack_dir).as_posix() for p in pack_dir.rglob("*")
            if p.is_file() and p.suffix.lower() not in ALLOWED]
    if code:
        raise ImportRefused("the pack holds files that are not .md/.yaml/.csv: "
                            + ", ".join(sorted(code)[:5]))
    scan(texts, slop)
    check_sizes({k: v for k, v in texts.items() if k in (rubric_name, taste_name)}, cap)
    yaml_path = pack_dir / "pack.yaml"
    text = yaml_path.read_text(encoding="utf-8")
    new, count = re.subn(r"^status:[ \t]*draft[ \t]*$", "status: active", text, count=1,
                         flags=re.M)
    if count != 1:
        raise ImportRefused("pack.yaml has no `status: draft` line to flip")
    yaml_path.write_text(new, encoding="utf-8")
    _append(state / "proposals.md", f"\n## Pack approved — {_stamp()}: {name} "
                                     f"(draft -> active)\n")
    out = [f"ACTIVE pack {name!r}: rubric complete, gates passed. Select it with "
           f"`pack: {name}` in team.yaml."]
    if (state / "fence.json").exists():
        out.append("Note: packs/ is inside the fence; the human runs `kl begin "
                   "--accept-changes` between cycles (it needs a clean workspace).")
    return out


def listing(root: Path) -> list[str]:
    rows = []
    for name in packs.discover(root):
        try:
            meta = load_team(root / "packs" / name / "pack.yaml")
        except ValueError:
            rows.append(f"{name:<24} {'unreadable':<13} -")
            continue
        src = meta.get("source") if isinstance(meta.get("source"), dict) else {}
        rows.append(f"{name:<24} {str(meta.get('status') or 'active'):<13} "
                    f"{src.get('url') or 'local'}")
    return [f"{'name':<24} {'status':<13} source"] + rows if rows else ["no packs"]
