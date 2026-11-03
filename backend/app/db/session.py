"""Database engines and sessions.

The API is async (FastAPI + asyncio) and uses AsyncEngine/AsyncSession. The Celery worker is
synchronous by design and uses Engine/Session. psycopg 3 supports both modes with the same
`postgresql+psycopg://` URL, so models and queries are shared.

Engines are created lazily: a Celery prefork worker must create its connection pool *after*
forking, never inherit the parent's sockets.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_async_engine() -> AsyncEngine:
    return create_async_engine(
        get_settings().database_url,
        # Transparently replaces pooled connections broken by a database restart.
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
        # SQL errors otherwise embed bound parameters (policy text!) in messages and logs.
        hide_parameters=True,
    )


@lru_cache
def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_async_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with get_async_sessionmaker()() as session:
        yield session


@lru_cache
def get_sync_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        hide_parameters=True,
    )


@lru_cache
def get_sync_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(get_sync_engine(), expire_on_commit=False)
