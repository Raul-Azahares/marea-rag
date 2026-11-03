"""FastAPI dependency wiring. Tests override these to inject fakes."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.services.documents import DocumentService
from app.storage import FileStorage, LocalFileStorage
from app.task_queue import CeleryTaskQueue, TaskQueue

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_storage(settings: SettingsDep) -> FileStorage:
    return LocalFileStorage(settings.upload_dir)


def get_task_queue() -> TaskQueue:
    return CeleryTaskQueue()


StorageDep = Annotated[FileStorage, Depends(get_storage)]
TaskQueueDep = Annotated[TaskQueue, Depends(get_task_queue)]


def get_document_service(
    session: SessionDep, storage: StorageDep, queue: TaskQueueDep, settings: SettingsDep
) -> DocumentService:
    return DocumentService(session, storage, queue, settings)


DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
