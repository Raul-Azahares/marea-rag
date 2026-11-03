"""Liveness and readiness probes."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.deps import SettingsDep
from app.db.session import get_async_engine

router = APIRouter(prefix="/health", tags=["health"])

CheckState = Literal["ok", "unavailable"]


class ReadinessOut(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    checks: dict[str, CheckState]


@router.get("/live")
async def liveness() -> dict[str, str]:
    """The process is up. Dependencies are checked by /health/ready."""
    return {"status": "ok"}


@router.get("/ready", response_model=ReadinessOut, responses={503: {"model": ReadinessOut}})
async def readiness(response: Response, settings: SettingsDep) -> ReadinessOut:
    """PostgreSQL is a hard dependency; Redis is a soft one.

    Without Redis, uploads are still accepted (they wait as `pending`, see the reconciler)
    and questions are still answered, so the API reports `degraded` instead of failing.
    """
    database_ok, redis_ok = await asyncio.gather(_database_ok(), _redis_ok(settings.redis_url))
    if not database_ok:
        response.status_code = 503
        status: Literal["ok", "degraded", "unavailable"] = "unavailable"
    else:
        status = "ok" if redis_ok else "degraded"
    return ReadinessOut(
        status=status,
        checks={
            "database": "ok" if database_ok else "unavailable",
            "redis": "ok" if redis_ok else "unavailable",
        },
    )


async def _database_ok() -> bool:
    try:
        async with asyncio.timeout(2), get_async_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


async def _redis_ok(url: str) -> bool:
    client = Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
    try:
        async with asyncio.timeout(2):
            return bool(await client.ping())
    except Exception:
        return False
    finally:
        await client.aclose()
