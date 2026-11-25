# Day 14 Lab — Mission Answers

**Họ tên:** Mai Huy Hoạt
**MSSV:** 2A202603656
**Lớp:** K5-L3A
**Ngày chạy:** 2026-11-25
**Môi trường:** Linux (12 CPU / 32 GB RAM), Docker 29.9.3, Docker Compose v5.7.1, Python 3.11.13

> Ghi chú: máy chạy bài đang chia sẻ cổng 8000 với một service khác, nên các ví dụ được chạy trên cổng thay thế (8100, 8101, 8120, 8121). Bản `06-lab-complete` và Part 7 vẫn dùng đúng cổng quy định (8000/8001/8002/8080).

---

## Part 1 — Localhost vs Production

### Exercise 1.1 — Anti-patterns trong `01-localhost-vs-production/develop/app.py`

| # | Anti-pattern | Dòng code | Vì sao nguy hiểm |
| --- | --- | --- | --- |
| 1 | Hardcode API key + DB password | `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:<password>@localhost:5432/mydb"` (giá trị giả trong file mẫu của đề) | Push lên GitHub là lộ key/DB ngay; key nằm trong lịch sử Git thì xoá file cũng không hết |
| 2 | Log ra secret | `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | Secret đi vào log aggregator (Datadog/Loki), ai đọc log cũng lấy được key |
| 3 | `print()` thay vì structured logging | `print(f"[DEBUG] Got question: {question}")` | Không parse/lọc được theo field, không có level, không có request_id |
| 4 | Không có health/readiness endpoint | (không có `/health`, `/ready`) | Platform không biết container sống hay chết để restart; load balancer không biết instance đã sẵn sàng |
| 5 | Port và host cố định, `reload=True` | `uvicorn.run("app:app", host="localhost", port=8000, reload=True)` | Railway/Render inject `PORT`; `host="localhost"` không nhận kết nối từ ngoài container; reload là debug-only |
| 6 | Không có shutdown handler | (không có `lifespan`/signal handler) | `docker stop` cắt ngang request đang chạy → user nhận lỗi |
| 7 | Debug flag hardcode | `DEBUG = True` | Bật debug trên production = lộ stack trace, tốn tài nguyên |

**Kết quả gọi bản develop** (Exercise 1.2, chạy cổng 8100):

```bash
$ curl -sS -X POST "http://127.0.0.1:8100/ask?question=Hello%20Docker" -w '\nHTTP:%{http_code}\n'
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
HTTP:200

$ curl -sS -X POST "http://127.0.0.1:8100/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'
{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}
HTTP:422
```

→ Nhận `question` qua **query param**, gửi JSON bị 422 (đúng như lưu ý số 3 trong README).

```bash
$ curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8100/health
404
$ curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8100/ready
404
```

Log của bản develop lộ secret:

```text
[DEBUG] Got question: Hello Docker
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this   ← giá trị giả của đề, in ra log
[DEBUG] Response: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!
```

**Bản production** (Exercise 1.3, cổng 8101):

```bash
$ curl -sS -X POST http://127.0.0.1:8101/ask -H 'Content-Type: application/json' -d '{"question":"Hello"}' -w '\nHTTP:%{http_code}\n'
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","model":"gpt-4o-mini"}
HTTP:200

$ curl -sS http://127.0.0.1:8101/health
{"status":"ok","uptime_seconds":6.8,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T06:18:04.916085+00:00"}

$ curl -sS http://127.0.0.1:8101/ready
{"ready":true}

$ curl -sS -X POST http://127.0.0.1:8101/ask -H 'Content-Type: application/json' -d '{}' -w '\nHTTP:%{http_code}\n'
{"detail":"question field is required"}
HTTP:422
```

### Exercise 1.3 — Bảng so sánh

| Feature | Basic (develop) | Advanced (production) | Tại sao quan trọng? |
| --- | --- | --- | --- |
| Config | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG=True`, port 8000 | `config.py` đọc `HOST`, `PORT`, `DEBUG`, `ENVIRONMENT`, `AGENT_API_KEY`, `ALLOWED_ORIGINS` từ env + `validate()` fail-fast | Cùng một image chạy được ở dev/staging/prod; secret không nằm trong code (12-Factor III) |
| Health check | Không có (`/health` → 404) | `GET /health` trả 200 + uptime + version; `GET /ready` trả 503 khi `is_ready=False` | Platform dùng liveness để restart, load balancer dùng readiness để route traffic |
| Logging | `print()` kèm secret và nội dung câu hỏi | JSON log chỉ ghi `question_length`, `response_length`, `client_ip` — không ghi secret/nội dung | Log JSON lọc được theo field, không rò rỉ dữ liệu người dùng |
| Shutdown | Không có handler → bị SIGKILL, request đang chạy mất | `lifespan` shutdown: `is_ready=False`, chờ in-flight request xong, đóng connection | `docker stop`/rolling deploy không làm rớt request của user |
| Binding | `host="localhost"` — chỉ nhận từ trong máy | `host=0.0.0.0` từ env `HOST` | Trong container phải bind 0.0.0.0 mới nhận traffic từ ngoài |
| Port | Cứng 8000 | `int(os.getenv("PORT", "8000"))` | Railway/Render/Cloud Run cấp `PORT` động |
| CORS | Không cấu hình | `ALLOWED_ORIGINS` từ env, giới hạn method/header | Tránh mở API cho mọi origin |
| Reload | `reload=True` luôn bật | `reload=settings.debug` | Reload/debug trên production gây lộ stack trace và tốn CPU |

---

## Part 2 — Docker

### Exercise 2.1 — Câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image là gì?** `python:3.11` — bản full distribution (~1 GB, có cả compiler và nhiều tool không cần cho runtime).
2. **Working directory là gì?** `WORKDIR /app` — mọi lệnh sau đó (`COPY`, `RUN`, `CMD`) chạy tương đối trong `/app`.
3. **Tại sao `COPY requirements.txt` đứng trước `COPY . .`?** Docker cache theo từng layer. Chừng nào `requirements.txt` không đổi, layer `RUN pip install` được dùng lại từ cache; chỉ khi source code đổi thì mới phải chạy lại các layer sau. Đặt `COPY . .` trước sẽ làm mất cache pip mỗi lần sửa 1 dòng code.
4. **CMD vs ENTRYPOINT khác nhau thế nào?** `ENTRYPOINT` là chương trình cố định luôn chạy, `CMD` là tham số mặc định (và bị thay hoàn toàn khi `docker run <image> <cmd>`). Dùng `ENTRYPOINT` khi image là một CLI cố định; dùng `CMD` khi muốn người dùng override lệnh. Có thể kết hợp: `ENTRYPOINT ["uvicorn"]` + `CMD ["app:app"]`.

### Exercise 2.2 — Build & run bản develop

```bash
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -d --name p2dev -p 127.0.0.1:8110:8000 my-agent:develop
$ curl -sS -X POST "http://127.0.0.1:8110/ask?question=What%20is%20Docker?" -w '\nHTTP:%{http_code}\n'
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
HTTP:200

$ docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep my-agent
my-agent:advanced 240MB
my-agent:develop 1.67GB
```

### Exercise 2.3 — Multi-stage build & kích thước image

`02-docker/production/Dockerfile` có 2 stage:

- **Stage 1 `builder`** (`python:3.11-slim`): cài `gcc`, `libpq-dev` rồi `pip install --user -r requirements.txt` → mọi package nằm trong `/root/.local`.
- **Stage 2 `runtime`** (`python:3.11-slim`): tạo user non-root, **chỉ** copy `/root/.local` từ builder + source code, bỏ toàn bộ compiler/build tool. Image nhỏ hơn vì không mang theo `gcc`, `libpq-dev`, `apt` cache và các file trung gian của pip.

| Image | Dung lượng đo được | Ghi chú |
| --- | ---: | --- |
| `my-agent:develop` (single-stage, `python:3.11`) | **1670 MB** | Full Python + pip cache + build tool |
| `my-agent:advanced` (multi-stage, `python:3.11-slim`) | **240 MB** | Chỉ site-packages + code, chạy non-root |
| Chênh lệch | **−1430 MB (−85.6 %)** | `(1670 − 240) / 1670 × 100 = 85.6 %` |

→ Multi-stage + slim base giảm **85.6 %** dung lượng, đồng thời giảm bề mặt tấn công (ít package có CVE hơn).

### Exercise 2.4 — Docker Compose stack

Sơ đồ service của `02-docker/production/docker-compose.yml`:

```text
                      ┌────────────────────────────┐
   client ──:8081──▶  │  nginx (nginx:alpine)      │  LB + rate limit 10 r/s
                      │  proxy_pass agent_backend  │
                      └──────────────┬─────────────┘
                                     │ internal network
                      ┌──────────────▼─────────────┐
                      │  agent (build 02-docker/   │  FastAPI, 2 workers
                      │  production/Dockerfile)    │  ENVIRONMENT=staging
                      └───────┬───────────┬────────┘
                              │           │
                  ┌───────────▼──┐   ┌────▼─────────────┐
                  │ redis:7-alpine│  │ qdrant:v1.9.0    │
                  │ session/limit │  │ vector DB (RAG)  │
                  └───────────────┘  └──────────────────┘
```

Kết quả test qua Nginx:

```bash
$ curl -sS http://127.0.0.1:8081/health
{"status":"ok","uptime_seconds":14.2,"version":"2.0.0","timestamp":"2026-11-25T06:21:41.980502"}

$ curl -sS -X POST http://127.0.0.1:8081/ask -H 'Content-Type: application/json' -d '{"question":"Explain microservices"}'
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

$ curl -sS http://127.0.0.1:8081/
{"app":"AI Agent","version":"2.0.0","environment":"staging"}
```

Rate limit của Nginx (zone `10r/s burst=20`, bắn 40 request song song):

```bash
$ seq 1 40 | xargs -P 40 -I{} curl -sS -o /dev/null -w "%{http_code}\n" \
    -X POST http://127.0.0.1:8081/ask -H 'Content-Type: application/json' -d '{"question":"parallel"}' \
  | sort | uniq -c
     21 200
     19 429
```

Trạng thái stack:

```text
k5-day14-part2-agent-1    k5-day14-part2-agent   8000/tcp                            Up (healthy)
k5-day14-part2-nginx-1    nginx:alpine           0.0.0.0:8081->80/tcp                Up
k5-day14-part2-qdrant-1   qdrant/qdrant:v1.9.0   6333-6334/tcp                       Up (healthy)
k5-day14-part2-redis-1    redis:7-alpine         6379/tcp                            Up (healthy)
```

> Cổng 80 trên máy đang bị service khác chiếm, nên bài chạy Nginx ở 8081 (map `8081:80`) theo đúng tinh thần "đổi cổng host, không đổi cổng container".

---

## Part 3 — Cloud Deployment

### Exercise 3.1 — Deploy (Railway/Render)

> Phần deploy cloud cần tài khoản Railway/Render gắn với repo GitHub. Xem [DEPLOYMENT.md](DEPLOYMENT.md) để biết trạng thái và cách chạy lại 4 lệnh tự kiểm của CP6.

Bản `06-lab-complete/` đã sẵn sàng deploy:

- `Dockerfile` multi-stage, lắng nghe `${PORT}` → Railway/Render inject `PORT` là chạy được ngay.
- `railway.toml` khai báo `builder = "DOCKERFILE"`, `healthcheckPath = "/health"`.
- `render.yaml` khai báo web service `runtime: docker` + Redis blueprint, `AGENT_API_KEY` dùng `generateValue: true`, `REDIS_URL` lấy `fromService` của Redis (không ghi secret vào file).

### Exercise 3.2 — So sánh `railway.toml` với `render.yaml`

| Khía cạnh | `railway.toml` | `render.yaml` |
| --- | --- | --- |
| Định dạng | TOML, cấu hình **một** service (project tạo bằng CLI `railway init`) | YAML Blueprint, mô tả **cả cụm** service (web + redis + worker...) |
| Khai báo build | `[build] builder = "DOCKERFILE"` (+ `dockerfilePath`) | `runtime: docker` + `dockerfilePath` (hoặc `buildCommand` nếu dùng runtime ngôn ngữ) |
| Health check | `[deploy] healthcheckPath = "/health"` | `healthCheckPath: /health` |
| Secret | Đặt ngoài file bằng `railway variables set AGENT_API_KEY=...` | Khai báo ngay trong file: `generateValue: true` (Render tự sinh) hoặc `sync: false` (điền trên dashboard) |
| Redis | Tạo service Redis riêng trên project rồi set `REDIS_URL` bằng CLI | Khai báo `type: redis` trong cùng blueprint, web nối bằng `fromService: {property: connectionString}` |
| Scale | `railway.json`/dashboard, hoặc `numReplicas` | `numInstances` trong `scaling`, hoặc `plan` |
| Triết lý | CLI-first, file chỉ tinh chỉnh service hiện có | GitOps-first: commit file → Render tự sync toàn bộ hạ tầng |

→ `railway.toml` phù hợp khi deploy nhanh một service từ CLI; `render.yaml` phù hợp khi muốn **infrastructure as code** cho cả agent + Redis trong một lần review.

### Exercise 3.3 — Cloud Run CI/CD pipeline

`03-cloud-deployment/production-cloud-run/cloudbuild.yaml` mô tả pipeline 4 bước, chạy tự động khi push lên `main`:

1. **test** — image `python:3.11-slim` cài `requirements.txt` + `pytest`, chạy `pytest tests/ -v`. Fail ở đây thì không build.
2. **build** — `docker build` gắn 2 tag: `gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` và `:latest`, dùng `--cache-from` để tái sử dụng layer.
3. **push** — `docker push --all-tags` lên Container Registry (mỗi commit một tag bất biến để rollback).
4. **deploy** — `gcloud run deploy ai-agent --image=...:$COMMIT_SHA` với `--min-instances=1` (tránh cold start), `--max-instances=10`, `--memory=512Mi`, `--cpu=1`, `--timeout=60s`, `--set-env-vars=ENVIRONMENT=production` và `--set-secrets=OPENAI_API_KEY=openai-key:latest` (lấy từ Secret Manager, không nằm trong pipeline).

`service.yaml` là bản IaC tương đương cho `gcloud run services replace`: `minScale=1`, `maxScale=10`, `containerConcurrency=80`, `timeoutSeconds=60`, `livenessProbe` gọi `/health`, `startupProbe` gọi `/ready`, secret mount qua `secretKeyRef`. Điểm đáng chú ý: Cloud Run **scale về 0**, nên `min-instances=1` là cách duy nhất giữ latency ổn định; và vì là mô hình pull metrics không hoạt động, phải dùng OTLP push hoặc Cloud Monitoring.

---

## Part 4 — API Security

### Exercise 4.1 — API key authentication (`04-api-gateway/develop`)

Chạy: `AGENT_API_KEY=secret-key-123 python app.py`

Key được kiểm trong `verify_api_key()` — dependency gắn vào `/ask` qua `Depends(verify_api_key)`. Thiếu key → 401, sai key → 403, đúng → 200 (dùng `curl -i` để thấy mã HTTP):

```bash
$ curl -sS -i -X POST http://127.0.0.1:8120/ask -H 'Content-Type: application/json' -d '{"question":"Hello"}' | head -1
HTTP/1.1 401 Unauthorized

$ curl -sS -i -X POST http://127.0.0.1:8120/ask -H 'X-API-Key: wrong-key' -H 'Content-Type: application/json' -d '{"question":"Hello"}' | head -1
HTTP/1.1 403 Forbidden

$ curl -sS -i -X POST http://127.0.0.1:8120/ask -H 'X-API-Key: secret-key-123' -H 'Content-Type: application/json' -d '{"question":"Hello"}' | head -1
HTTP/1.1 200 OK
```

**Rotate key:** vì key nằm trong env `AGENT_API_KEY` (không hardcode), chỉ cần set biến mới và restart/rolling deploy. Muốn rotate không downtime thì đọc danh sách key từ secret manager/Redis và chấp nhận cả key cũ trong một cửa sổ chuyển tiếp.

### Exercise 4.2 — JWT authentication (`04-api-gateway/production`)

```bash
$ TOKEN=$(curl -sS -X POST http://127.0.0.1:8121/auth/token \
    -H 'Content-Type: application/json' \
    -d '{"username":"student","password":"demo123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

$ curl -sS -i -X POST http://127.0.0.1:8121/ask -H 'Content-Type: application/json' -d '{"question":"Hello"}' | head -1
HTTP/1.1 401 Unauthorized

$ curl -sS -i -X POST http://127.0.0.1:8121/ask \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"question":"Explain JWT"}' | head -1
HTTP/1.1 200 OK

$ curl -sS http://127.0.0.1:8121/me/usage -H "Authorization: Bearer $TOKEN"
{"user_id":"student","date":"2026-11-25","requests":1,"input_tokens":4,"output_tokens":30,"cost_usd":1.9e-05,"budget_usd":1.0,"budget_remaining_usd":0.999981,"budget_used_pct":0.0}
```

Token là JWT HS256 chứa `sub`, `role`, `iat`, `exp` (60 phút). Không cần query DB mỗi request → stateless. `/ask` lấy `user` từ `Depends(verify_token)`.

### Exercise 4.3 — Rate limiting

Algorithm: **sliding window counter** bằng `deque` timestamp cho mỗi user (`rate_limiter.py`). User thường 10 req/phút, admin 100 req/phút. Không "bypass" cho admin — admin được **limit cao hơn**, đó là thiết kế tier chứ không phải lỗ hổng. Vượt limit → 429 kèm `Retry-After`, `X-RateLimit-*`:

```bash
$ for i in $(seq 1 12); do
    code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8121/ask \
      -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "{\"question\":\"Test $i\"}")
    echo "req $i -> $code"; done
req 1 -> 200
...
req 9 -> 200
req 10 -> 429
req 11 -> 429
req 12 -> 429
```

Header của response 429:

```text
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795587810
retry-after: 54
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":56}}
```

> Lưu ý: rate limiter của Part 4 là **in-memory** (`deque` trong process) — chỉ đúng cho 1 instance. Bản Part 6 đã chuyển sang Redis sorted set để dùng chung giữa các worker/instance.

### Exercise 4.4 — Cost guard

Cách làm trong `04-api-gateway/production/cost_guard.py` (và bản Redis ở Part 6):

- Key theo user và theo chu kỳ: `budget:{user}:{YYYY-MM}` (tháng) hoặc `cost:{YYYY-MM-DD}` (ngày) → tự "reset" khi sang chu kỳ mới, không cần cron.
- `check_budget()` gọi **trước** LLM: đọc tổng đã tiêu, nếu `>= DAILY_BUDGET_USD` → **402 Payment Required** (phân biệt với 429 của rate limit: 429 là "chậm lại", 402 là "hết tiền").
- `record_cost(input_tokens, output_tokens)` gọi **sau** LLM: `cost = input/1000 × 0.00015 + output/1000 × 0.0006`, cộng dồn bằng `INCRBYFLOAT` và `EXPIRE`.
- Part 4 có thêm **global budget** ($10/ngày toàn hệ thống) → 503 khi vượt, để một user không đốt hết tiền của mọi người.
- Cảnh báo ở 80 % ngân sách (`warn_at_pct`) để có thời gian xử lý trước khi chặn cứng.
- Vì state ở Redis, nhiều instance cùng thấy một con số → không thể "lách" bằng cách gọi vào instance khác.

**Vì sao cần cả rate limit và cost guard?** Rate limit chặn **tốc độ** (1000 request/phút vẫn có thể rẻ nếu prompt ngắn), cost guard chặn **tổng tiền** (1 request/phút với prompt 100k token vẫn đắt). Hai rủi ro khác nhau, cần hai lớp khác nhau.

---

## Part 5 — Scaling & Reliability

### Exercise 5.1 — Health checks (`05-scaling-reliability/develop`)

- `/health` (**liveness**): trả 200 khi process còn chạy, kèm uptime, version, và `checks.memory` (dùng `psutil`, `degraded` khi RAM > 90 %). Platform chỉ restart khi endpoint này fail.
- `/ready` (**readiness**): 503 khi `_is_ready == False` (đang startup hoặc đang shutdown). Load balancer dùng endpoint này để ngừng route traffic — **không** restart container.

Khác biệt cốt lõi: liveness = "có nên restart không?", readiness = "có nên gửi traffic không?". Trả 503 ở `/health` khi Redis chết là sai: process vẫn sống, restart không chữa được Redis, chỉ tạo vòng restart liên tục. Đó chính là lý do Part 6 tách `/health` (luôn 200) và `/ready` (503 khi mất Redis).

### Exercise 5.2 — Graceful shutdown

Bản develop đăng ký handler cho SIGTERM/SIGINT để log, và `lifespan` shutdown chờ tối đa 30 giây cho `_in_flight_requests` về 0. `uvicorn.run(..., timeout_graceful_shutdown=30)` cho uvicorn thời gian hoàn thành request.

Kết quả đo trên bản Docker của Part 6 (cùng cơ chế): `docker stop` → **exit code 0 trong 0.7 s**, request đang chạy vẫn nhận 200:

```text
✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 0.7s
```

### Exercise 5.3 — Stateless design

Anti-pattern là `conversation_history = {}` ở cấp module: mỗi instance có dict riêng, user gọi vào instance B sẽ "mất" history vừa tạo ở instance A; restart là mất sạch.

Bản production lưu history trong Redis: `r.rpush(f"history:{session_id}", ...)` và đọc lại bằng `LRANGE`, kèm `EXPIRE`. Instance nào phục vụ cũng đọc được cùng một Redis → scale ngang tự do. Trong Part 6, state của rate limit và cost guard cũng nằm trong Redis vì lý do tương tự (script chấm restart agent rồi kiểm tra vẫn bị 429 chứng minh điều này).

### Exercise 5.4 — Load balancing (`docker compose -p k5-day14-scaling up -d --build --scale agent=3`)

```text
k5-day14-scaling-agent-1   Up (healthy)
k5-day14-scaling-agent-2   Up (healthy)
k5-day14-scaling-agent-3   Up (healthy)
k5-day14-scaling-nginx-1   Up
k5-day14-scaling-redis-1   Up (healthy)
```

Nginx round-robin chia đều theo từng request (header `X-Served-By`):

```bash
$ for i in $(seq 1 9); do curl -sS -D - -o /dev/null -X POST http://127.0.0.1:8080/chat \
    -H 'Content-Type: application/json' -d "{\"question\":\"lb test $i\"}" | grep -i 'x-served-by'; done
X-Served-By: 172.20.0.3:8000
X-Served-By: 172.20.0.4:8000
X-Served-By: 172.20.0.5:8000
X-Served-By: 172.20.0.3:8000
X-Served-By: 172.20.0.4:8000
X-Served-By: 172.20.0.5:8000
X-Served-By: 172.20.0.3:8000
X-Served-By: 172.20.0.4:8000
X-Served-By: 172.20.0.5:8000
```

Dừng 1 instance để kiểm tra graceful shutdown:

```bash
$ docker stop -t 12 k5-day14-scaling-agent-2
k5-day14-scaling-agent-2
$ docker inspect -f 'exit={{.State.ExitCode}}' k5-day14-scaling-agent-2
exit=0
```

### Exercise 5.5 — Test stateless

```bash
$ python test_stateless.py
Session ID: 2b1f0b3a-...

Request 1: [instance-01b22a]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-55f205]
  Q: Why do we need containers?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....
...
Total requests: 5
Instances used: {'instance-01b22a', 'instance-55f205', 'instance-87a9ab'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
...
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 request được 3 instance khác nhau phục vụ (round-robin), nhưng `GET /chat/{session}/history` trả đủ **10 message** (5 user + 5 assistant). Nếu history nằm trong RAM, mỗi instance sẽ chỉ thấy 1–2 message của riêng nó. Đây là bằng chứng state đã nằm ngoài process → scale ngang an toàn.

---

## Part 6 — Final Project (`06-lab-complete/`)

### Kết quả `python check_production_ready.py` (chạy đầy đủ, có Docker)

```text
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

Vài chi tiết đo được từ output:

```text
✅ Docker: build image thành công — 1s
✅ Docker: image < 500 MB — 255 MB
✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 0.7s
✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429
✅ Khi chạy: hết budget → 402 — 402 ở request thứ 1
✅ Khi chạy: Redis mất kết nối → /ready 503 (còn /health vẫn 200)
✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
✅ Khi chạy: mọi dòng log của app là JSON hợp lệ — 17 dòng JSON
```

### Những gì đã làm trong `06-lab-complete/`

| File | Nội dung |
| --- | --- |
| `app/config.py` | Đọc toàn bộ cấu hình từ env (`PORT`, `ENVIRONMENT`, `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_WINDOW_SECONDS`, `DAILY_BUDGET_USD`/`MONTHLY_BUDGET_USD`, `LOG_LEVEL`); `DAILY` được ưu tiên nếu có cả hai |
| `app/redis_client.py` | `redis.from_url` lazy (không ping lúc import → app khởi động được khi không có Redis); `redis_healthy()` ping cho `/ready` |
| `app/auth.py` | `APIKeyHeader(auto_error=False)` + `hmac.compare_digest` → thiếu/sai key đều **401** (không 422/403) |
| `app/rate_limiter.py` | Sliding window bằng sorted set: `ZREMRANGEBYSCORE` → `ZCARD` → `ZADD`/`PEXPIRE`, 429 + `Retry-After` tính từ request cũ nhất |
| `app/cost_guard.py` | `check_budget()` → 402; `record_cost()` dùng `INCRBYFLOAT` + `EXPIRE`; key theo ngày/tháng nên tự reset |
| `app/main.py` | `JsonFormatter` cho mọi log; middleware log JSON mỗi request; `/health` (luôn 200), `/ready` (503 khi mất Redis), `/ask` nối auth → rate limit → budget → LLM → record cost; handler SIGTERM gọi lại handler cũ của uvicorn; handler 422/500 không lộ stack trace |
| `Dockerfile` | 2 stage (`builder` → `runtime`), `python:3.11-slim`, `pip --prefix=/install`, `PATH=/install/bin`, user `appuser` (uid 10001), `HEALTHCHECK` gọi `/health`, `CMD ["sh","-c","exec uvicorn ... --port ${PORT:-8000}"]` để uvicorn là PID 1 |
| `docker-compose.yml` | `agent` (build, `env_file` với `required: false`) + `redis:7-alpine` có healthcheck; `REDIS_URL=redis://redis:6379/0`; `depends_on: condition: service_healthy`; `stop_grace_period: 10s` |
| `.dockerignore` | Loại `.env*` (giữ `.env.example`), `__pycache__`, `venv/.venv`, `.git`, docs, `benchmark-observability/` |
| `.env.example` | Liệt kê đủ 8 biến, không có secret thật |
| `railway.toml` | `builder = "DOCKERFILE"`, `healthcheckPath = "/health"` |
| `render.yaml` | Web service `runtime: docker` + Redis blueprint; `AGENT_API_KEY` dùng `generateValue`, `REDIS_URL` lấy `fromService` |

**Vì sao `/health` phải 200 khi Redis chết, còn `/ready` phải 503?** `/health` là liveness: process Python còn phản hồi được thì restart không giải quyết gì, chỉ làm mất thêm request. `/ready` là readiness: không có Redis thì rate limit và cost guard không hoạt động đúng, nên instance phải bị rút khỏi load balancer (503) — traffic dồn sang instance còn khoẻ, và khi Redis trở lại thì instance tự 200 trở lại mà không cần restart.

---

## AI log

- Dùng AI assistant (GitHub Copilot trong VS Code) để: gõ các TODO của Part 6 theo hướng dẫn trong `CODE_LAB.md`, chạy `check_production_ready.py` và sửa các lỗi nó báo (thiếu `PATH=/install/bin` trong Dockerfile làm `exec uvicorn: not found`; `HOME=/app` trong Dockerfile của Part 7 làm container không import được package cài bằng `--user`), chạy load test/eval và thu thập số liệu, soạn thảo tài liệu từ số liệu thật.
- Toàn bộ số liệu trong `MISSION_ANSWERS.md` và `BENCHMARK_REPORT.md` là output thật của các lệnh đã chạy trên máy này; file JSON/CSV/PNG tương ứng nằm trong `reports/`, `benchmark-results/`, `screenshots/`.
- Không có secret thật nào trong repo; `AGENT_API_KEY` chỉ là giá trị demo đặt qua biến môi trường/`.env.example`.
