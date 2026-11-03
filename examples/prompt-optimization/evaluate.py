"""evaluate.py - accuracy of the workspace's prompt.md on the visible dev set. Humans only.

The prompt is the SYSTEM prompt of a small model (Claude Haiku through the
`claude` CLI). The harness supplies the label list, the numbered tickets and the
answer format, so prompt.md only has to say how to decide. Same contract as the
demo evaluate.py: ONE float on stdout (accuracy 0..1, higher is better), exit 2
on an invalid workspace, exit 1 on a crash. A failed or unparseable scoring call
is a crash, never a silent 0. A per-label breakdown and the commonest confusions
go to stderr.

Usage:  python evaluate.py <workspace-dir>
        python evaluate.py --self-check     (offline: parser and validation, no model call)
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MAX_PROMPT_CHARS = 6000
BATCH = 25
MODEL = "haiku"
CALL_TIMEOUT_S = 180
ASK = ("Classify each numbered banking customer message into exactly one of these labels:\n"
       "{labels}\n\nMessages:\n{tickets}\n\n"
       "Return only a JSON object that maps each message number (1 to {n}) to its label, "
       'like {{"1": "label", "2": "label"}}.')


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate(workspace: Path, data_name: str = "dev.jsonl") -> tuple[str, list[dict], str | None]:
    """(prompt, rows, error). error is None when the workspace can be scored."""
    p = workspace / "prompt.md"
    if not p.is_file():
        return "", [], "prompt.md is missing"
    prompt = p.read_text(encoding="utf-8").strip()
    if not prompt:
        return "", [], "prompt.md is empty"
    if len(prompt) > MAX_PROMPT_CHARS:
        return "", [], f"prompt.md is {len(prompt)} chars; the cap is {MAX_PROMPT_CHARS}"
    d = workspace / "data" / data_name
    if not d.is_file():
        return prompt, [], f"data/{data_name} is missing"
    return prompt, load_rows(d), None


def parse_labels(text: str, n: int) -> list[str] | None:
    """n labels from the JSON object {"1": label, ...} in a model reply (fences and chatter
    tolerated); a missing or non-string entry becomes "" (wrong). None if no usable object.
    Keyed, not a bare array: Haiku drops or merges items in a 25-long array about one batch in
    four (measured), and a miscount must cost one item, not crash the evaluation."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(out, dict):
        return None
    got = [out.get(str(i)) for i in range(1, n + 1)]
    if not any(isinstance(x, str) for x in got):
        return None
    return [x.strip() if isinstance(x, str) else "" for x in got]


def call_claude(system_prompt: str, user: str) -> str:
    """One scoring call. --safe-mode keeps the user's CLAUDE.md and hooks out (OAuth login stays)."""
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("claude CLI not found: this example scores prompts with real Claude "
                           "calls; install Claude CLI and log in (README, Reproduce), or run "
                           "evaluate.py --self-check for the offline check")
    argv = [exe, "-p", "--safe-mode", "--model", MODEL, "--tools", "",
            "--no-session-persistence", "--system-prompt", system_prompt]
    proc = subprocess.run(argv, input=user, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=CALL_TIMEOUT_S,
                          cwd=tempfile.gettempdir())  # a neutral cwd: nothing project-like to read
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:200]}")
    return proc.stdout


def classify(system_prompt: str, texts: list[str], labels: list[str], ask=call_claude) -> list[str]:
    """Labels for one batch. One retry on a failed or unparseable reply, then RuntimeError."""
    user = ASK.format(labels="\n".join(labels), n=len(texts),
                      tickets="\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1)))
    err = ""
    for _ in range(2):
        try:
            got = parse_labels(ask(system_prompt, user), len(texts))
            if got is not None:
                return got
            err = "reply held no JSON object of labels"
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
            err = str(exc)
    raise RuntimeError(f"batch failed twice: {err}")


def score(system_prompt: str, rows: list[dict], ask=call_claude) -> tuple[float, list[tuple[str, str]]]:
    """(accuracy, [(true, predicted)...]). Unknown or missing labels are wrong."""
    labels = sorted({r["label"] for r in rows})
    batches = [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]
    with ThreadPoolExecutor(len(batches)) as pool:
        preds = list(pool.map(lambda b: classify(system_prompt, [r["text"] for r in b], labels, ask), batches))
    pairs = [(r["label"], p) for b, got in zip(batches, preds) for r, p in zip(b, got)]
    return sum(t == p for t, p in pairs) / len(pairs), pairs


def report(pairs: list[tuple[str, str]]) -> None:
    per = Counter(t for t, _ in pairs)
    right = Counter(t for t, p in pairs if t == p)
    print("per-label accuracy:", file=sys.stderr)
    for lab in sorted(per):
        print(f"  {right[lab]:2d}/{per[lab]:2d}  {lab}", file=sys.stderr)
    conf = Counter((t, p) for t, p in pairs if t != p).most_common(8)
    print("top confusions (true -> predicted):", file=sys.stderr)
    for (t, p), c in conf:
        print(f"  {c}x  {t} -> {p}", file=sys.stderr)


def run(workspace: Path, data_name: str = "dev.jsonl") -> int:
    prompt, rows, error = validate(workspace, data_name)
    if error:
        print(f"INVALID WORKSPACE: {error}", file=sys.stderr)
        return 2
    try:
        acc, pairs = score(prompt, rows)
    except RuntimeError as exc:
        print(f"SCORING CRASHED: {exc}", file=sys.stderr)
        return 1
    report(pairs)
    print(f"{acc:.6f}")
    return 0


def self_check() -> int:
    assert parse_labels('{"1": "a", "2": "b"}', 2) == ["a", "b"]
    assert parse_labels('Sure!\n```json\n{"1": "a", "2": " b "}\n```', 2) == ["a", "b"]
    assert parse_labels('{"1": "a"}', 2) == ["a", ""]  # a missing entry is wrong, not a crash
    assert parse_labels('{"1": "a", "3": "c"}', 2) == ["a", ""]  # extra keys ignored
    assert parse_labels('{"1": 5, "2": null}', 2) is None  # no string label at all
    assert parse_labels("no object", 1) is None
    assert parse_labels('["a", "b"]', 2) is None  # a bare array is not the format
    assert parse_labels("{1: a}", 1) is None  # not JSON
    rows = [{"text": f"t{i}", "label": "x" if i % 2 else "y"} for i in range(50)]
    ticket = lambda user: re.findall(r"^(\d+)\. (t\d+)$", user, re.M)
    oracle = lambda sp, user: json.dumps({k: "x" if int(t[1:]) % 2 else "y" for k, t in ticket(user)})
    acc, pairs = score("p", rows, ask=oracle)
    assert acc == 1.0 and len(pairs) == 50
    wrong = lambda sp, user: json.dumps({k: "unknown" for k, _ in ticket(user)})
    assert score("p", rows, ask=wrong)[0] == 0.0  # unknown label = wrong
    calls = []

    def flaky(sp, user):
        calls.append(1)
        return "oops" if len(calls) == 1 else oracle(sp, user)
    assert classify("p", ["t1"], ["x", "y"], ask=flaky) == ["x"] and len(calls) == 2  # one retry
    try:
        classify("p", ["t1"], ["x"], ask=lambda sp, user: "oops")
        raise AssertionError("a batch that fails twice must raise")
    except RuntimeError:
        pass
    with tempfile.TemporaryDirectory() as tmp:
        w = Path(tmp)
        assert validate(w)[2] == "prompt.md is missing"
        (w / "prompt.md").write_text("  \n", encoding="utf-8")
        assert validate(w)[2] == "prompt.md is empty"
        (w / "prompt.md").write_text("x" * (MAX_PROMPT_CHARS + 1), encoding="utf-8")
        assert "cap" in validate(w)[2]
        (w / "prompt.md").write_text("ok", encoding="utf-8")
        assert validate(w)[2] == "data/dev.jsonl is missing"
        (w / "data").mkdir()
        (w / "data" / "dev.jsonl").write_text('{"text": "a", "label": "x"}\n', encoding="utf-8")
        assert validate(w)[2] is None and run(Path(tmp) / "nope") == 2
    print("self-check ok")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-check"]:
        raise SystemExit(self_check())
    if len(sys.argv) != 2:
        raise SystemExit("usage: python evaluate.py <workspace-dir> | --self-check")
    raise SystemExit(run(Path(sys.argv[1])))
