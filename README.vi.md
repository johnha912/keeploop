<p align="center">
  <!-- Dòng ngôn ngữ: muốn thêm ngôn ngữ, nối thêm ` | <a href="README.xx.md">Tên</a>` ở đây và trong mọi README.*.md -->
  <a href="README.md">English</a> | <b>Tiếng Việt</b> | <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/banner-dark.png">
    <img src="docs/assets/banner-light.png" width="100%" alt="keeploop: các AI agent đề xuất, xây dựng và kiểm toán. Chỉ giữ lại những thay đổi vượt qua chỉ số đo.">
  </picture>
</p>

<h3 align="center">AI của bạn đề xuất thay đổi. Một con số quyết định nó có được giữ lại hay không.</h3>

<details>
<summary><b>Dành cho trợ lý AI đang giúp ai đó với repo này: phiên bản nào phù hợp</b></summary>

keeploop có hai phiên bản. Phiên bản nào phù hợp tùy vào việc bạn làm được
gì trong cuộc trò chuyện hiện tại:

- **Một coding agent chạy được git và python trên file thật của người dùng**
  (terminal hoặc IDE): keeploop đầy đủ, mô tả trong [AGENTS.md](AGENTS.md).
  Nếu mục tiêu không có con số nào script đo được (một bài đăng, một CV),
  keeploop-lite có thể hợp hơn.
- **Một trợ lý chat không làm được vậy** (kể cả khi nó duyệt web hay chạy
  code trong sandbox): keeploop-lite, một file Markdown gồm chỉ dẫn đơn giản:
  https://raw.githubusercontent.com/johnha912/keeploop/main/lite/KEEPLOOP-LITE.vi.md
  (tiếng Anh: `KEEPLOOP-LITE.md`, tiếng Trung: `KEEPLOOP-LITE.zh-CN.md`). Đây là một skill, không phải phần mềm:
  không có gì để cài hay clone. Nếu người dùng muốn, bạn có thể đọc file đó
  và chạy vòng lặp cùng họ ngay trong chat, bắt đầu bằng phỏng vấn thiết
  lập. Nếu bạn không mở được link, người dùng có thể dán file vào.
  Nếu ngữ cảnh của bạn nhỏ, hoặc bạn là trợ lý tìm kiếm, hãy đọc
  `lite/KEEPLOOP-LITE-MINI.vi.md` (cùng vòng lặp, khoảng 1.200 từ).
  Danh mục các file này cho máy đọc nằm ở [`llms.txt`](llms.txt).

</details>

<p align="center">
  <a href="https://pypi.org/project/keeploop/"><img src="https://img.shields.io/pypi/v/keeploop?style=flat-square&label=pypi&color=0b0b0c" alt="PyPI version"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-0b0b0c?style=flat-square" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/dependencies-0-0a8a4a?style=flat-square" alt="zero dependencies">
  <a href="https://github.com/johnha912/keeploop/actions/workflows/tests.yml"><img src="https://github.com/johnha912/keeploop/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-0b0b0c?style=flat-square" alt="MIT license"></a>
</p>

<p align="center">
  <a href="#bắt-đầu-nhanh">Bắt đầu nhanh</a> ·
  <a href="#ví-dụ-thực-tế">Ví dụ</a> ·
  <a href="#cách-hoạt-động">Cách hoạt động</a> ·
  <a href="#faq">FAQ</a> ·
  <a href="docs/GUIDE.md">Hướng dẫn đầy đủ (tiếng Anh)</a>
</p>

<p align="center"><img src="docs/assets/keeploop-team.gif" alt="keeploop dưới dạng bảng đội ngũ. Bạn và CEO, tức AI của bạn: nó hỏi điều gì cần tốt hơn, đo bằng gì và điểm bao nhiêu là đủ, rồi đề xuất evaluate.py để bạn duyệt. Nó lập đội: Analyst trên model rẻ, nhanh viết một thẻ giả thuyết; Engineer trên model chính của bạn làm một thay đổi nhỏ; Auditor trên model mạnh nhất đọc diff thật trong ngữ cảnh mới. Thay đổi đi qua evaluate.py và cổng giữ best + 2σ: một cái được giữ và commit, cái sau bị reset kèm bài học. Hai lệnh mỗi chu kỳ, kl next và kl try. Với profile: fast, ít lượt gọi AI và ít token hơn mỗi chu kỳ." width="860"></p>

<p align="center"><sub>Các dòng phiên làm việc là đầu ra thật của <code>kl next</code> / <code>kl try</code> trên bản demo offline (<a href="docs/assets/demo-run/fastpath.txt">fastpath.txt</a>); số đo tốc độ là đo thật (<a href="docs/proof">docs/proof/bench-latency-*.json</a>). Video cho X: <a href="docs/assets/keeploop-x.mp4">keeploop-x.mp4</a>. Hướng dẫn: <a href="docs/GUIDE.md#video-guides">AI chat · AI code</a>.</sub></p>

keeploop biến AI bạn đang dùng thành một đội nhỏ, có một CEO làm việc cùng bạn.

- **Dễ dùng.** Dán một file vào ứng dụng chat, hoặc một câu lệnh vào agent viết code.
  Bạn nói bằng lời thường; không phải học lệnh nào.
- **Hỏi trước, rồi chọn liều lượng và lập đội.** CEO (AI của bạn) hỏi "tốt hơn" nghĩa
  là gì, đo bằng gì, điểm bao nhiêu là đủ và nếu một thay đổi sai lọt ra thì bạn tốn gì.
  Một bản nháp được vòng lặp nhẹ vài chu kỳ; việc người khác dựa vào được vòng lặp
  nghiêm ngặt (`kl level`). Sau đó nó lập một đội đúng việc: model rẻ, nhanh đề xuất,
  model chính của bạn làm, model mạnh nhất kiểm tra diff thật trong ngữ cảnh mới. Ở mức
  nào thì lỗi cũng thành bài học và không lặp lại.
- **Nhanh.** Hai lệnh mỗi chu kỳ trong agent viết code (`kl next`, `kl try`); một lần
  dán đi, một lần dán về cho AI chat không thấy được repo của bạn.
- **Tiết kiệm token.** Với `profile: fast`, Engineer tự viết thẻ và các ý bạn đã liệt kê
  không cần lượt gọi Analyst: −33% token và −26% thời gian mỗi chu kỳ trong
  benchmark offline của chúng tôi.
- **Chỉ giữ cải thiện thật.** Một thay đổi chỉ được commit khi vượt điểm tốt nhất nhiều
  hơn độ nhiễu đo được của chính bài đánh giá (best + 2σ). Mọi thứ khác bị reset, và lý
  do được ghi lại ([đã đo](#vì-sao-tin-được-các-lần-giữ)).

Dùng được với ChatGPT, Gemini, Claude, Perplexity, Claude Code, Codex, Cursor, Copilot
và Gemini CLI. Bản thân keeploop không phải AI: nó là một công cụ Python nhỏ biết đo và
biết từ chối, không cần cài thêm gì, không gửi telemetry và không cần API key.

> **Chỉ có ứng dụng chat** (ChatGPT, Claude, Gemini, không code)? Dùng
> [**keeploop-lite**](lite/KEEPLOOP-LITE.vi.md): một file dán vào chat,
> cùng vòng giữ-hay-bỏ cho một bài đăng, một CV hay một kế hoạch
> ([English](lite/KEEPLOOP-LITE.md), [简体中文](lite/KEEPLOOP-LITE.zh-CN.md), [ví dụ](lite/EXAMPLE.vi.md)).
> Mặc định chạy nhanh: nói **chạy 3 chu kỳ** để thử tối đa năm thay đổi trong
> một câu trả lời, và **lưu** để lấy sổ ghi. Ít chỗ (gói miễn phí, Perplexity)? Dùng
> [KEEPLOOP-LITE-MINI.vi.md](lite/KEEPLOOP-LITE-MINI.vi.md). Có thể lưu file một lần làm
> chỉ dẫn cố định (Project hoặc custom GPT của ChatGPT, Gem của Gemini, Space của
> Perplexity, Project của Claude) thay vì dán vào mỗi cuộc chat.
> **AI của bạn chạy được code?** Dùng bản đầy đủ bên dưới.

<p align="center"><img src="docs/assets/keeploop-guide-chat.gif" alt="keeploop-lite trong ứng dụng chat, từng bước: dán file (hoặc lưu một lần làm chỉ dẫn cố định), dán thứ bạn muốn tốt hơn, thống nhất thế nào là tốt hơn thành một bảng điểm khóa lại, gặp đội đặt tên theo nghề của bạn, nói chạy 3 chu kỳ và chỉ bản tốt hơn được giữ, nói lưu để lấy sổ ghi." width="860"></p>

<p align="center"><sub>Từng bước trong ứng dụng chat. Video bản đầy đủ (1080p): <a href="docs/GUIDE.md#video-guides">hướng dẫn chi tiết</a>.</sub></p>

## Bắt đầu nhanh

**(a) Giao cho AI của bạn.** Nếu AI chạy được lệnh, hãy dán đoạn này vào
và điền dòng cuối:

```text
Clone https://github.com/johnha912/keeploop cạnh project của tôi (không đặt bên trong nó),
chạy `python prepare.py` trong bản clone, rồi đọc AGENTS.md của nó và đóng vai CEO
như file đó mô tả. Điều tôi muốn tốt hơn: <ví dụ "làm bộ test của tôi chạy nhanh hơn">
```

AI hiểu prompt tiếng Việt; đường link và tên lệnh giữ nguyên như trên.

Bạn không bao giờ gõ `kl` và không có cờ nào phải học. Lần đầu, AI của bạn
hỏi bằng lời thường "tốt hơn" nghĩa là gì và đo bằng cách nào, rồi đề xuất
một `evaluate.py` (một script nhỏ in ra con số đó) để bạn duyệt trước khi
có gì thay đổi. Trong Claude Code, `/keeploop 3` chạy trong bản clone sẽ
chạy ba chu kỳ.

<p align="center"><img src="docs/assets/keeploop-guide-code.gif" alt="keeploop với AI lập trình, từng bước: dán một prompt, trả lời bốn câu hỏi bằng lời thường và duyệt evaluate.py, CEO chọn mức nặng nhẹ (light, fast hoặc rigorous), chia đội với một model cho mỗi vai, chạy hai lệnh mỗi chu kỳ (kl next, kl try) và chia sẻ kết quả bằng kl report." width="860"></p>

<p align="center"><sub>Từng bước với AI lập trình. Video bản đầy đủ (1080p): <a href="docs/GUIDE.md#video-guides">hướng dẫn chi tiết</a>.</sub></p>

<details>
<summary><b>Ứng dụng chat không chạy được lệnh (ứng dụng ChatGPT, Gemini)</b></summary>

Để cải thiện việc hằng ngày (một bài đăng, một CV, một kế hoạch), hãy dùng
[keeploop-lite](lite/KEEPLOOP-LITE.vi.md): không clone, không lệnh.

Để cải thiện một dự án code từ ứng dụng chat,
hãy dán toàn bộ [`BOOTSTRAP.md`](BOOTSTRAP.md) vào một cuộc
chat mới. Mỗi chu kỳ chỉ một lượt qua lại: `python kl.py handoff` in ra một gói
cho chat (mục tiêu, điểm số, các file), AI trả lời bằng một thẻ và các file đã sửa,
và `python kl.py apply reply.md` kiểm tra, chấm điểm, rồi giữ hoặc bỏ.

</details>

<details>
<summary><b>Nếu bạn là một AI agent đang đọc trang này</b></summary>

1. Clone repo này vào một thư mục riêng, bên ngoài dự án của người dùng, và
   chạy `python prepare.py` ở đó. Chạy mọi lệnh từ thư mục gốc của bản clone.
2. Đọc [`AGENTS.md`](AGENTS.md). Đó là quy trình đầy đủ: các vai, các lệnh
   `python kl.py` chính xác và các quy tắc cứng.
3. Nếu `evaluate.py` vẫn là bản demo, đừng bắt đầu vòng lặp. Hỏi người
   dùng, trong một tin nhắn, "tốt hơn" nghĩa là gì và đo bằng cách nào, rồi
   đề xuất một `evaluate.py` (nó nhận đường dẫn workspace và in ra một con
   số, càng cao càng tốt).
4. Để làm việc trên repo của người dùng, nhờ họ tạo một git worktree cho
   vòng lặp và đặt `workspace:` trong `team.yaml` trỏ tới đó; các bước nằm
   trong [docs/GUIDE.md](docs/GUIDE.md#use-it-on-your-own-repo). Bạn có thể
   soạn nháp `team.yaml`, `program.md` và `evaluate.py` cho người dùng,
   nhưng chỉ người dùng được sửa chúng.
5. Không bao giờ commit bằng tay: chỉ `python kl.py keep` mới commit. Với
   mọi tuyên bố về tiến độ, hãy dán nguyên văn `python kl.py report`.
6. Đường nhanh, hai lệnh mỗi chu kỳ: `python kl.py next` (một bản tóm tắt), viết
   thẻ và sửa, rồi `python kl.py try card.md` (cổng kiểm tra, chấm điểm, giữ hoặc
   bỏ; nó nói khi nào cần phán quyết của Auditor).

</details>

**(b) Thử offline.** Cần Python 3.10+ và git; không cần AI, không cần API key, mất vài giây.

```bash
git clone https://github.com/johnha912/keeploop.git && cd keeploop
python prepare.py
python run.py --mock --iterations 5
```

```text
cycle 3: discard  metric=0.942  best=0.992000  tokens=2820
cycle 4: crash  metric=None  best=0.992000  tokens=3510  lesson=L-001
run complete: 3 keeps, 1 discards, 1 crashes, 1 lessons, 17259 tokens. Best metric: 1.000000
```

Bản mock là một AI giả viết theo kịch bản. Nó cho thấy vòng lặp hoạt động
ra sao, không cho thấy một model thật giỏi đến đâu. Mỗi lần keep là một
commit thật: `git -C .keeploop/workspace log --oneline`.

**(c) Cài thành một lệnh.** Dùng `kl` không cần clone, cài từ PyPI:

```bash
pipx install keeploop      # hoặc: pip install keeploop (trong một venv riêng)
mkdir my-loop && cd my-loop
kl init                    # chép AGENTS.md, program.md, team.yaml, packs/, .claude/ vào đây
kl begin                   # baseline của bản demo
```

`kl init` đặt các file bạn sẽ sửa vào chính thư mục của bạn và không bao giờ
ghi đè file có sẵn. Sau đó mở thư mục này trong AI của bạn như ở (a), rồi
làm theo [AGENTS.md](AGENTS.md) để trỏ nó vào repo của bạn. `kl run` là chế
độ headless. Giữ bản clone nếu bạn muốn đọc hoặc sửa chính keeploop.

Hoặc chỉ một lệnh từ chính repo của bạn, kèm một `evaluate.py` viết sẵn:

```bash
cd my-repo
kl quickstart tests        # hoặc: command | prompt | buildtime (tạo ../my-repo-keeploop)
cd ../my-repo-keeploop
kl doctor                  # chạy evaluate.py 5 lần: nhiễu cỡ nào, thấy được mức tăng nào?
kl begin
```

Đã bắt đầu trong chat với keeploop-lite? `kl import-lite ledger.md` chuyển
phiên đó sang CLI. Phiên bản tốt nhất thành workspace, bảng chấm điểm thành
một `evaluate.py`.

**(d) Chia sẻ một lần chạy.** `kl report --html run.html` biến ledger thành
một trang, không gọi model. Trang có một dòng tóm tắt và một biểu đồ: thay đổi
được giữ tô đặc, bị bỏ để rỗng, đường best và dải nhiễu của nó. Ví dụ:
[biểu đồ của proof run](docs/proof/keeploop/report.svg).

## Ví dụ thực tế

| Ví dụ | Lĩnh vực | Điều đã xảy ra | Liên kết |
|---|---|---|---|
| Proof run | Đánh giá nhiễu, ngây thơ vs keeploop | Cùng 20 đề xuất, 25 seed: giữ 2.76 vs 0.44 thay đổi không có lợi thật; cái giá là bỏ 2.64 vs 1.28 cải thiện thật | [Đọc](docs/proof/PROOF.md) |
| Demo offline | Cấu hình đồ chơi | 3 lần keep, 1 lần discard, 1 lần crash thành bài học L-001; không cần AI | [Bản ghi](docs/DEMO-OUTPUT.txt) |
| Nghiên cứu marketing | Báo cáo insight người tiêu dùng | 1 chu kỳ thật: 0.970000 → 1.000000, kiểm toán APPROVED, được giữ lại | [Đọc](examples/marketing-research/) |
| Tối ưu prompt | Prompt AI/LLM | 8 chu kỳ headless, giữ 2, bỏ 6 (một lần đạt 0.915 bị từ chối khi chạy lại). Dev 0.873333 → 0.900000; holdout 0.835 → 0.855 | [Đọc](examples/prompt-optimization/) |

Dựng bất kỳ ví dụ nào thành một sandbox bằng `kl init --example <name> <new short folder>`
(khi đã cài `kl`) hoặc `python tools/make_sandbox.py examples/<name> <new short folder>`
(khi dùng bản clone) ([chi tiết](docs/GUIDE.md#run-a-worked-example)).

## Vì sao tin được các lần giữ

<p align="center"><img src="docs/assets/keeploop-gate.gif" alt="Cổng giữ, dạng hoạt hình: một trục số với điểm tốt nhất, dải nhiễu màu vàng tới ngưỡng best + 2σ, và ba thay đổi thật từ lần chạy noisy-eval. Chu kỳ 7 đạt 0.755 so với best 0.754, nằm trong dải, bị reset. Chu kỳ 8 đạt 0.793 và 0.786 khi chạy lại, cả hai vượt ngưỡng 0.777, được commit; best lên 0.786 và ngưỡng lên 0.809. Chu kỳ 14 đạt 0.795, cao hơn chu kỳ 8, nhưng nằm trong dải mới, bị reset." width="760"></p>

Trong lần rà soát các vòng lặp kiểu autoresearch (tháng 11/2026), keeploop là
công cụ cài đặt được đầu tiên mà chúng tôi tìm thấy biến nhiễu đánh giá thành
luật commit. Một thay đổi chỉ được giữ khi nó vượt điểm tốt nhất nhiều hơn độ
nhiễu đo được của chính bài đánh giá (best + 2σ). Quy tắc bác bỏ được cố định
từ trước, và một Auditor ở phiên mới đọc diff thật. Nhiễu đánh giá không phải
phát hiện của chúng tôi: giới nghiên cứu đã bàn về nó từ trước. Điều mới là
một công cụ biến nó thành quy tắc quyết định mọi commit.

**Đổi lại được gì, có đo.** Chúng tôi cho một vòng lặp ngây thơ (thấy điểm cao
hơn là giữ) và keeploop chạy cùng 20 đề xuất, trên cùng một bài đánh giá nhiễu:
mỗi lần chấm lấy ngẫu nhiên 1.000 trong 10.000 ca dev. Kết quả được chấm trên
một tập holdout 5.000 ca mà vòng lặp không bao giờ thấy. Mỗi bên chạy 25 seed
cố định từ trước ([docs/proof/PROOF.md](docs/proof/PROOF.md),
`python tools/proof_run.py`):

| trung bình trên 25 seed | ngây thơ | keeploop |
|---|---|---|
| số thay đổi được giữ mà thật ra không có lợi | 2.76 | **0.44** |
| điểm của chính vòng lặp phóng đại holdout bao nhiêu | +0.017 | **+0.005** |
| số thay đổi có lợi thật nhưng bị bỏ | **1.28** | 2.64 |
| mức tăng holdout, trung vị / trung bình | +0.130 / **+0.129** | **+0.135** / +0.107 |

Cái giá là có thật: keeploop bỏ đi một số cải thiện thật nằm lọt trong dải
nhiễu. Ở 9 trên 25 seed, holdout của nó kết thúc thấp hơn vòng lặp ngây thơ,
kể cả seed 1, lần chạy được chọn làm tiêu điểm trước khi quét. `kl doctor` đo
độ nhiễu của bài đánh giá trước khi bạn bắt đầu, và cho biết khi nào cần giảm nó.

## Vì sao chọn keeploop

Một agent nói "xong rồi" không phải là một phép đo.

| Cách thông thường | Với keeploop |
|---|---|
| Chính model viết thay đổi cũng tự bảo là ổn | **Một phiên mới hoặc một vendor khác** kiểm toán diff thật; người làm không bao giờ tự kiểm tra việc của mình |
| "Trông ổn đấy" | Chỉ `kl keep` mới commit. Nó tự chạy lại phần đánh giá, và con số phải vượt mức tốt nhất một khoảng lớn hơn nhiễu của chính phép đánh giá, nếu không thì thay đổi bị reset |
| Câu trả lời trôi chảy được coi là câu trả lời đúng | Mỗi thay đổi bắt đầu bằng một **thẻ giả thuyết viết sẵn** với quy tắc đo được sẽ loại bỏ nó, chốt trước khi chạy phép đánh giá |
| Agent lặng lẽ sửa test hoặc làm lộ key | **Cổng bằng code, không phải prompt**, chặn lại: đường dẫn được bảo vệ, quét bí mật, mẫu rác (slop) bị cấm, cỡ diff và một hàng rào băm nội dung |
| Điểm số cao nhưng không tổng quát hóa được | Một điểm **holdout** tùy chọn mà agent không bao giờ thấy, kèm cảnh báo khi mức tăng của nó tụt lại sau điểm chính |

Cũng có trong hướng dẫn: [bài học](docs/GUIDE.md#never-repeat-lessons) để
không lặp lại một lỗi, một [trend scout](docs/GUIDE.md#trend-scout), và một
file `AGENTS.md` duy nhất mà Codex, Cursor, Copilot và các công cụ khác đọc.

## Cách hoạt động

Dựa trên ý tưởng [autoresearch](https://github.com/karpathy/autoresearch)
của Andrej Karpathy: một chỉ số cố định, một quy tắc giữ/bỏ, và git làm bộ
nhớ về những gì hiệu quả.

```mermaid
flowchart LR
    A[Analyst<br/>viết một card] --> E[Engineer<br/>thực hiện thay đổi]
    E --> G{Cổng kiểm tra bằng code<br/>fence · vùng bảo vệ<br/>secret · kích thước}
    G -- đạt --> V[evaluate.py<br/>một con số]
    V --> U[Auditor<br/>góc nhìn mới,<br/>diff thật]
    U --> C{vượt best<br/>+ nhiễu?}
    C -- có --> K[git commit]
    C -- không --> D[git reset]
    G -- trượt --> L[(bài học)]
    D -. vì sao .-> L
    L -. đọc lần sau .-> A
```

Một Analyst viết một thẻ, một Engineer thực hiện đúng thay đổi đó, các cổng
bằng code và `evaluate.py` kiểm tra nó, và một Auditor phiên mới đọc diff.
Chỉ `kl keep` mới commit. Chu kỳ đầy đủ, vòng critic, bài học, trend scout
và việc chỉnh tốc độ nằm trong [hướng dẫn](docs/GUIDE.md#how-a-cycle-works).

## Dùng cho công việc của bạn: pack

Một **pack** đưa cho đội các quy tắc tay nghề và checklist rà soát cho một
lĩnh vực.

| Pack | Dành cho | Trạng thái |
|---|---|---|
| `software` | code | Sẵn sàng |
| `ui-design` | UI/UX | Thử nghiệm |
| `marketing-content` | nội dung marketing | Thử nghiệm |
| `marketing-research` | báo cáo insight người tiêu dùng | Thử nghiệm |
| `prompt-engineering` | system prompt cho LLM | Thử nghiệm |

Lĩnh vực mới? `python kl.py pack new NAME` dựng khung một pack. Cách thiết
lập cho repo của bạn, `team.yaml`, vendor và chế độ headless chạy qua đêm
(`python run.py`) nằm trong [docs/GUIDE.md](docs/GUIDE.md#use-it-on-your-own-repo).
Vì sao các pack thử nghiệm lại là thử nghiệm: [hướng dẫn](docs/GUIDE.md#profession-packs).

## An toàn

- keeploop không bao giờ thực thi văn bản từ model hay trang web. Chỉ
  Engineer có quyền sửa; các file đã đổi được quét tìm thông tin xác thực,
  và các biến môi trường trông giống token bị gỡ trước khi bất kỳ CLI
  vendor hay phép đánh giá nào khởi động.
- Trong lúc code bạn không viết đang chạy, mọi file trong thư mục dự án
  nằm ngoài workspace đều được băm nội dung. Bất kỳ thay đổi nào cũng dừng
  lần chạy.
- Hàng rào phát hiện thay đổi; **nó không phải sandbox**. Nếu điều đó quan
  trọng với bạn, hãy chạy vendor thật trong container hoặc VM.

Chi tiết: [docs/GUIDE.md](docs/GUIDE.md#safety) và [SECURITY.md](SECURITY.md).

## FAQ

<details>
<summary><b>Bốn câu hỏi người hoài nghi hay hỏi</b></summary>

**Giữ lại cái tốt nhất trong nhiều lần thử có làm overfit điểm số không?**
Có, đó là rủi ro chính của mọi vòng lặp keep/discard. keeploop đo nhiễu của
điểm số, đòi mức tăng vượt qua nó, chạy lại phép đánh giá trước mỗi lần
keep, và hỗ trợ một điểm holdout mà agent không bao giờ thấy.

**Bản demo có chứng minh các agent giỏi không?**
Không. Bản mock được viết theo kịch bản. Một lần chạy thật chỉ tốt bằng AI
của bạn và `evaluate.py` của bạn.

**Đây có phải chỉ là một framework multi-agent nữa không?**
Không có model nào chạy bên trong keeploop. Nó là một sơ đồ tổ chức mà AI
của bạn đọc, cộng với các công cụ từ chối commit những gì chưa được đo. Đổi
AI mà quy trình vẫn còn.

**Khi nào tôi không nên dùng keeploop?**
Khi không có điểm số tự động, khi điểm số mất hàng ngày mới có, khi công
việc không nằm trong git, hoặc khi mỗi thay đổi cần chuyên gia ký duyệt
(y khoa, luật, giao dịch).

</details>

Thêm câu hỏi: [docs/GUIDE.md](docs/GUIDE.md#faq-for-skeptics).

## Tài liệu

| | |
|---|---|
| [docs/GUIDE.md](docs/GUIDE.md) | Cuốn hướng dẫn đầy đủ: từng bước, bài học, scout, tốc độ, pack, an toàn, cấu trúc |
| [AGENTS.md](AGENTS.md) | Sơ đồ tổ chức và các lệnh chính xác mà AI của bạn làm theo |
| [BOOTSTRAP.md](BOOTSTRAP.md) | Một file để dán vào ứng dụng chat |
| [lite/KEEPLOOP-LITE.vi.md](lite/KEEPLOOP-LITE.vi.md) | keeploop-lite: bản chỉ cần chat, không code |
| [docs/SPEC.md](docs/SPEC.md) | Tham số, định dạng file, các bất biến |
| [SECURITY.md](SECURITY.md) | Mô hình mối đe dọa và cách báo lỗ hổng |
| [CHANGELOG.md](CHANGELOG.md) | Các phiên bản ([SemVer](https://semver.org)) |

## Ghi công

keeploop đứng trên vai [**autoresearch**](https://github.com/karpathy/autoresearch)
của Andrej Karpathy: một phép đánh giá cố định mà agent không đụng tới
được, một `results.tsv` chỉ ghi nối thêm, một quy tắc keep/discard và git
làm bộ nhớ. keeploop biến nó thành một sơ đồ tổ chức mà AI nào cũng chạy
được, và thêm các vai trò, kiểm toán chéo vendor, cổng bằng code, bài học
và một trend scout. Không có code nào của autoresearch được sao chép. Nếu
bạn thích repo này, hãy star repo của ông trước.

<details>
<summary>Một số ý tưởng cũng được mượn từ các công cụ chúng tôi dùng hằng ngày (viết lại, không sao chép code)</summary>

| Dự án | Ý tưởng được lấy |
|---|---|
| [ponytail](https://github.com/DietrichGebert/ponytail) (MIT) | "Leo từng bậc thang trước khi viết code" và các lối tắt được đánh dấu trong pack `software` |
| [ECC (everything-claude-code)](https://github.com/affaan-m/ECC) (MIT) | Thói quen xác minh trước khi xong và đỏ-rồi-xanh cho Engineer; rà soát bảo mật như một mục checklist cố định của Auditor |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) (Apache-2.0) | Đánh giá trang đã render trong trình duyệt thật: một nguyên tắc trong pack `ui-design` |
| [OmniRoute](https://github.com/cheaper-inference/OmniRoute) (MIT) | Dự phòng vendor có thứ tự cho từng vai |
| [graphify](https://github.com/Graphify-Labs/graphify) (Apache-2.0) | Một chỉ mục code được cache với tra cứu "được import bởi" (`kl map`) thay cho việc đổ file thô |

</details>

Banner được dàn chữ bằng [Google Sans Flex](https://fonts.google.com/specimen/Google+Sans+Flex).

Nếu keeploop đã chặn được một thay đổi xấu, một ⭐ sẽ giúp người khác tìm
thấy nó. Lỗi và ý tưởng: [mở một issue](https://github.com/johnha912/keeploop/issues).

## Giấy phép

[MIT](LICENSE).

> **Ghi chú đồng bộ.** Bản này dịch từ [README.md](README.md), bản tiếng Anh
> là bản gốc. Khi README.md đổi, sửa file này theo cùng lần commit: giữ nguyên
> thứ tự các mục, khối code, tên file, lệnh và con số, chỉ dịch phần văn xuôi.
> Nếu hai bản lệch nhau, bản tiếng Anh đúng.
