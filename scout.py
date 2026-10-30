"""scout.py — the Scout: watch the outside world, file proposals, change nothing.

Reads public sources about AI-assisted workflows, ranks them, dedupes against
everything ever seen, and appends survivors to `.keeploop/proposals.md`.
Proposals are INPUT, not commands: each one still has to pass the experiment
contract in program.md (a card, a test, the metric) before it changes anything.

Sources (stdlib urllib, fixed HTTPS hosts, 10 s timeout): Hacker News
(Algolia), arXiv cs.AI RSS, GitHub repository search (topics ai-agents, llm,
agentic-workflow, created in the last 14 days). GITHUB_TOKEN, if set, is sent
to api.github.com only (never redirected, never printed). A failing source
prints one line and is skipped; the scout still exits 0 offline.

Score = relevance x momentum x recency
  relevance = min(1, matched terms / 4); terms = TERMS + the words of 5+
              letters in program.md's "## Mission" (minus STOP). Items below
              --min-score relevance are dropped.
  momentum  = log1p(signal) / max over the same source, in 0..1, where signal
              is points+comments (HN), stars per day of age (GitHub), 1 (arXiv)
  recency   = exp(-age_days / 14)

All fetched text is untrusted: titles lose control and markdown-active
characters and are capped at 200 chars; only https URLs are written.

Usage:  python scout.py [--max N] [--min-score F] [--dry-run]
"""

import argparse
import ipaddress
import json
import math
import os
import re
import socket
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import packs
from prepare import CONFIG, CONTROL_RX, ROOT, __version__, load_team

TERMS = ["agent", "multi-agent", "workflow", "evaluation", "eval", "prompt",
         "llm", "automation", "benchmark", "orchestration", "guardrail",
         "ai coding", "code review", "self-improving"]
STOP = {"improve", "complete", "tasks", "domain", "measured", "prints", "cycle",
        "move", "information", "progress", "which", "their", "there", "would",
        "should", "could", "other", "these", "those", "where", "while", "every",
        "never", "always", "about", "after", "before", "first", "given"}

HN_QUERIES = ["AI agents workflow", "LLM evaluation", "multi-agent systems"]
ARXIV_FEED = "https://export.arxiv.org/rss/cs.AI"
GH_TOPICS = ["ai-agents", "llm", "agentic-workflow"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age(when: datetime) -> float:
    return max(0.0, (_now() - when).total_seconds() / 86400)


def _check_url(url: str) -> None:
    """https only, and the host must resolve to public addresses only (the first URL
    and every redirect). ponytail: DNS can change between this check and the connect
    (rebinding); pin the resolved IP if that threat matters."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("only https URLs")
    for info in socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP):
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        ip = getattr(ip, "ipv4_mapped", None) or ip
        if not ip.is_global:
            raise ValueError("host resolves to a non-public address")


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpsOnly)


def _open(req, timeout):
    return _OPENER.open(req, timeout=timeout)


def _fetch(url: str, as_json: bool = True):
    """GET a fixed https URL; None (plus one line) on any failure."""
    req = urllib.request.Request(url, headers={"User-Agent": f"keeploop-scout/{__version__}"})
    token = os.environ.get("GITHUB_TOKEN")
    if token and urllib.parse.urlsplit(url).hostname == "api.github.com":
        req.add_unredirected_header("Authorization", f"Bearer {token}")
    try:
        _check_url(url)
        with _open(req, 10) as resp:
            body = resp.read(2_000_000).decode("utf-8", "replace")  # cap a hostile response
        return json.loads(body) if as_json else body
    except Exception as exc:  # offline, blocked, malformed — all survivable
        print(f"scout: source unavailable ({urllib.parse.urlsplit(url).hostname}): "
              f"{exc.__class__.__name__}: {exc}")
        return None


def fetch_hn(queries: list[str] = HN_QUERIES) -> list[dict]:
    items = []
    for query in queries:
        data = _fetch("https://hn.algolia.com/api/v1/search?tags=story&hitsPerPage=10"
                      f"&query={urllib.parse.quote(query)}")
        for hit in (data or {}).get("hits", []):
            if hit.get("title") and hit.get("url") and hit.get("created_at_i"):
                raw = (hit.get("points") or 0) + (hit.get("num_comments") or 0)
                items.append({
                    "title": hit["title"], "url": hit["url"], "source": "Hacker News",
                    "summary": "", "signal": raw, "raw": f"points+comments={raw}",
                    "age": _age(datetime.fromtimestamp(hit["created_at_i"], timezone.utc))})
    return items


def fetch_arxiv() -> list[dict]:
    text = _fetch(ARXIV_FEED, as_json=False)
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    items = []
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]  # ignore namespaces
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        try:
            age = _age(parsedate_to_datetime(node.findtext("pubDate") or ""))
        except (TypeError, ValueError):
            age = 0.0
        if title and link:
            items.append({
                "title": title, "url": link, "source": "arXiv", "signal": 1.0,
                "summary": re.sub(r"<[^>]+>", "", node.findtext("description") or "")[:300],
                "raw": "n/a", "age": age})
    return items


def fetch_github(topics: list[str] = GH_TOPICS) -> list[dict]:
    since = (_now() - timedelta(days=14)).date().isoformat()
    items = []
    for topic in topics:
        data = _fetch("https://api.github.com/search/repositories?q="
                      f"topic:{topic}+created:%3E{since}&sort=stars&order=desc&per_page=10")
        for repo in (data or {}).get("items", []):
            try:
                age = _age(datetime.fromisoformat(repo["created_at"]))
                per_day = repo["stargazers_count"] / max(age, 1)
                items.append({
                    "title": f"{repo['full_name']}: {repo.get('description') or ''}",
                    "url": repo["html_url"], "source": "GitHub", "summary": "",
                    "signal": per_day, "raw": f"stars/day={per_day:.1f}", "age": age})
            except (KeyError, TypeError, ValueError):
                continue
    return items


def mission_terms(program: Path) -> list[str]:
    """Words of 5+ letters from the '## Mission' section of program.md."""
    if not program.exists():
        return []
    section = re.search(r"^## Mission\s*(.*?)(?=^## |\Z)",
                        program.read_text(encoding="utf-8"), re.S | re.M)
    words = re.findall(r"[a-z]{5,}", section.group(1).lower()) if section else []
    return sorted(set(words) - STOP)


def rank(items: list[dict], terms: list[str]) -> list[dict]:
    """Attach relevance, momentum, recency and their product; best first."""
    top: dict[str, float] = {}
    for i in items:
        top[i["source"]] = max(top.get(i["source"], 0.0), math.log1p(i["signal"]))
    out = []
    for i in items:
        text = f"{i['title']} {i['summary']}".lower()
        matched = [t for t in terms if t in text]
        rel = min(1.0, len(matched) / 4)
        mom = math.log1p(i["signal"]) / top[i["source"]] if top[i["source"]] else 1.0
        rec = math.exp(-i["age"] / 14)
        out.append({**i, "matched": matched, "rel": rel, "mom": mom, "rec": rec,
                    "score": rel * mom * rec})
    return sorted(out, key=lambda x: x["score"], reverse=True)


def clean_title(text: str) -> str:
    text = re.sub(CONTROL_RX, " ", text)
    return " ".join(re.sub(r"[\[\]()<>!`*_#|]", "", text).split())[:200]


def safe_url(url: str) -> str | None:
    ok = urllib.parse.urlsplit(url).scheme == "https" and not re.search(r"[\s\x00-\x1f<>]", url)
    return url if ok else None


def filter_new(items: list[dict], seen: dict) -> list[dict]:
    return [item for item in items if item["url"] not in seen]


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(prog="scout", description="keeploop scout")
    parser.add_argument("--max", type=int, default=CONFIG["scout_max_proposals"])
    parser.add_argument("--min-score", type=float,
                        default=CONFIG["scout_min_relevance"],
                        help="minimum relevance factor (0..1)")
    parser.add_argument("--state-dir", type=Path, default=root / ".keeploop")
    parser.add_argument("--dry-run", action="store_true",
                        help="print proposals; write nothing")
    args = parser.parse_args(argv)

    state = args.state_dir
    seen_path = state / "scout_seen.json"
    seen = json.loads(seen_path.read_text(encoding="utf-8")) if seen_path.exists() else {}

    # a pack's scout_topics replace the generic AI-workflow queries and terms
    team = load_team(root / "team.yaml") if (root / "team.yaml").exists() else {}
    topics = packs.scout_topics(packs.load_pack(root, team.get("pack", "software")))
    base_terms = [w for t in topics for w in re.findall(r"[a-z0-9]{3,}", t.lower())] or TERMS
    fetched = {i["url"]: i for i in
               (fetch_hn(topics) if topics else fetch_hn()) + fetch_arxiv()
               + (fetch_github([re.sub(r"\W+", "-", t.lower()) for t in topics])
                  if topics else fetch_github())}
    candidates = filter_new([i for i in fetched.values() if safe_url(i["url"])], seen)
    terms = list(dict.fromkeys(base_terms + mission_terms(root / "program.md")))
    ranked = rank(candidates, terms)
    proposals = [i for i in ranked if i["rel"] >= args.min_score][:args.max]

    stamp = _now().isoformat(timespec="seconds")
    text = "".join(
        f"\n## Proposal — {stamp}\n"
        f"- **{clean_title(i['title'])}** ({i['source']}) score {i['score']:.3f} = "
        f"relevance {i['rel']:.2f} x momentum {i['mom']:.2f} x recency {i['rec']:.2f}\n"
        f"- matched: {', '.join(i['matched'])}; {i['raw']}\n"
        f"- {i['url']}\n"
        f"- Status: proposed — needs an experiment card before adoption.\n"
        for i in proposals)
    if args.dry_run:
        print(text or "(no proposals)")
    else:
        state.mkdir(parents=True, exist_ok=True)
        for i in ranked:  # everything fetched counts as seen, proposed or not
            seen[i["url"]] = stamp
        seen_path.write_text(json.dumps(seen, indent=1), encoding="utf-8")
        if text:
            with (state / "proposals.md").open("a", encoding="utf-8") as f:
                f.write(text)
    print(f"scout: {len(candidates)} new items, {len(proposals)} proposals"
          + ("" if args.dry_run else f" filed to {state / 'proposals.md'}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
