"""
Rate limiting (tiêu chí 7).

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429 kèm header Retry-After
  • State lưu trong Redis → mọi worker/instance dùng chung và còn sau khi restart
"""
import time
import uuid

from fastapi import HTTPException, status

from app.config import settings
from app.redis_client import r

KEY_PREFIX = "ratelimit:"


def check_rate_limit(key: str) -> None:
    """Sliding window bằng sorted set: score = timestamp (ms), member = id duy nhất."""
    window_ms = settings.rate_limit_window_seconds * 1000
    limit = settings.rate_limit_per_minute
    now_ms = int(time.time() * 1000)
    redis_key = f"{KEY_PREFIX}{key}"

    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, now_ms - window_ms)
        pipe.zcard(redis_key)
        _, used = pipe.execute()
    except Exception:
        # Redis chưa sẵn sàng (vd /ready đang 503) — không chặn request vì lỗi hạ tầng
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiter unavailable (Redis not connected)",
        )

    if used >= limit:
        try:
            oldest = r.zrange(redis_key, 0, 0, withscores=True)
            retry_after = settings.rate_limit_window_seconds
            if oldest:
                retry_after = max(1, int((oldest[0][1] + window_ms - now_ms) / 1000) + 1)
        except Exception:
            retry_after = settings.rate_limit_window_seconds
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {limit} requests per "
                   f"{settings.rate_limit_window_seconds}s",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        pipe = r.pipeline()
        pipe.zadd(redis_key, {f"{now_ms}-{uuid.uuid4().hex}": now_ms})
        pipe.pexpire(redis_key, window_ms)
        pipe.execute()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiter unavailable (Redis not connected)",
        )
