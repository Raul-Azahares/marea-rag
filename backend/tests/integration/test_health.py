import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings, get_settings

pytestmark = pytest.mark.integration


async def test_ready_when_database_and_redis_are_up(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


async def test_redis_down_is_degraded_not_unavailable(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(redis_url="redis://127.0.0.1:1/0")
    try:
        response = await client.get("/health/ready")
    finally:
        del app.dependency_overrides[get_settings]

    assert response.status_code == 200  # still serving: uploads wait as pending
    assert response.json() == {
        "status": "degraded",
        "checks": {"database": "ok", "redis": "unavailable"},
    }
