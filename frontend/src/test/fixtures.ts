/** Builders for API payloads: valid defaults, override only what a test is about. */
import type {
  ChunkOut,
  Citation,
  DocumentOut,
  DocumentUploadOut,
  QueryResponse,
  RetrievedFragment,
} from "../api/types";

export function makeDocument(overrides: Partial<DocumentOut> = {}): DocumentOut {
  return {
    id: "doc-1",
    lineage_id: "lineage-1",
    version: 1,
    title: "Marea Hogar · Condicionado general 2025",
    filename: "marea-hogar-condicionado-2025.pdf",
    size_bytes: 48_213,
    page_count: 6,
    status: "ready",
    stage: null,
    progress: 100,
    error_code: null,
    error_message: null,
    chunk_count: 21,
    ingest_trace_id: "4bf92f3577b34da6a3ce929d0e0e4736",
    superseded: false,
    superseded_by_id: null,
    created_at: "2026-11-02T10:00:00Z",
    updated_at: "2026-11-02T10:00:05Z",
    processed_at: "2026-11-02T10:00:05Z",
    ...overrides,
  };
}

export function makeUpload(overrides: Partial<DocumentUploadOut> = {}): DocumentUploadOut {
  return {
    ...makeDocument({ status: "pending", progress: 0, chunk_count: null, page_count: null }),
    deduplicated: false,
    queued: true,
    ...overrides,
  };
}

export function makeCitation(overrides: Partial<Citation> = {}): Citation {
  return {
    ref: 1,
    chunk_id: "chunk-1",
    document_id: "doc-1",
    document_title: "Marea Hogar · Condicionado general 2026",
    document_version: 2,
    section: "Artículo 4. Daños por agua",
    page_start: 3,
    page_end: 3,
    quote: "la franquicia aplicable será de 100 euros por siniestro",
    exact_match: true,
    ...overrides,
  };
}

export function makeFragment(overrides: Partial<RetrievedFragment> = {}): RetrievedFragment {
  return {
    chunk_id: "chunk-1",
    document_id: "doc-1",
    document_title: "Marea Hogar · Condicionado general 2026",
    document_version: 2,
    section: "Artículo 4. Daños por agua",
    page_start: 3,
    page_end: 3,
    similarity: 0.71,
    text_rank: 1,
    score: 0.032,
    cited: true,
    flagged: false,
    preview: "Para la vivienda habitual, la franquicia aplicable será de 100 euros por siniestro…",
    ...overrides,
  };
}

export function makeResponse(overrides: Partial<QueryResponse> = {}): QueryResponse {
  return {
    status: "answered",
    answer: "Para la vivienda habitual, la franquicia es de 100 euros por siniestro. [1]",
    no_evidence: false,
    confidence: "high",
    statements: [
      { text: "Para la vivienda habitual, la franquicia es de 100 euros por siniestro.", citation_refs: [1] },
    ],
    citations: [makeCitation()],
    retrieved: [makeFragment()],
    warnings: [],
    validation: { passed: true, attempts: 1, degraded: false, issues: [] },
    usage: { model: "fake/deterministic", input_tokens: 812, output_tokens: 64 },
    trace_id: "0af7651916cd43dd8448eb211c80319c",
    latency_ms: 1240,
    ...overrides,
  };
}

export function makeChunk(overrides: Partial<ChunkOut> = {}): ChunkOut {
  return {
    id: "chunk-1",
    document_id: "doc-1",
    document_title: "Marea Hogar · Condicionado general 2026",
    document_version: 2,
    document_superseded: false,
    section: "Artículo 4. Daños por agua",
    page_start: 3,
    page_end: 3,
    content:
      "Artículo 4. Daños por agua.\nPara la vivienda habitual, la franquicia aplicable será de " +
      "100 euros por siniestro. Para la segunda residencia, de 250 euros.",
    flags: [],
    ...overrides,
  };
}
