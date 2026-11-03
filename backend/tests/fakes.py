"""Test doubles shared across test modules."""

import uuid


class RecordingQueue:
    """In-memory TaskQueue: records what would have been published to the broker."""

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []
        self.available = True

    def enqueue_ingestion(self, document_id: uuid.UUID) -> bool:
        if not self.available:
            return False
        self.enqueued.append(document_id)
        return True
