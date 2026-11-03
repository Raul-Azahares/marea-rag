import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, documentFileUrl } from "./client";

/** Stub `fetch` with a fresh response per call (a body can only be read once). */
function mockFetch(respond: () => Response | Error) {
  const fetchMock = vi.fn<typeof fetch>(() => {
    const result = respond();
    return result instanceof Error ? Promise.reject(result) : Promise.resolve(result);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const json = (body: unknown, init: ResponseInit = {}) =>
  new Response(JSON.stringify(body), {
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  });

async function caught(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("expected the call to fail");
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("returns the parsed body on success", async () => {
    mockFetch(() => json({ items: [], total: 0 }));
    await expect(api.listDocuments()).resolves.toEqual({ items: [], total: 0 });
  });

  it("turns the backend error envelope into an ApiError with its trace id", async () => {
    mockFetch(() =>
      json(
        { error: { code: "DOCUMENT_NOT_FOUND", message: "El documento no existe." }, trace_id: "abc" },
        { status: 404 },
      ),
    );

    const error = await caught(api.getChunk("missing"));

    expect(error).toMatchObject({
      message: "El documento no existe.",
      status: 404,
      code: "DOCUMENT_NOT_FOUND",
      traceId: "abc",
    });
  });

  it("falls back to a generic message when the error is not ours (e.g. a proxy page)", async () => {
    mockFetch(
      () => new Response("<html>Bad Gateway</html>", { status: 502, headers: { "X-Trace-Id": "def" } }),
    );

    const error = await caught(api.listDocuments());

    expect(error).toMatchObject({
      message: "Error inesperado del servidor (HTTP 502).",
      code: "HTTP_502",
      traceId: "def",
    });
  });

  it("reports an unreachable server as a network error", async () => {
    mockFetch(() => new TypeError("Failed to fetch"));
    expect((await caught(api.listDocuments())).code).toBe("NETWORK_ERROR");
  });

  it("sends document_ids only when the question is scoped", async () => {
    const fetchMock = mockFetch(() => json({}));
    await api.ask("¿Qué cubre?", []);
    await api.ask("¿Qué cubre?", ["doc-1"]);

    const sentBody = (call: number) => JSON.parse(String(fetchMock.mock.calls[call]?.[1]?.body));
    expect(sentBody(0)).toEqual({ question: "¿Qué cubre?" });
    expect(sentBody(1)).toEqual({ question: "¿Qué cubre?", document_ids: ["doc-1"] });
  });

  it("links a citation to its page in the browser's PDF viewer", () => {
    expect(documentFileUrl("doc-1")).toBe("/api/v1/documents/doc-1/file");
    expect(documentFileUrl("doc-1", 3)).toBe("/api/v1/documents/doc-1/file#page=3");
  });
});
