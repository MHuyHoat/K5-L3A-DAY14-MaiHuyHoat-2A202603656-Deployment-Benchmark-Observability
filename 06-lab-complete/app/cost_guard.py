"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis
  • Tổng chi phí vượt DAILY_BUDGET_USD (hoặc MONTHLY_BUDGET_USD) → HTTP 402
"""
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

KEY_PREFIX = "cost:"


def _period_key() -> str:
    now = datetime.now(timezone.utc)
    if settings.budget_period == "month":
        return f"{KEY_PREFIX}{now:%Y-%m}"
    return f"{KEY_PREFIX}{now:%Y-%m-%d}"


def _current_spend() -> float:
    return float(r.get(_period_key()) or 0.0)


def _ttl_seconds() -> int:
    # Giữ key lâu hơn 1 chu kỳ để tránh mất dữ liệu do đồng hồ lệch
    return 32 * 24 * 3600 if settings.budget_period == "month" else 2 * 24 * 3600


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    try:
        spent = _current_spend()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cost guard unavailable (Redis not connected)",
        )
    if spent >= settings.budget_usd:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Budget exhausted: spent ${spent:.6f} of "
                   f"${settings.budget_usd:.6f} per {settings.budget_period}",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K \
        + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K
    try:
        key = _period_key()
        pipe = r.pipeline()
        pipe.incrbyfloat(key, cost)
        pipe.expire(key, _ttl_seconds())
        pipe.execute()
    except Exception:
        # Không chặn response chỉ vì không ghi được chi phí; lỗi đã lộ qua /ready
        pass
    return cost


def current_spend() -> float:
    """Tổng chi phí đã dùng trong chu kỳ hiện tại (dùng cho /stats và log)."""
    try:
        return _current_spend()
    except Exception:
        return 0.0
