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

<p align="center">
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/version-0.1.0-0b0b0c?style=flat-square" alt="version 0.1.0"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-0b0b0c?style=flat-square" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/dependencies-0-0a8a4a?style=flat-square" alt="zero dependencies">
  <a href="https://github.com/johnha912/keeploop/actions/workflows/tests.yml"><img src="https://github.com/johnha912/keeploop/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-0b0b0c?style=flat-square" alt="MIT license"></a>
</p>

<p align="center">
  <a href="#giao-cho-ai-của-bạn">Giao cho AI của bạn</a> ·
  <a href="#thử-offline">Thử offline</a> ·
  <a href="#ví-dụ-thực-tế">Ví dụ</a> ·
  <a href="#cách-hoạt-động">Cách hoạt động</a> ·
  <a href="#faq">FAQ</a> ·
  <a href="docs/GUIDE.md">Hướng dẫn đầy đủ (tiếng Anh)</a>
</p>

<p align="center"><img src="docs/demo.gif" alt="Bản ghi terminal chạy mock của keeploop: đo mức gốc, hai lần giữ, một lần bỏ, một lần crash thành bài học, rồi giữ lần cuối." width="853"></p>

<p align="center"><sub>Ghi lại từ đầu ra thật của bản demo mock chạy offline (có thêm màu). Bản ghi đầy đủ nằm ở <a href="docs/DEMO-OUTPUT.txt">docs/DEMO-OUTPUT.txt</a>.</sub></p>

AI agent rất giỏi nói như thể chắc chắn. keeploop bắt chúng phải chứng minh.

- **Bạn nói "tốt hơn" nghĩa là gì**: test chạy nhanh hơn, benchmark cao hơn,
  báo cáo gọn hơn. Chỉ một con số.
- **AI của bạn thử từng thay đổi một**, và một AI thứ hai, phiên mới, kiểm tra nó.
- **Chỉ thay đổi nào vượt được con số mới được giữ lại.** Mọi thứ khác bị
  hoàn tác, và lý do được ghi lại để không thử lại lần nữa.

Dùng được với AI bạn đang dùng: Claude Code, Codex, Cursor, Copilot,
Gemini CLI và nhiều công cụ khác. Bản thân keeploop không phải AI: nó là
một công cụ Python nhỏ biết đo và biết từ chối. Nó không cần cài thêm gì,
không gửi telemetry và không lưu API key.

## Giao cho AI của bạn

**Nếu AI của bạn chạy được lệnh** (Claude Code, Codex, Cursor, Copilot,
Gemini CLI, Aider và các công cụ tương tự), hãy dán đoạn này vào nó và điền
dòng cuối:

```text
Clone https://github.com/johnha912/keeploop next to my project (not inside it),
run `python prepare.py` in the clone, then read its AGENTS.md and act as the CEO
it describes. What I want better: <for example "make my test suite faster">
```

Dòng cuối bạn có thể viết bằng tiếng Việt.

Vậy là xong. Bạn không bao giờ gõ `kl` và không có cờ nào phải học. Lần
đầu, AI của bạn hỏi bằng lời thường "tốt hơn" nghĩa là gì và đo bằng cách
nào, rồi đề xuất một `evaluate.py` (một script nhỏ in ra con số đó) để bạn
duyệt trước khi có gì thay đổi. Trong Claude Code, `/keeploop 3` chạy trong bản clone sẽ chạy ba
chu kỳ.

**Nếu AI của bạn là một ứng dụng chat không mở được link hay chạy lệnh**
(ứng dụng ChatGPT hoặc Gemini), hãy dán toàn bộ
[`BOOTSTRAP.md`](BOOTSTRAP.md) vào một cuộc chat mới. Khi đó AI sẽ đưa bạn
từng lệnh `python kl.py ...` để chạy trong một bản clone, và bạn dán đầu
ra lại cho nó.

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

</details>

## Thử offline

Muốn xem thử trước khi giao cho AI? Cần Python 3.10+ và git. Không cần AI,
không cần API key; mất vài giây.

```bash
git clone https://github.com/johnha912/keeploop.git && cd keeploop
python prepare.py
python run.py --mock --iterations 5
```

```text
cycle 1: keep  metric=0.942  best=0.942000  tokens=3501
cycle 2: keep  metric=0.992  best=0.992000  tokens=3568
cycle 3: discard  metric=0.942  best=0.992000  tokens=2820
cycle 4: crash  metric=None  best=0.992000  tokens=3510  lesson=L-001
cycle 5: keep  metric=1.0  best=1.000000  tokens=3860
run complete: 3 keeps, 1 discards, 1 crashes, 1 lessons, 17259 tokens. Best metric: 1.000000
```

(Thời gian đã được rút gọn.) Bản mock là một AI giả viết theo kịch bản, để
bạn xem một lần keep, một lần discard và một lần crash xảy ra thế nào. Nó
cho thấy vòng lặp hoạt động ra sao, không cho thấy một model thật giỏi đến
đâu. Mỗi lần keep là một commit thật:
`git -C .keeploop/workspace log --oneline`.

## Ví dụ thực tế

<table>
<tr>
<td width="50%" valign="top">

**Demo offline (cấu hình đồ chơi)**

Chính là cái GIF ở trên. Một bản mock theo kịch bản chỉnh `config.json` của
demo qua năm chu kỳ: ba lần keep, một lần discard và một lần crash thành
bài học L-001. Chạy trong vài giây, không cần AI.

[Bản ghi](docs/DEMO-OUTPUT.txt) · [Thử ngay](#thử-offline)

</td>
<td width="50%" valign="top">

<a href="examples/marketing-research/"><img src="docs/assets/example-marketing-research.png" alt="Phần đầu bảng bìa của ví dụ nghiên cứu marketing: câu trả lời một dòng và ba con số nổi bật" width="100%"></a>

**Báo cáo insight người tiêu dùng (nghiên cứu marketing)**

Một nghiên cứu lắng nghe mạng xã hội về năm thương hiệu thời trang nhanh,
kèm một dashboard và một file PDF 30 trang. Một chu kỳ thật, chạy trong
Claude Code, đã sửa hai tuyên bố thiếu căn cứ: điểm 0.970000 → 1.000000,
kiểm toán APPROVED, được giữ lại. Trang đó cũng nói rõ điểm số không đo
điều gì.

[Đọc ví dụ](examples/marketing-research/)

</td>
</tr>
</table>

## Sao không để AI tự lặp?

Vì một agent nói "xong rồi" không phải là một phép đo.

| Cách thông thường | Với keeploop |
|---|---|
| Chính model viết thay đổi cũng tự bảo là ổn | **Một phiên mới hoặc một vendor khác** kiểm toán diff thật; người làm không bao giờ tự kiểm tra việc của mình |
| "Trông ổn đấy" | Chỉ `kl keep` mới commit. Nó tự chạy lại phần đánh giá, và con số phải vượt mức tốt nhất quá nhiễu của chính phép đánh giá, nếu không thì thay đổi bị reset |
| Câu trả lời trôi chảy được coi là câu trả lời đúng | Mỗi thay đổi bắt đầu bằng một **thẻ giả thuyết viết sẵn** với quy tắc đo được sẽ loại bỏ nó, chốt trước khi chạy phép đánh giá |
| Tuần sau lại mắc đúng lỗi cũ | Mọi lần crash, bị từ chối hay bị phàn nàn đều thành một **bài học**, có thể kèm một kiểm tra chạy trước mỗi lần keep |
| Agent lặng lẽ sửa test hoặc làm lộ key | **Cổng bằng code, không phải prompt**, chặn lại: đường dẫn được bảo vệ, quét bí mật, mẫu rác (slop) bị cấm, cỡ diff và một hàng rào băm nội dung |
| Điểm số cao nhưng không tổng quát hóa được | Một điểm **holdout** tùy chọn mà agent không bao giờ thấy, kèm cảnh báo khi mức tăng của nó tụt lại sau điểm chính |
| Bạn tìm kỹ thuật mới bằng cách lướt web | Một **trend scout** xếp hạng repo GitHub mới, bài trên Hacker News và bài báo arXiv; ý tưởng của nó vẫn phải đi qua một thẻ |
| Bị khóa vào một vendor | `AGENTS.md` được Codex, Cursor, Copilot, Jules, Aider và nhiều công cụ khác đọc; Claude Code và Gemini CLI dùng file trỏ |

## Cách hoạt động

Dựa trên ý tưởng [autoresearch](https://github.com/karpathy/autoresearch)
của Andrej Karpathy: một chỉ số cố định, một quy tắc giữ/bỏ, và git làm bộ
nhớ về những gì hiệu quả.

```mermaid
flowchart LR
    A[Analyst<br/>writes one card] --> E[Engineer<br/>makes the change]
    E --> G{Code gates<br/>fence · protected<br/>secrets · size}
    G -- pass --> V[evaluate.py<br/>one number]
    V --> U[Auditor<br/>fresh eyes,<br/>real diff]
    U --> C{beats best<br/>+ noise?}
    C -- yes --> K[git commit]
    C -- no --> D[git reset]
    G -- fail --> L[(lesson)]
    D -. why .-> L
    L -. read next time .-> A
```

1. **Analyst** viết một thẻ: giả thuyết, thay đổi nhỏ nhất, điều được kỳ
   vọng sẽ xảy ra, và kết quả sẽ chứng minh nó sai.
2. **Engineer** thực hiện đúng thay đổi đó, và là vai duy nhất được sửa
   file.
3. **Cổng bằng code** (`kl check`) từ chối thay đổi ngoài workspace, sửa
   file được bảo vệ, thông tin xác thực và diff quá lớn.
4. **evaluate.py** in ra một con số. Vòng lặp không sửa được nó.
5. **Auditor**, trong một phiên mới hoặc từ vendor khác, kiểm tra diff so
   với thẻ mà không thấy lời giải thích của Engineer.
6. **`kl keep`** chỉ commit nếu mọi kiểm tra đều đạt và con số vượt ngưỡng;
   nếu không thì **`kl discard`** reset và ghi lại lý do.

Chu kỳ đầy đủ, vòng critic cho thay đổi nặng, bài học, trend scout và việc
chỉnh tốc độ nằm trong [hướng dẫn](docs/GUIDE.md#how-a-cycle-works).

## Dùng cho công việc của bạn

keeploop chạy được trên mọi thư mục nằm trong git và có điểm số tự động.
Một **pack** đưa cho đội các quy tắc tay nghề và checklist rà soát cho một
lĩnh vực:

| Pack | Dành cho | Trạng thái |
|---|---|---|
| `software` | code | Sẵn sàng: test và benchmark là các chỉ số trung thực |
| `ui-design` | UI/UX | Thử nghiệm: điểm Lighthouse hay axe đo mức sàn, không đo gu thẩm mỹ |
| `marketing-content` | nội dung marketing | Thử nghiệm: kết quả thật đến muộn và nhiễu |
| `marketing-research` | báo cáo insight người tiêu dùng | Thử nghiệm: kiểm tra quy tắc và khả năng truy vết, không kiểm tra insight có đúng không |

Lĩnh vực mới? `python kl.py pack new NAME` dựng khung một pack. Cách thiết
lập cho repo của bạn, `team.yaml`, vendor và chế độ headless chạy qua đêm
(`python run.py`) nằm trong [docs/GUIDE.md](docs/GUIDE.md#use-it-on-your-own-repo).

## An toàn, nói gọn

- keeploop không bao giờ thực thi văn bản từ model hay trang web. CLI vendor
  nhận prompt qua stdin, và chỉ Engineer có quyền sửa.
- Trong lúc code bạn không viết đang chạy, mọi file trong thư mục dự án
  nằm ngoài workspace đều được băm nội dung. Bất kỳ thay đổi nào cũng dừng
  lần chạy.
- Các file đã đổi được quét tìm thông tin xác thực, và các biến môi trường
  trông giống token bị gỡ trước khi bất kỳ CLI vendor hay phép đánh giá nào
  khởi động.
- Hàng rào phát hiện thay đổi; **nó không phải sandbox**. Nếu điều đó quan
  trọng với bạn, hãy chạy vendor thật trong container hoặc VM.

Chi tiết: [docs/GUIDE.md](docs/GUIDE.md#safety) và [SECURITY.md](SECURITY.md).

## FAQ

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

Thêm câu hỏi: [docs/GUIDE.md](docs/GUIDE.md#faq-for-skeptics).

## Tài liệu

| | |
|---|---|
| [docs/GUIDE.md](docs/GUIDE.md) | Cuốn hướng dẫn đầy đủ: từng bước, bài học, scout, tốc độ, pack, an toàn, cấu trúc |
| [AGENTS.md](AGENTS.md) | Sơ đồ tổ chức và các lệnh chính xác mà AI của bạn làm theo |
| [BOOTSTRAP.md](BOOTSTRAP.md) | Một file để dán vào ứng dụng chat |
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

Một số ý tưởng cũng được mượn (viết lại, không sao chép code) từ các công
cụ chúng tôi dùng hằng ngày:

| Dự án | Ý tưởng được lấy |
|---|---|
| [ponytail](https://github.com/DietrichGebert/ponytail) (MIT) | "Leo thang trước khi viết code" và các lối tắt được đánh dấu trong pack `software` |
| [ECC (everything-claude-code)](https://github.com/affaan-m/ECC) (MIT) | Thói quen xác minh trước khi xong và đỏ-rồi-xanh cho Engineer; rà soát bảo mật như một mục checklist cố định của Auditor |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) (Apache-2.0) | Đánh giá trang đã render trong trình duyệt thật: một nguyên tắc trong pack `ui-design` |
| [OmniRoute](https://github.com/cheaper-inference/OmniRoute) (MIT) | Dự phòng vendor có thứ tự cho từng vai |
| [graphify](https://github.com/Graphify-Labs/graphify) (Apache-2.0) | Một chỉ mục code được cache với tra cứu "được import bởi" (`kl map`) thay cho việc đổ file thô |

Banner được dàn chữ bằng [Google Sans Flex](https://fonts.google.com/specimen/Google+Sans+Flex).

Nếu keeploop đã chặn được một thay đổi xấu, một ⭐ sẽ giúp người khác tìm
thấy nó. Lỗi và ý tưởng: [mở một issue](https://github.com/johnha912/keeploop/issues).

## Giấy phép

[MIT](LICENSE).

> **Ghi chú đồng bộ.** Bản này dịch từ [README.md](README.md), bản tiếng Anh
> là bản gốc. Khi README.md đổi, sửa file này theo cùng lần commit: giữ nguyên
> thứ tự các mục, khối code, tên file, lệnh và con số, chỉ dịch phần văn xuôi.
> Nếu hai bản lệch nhau, bản tiếng Anh đúng.
