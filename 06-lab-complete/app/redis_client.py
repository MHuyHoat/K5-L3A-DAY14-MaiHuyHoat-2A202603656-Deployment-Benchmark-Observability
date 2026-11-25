"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

App vẫn phải KHỞI ĐỘNG ĐƯỢC khi Redis chưa sẵn sàng → chỉ tạo client lúc import,
không ping. redis_healthy() dùng cho GET /ready.
"""
import redis

from app.config import settings

# Client lazy: redis-py không mở kết nối cho tới lệnh đầu tiên
r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=2,
    health_check_interval=30,
)


def redis_healthy() -> bool:
    try:
        return bool(r.ping())
    except (redis.RedisError, OSError):
        return False
