import pytest

from app.worker.tasks import backoff_delay


@pytest.mark.parametrize(("retries", "nominal"), [(0, 5), (1, 10), (2, 20), (3, 40), (6, 300)])
def test_exponential_backoff_with_jitter_and_cap(retries: int, nominal: float) -> None:
    delays = [backoff_delay(retries, base=5) for _ in range(200)]

    assert all(0.5 * nominal <= d <= 1.5 * nominal for d in delays)
    assert len({round(d, 3) for d in delays}) > 1  # jittered, not synchronised
