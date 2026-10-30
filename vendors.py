"""vendors.py — one interface, every AI vendor.

The team's roles are routed to vendors in team.yaml. A vendor is anything
that can take a prompt and return text: a hosted API (v0.2), a local CLI
(`claude`, `codex`, `gemini`), or the built-in deterministic MockVendor
used by the demo and the tests.

Contract (docs/SPEC.md §5):
- `available()` says whether the vendor can be called at all.
- `complete()` returns a VendorResult for task-level outcomes — including
  bad ones. It raises VendorUnavailable only when the vendor cannot be
  called, which the loop records as a crash, not a silent skip.
- The engineer edits files in `cwd` (the workspace); every other role only
  reads. CLI adapters use argument lists, never shell=True, always with a
  timeout, and send the prompt on stdin (no argv length or quoting limits).
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

SECRET_WORDS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "API_KEY",
                "APIKEY", "PRIVATE_KEY", "ACCESS_KEY")


def safe_env(keep_prefixes=(), allow=None) -> dict:
    """os.environ minus secret-looking names, except those under keep_prefixes.

    Everything an agent or an evaluation runs gets this, so a stray GITHUB_TOKEN
    never reaches code the loop does not trust. With `allow` (a custom vendor),
    a kept prefix lets non-secret names through only; a secret-looking name
    must be listed in `allow` exactly.
    """
    keep = tuple(p.upper() for p in keep_prefixes)
    out = {}
    for k, v in os.environ.items():
        u = k.upper()
        secret = any(w in u for w in SECRET_WORDS)
        if (u in (allow or ())) or (not secret) or (allow is None and u.startswith(keep)):
            out[k] = v
    return out


class VendorUnavailable(Exception):
    pass


@dataclass
class VendorResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    latency_s: float

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class Vendor:
    name = "base"
    is_mock = False

    def available(self) -> bool:
        return True

    def complete(self, prompt: str, *, role: str, max_tokens: int,
                 cwd=None) -> VendorResult:
        raise NotImplementedError


class MockVendor(Vendor):
    """Deterministic, offline. Drives the demo and the tests.

    Behavior by role:
    - analyst:  writes an experiment card.
    - engineer: acts like an agent editing a file: merges the next entry of
      a fixed script into `cwd`/config.json. The script deliberately has
      improving, regressing and invalid entries — a demo that only succeeds
      teaches nothing. Asked to repair, it changes nothing (and the script
      does not advance), so the demo stays deterministic.
    - auditor:  always approves.
    """

    name = "mock"
    is_mock = True
    PATCH_SCRIPT = [
        {"learning_rate": 0.03},   # toward the optimum -> keep
        {"batch_size": 64},        # toward the optimum -> keep
        {"optimizer": "sgd"},      # a regression -> discard
        {"dropout": 1.5},          # invalid -> crash -> lesson
        {"dropout": 0.2},          # the optimum -> keep
        {"learning_rate": 0.02},   # away from the optimum -> discard
    ]

    def __init__(self):
        self._calls: dict[str, int] = {}

    def _next(self, role: str) -> int:
        n = self._calls.get(role, 0)
        self._calls[role] = n + 1
        return n

    def complete(self, prompt: str, *, role: str, max_tokens: int,
                 cwd=None) -> VendorResult:
        start = time.time()
        text = ""
        if role == "analyst":
            # names the parameter and value the engineer will change next, so every
            # card differs from the others (the duplicate precheck compares them)
            param, value = next(iter(self.PATCH_SCRIPT[self._next(role) % len(self.PATCH_SCRIPT)].items()))
            # (kept short on purpose: two cards that differ in one token must still
            # score below the 0.8 duplicate threshold)
            text = (f"HYPOTHESIS: Setting {param} to {value} helps.\n"
                    f"ALTERNATIVES: the gain is noise; the confirm re-run tells them apart.\n"
                    f"CHANGE: edit one value in config.json.\n"
                    f"EXPECT: the metric rises.\n"
                    f"REJECT IF: the metric does not beat the best so far.\n"
                    f"MISSING: none")
        elif role == "engineer":
            text = "done"
            path = Path(cwd) / "config.json" if cwd else None
            if path and path.exists() and "Your last attempt failed" not in prompt:
                patch = self.PATCH_SCRIPT[self._next(role) % len(self.PATCH_SCRIPT)]
                cfg = json.loads(path.read_text(encoding="utf-8"))
                path.write_text(json.dumps({**cfg, **patch}, indent=2) + "\n",
                                encoding="utf-8")
        elif role == "auditor":
            text = "APPROVED: diff matches the card; nothing else touched."
        return VendorResult(text=text,
                            tokens_in=_estimate_tokens(prompt),
                            tokens_out=_estimate_tokens(text),
                            model="mock-1",
                            latency_s=time.time() - start)


class CliVendor(Vendor):
    """A vendor reached through a local CLI (argument list, prompt on stdin)."""

    def __init__(self, name: str, argv: list[str], edit_args: list[str],
                 timeout_s: int = 240, env_keep: tuple = (), model: str | None = None,
                 model_flag: str = "--model", env_allow: tuple | None = None):
        self.name = name
        self.env_allow = env_allow  # None = preset (prefix keeps everything); tuple = custom
        self.argv = argv
        self.edit_args = edit_args  # only the engineer gets edit rights
        self.timeout_s = timeout_s
        self.env_keep = env_keep  # env prefixes (its own API keys) this CLI may see
        self.model = check_model(model)
        self.model_flag = model_flag

    def available(self) -> bool:
        return shutil.which(self.argv[0]) is not None

    def complete(self, prompt: str, *, role: str, max_tokens: int,
                 cwd=None) -> VendorResult:
        # which() resolves Windows .cmd/.exe shims that a bare name cannot.
        binary = shutil.which(self.argv[0])
        if binary is None:
            raise VendorUnavailable(f"CLI binary not found: {self.argv[0]}")
        argv = [binary, *self.argv[1:], *(self.edit_args if role == "engineer" else ()),
                *([self.model_flag, self.model] if self.model else [])]
        start = time.time()
        try:
            proc = subprocess.run(argv, input=prompt, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  cwd=cwd, timeout=self.timeout_s,
                                  env=safe_env(self.env_keep, self.env_allow))
        except subprocess.TimeoutExpired as exc:
            raise VendorUnavailable(f"{self.name} timed out") from exc
        except OSError as exc:
            raise VendorUnavailable(f"{self.name} could not run: {exc}") from exc
        if proc.returncode != 0:
            raise VendorUnavailable(
                f"{self.name} exited {proc.returncode}: {proc.stderr[:200]}")
        return VendorResult(text=proc.stdout.strip(),
                            tokens_in=_estimate_tokens(prompt),
                            tokens_out=_estimate_tokens(proc.stdout),
                            model=self.name,
                            latency_s=time.time() - start)


class FallbackVendor(Vendor):
    """An ordered list of vendors for one role: the first that can answer wins.

    `served` is the name of the vendor that answered last (None before a call).
    """

    def __init__(self, members: list[Vendor]):
        self.members = members
        self.served = None
        self.name = ",".join(v.name for v in members)
        self.is_mock = all(v.is_mock for v in members)

    def available(self) -> bool:
        return any(v.available() for v in self.members)

    def complete(self, prompt: str, *, role: str, max_tokens: int,
                 cwd=None) -> VendorResult:
        errors = []
        for v in self.members:
            try:
                res = v.complete(prompt, role=role, max_tokens=max_tokens, cwd=cwd)
            except VendorUnavailable as exc:
                errors.append(str(exc))
                continue
            self.served = v.name
            return res
        raise VendorUnavailable("; ".join(errors))


# CLI flags drift between versions: check `<cli> --help` if a vendor fails.
CLI_VENDORS = {
    "claude-cli": (["claude", "-p"], ["--permission-mode", "acceptEdits"]),
    "codex-cli": (["codex", "exec"], ["--full-auto"]),
    "gemini-cli": (["gemini"], ["--approval-mode", "auto_edit"]),
}
ENV_KEEP = {  # each CLI keeps only its own vendor's variables
    "claude-cli": ("ANTHROPIC_", "CLAUDE_"),
    "codex-cli": ("OPENAI_", "CODEX_"),
    "gemini-cli": ("GEMINI_", "GOOGLE_", "GOOGLE_GENAI_"),
}


def check_model(model) -> str | None:
    """A model name goes into argv (no shell), but stays strict anyway."""
    if model is not None and not re.fullmatch(r"[A-Za-z0-9._:/-]{1,80}", str(model)):
        raise VendorUnavailable(f"bad model name {str(model)[:40]!r}: use letters, "
                                f"digits and . _ : / - (max 80)")
    return None if model is None else str(model)


# Prefixes too generic to hand a vendor CLI: they hold other services' credentials.
GENERIC_PREFIXES = ("AWS_", "AZURE_", "GITHUB_", "GH_", "GITLAB_", "NPM_", "PYPI_",
                    "SSH_", "GPG_", "DOCKER_", "KUBE", "GOOGLE_APPLICATION")


def custom_vendor(name: str, spec: dict, timeout_s: int, model: str | None) -> CliVendor:
    """A CLI vendor declared in team.yaml (`vendors:` block): cmd, edit_args,
    model_flag, env_keep. Plain strings, split like argv (no shell). env_keep
    holds env PREFIXES the CLI may see (its own API key); a prefix that is short,
    secret-looking or a generic cloud/forge one is refused. A kept variable whose
    name looks secret (TOKEN, API_KEY, ...) is dropped unless its exact name is in
    `env_allow` (and starts with a kept prefix)."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", name) or name in CLI_VENDORS or name == "mock":
        raise VendorUnavailable(f"bad custom vendor name {name!r}")
    cmd = shlex.split(str(spec.get("cmd") or ""))
    if not cmd:
        raise VendorUnavailable(f"vendors.{name}: cmd is required (the CLI and its non-interactive flag)")
    keep = [k.strip() for k in str(spec.get("env_keep") or "").strip("[] ").replace('"', "").split(",") if k.strip()]
    for k in keep:
        if (not re.fullmatch(r"[A-Z][A-Z0-9]*_", k) or len(k) < 4 or k.startswith(GENERIC_PREFIXES)
                or any(w in k for w in SECRET_WORDS)):
            raise VendorUnavailable(f"vendors.{name}: env_keep {k!r} must be a specific "
                                    f"vendor prefix like MYVENDOR_ (not generic or secret-looking)")
    allow = [k.strip() for k in str(spec.get("env_allow") or "").strip("[] ").replace('"', "").split(",") if k.strip()]
    for k in allow:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", k) or not k.startswith(tuple(keep)):
            raise VendorUnavailable(f"vendors.{name}: env_allow {k!r} must be an exact "
                                    f"UPPER_CASE name starting with one of env_keep")
    return CliVendor(name, cmd, shlex.split(str(spec.get("edit_args") or "")), timeout_s,
                     tuple(keep), model, str(spec.get("model_flag") or "--model"), tuple(allow))


def get_vendor(name: str, *, timeout_s: int = 240, model: str | None = None,
               custom: dict | None = None) -> Vendor:
    """Resolve a team.yaml vendor name to an adapter. `model` is passed to a CLI
    as `--model <name>` (all three accept it today; flags drift between versions,
    so check `<cli> --help`); the mock ignores it."""
    model = check_model(model)
    if name == "mock":
        return MockVendor()
    if custom and name in custom:
        return custom_vendor(name, custom[name], timeout_s, model)
    if name in CLI_VENDORS:
        return CliVendor(name, *CLI_VENDORS[name], timeout_s, ENV_KEEP.get(name, ()), model)
    if name.startswith("api:"):
        raise VendorUnavailable(
            f"{name}: API vendors land in v0.2 — use a CLI vendor or mock for now")
    raise VendorUnavailable(f"unknown vendor: {name!r}")
