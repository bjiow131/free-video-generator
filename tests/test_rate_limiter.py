import time

from core.api.rate_limiter import AgnesRateLimiter


def test_rate_limiter_wait_does_not_move_refill_clock_into_future():
    limiter = AgnesRateLimiter(rate_per_minute=6000, max_burst=1)
    limiter.tokens = 0.0
    before = time.monotonic()
    limiter.acquire()
    assert limiter.last_refill <= time.monotonic()
    assert limiter.last_refill >= before
