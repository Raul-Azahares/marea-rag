import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { hasActiveIngestion } from "../lib/documents";
import { api } from "./client";

const DOCUMENTS_KEY = ["documents"] as const;
const POLL_MS = 1500;

/**
 * Document list, polled only while something is being ingested: progress updates every
 * 1.5 s during an ingestion and zero requests when everything is settled. Polling is
 * stateless and works through any proxy; SSE would need a Redis pub/sub fan-out for a few
 * seconds of latency gained.
 */
export function useDocuments() {
  return useQuery({
    queryKey: DOCUMENTS_KEY,
    queryFn: api.listDocuments,
    refetchInterval: (query) =>
      hasActiveIngestion(query.state.data?.items ?? []) ? POLL_MS : false,
  });
}

function useInvalidateDocuments() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: DOCUMENTS_KEY });
}

export function useUploadDocument() {
  const invalidate = useInvalidateDocuments();
  return useMutation({ mutationFn: api.uploadDocument, onSettled: invalidate });
}

export function useUploadVersion() {
  const invalidate = useInvalidateDocuments();
  return useMutation({
    mutationFn: ({ documentId, file }: { documentId: string; file: File }) =>
      api.uploadVersion(documentId, file),
    onSettled: invalidate,
  });
}

export function useRetryDocument() {
  const invalidate = useInvalidateDocuments();
  return useMutation({ mutationFn: api.retryDocument, onSettled: invalidate });
}

/** Chunks never change once written, so a fetched fragment stays cached for good. */
export function useChunk(chunkId: string | null) {
  return useQuery({
    queryKey: ["chunk", chunkId],
    queryFn: () => api.getChunk(chunkId ?? ""),
    enabled: chunkId !== null,
    staleTime: Infinity,
  });
}
