/** Links to the operator tools. Baked in at build time (Docker build args); local defaults. */
export const JAEGER_URL = import.meta.env.VITE_JAEGER_URL ?? "http://localhost:16686";
export const FLOWER_URL = import.meta.env.VITE_FLOWER_URL ?? "http://localhost:5555";

/** Must match MAX_UPLOAD_MB on the backend; the server enforces it regardless. */
export const MAX_UPLOAD_MB = 20;

export const traceUrl = (traceId: string): string => `${JAEGER_URL}/trace/${traceId}`;
