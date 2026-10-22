from ratelimit import Limiter


def test_per_ip_limit_and_recovery():
    lim = Limiter(per_ip=2, per_ip_window=60, per_day=100)
    assert lim.check("a", now=0) is None
    assert lim.check("a", now=1) is None
    assert lim.check("a", now=2) is not None
    assert lim.check("b", now=2) is None      # other visitors unaffected
    assert lim.check("a", now=70) is None     # window passed


def test_daily_cap():
    lim = Limiter(per_ip=100, per_day=3)
    for i in range(3):
        assert lim.check(f"ip{i}", now=i) is None
    assert "daily" in lim.check("new", now=5)
    assert lim.check("new", now=86500) is None
