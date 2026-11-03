"""FastAPI dependency wiring. Tests override these to inject fakes."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.providers.base import ChatModel, EmbeddingProvider
from app.providers.factory import build_chat_model, build_embedding_provider
from app.rag.service import QueryService
from app.services.documents import DocumentService
from app.storage import FileStorage, LocalFileStorage
from app.task_queue import CeleryTaskQueue, TaskQueue

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_storage(settings: SettingsDep) -> FileStorage:
    return LocalFileStorage(settings.upload_dir)


def get_task_queue() -> TaskQueue:
    return CeleryTaskQueue()


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    """One provider per process (stateless clients)."""
    return build_embedding_provider(get_settings())


@lru_cache
def get_chat_model() -> ChatModel:
    return build_chat_model(get_settings())


StorageDep = Annotated[FileStorage, Depends(get_storage)]
TaskQueueDep = Annotated[TaskQueue, Depends(get_task_queue)]
EmbedderDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]
ChatModelDep = Annotated[ChatModel, Depends(get_chat_model)]


def get_document_service(
    session: SessionDep, storage: StorageDep, queue: TaskQueueDep, settings: SettingsDep
) -> DocumentService:
    return DocumentService(session, storage, queue, settings)


def get_query_service(
    session: SessionDep, embedder: EmbedderDep, chat: ChatModelDep, settings: SettingsDep
) -> QueryService:
    return QueryService(session, embedder, chat, settings)


DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
QueryServiceDep = Annotated[QueryService, Depends(get_query_service)]
