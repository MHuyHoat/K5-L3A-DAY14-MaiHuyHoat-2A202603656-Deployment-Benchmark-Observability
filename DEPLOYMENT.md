# Deployment Information — Day 14

**Họ tên:** Mai Huy Hoạt · **MSSV:** 2A202603656 · **Ngày:** 2026-11-25

## Public URL

> ⚠️ **Chưa deploy lên cloud trong lần chạy này.**
>
> Phần deploy (CP6) cần tài khoản Railway hoặc Render gắn với repo GitHub và thẻ thanh toán xác thực. Máy chạy bài không có credential của nền tảng nào (`railway`, `render`, GCP đều chưa đăng nhập), nên không thể tạo URL public thật. Không có URL nào được ghi ở đây để tránh nộp một link không tồn tại.
>
> Toàn bộ phần **cấu hình deploy đã hoàn tất và đã được `check_production_ready.py` xác nhận** (tiêu chí 12 — Public URL ready): `railway.toml`, `render.yaml`, Dockerfile lắng nghe `${PORT}`, `HEALTHCHECK` gọi `/health`. Chỉ còn bước chạy lệnh deploy.

Cách deploy (chạy trong `06-lab-complete/`) và tự kiểm tra:

```bash
# Railway
npm i -g @railway/cli
cd 06-lab-complete
railway login
railway init                                   # tạo project
railway add --plugin redis                     # hoặc tạo Redis service trên dashboard
railway variables set AGENT_API_KEY="$(openssl rand -hex 24)"
railway variables set REDIS_URL='${{Redis.REDIS_URL}}'
railway variables set RATE_LIMIT_PER_MINUTE=10
railway variables set DAILY_BUDGET_USD=1.0
railway up
railway domain                                 # → https://<app>.up.railway.app

# Render
# Dashboard → New → Blueprint → chọn repo (Render đọc 06-lab-complete/render.yaml)
#   - AGENT_API_KEY: generateValue (Render tự sinh)
#   - REDIS_URL: fromService → day14-agent-redis
```

Bốn lệnh tự kiểm tra của CP6 (mỗi lệnh chỉ in mã HTTP nên chụp ảnh không lộ key):

```bash
BASE="https://<your-app-domain>"
AGENT_API_KEY="<key đã đặt trên nền tảng>"

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200  (503 nếu REDIS_URL sai)
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -d '{"question":"Hello"}'                     # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'                                                          # 200
```

## Platform

Railway (chính) hoặc Render — file cấu hình có sẵn cho cả hai. So sánh chi tiết ở mục Part 3 của [MISSION_ANSWERS.md](MISSION_ANSWERS.md).

## Test Commands (local — đã chạy thật)

Stack đã chạy và pass 12/12 tiêu chí trên máy này:

```bash
cd 06-lab-complete
pip install -r requirements.txt
python check_production_ready.py          # → PASS 12/12, 43/43 checks

# hoặc chạy bằng Docker Compose (agent + redis)
docker compose up --build
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl -X POST http://localhost:8000/ask \
     -H "X-API-Key: dev-local-key" -H "Content-Type: application/json" \
     -d '{"question": "What is deployment?"}'
```

Output tiêu biểu:

```bash
$ curl -sS http://localhost:8000/health
{"status":"ok","uptime_seconds":12.4}

$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/ask \
    -H 'Content-Type: application/json' -d '{"question":"Hello"}'
401

$ curl -sS -X POST http://localhost:8000/ask \
    -H 'X-API-Key: dev-local-key' -H 'Content-Type: application/json' \
    -d '{"question":"What is deployment?"}'
{"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","user_id":null,"cost_usd":8.1e-06,"budget_used_usd":8.1e-06,"budget_limit_usd":1.0}
```

## Environment Variables Set

Đặt trên nền tảng (dashboard/CLI), **không** ghi giá trị thật vào repo. Danh sách đầy đủ ở `06-lab-complete/.env.example`:

| Biến | Bắt buộc | Ý nghĩa |
| --- | :---: | --- |
| `PORT` | ✅ | Nền tảng inject; Dockerfile dùng `${PORT:-8000}` |
| `AGENT_API_KEY` | ✅ | Secret cho header `X-API-Key` (thiếu/sai → 401) |
| `REDIS_URL` | ✅ | Redis cho rate limit + cost guard; sai → `/ready` 503 |
| `ENVIRONMENT` | ✅ | `production` trên cloud |
| `RATE_LIMIT_PER_MINUTE` | ✅ | Mặc định 10 |
| `RATE_LIMIT_WINDOW_SECONDS` | ➖ | Mặc định 60 |
| `DAILY_BUDGET_USD` | ✅* | Ngân sách ngày, vượt → 402 |
| `MONTHLY_BUDGET_USD` | ✅* | Thay thế cho ngân sách tháng |
| `LOG_LEVEL` | ➖ | Mặc định `INFO` |

\* Cần đặt ít nhất một trong hai; `DAILY_BUDGET_USD` được ưu tiên.

Trên cloud: `AGENT_API_KEY` phải tạo bằng `openssl rand -hex 24` rồi set qua dashboard/CLI — không bao giờ commit. Nếu key bị lộ, rotate ngay (set biến mới + rolling restart) thay vì xoá file.

## Screenshots

- [Running — check_production_ready.py PASS 12/12](screenshots/running.png)
- [Test — 4 lệnh CP6 trả 401/200 đúng](screenshots/test.png)
- [Dashboard — tiêu chí 12 được script chấm xác nhận](screenshots/dashboard.png)

> Ba ảnh trên là ảnh chụp **chạy thật trên máy local** (không phải URL cloud), dùng để chứng minh agent hoạt động đúng hợp đồng của CP6. Khi có credential nền tảng, chụp lại đúng 4 lệnh ở trên với `BASE` là domain cloud và thay 3 file này.

## Part 7 endpoints (local)

| Service | URL | Ghi chú |
| --- | --- | --- |
| Agent qua Nginx | http://localhost:8080 | `X-API-Key: day14-lab-key` |
| Grafana | http://localhost:3000 (máy này dùng 3001) | dashboard "Day 14 — AI Agent Overview" |
| Prometheus | http://localhost:9090 | `/alerts` để xem alert |
| Jaeger | http://localhost:16686 | service `observable-agent` |
| Locust | http://localhost:8089 | |
