import type {
  ApiErrorBody,
  ChunkOut,
  DocumentListOut,
  DocumentUploadOut,
  QueryResponse,
} from "./types";

const API_BASE = "/api/v1";

/** An error the UI can show as-is: the backend already sends a user-facing Spanish message. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly traceId: string | null;

  constructor(message: string, status: number, code: string, traceId: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.traceId = traceId;
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError(
      "No se pudo conectar con el servidor. Comprueba que la API está en marcha.",
      0,
      "NETWORK_ERROR",
      null,
    );
  }
  if (!response.ok) {
    throw await toApiError(response);
  }
  return (await response.json()) as T;
}

async function toApiError(response: Response): Promise<ApiError> {
  const traceId = response.headers.get("x-trace-id");
  try {
    const body = (await response.json()) as Partial<ApiErrorBody>;
    if (body.error) {
      return new ApiError(
        body.error.message,
        response.status,
        body.error.code,
        body.trace_id ?? traceId,
      );
    }
  } catch {
    // Not our JSON envelope (e.g. a proxy error page): fall through to a generic message.
  }
  return new ApiError(
    `Error inesperado del servidor (HTTP ${response.status}).`,
    response.status,
    `HTTP_${response.status}`,
    traceId,
  );
}

function pdfForm(file: File): FormData {
  const form = new FormData();
  form.append("file", file);
  return form;
}

export const api = {
  listDocuments: () => apiFetch<DocumentListOut>("/documents?limit=200"),

  uploadDocument: (file: File) =>
    apiFetch<DocumentUploadOut>("/documents", { method: "POST", body: pdfForm(file) }),

  uploadVersion: (documentId: string, file: File) =>
    apiFetch<DocumentUploadOut>(`/documents/${documentId}/versions`, {
      method: "POST",
      body: pdfForm(file),
    }),

  retryDocument: (documentId: string) =>
    apiFetch<DocumentUploadOut>(`/documents/${documentId}/retry`, { method: "POST" }),

  ask: (question: string, documentIds: string[]) =>
    apiFetch<QueryResponse>("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        document_ids: documentIds.length > 0 ? documentIds : undefined,
      }),
    }),

  getChunk: (chunkId: string) => apiFetch<ChunkOut>(`/chunks/${chunkId}`),
};

/** Browsers' PDF viewers honour `#page=N`, so a citation opens on its page. */
export function documentFileUrl(documentId: string, page?: number): string {
  return `${API_BASE}/documents/${documentId}/file${page ? `#page=${page}` : ""}`;
}
