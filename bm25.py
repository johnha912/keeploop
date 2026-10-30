"""bm25.py - the one BM25 ranker (stdlib). Shared by packs/ui-design/search.py
and kl recall / the headless prompt diet. Rows are dicts with a `_text` field."""

import math
import re
from collections import Counter

K1, B = 1.5, 0.75


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def bm25_rank(query: str, rows: list[dict]) -> list[tuple[float, dict]]:
    query_terms = _tokens(query)
    docs = [_tokens(row["_text"]) for row in rows]
    avg_len = sum(len(d) for d in docs) / max(1, len(docs))
    doc_freq = Counter()
    for doc in docs:
        doc_freq.update(set(doc))
    total = len(docs)
    scored = []
    for row, doc in zip(rows, docs):
        freq = Counter(doc)
        score = 0.0
        for term in query_terms:
            if term not in freq:
                continue
            idf = math.log(1 + (total - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            denom = freq[term] + K1 * (1 - B + B * len(doc) / avg_len)
            score += idf * (freq[term] * (K1 + 1)) / denom
        scored.append((score, row))
    return sorted(scored, key=lambda pair: pair[0], reverse=True)
