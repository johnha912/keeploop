<p align="center"><b>English</b> | <a href="README.vi.md">Tiếng Việt</a> | <a href="README.zh-CN.md">简体中文</a></p>

# Example: a noisy evaluation (the proof run)

A toy question-answering pipeline (`config.json`: few-shot count, reranking, prompt
style, temperature, chunk size, ...) scored by a deliberately noisy `evaluate.py`.
Each call scores a random 1,000 of 10,000 dev cases, so the same config scores a
little differently every time (sigma about 0.014). `holdout.py` scores 5,000 other
cases, all of them, and the loop never sees it. Everything is simulated, offline
and stdlib only: every role runs on the mock vendor, whose engineer applies the 20
proposals in `mock_script.json` in order.

This is the workspace of the proof run, [docs/proof/PROOF.md](../../docs/proof/PROOF.md).
It runs a naive keep-if-better loop and keeploop on the same proposals and the same
noise, for 25 seeds.

```bash
python tools/proof_run.py                              # the whole A/B, from a clone
kl init --example noisy-eval /tmp/ne && cd /tmp/ne/kl  # or one run by hand
kl doctor                                              # how noisy is evaluate.py?
kl begin && kl run --mock --narrate                    # watch each keep/discard decision
kl report --html run.html                              # the run as one chart
```

Without `KEEPLOOP_DEMO_SEED` the noise is truly random, so your numbers will differ
from the proof run's. `tools/proof_run.py` sets the seed so its runs replay exactly.
