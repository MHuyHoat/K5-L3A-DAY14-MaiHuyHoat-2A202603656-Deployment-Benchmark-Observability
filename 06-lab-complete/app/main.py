"""
Production AI Agent — Part 6 Final Project.

Đủ 12 tiêu chí trong README.md:
  /health (liveness) · /ready (readiness) · /ask (API key + rate limit + cost guard)
  JSON logging · graceful shutdown · config từ env.
"""
import json
import logging
import signal
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, current_spend, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask

START_TIME = time.time()


# ─────────────────────────────────────────────────────────
# Structured logging — mỗi dòng là 1 JSON object
# ─────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    # Log của uvicorn vẫn là text thường (script chấm bỏ qua), tắt access log cho gọn
    logging.getLogger("uvicorn.access").disabled = True


_configure_logging()
logger = logging.getLogger("agent")


def log_event(event: str, **fields) -> None:
    logger.info(event, extra={"extra_fields": fields})


# ─────────────────────────────────────────────────────────
# Graceful shutdown: SIGTERM → log rồi nhường lại handler của uvicorn
# ─────────────────────────────────────────────────────────
_previous_sigterm = None


def _handle_sigterm(signum, frame):
    log_event("sigterm_received", signal=signum)
    # Phải gọi lại handler cũ của uvicorn, nếu không process không bao giờ tắt
    if callable(_previous_sigterm):
        _previous_sigterm(signum, frame)


def _install_sigterm_handler() -> None:
    global _previous_sigterm
    current = signal.getsignal(signal.SIGTERM)
    if current is _handle_sigterm:
        return
    _previous_sigterm = current
    try:
        signal.signal(signal.SIGTERM, _handle_sigterm)
    except (ValueError, OSError):  # không phải main thread
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    _install_sigterm_handler()
    log_event("startup", environment=settings.environment, port=settings.port,
              rate_limit_per_minute=settings.rate_limit_per_minute,
              budget_usd=settings.budget_usd, budget_period=settings.budget_period,
              redis_url=settings.redis_url.split("@")[-1])
    if not settings.agent_api_key:
        log_event("config_warning", message="AGENT_API_KEY chưa đặt — mọi request /ask sẽ 401")
    yield
    log_event("shutdown", uptime_seconds=round(time.time() - START_TIME, 1))


app = FastAPI(title="Production AI Agent", version="1.0.0", lifespan=lifespan)


# ─────────────────────────────────────────────────────────
# Middleware: log JSON mỗi request (không log body/câu hỏi → tránh lộ dữ liệu)
# ─────────────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    log_event("request", method=request.method, path=request.url.path,
              status=response.status_code, ms=elapsed_ms)
    response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Input sai → 422 với thông báo gọn, không lộ stack trace."""
    errors = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]) or "body",
               "message": e.get("msg", "invalid value")} for e in exc.errors()]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Invalid request body", "errors": errors},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    log_event("unhandled_error", path=request.url.path, error=type(exc).__name__)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# ─────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


class AskResponse(BaseModel):
    question: str
    answer: str
    user_id: str | None = None
    cost_usd: float
    budget_used_usd: float
    budget_limit_usd: float


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Liveness: luôn 200 khi process còn chạy, không phụ thuộc Redis."""
    return {"status": "ok", "uptime_seconds": round(time.time() - START_TIME, 1)}


@app.get("/ready")
def ready():
    """Readiness: 200 khi Redis kết nối được, 503 khi mất Redis."""
    if not redis_healthy():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis not reachable",
        )
    return {"status": "ready",
            "budget_used_usd": round(current_spend(), 8),
            "budget_limit_usd": settings.budget_usd}


@app.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)   # 429 khi vượt RATE_LIMIT_PER_MINUTE
    check_budget()              # 402 khi hết ngân sách

    started = time.perf_counter()
    answer = llm_ask(body.question)
    llm_ms = round((time.perf_counter() - started) * 1000, 1)

    # Mock LLM không trả usage thật → ước lượng ~4 ký tự/token
    input_tokens = max(1, (len(body.question) + 40) // 4)
    output_tokens = max(1, len(answer) // 4)
    cost = record_cost(input_tokens, output_tokens)
    used = current_spend()

    log_event("llm_call", user_id=body.user_id, input_tokens=input_tokens,
              output_tokens=output_tokens, cost_usd=round(cost, 8),
              llm_ms=llm_ms, budget_used_usd=round(used, 8))

    if used >= settings.budget_usd:
        log_event("budget_exhausted", budget_used_usd=round(used, 8),
                  budget_limit_usd=settings.budget_usd)

    return AskResponse(question=body.question, answer=answer, user_id=body.user_id,
                       cost_usd=round(cost, 8), budget_used_usd=round(used, 8),
                       budget_limit_usd=settings.budget_usd)
