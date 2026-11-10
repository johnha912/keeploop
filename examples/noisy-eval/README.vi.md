<p align="center"><a href="README.md">English</a> | <b>Tiếng Việt</b> | <a href="README.zh-CN.md">简体中文</a></p>

# Ví dụ: một bài đánh giá nhiễu (proof run)

Một pipeline hỏi-đáp đồ chơi (`config.json`: số ví dụ few-shot, rerank, kiểu prompt,
temperature, kích thước chunk, ...) được chấm bởi một `evaluate.py` cố tình nhiễu.
Mỗi lần chấm lấy ngẫu nhiên 1.000 trong 10.000 ca dev, nên cùng một config lần nào
cũng ra điểm hơi khác (sigma khoảng 0.014). `holdout.py` chấm 5.000 ca khác, chấm
hết, và vòng lặp không bao giờ thấy nó. Mọi thứ đều mô phỏng, chạy offline, chỉ
dùng stdlib: mọi vai chạy trên vendor mock, Engineer của nó áp lần lượt 20 đề xuất
trong `mock_script.json`.

Đây là workspace của proof run, [docs/proof/PROOF.md](../../docs/proof/PROOF.md).
Nó cho một vòng lặp ngây thơ (thấy cao hơn là giữ) và keeploop chạy cùng các đề xuất,
cùng độ nhiễu, trên 25 seed.

```bash
python tools/proof_run.py                              # toàn bộ A/B, từ bản clone
kl init --example noisy-eval /tmp/ne && cd /tmp/ne/kl  # hoặc tự chạy một lần
kl doctor                                              # evaluate.py nhiễu cỡ nào?
kl begin && kl run --mock --narrate                    # xem từng quyết định giữ/bỏ
kl report --html run.html                              # lần chạy thành một biểu đồ
```

Không có `KEEPLOOP_DEMO_SEED` thì độ nhiễu là ngẫu nhiên thật, nên số của bạn sẽ khác
số của proof run. `tools/proof_run.py` đặt seed để các lần chạy lặp lại y hệt.
