# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây lấy từ file JSON/CSV/ảnh đã nộp trong `reports/`, `benchmark-results/`, `screenshots/`.

**Họ tên:** Mai Huy Hoạt
**MSSV:** 2A202603656
**Ngày chạy:** 2026-11-25
**Môi trường:** Linux 12 vCPU / 32 GB RAM, Docker 29.9.3, Docker Compose v5.7.1, Python 3.11.13, agent `mock-llm-small` trừ khi ghi khác

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < **500 ms** | Mock LLM có latency nền ~120 ms + jitter 60 ms + thời gian retrieval ~20 ms, nên p95 thực tế ~220 ms. 500 ms cho dư ~2× biên an toàn để hấp thụ biến động của CPU/GC mà vẫn bắt được sự cố thật (khi p95 vượt 1 s là tail latency đã lan ra >5 % request). Đây cũng là ngưỡng `load_test.py` dùng mặc định để exit code 1 khi vi phạm. |
| Error rate `/ask` | < **2 %** | Mock LLM bơm lỗi upstream ~1 % (`MOCK_ERROR_RATE`), cộng thêm 503 lẻ tẻ. 2 % = 2× mức nền, đủ để không báo động vì nhiễu ngẫu nhiên nhưng vẫn bắt được lỗi hệ thống. |
| Accuracy trên golden dataset | ≥ **100 %** | Bộ 23 câu là kiến thức tĩnh, có đáp án tường minh nên không có lý do gì để sai. Đặt 100 % để chặn merge ngay khi có bất kỳ regression nào (baseline `eval_v2.json` đã đạt 91.3 %, sau khi sửa KB đạt 100 %). |

Baseline hạ tầng alert (lỏng hơn SLO để tránh alert fatigue): error rate > 5 % trong 1 phút, p95 > 1 s trong 2 phút, `up == 0` trong 30 giây, cost > $2/giờ trong 2 phút.

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 request/mức)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.41 | 189.5 | 219.0 | 1691.8 | 1.00 % | ✅ PASS |
| 10 | 36.71 | 189.6 | 220.2 | 1700.5 | 0.33 % | ✅ PASS |
| 50 | 109.85 | 196.4 | 240.3 | 1701.8 | 0.33 % | ✅ PASS |
| 100 | 60.22 | 378.2 | 3367.6 | 3827.0 | 0.67 % | ❌ FAIL |

Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.

**Nhận xét:** RPS **không** tăng tuyến tính. Từ 1 → 50, RPS tăng gần như tuyến tính (4.4 → 36.7 → 109.9 req/s, chênh ~8× cho 10× concurrency và ~25× cho 50×) vì agent là async và phần lớn thời gian là `await asyncio.sleep()` mô phỏng LLM — CPU gần như rảnh, nên tăng concurrency là "lấp" được thời gian chờ. Ở 100 concurrency, RPS **giảm** còn 60.2 req/s và p95 nhảy từ 240 ms lên **3368 ms**: 100 request đồng thời trên một process vượt quá khả năng của event loop + threadpool, request bị xếp hàng; p99 vọt lên 3827 ms trong khi p50 chỉ 378 ms — dấu hiệu kinh điển của **queueing**, không phải LLM chậm. Muốn nhiều hơn nữa phải scale **số instance** (xem mục 5) chứ không tăng concurrency.

### 2.2 Tail latency theo `MOCK_SLOW_RATE` (300 request, concurrency 20)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 186.5 | 215.6 | 221.3 |
| 0.03 (mặc định) | 223.6 | 220.5 | 1696.0 |
| 0.1 | 319.8 | 1685.1 | 1707.8 |

Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.

**Nhận xét:** Chỉ số nhạy nhất là **p99** (và p95 khi tỉ lệ đủ cao). Từ 0 → 0.03: avg chỉ +37 ms (+20 %) nhưng p99 nhảy 221 → 1696 ms (**7.7×**). Từ 0.03 → 0.1: avg +96 ms nhưng p95 nhảy 220 → 1685 ms — vì đã có >5 % request chậm nên p95 bị "kéo" vào vùng 1.7 s.

Vì sao SLO không nên đặt theo average: một request chậm 1.5 s chỉ cộng 1500/300 = 5 ms vào average của 300 request, nên **average gần như không đổi trong khi 1/10 người dùng thật phải chờ 1.7 giây**. Ở 0.1, SLO p95 đã FAIL trong khi error rate vẫn 0.67 % và average 320 ms "trông ổn". Percentile mô tả đúng trải nghiệm của nhóm người dùng xấu nhất — đó là nhóm quyết định việc họ có bỏ đi hay không.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3 % (1/23) | 91.3 % (21/23) | **100 % (23/23)** |
| Avg tokens / câu | 57.0 | 109.3 | 117.3 |
| Tổng cost (USD) | 0.000403 | 0.000764 | 0.000822 |
| Cost / câu đúng (USD) | 0.00040335 | 0.00003639 | **0.00003573** |
| Quality gate | ❌ FAIL | ✅ PASS | ✅ PASS (min-accuracy 1.0, 0 regression) |

Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.

**Những câu v2 trả lời sai ban đầu và cách sửa**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| `security-02` (JWT khác gì API key) | `token`, `hết hạn`, `chữ ký` | Thêm entry `KNOWLEDGE_BASE`: *"JWT là token tự chứa thông tin: server ký bằng secret (chữ ký HMAC/RSA)… Token có thời gian hết hạn (exp)… API key chỉ là chuỗi bí mật cố định, không có hạn dùng…"* |
| `scaling-03` (Kubernetes HPA scale dựa trên gì) | `cpu`, `memory`, `custom metrics` | Thêm entry: *"Kubernetes HPA scale số pod dựa trên CPU và memory (resource metrics), hoặc custom metrics qua Prometheus adapter…"* |

Sửa ở `develop/utils/mock_llm.py` và chép sang `production/utils/mock_llm.py` (stack Docker dùng bản production). Phải **tắt và bật lại** agent vì `KNOWLEDGE_BASE` được nạp lúc import.

**Trade-off chất lượng / chi phí / latency:** v2 dùng gấp ~1.9× token (109 vs 57) vì prompt có thêm context retrieval, latency p95 cao hơn (1557 ms so với 188 ms ở lần eval v1 — do chỉ 1 trong 23 câu rơi vào nhánh chậm, đủ để p95 vọt), nhưng accuracy từ 4.3 % lên 91.3 %. Điểm quan trọng: **cost/câu đúng giảm ~11×** (4.03e-4 → 3.64e-5 USD) — v2 đắt hơn trên mỗi *request* nhưng rẻ hơn rất nhiều trên mỗi *câu trả lời đúng*, vì v1 trả lời sai gần như toàn bộ. Đây là lý do phải so sánh bằng cost/câu đúng chứ không phải cost/câu.

**Quality gate dùng trong CI:** `run_eval.py` trả **exit code 1** khi accuracy < `--min-accuracy` hoặc có regression so với `--baseline`. Đã kiểm chứng bằng cách chạy v1 với baseline v2:

```
$ python eval/run_eval.py --url http://localhost:8001 --min-accuracy 1.0 --baseline reports/eval_v2.json
  Accuracy : 4.3%   Baseline: 91.3%   (-87.0 điểm %)
  ⚠️  Câu bị regression : 20
  Quality gate (accuracy ≥ 100%, không regression): ❌ FAIL
$ echo $?
1
```

GitHub Actions chỉ cần chạy lệnh này là chặn được merge (xem `.github/workflows/eval.yml`):

```yaml
name: eval-quality-gate
on: pull_request
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.11"}
      - run: pip install -r 06-lab-complete/benchmark-observability/develop/requirements.txt
      - name: Start agent v2
        run: |
          cd 06-lab-complete/benchmark-observability/develop
          AGENT_VERSION=v2 PORT=8002 nohup python app.py &
          for i in $(seq 1 30); do curl -sf http://localhost:8002/health && break; sleep 1; done
      - name: Quality gate (exit code 1 chặn merge)
        run: |
          cd 06-lab-complete/benchmark-observability/develop
          python eval/run_eval.py --url http://localhost:8002 \
            --min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_ci.json
```

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] `screenshots/grafana-dashboard.png` — dashboard khi đang có tải: Traffic **49.5 req/s**, Error rate **1.10 %**, Latency p95 **294 ms**, In-flight **10**, Instances up **2**, LLM cost 1h **$2.36**; panel latency vẽ rõ p50/p95 sát 220 ms còn p99 ở 1.7 s.
- [x] `screenshots/jaeger-slow-trace.png` — trace chậm `ee3ca66e9c99321cffc88dc7a3f9d9d7`, tổng 1.7 s, span `chat mock-llm-small` 1.7 s (chiếm 99 %), kèm panel GenAI: model `mock-llm-small`, input 83 token, output 44 token.
- [x] `screenshots/jaeger-error-trace.png` — trace lỗi `3ae5387ce47d408677d4694aad9c2bea` (HTTP 503), span `agent.run` có event `exception` với `exception.type=utils.mock_llm.LLMError`, `exception.message=Upstream LLM error: 503 Service Unavailable (mock)`, `exception.stacktrace` 829 ký tự.
- [x] `screenshots/prometheus-alert-firing.png` — trang `/alerts` của Prometheus với **2 alert đang firing**: `LLMCostBurnRateHigh` (nhóm `agent-cost`) và `AgentHighErrorRate` (nhóm `agent-slo`); 2 alert còn lại `inactive`.

### 4.2 Thí nghiệm "phá hệ thống"

Giữ Locust ~40–50 user trong suốt thí nghiệm. Mỗi thí nghiệm reset `.env` về baseline rồi `docker compose up -d` để áp dụng.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | **80 s** (pending từ t+20 s, đủ `for: 1m`) | "Error rate" chuyển cam → đỏ (1 % → ~20 %); "Requests/s theo status code" mọc dải 503; Jaeger có trace lỗi |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | **92 s** (pending từ t+1 s, `for: 2m` tính từ lúc điều kiện đúng) | "Latency /ask — p50/p95/p99": p99 bật từ 220 ms lên 1.7 s, p95 leo theo; "Latency p95" đổi xanh → đỏ |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | **21 s** (điều kiện đúng ngay, kế thừa `for` đang đếm dở từ lần trước) | "Cost burn rate (USD/giờ)" và "LLM cost (1h)": $2.43/giờ → **$47.87/giờ** (~19.7×); "Tokens/s" tăng do prompt dài hơn |
| D | `docker pause` 1 instance (`agent-1`) | `AgentInstanceDown` | **50 s** (pending t+20 s, `for: 30s`) | "Instances up" 2 → 1; "Requests/s theo instance" mất một series; Locust thấy vài lỗi 504 nhưng error rate *của agent* vẫn xanh |
| E | `AGENT_VERSION=v1` | **Không alert nào** (theo dõi 180 s) | — | "Retrieval hit ratio (agent v2)" không còn dữ liệu hit, "Phiên bản đang chạy" đổi sang v1, tokens/s giảm; không panel hạ tầng nào đỏ |

Số đo bổ sung cho C (cùng 40 user, `increase(llm_cost_usd_total[3m])`):

| Model | cost 3 phút | request 3 phút | cost / request |
| --- | ---: | ---: | ---: |
| `mock-llm-small` (baseline) | $0.2467 | 6732 | $0.0000366 |
| `mock-llm-large` | $0.6464 | 5587 | $0.0001157 (≈3.2×) |

Ở mức tải steady-state: `small` = **$2.43/giờ**, `large` = **$47.87/giờ** (~19.7×) — chênh lệch lớn hơn 3.2× vì request `large` chậm hơn 2.5× nên cùng lượng user tạo ít request hơn nhưng mỗi request đắt ~3.2×.

**Thí nghiệm E không làm alert nào firing. Phát hiện loại sự cố này trong production bằng cách nào?**

Đây là **sự cố chất lượng**, không phải sự cố hạ tầng: agent v1 vẫn trả 200, latency thấp hơn, error rate thấp hơn — mọi metric hạ tầng đều xanh. Cách phát hiện:

1. **Quality gate trong CI** (mục 3): eval trên golden dataset với baseline, exit code 1 chặn deploy. Đây là lớp duy nhất bắt được ngay trước khi release.
2. **Canary + eval trên traffic thật**: chạy v1 cho 1–5 % user, so sánh chỉ số chất lượng (tỉ lệ người dùng hỏi lại, thumbs-down, session bỏ giữa chừng) với nhóm còn lại; rollback tự động nếu lệch.
3. **Metric chất lượng phái sinh từ dữ liệu người dùng**: `retrieval_hit_ratio` tụt về 0 (như trong thí nghiệm này), tỉ lệ câu trả lời generic/fallback, tỉ lệ user copy câu trả lời, độ dài hội thoại trước khi user bỏ đi.
4. **LLM-as-judge chạy mẫu**: lấy ngẫu nhiên 1 % traffic, chấm điểm bằng model mạnh hơn, alert khi điểm trung bình giảm > X điểm trong 1 giờ.
5. **Synthetic check theo kịch bản**: cron chạy 20 câu hỏi "known-answer" mỗi 5 phút lên production và assert keyword — bắt được cả sự cố model/prompt bị đổi ngoài ý muốn.

Nói cách khác: **observability hạ tầng không thay thế được eval chất lượng**. Metric chỉ trả lời "hệ thống có đang chạy không", còn "có đang trả lời đúng không" phải đo bằng một đường ống eval riêng.

### 4.3 Debug bằng trace

- `trace_id`: **ee3ca66e9c99321cffc88dc7a3f9d9d7**
- Tổng thời gian: **1740.5 ms**
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small` — 1716.1 ms (99 %)**, `gen_ai.request.model=mock-llm-small`, `gen_ai.usage.input_tokens=83`, `gen_ai.usage.output_tokens=44`
- Phân rã: `POST /ask` 1740.5 ms → `agent.run` 1738.3 ms → [`agent.retrieve_context` 22.0 ms (1 %), `chat mock-llm-small` 1716.1 ms (99 %)]

→ Thời gian nằm ở **LLM call**, không phải code của agent (retrieval chỉ 22 ms). Đây là kết luận quan trọng khi debug: nếu đổ lỗi cho retrieval/RAG code thì đã sửa sai chỗ. Việc cần làm là retry/timeout/caching cho LLM, hoặc chuyển sang model nhanh hơn.

- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-25T06:58:22.933631+00:00", "level": "INFO", "service": "observable-agent", "instance": "f5478d248faf", "event": "llm_call", "trace_id": "ee3ca66e9c99321cffc88dc7a3f9d9d7", "span_id": "24c1f5bf5a67eead", "request_id": "092ff9f409d8", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 83, "output_tokens": 44, "cost_usd": 3.9e-05, "llm_ms": 1678.0}
{"ts": "2026-11-25T06:58:22.934554+00:00", "level": "INFO", "service": "observable-agent", "instance": "f5478d248faf", "event": "http_request", "trace_id": "ee3ca66e9c99321cffc88dc7a3f9d9d7", "span_id": "24c1f5bf5a67eead", "request_id": "092ff9f409d8", "method": "POST", "route": "/ask", "status": 200, "ms": 1739.8}
```

- Trace lỗi tương ứng (`3ae5387ce47d408677d4694aad9c2bea`, 98.3 ms, HTTP 503):

```json
{"ts": "2026-11-25T06:58:27.863325+00:00", "level": "INFO", "service": "observable-agent", "instance": "913b5adaeab4", "event": "llm_error", "trace_id": "3ae5387ce47d408677d4694aad9c2bea", "span_id": "1d827231feeedb09", "request_id": "e237360e29bb", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-25T06:58:27.863584+00:00", "level": "INFO", "service": "observable-agent", "instance": "913b5adaeab4", "event": "http_request", "trace_id": "3ae5387ce47d408677d4694aad9c2bea", "span_id": "1d827231feeedb09", "request_id": "e237360e29bb", "method": "POST", "route": "/ask", "status": 503, "ms": 97.8}
```

`trace_id` trong log trùng khớp 1-1 với trace trong Jaeger → từ một dòng log bất kỳ nhảy thẳng sang waterfall của request đó.

---

## 5. Benchmark scaling (production, Locust headless, 100 users, ramp 10/s, 2 phút)

| Số instance | RPS (agg) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 66.23 | 190 | 220 | 1700 | 68 / 7887 (0.86 %) |
| 3 | 66.26 | 190 | 220 | 1700 | 78 / 7892 (0.99 %) |

Nguồn: `benchmark-results/scale_1_stats.csv`, `benchmark-results/scale_3_stats.csv` (dòng `Aggregated`; riêng `/ask`: 60.48 req/s vs 60.17 req/s).

**Giải thích kết quả:** Scale 1 → 3 **không** cải thiện p95 (220 ms ở cả hai) và RPS gần như y hệt (66.23 → 66.26). Nút thắt **không phải CPU của agent**:

1. **Locust là bottleneck** — load generator chạy trong container 1 CPU, `-u 100` với latency 220 ms chỉ sinh được ~60 req/s cho `/ask`; đã bão hoà ở mức 100 user nên thêm agent cũng không có thêm request để phục vụ. Bằng chứng: RPS `/health` cũng gần như không đổi (5.74 → 6.09).
2. **LLM là bottleneck thứ hai** — theo mục 4.3, 99 % thời gian request nằm trong span `chat mock-llm-small` (sleep 1.5 s ở 3 % request). Dù có 3 process agent, mỗi request vẫn phải chờ đúng khoảng đó, nên p99 vẫn 1700 ms — đúng như kỳ vọng vì p99 ở đây là "đuôi do mock LLM cố tình tạo ra", không phải do thiếu instance.
3. **Nginx không phải nút thắt** — `X-Served-By` chia đều 3 instance (mục Part 5) nên LB hoạt động đúng.

Kết luận: p95 220 ms đã ở mức sàn của mock LLM, nên scale chỉ có ích khi **tải đến từ nhiều nguồn** hoặc khi **mỗi request tốn CPU thật** (vd model inference local). Muốn thấy scale có tác dụng cần tăng số Locust worker/CPU cho load generator trước, rồi mới tăng `--scale agent`.

---

## 6. Kết luận

**3 điều học được về benchmark & observability:**

1. **Percentile quan trọng hơn average, và p99 khác p95 rất xa.** Ở `MOCK_SLOW_RATE=0.1`, average chỉ 320 ms nhưng p95 = 1685 ms — nếu nhìn average sẽ tưởng hệ thống khoẻ. Tail latency là thứ người dùng thật cảm nhận, nên SLO phải đặt trên p95/p99 kèm điều kiện "kéo dài bao lâu" (`for`) để tránh báo động giả.
2. **Benchmark chất lượng và benchmark hạ tầng trả lời hai câu hỏi khác nhau, cần cả hai.** Thí nghiệm E chứng minh điều này: v1 xanh mọi metric hạ tầng nhưng accuracy 4.3 % — chỉ eval + quality gate mới bắt được. Ngược lại, eval 23 câu không đủ kết luận về latency (mẫu quá nhỏ), phải dùng load test.
3. **Trace + log có `trace_id` chung biến "hệ thống chậm" thành "chậm ở đâu".** Trace `ee3ca66e…` chỉ ra 99 % thời gian nằm ở span LLM (1716/1740 ms), retrieval chỉ 22 ms — nếu không có trace sẽ rất dễ tối ưu sai chỗ. Và số liệu cost cho thấy đổi model là quyết định **19.7× tiền**, nên cost phải là metric hạng nhất, không phải thứ xem sau.

**Nếu đưa agent này lên production thật, tôi sẽ thêm:**

- **Metric chất lượng online**: `answer_fallback_ratio` (tỉ lệ trả lời generic), `retrieval_hit_ratio` theo version, `user_retry_rate`, `thumbs_down_rate` — để bắt sự cố kiểu E tự động.
- **SLO theo error budget + multi-window burn rate**: alert khi burn rate 1 giờ > 14.4× và 5 phút > 14.4× (đúng chuẩn SRE), thay vì ngưỡng tĩnh.
- **Metric ở tầng load balancer** (`nginx_http_requests_total` theo status, `upstream_response_time`): hiện lỗi 504 do Nginx sinh ra không hiện trên dashboard của agent — cần giám sát cả biên hệ thống.
- **`llm_request_duration` theo `model` + `prompt_template_version`** và **cache hit ratio** cho retrieval, để thấy ngay khi prompt bị phình.
- **Cost guard ở tầng hạ tầng**: alert khi `cost_per_correct_answer` tăng > 2× so với 7 ngày trước (chất lượng giảm thường đi kèm chi phí/câu đúng tăng).
- **Synthetic check định kỳ** 20 câu known-answer + **canary deploy** 5 % traffic cho mọi thay đổi prompt/model.
- **Tracing sampling 10 %** và giữ 100 % cho request lỗi/chậm để không tốn chi phí lưu trace.
