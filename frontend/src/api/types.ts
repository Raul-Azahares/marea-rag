/** Mirror of the backend contracts (backend/app/schemas). Keep both in sync. */

export type DocumentStatus = "pending" | "processing" | "ready" | "failed";
export type IngestionStage = "extracting" | "chunking" | "embedding" | "indexing";

export interface DocumentOut {
  id: string;
  lineage_id: string;
  version: number;
  title: string;
  filename: string;
  size_bytes: number;
  page_count: number | null;
  status: DocumentStatus;
  stage: IngestionStage | null;
  progress: number;
  error_code: string | null;
  error_message: string | null;
  chunk_count: number | null;
  ingest_trace_id: string | null;
  superseded: boolean;
  superseded_by_id: string | null;
  created_at: string;
  updated_at: string;
  processed_at: string | null;
}

export interface DocumentUploadOut extends DocumentOut {
  deduplicated: boolean;
  queued: boolean;
}

export interface DocumentListOut {
  items: DocumentOut[];
  total: number;
}

export type AnswerStatus =
  | "answered"
  | "partial"
  | "conflicting_evidence"
  | "insufficient_evidence"
  | "llm_unavailable";

export type Confidence = "high" | "medium" | "low" | "none";

export interface Citation {
  ref: number;
  chunk_id: string;
  document_id: string;
  document_title: string;
  document_version: number;
  section: string | null;
  page_start: number;
  page_end: number;
  quote: string;
  exact_match: boolean;
}

export interface Statement {
  text: string;
  citation_refs: number[];
}

export interface RetrievedFragment {
  chunk_id: string;
  document_id: string;
  document_title: string;
  document_version: number;
  section: string | null;
  page_start: number;
  page_end: number;
  similarity: number | null;
  text_rank: number | null;
  score: number;
  cited: boolean;
  flagged: boolean;
  preview: string;
}

export interface ValidationIssue {
  code: string;
  detail: string;
  statement_index: number | null;
}

export interface ValidationReport {
  passed: boolean;
  attempts: number;
  degraded: boolean;
  issues: ValidationIssue[];
}

export interface Usage {
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
}

export interface QueryResponse {
  status: AnswerStatus;
  answer: string;
  no_evidence: boolean;
  confidence: Confidence;
  statements: Statement[];
  citations: Citation[];
  retrieved: RetrievedFragment[];
  warnings: string[];
  validation: ValidationReport;
  usage: Usage;
  trace_id: string | null;
  latency_ms: number;
}

export interface ChunkOut {
  id: string;
  document_id: string;
  document_title: string;
  document_version: number;
  document_superseded: boolean;
  section: string | null;
  page_start: number;
  page_end: number;
  content: string;
  flags: string[];
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown[] };
  trace_id?: string;
}

/** What the fragment viewer needs: which chunk, and which quote to highlight in it. */
export interface FragmentRef {
  chunkId: string;
  quote?: string;
}
