import time

from core.api.rate_limiter import AgnesRateLimiter


def test_rate_limiter_wait_does_not_move_refill_clock_into_future():
    limiter = AgnesRateLimiter(rate_per_minute=6000, max_burst=1)
    limiter.tokens = 0.0
    before = time.monotonic()
    limiter.acquire()
    assert limiter.last_refill <= time.monotonic()
    assert limiter.last_refill >= before


def test_limiter_refills_after_sleep_without_waiting_again_forever(monkeypatch):
    """Regression for full Server Test hanging at second Agnes video submit."""
    from core.api import rate_limiter

    class Clock:
        now = 100.0
        sleeps = []

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.sleeps.append(seconds)
            assert len(self.sleeps) <= 3, "Limiter failed to credit time slept"
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr(rate_limiter.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(rate_limiter.time, "sleep", clock.sleep)

    limiter = rate_limiter.AgnesRateLimiter(rate_per_minute=60, max_burst=1)
    limiter.acquire()
    assert limiter.tokens == 0
    limiter.acquire()
    assert clock.sleeps == [1.0]
    assert limiter.last_refill == clock.now
    assert limiter.tokens == 0


def test_limiter_preserves_fractional_token_balance(monkeypatch):
    from core.api import rate_limiter

    class Clock:
        now = 200.0
        waits = []

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.waits.append(seconds)
            assert len(self.waits) <= 2
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr(rate_limiter.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(rate_limiter.time, "sleep", clock.sleep)
    limiter = rate_limiter.AgnesRateLimiter(rate_per_minute=60, max_burst=1)
    limiter.tokens = 0.4

    limiter.acquire()
    assert len(clock.waits) == 1
    assert abs(clock.waits[0] - 0.6) < 0.000001
    assert limiter.tokens == 0


def test_real_video_submit_limiter_still_limits_to_one_per_minute(monkeypatch):
    from core.api import rate_limiter

    monkeypatch.setenv("AGNES_VIDEO_SUBMIT_RPM", "1")
    monkeypatch.setattr(rate_limiter, "_video_submit_instance", None)
    limiter = rate_limiter.get_video_submit_limiter()
    assert limiter.refill_rate == 1 / 60
    assert limiter.max_tokens == 1
