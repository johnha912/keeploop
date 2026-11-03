"""prepare_data.py - build data/dev.jsonl and data/holdout.jsonl from Banking77.

Banking77 (PolyAI, CC BY 4.0), test split. Ten near-duplicate "status" intents; per
intent a fixed-seed shuffle of the sorted rows, the first 20 go to dev, the next
20 to holdout (disjoint); each split is then shuffled (fixed seed). Output is byte-for-byte reproducible.

Usage:  python -X utf8 prepare_data.py [raw_dir]
raw_dir defaults to $KLP_RAW or <system temp>/klp-raw (never inside the repo).
"""

import csv
import json
import os
import random
import sys
import tempfile
import urllib.request
from pathlib import Path

URL = ("https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/"
       "master/banking_data/test.csv")
SEED = 77
PER_SPLIT = 20
# Rule, fixed before scoring: every top-up, transfer and cash-withdrawal intent whose name
# states a status (failed, reverted, pending, declined, not received) or timing. Exactly 10.
INTENTS = [
    "declined_cash_withdrawal", "declined_transfer", "failed_transfer", "pending_cash_withdrawal",
    "pending_top_up", "pending_transfer", "top_up_failed", "top_up_reverted",
    "transfer_not_received_by_recipient", "transfer_timing",
]


def download(raw: Path) -> Path:
    raw.mkdir(parents=True, exist_ok=True)
    dest = raw / "test.csv"
    if not dest.exists():
        tmp = raw / "test.csv.tmp"  # replace only on success
        with urllib.request.urlopen(URL, timeout=60) as resp:
            tmp.write_bytes(resp.read())
        tmp.replace(dest)
    return dest


def build(csv_path: Path) -> tuple[list[dict], list[dict]]:
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8", newline="")))
    dev, hold = [], []
    for label in INTENTS:
        texts = sorted(r["text"].strip() for r in rows if r["category"] == label)
        random.Random(f"{SEED}:{label}").shuffle(texts)
        if len(texts) < 2 * PER_SPLIT:
            raise SystemExit(f"{label}: only {len(texts)} rows")
        dev += [{"text": t, "label": label} for t in texts[:PER_SPLIT]]
        hold += [{"text": t, "label": label} for t in texts[PER_SPLIT:2 * PER_SPLIT]]
    for i, items in enumerate((dev, hold)):  # mixed order: a batch must not be one label
        random.Random(f"{SEED}:order:{i}").shuffle(items)
    return dev, hold


def write(path: Path, items: list[dict]) -> None:
    path.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items),
                    encoding="utf-8", newline="\n")


def main() -> int:
    raw = Path(sys.argv[1] if len(sys.argv) > 1
               else os.environ.get("KLP_RAW") or Path(tempfile.gettempdir()) / "klp-raw")
    dev, hold = build(download(raw))
    assert not {d["text"] for d in dev} & {h["text"] for h in hold}, "splits overlap"
    out = Path(__file__).resolve().parent / "data"
    out.mkdir(exist_ok=True)
    write(out / "dev.jsonl", dev)
    write(out / "holdout.jsonl", hold)
    print(f"wrote {len(dev)} dev and {len(hold)} holdout items to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
