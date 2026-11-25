# ============================================================
# Production image — multi-stage, slim base, non-root, HEALTHCHECK
#   Stage builder: cài dependencies vào /install (có compiler nếu cần)
#   Stage runtime: chỉ copy site-packages + code, chạy user appuser
# ============================================================
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt .
# psutil/redis/fastapi đều có wheel; --prefix giữ mọi thứ trong một thư mục để copy sang
RUN pip install --prefix=/install -r requirements.txt


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/install/lib/python3.11/site-packages \
    PATH=/install/bin:$PATH \
    PORT=8000 \
    ENVIRONMENT=production

# curl để HEALTHCHECK; --no-install-recommends giữ image nhỏ
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY --from=builder /install /install
WORKDIR /app
COPY app ./app
COPY utils ./utils

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# exec + $PORT: uvicorn là PID 1 nên nhận được SIGTERM từ `docker stop`
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
