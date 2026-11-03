"""Question answering over the indexed policies."""

from fastapi import APIRouter

from app.api.deps import QueryServiceDep
from app.schemas.query import QueryRequest, QueryResponse

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
async def ask(request: QueryRequest, service: QueryServiceDep) -> QueryResponse:
    """Answer using only the indexed documents. Every claim comes with a verified verbatim
    citation. The response always explains itself through `status`: answered, partial,
    conflicting_evidence, insufficient_evidence (`no_evidence: true`), or llm_unavailable
    (relevant fragments are returned so the agent can still review them)."""
    return await service.answer(request.question, request.document_ids)
