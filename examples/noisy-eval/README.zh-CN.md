<p align="center"><a href="README.md">English</a> | <a href="README.vi.md">Tiếng Việt</a> | <b>简体中文</b></p>

# 示例：一个有噪声的评测（proof run）

一个玩具问答流水线（`config.json`：few-shot 数量、rerank、提示词风格、temperature、
chunk 大小等），由一个故意带噪声的 `evaluate.py` 打分。每次调用从 10,000 个开发集
样本中随机抽 1,000 个，所以同一个配置每次得分都略有不同（sigma 约 0.014）。
`holdout.py` 对另外 5,000 个样本全部打分，循环从未见过它。一切都是模拟的，离线、
只用标准库：所有角色都跑在 mock vendor 上，它的 Engineer 依次应用
`mock_script.json` 里的 20 个提议。

这是 proof run 的 workspace，见 [docs/proof/PROOF.md](../../docs/proof/PROOF.md)。
它让一个朴素循环（分数更高就保留）和 keeploop 用同样的提议、同样的噪声，跑 25 个种子。

```bash
python tools/proof_run.py                              # 完整的 A/B，在克隆中运行
kl init --example noisy-eval /tmp/ne && cd /tmp/ne/kl  # 或者手动跑一次
kl doctor                                              # evaluate.py 噪声有多大？
kl begin && kl run --mock --narrate                    # 观看每次保留/丢弃的决定
kl report --html run.html                              # 把这次运行画成一张图
```

不设置 `KEEPLOOP_DEMO_SEED` 时噪声是真随机的，所以你的数字会和 proof run 不同。
`tools/proof_run.py` 会设置种子，让它的运行可以精确重现。
