import type { DocumentUploadOut } from "../api/types";
import { MAX_UPLOAD_MB } from "../config";

/** Quick client-side screening for immediate feedback. The server re-validates everything
 *  (magic bytes, size, page count, encryption), so this is a convenience, not a control. */
export function rejectionReason(file: File): string | null {
  const looksLikePdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!looksLikePdf) return "No es un PDF.";
  if (file.size === 0) return "El archivo está vacío.";
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `Supera el límite de ${MAX_UPLOAD_MB} MB.`;
  return null;
}

export type NoticeTone = "info" | "ok" | "warn" | "error";

/** What happened to an upload, in words an agent understands. */
export function describeUpload(result: DocumentUploadOut): { tone: NoticeTone; text: string } {
  if (result.deduplicated) {
    return { tone: "info", text: "Ya estaba subido: se reutiliza el documento existente." };
  }
  if (!result.queued) {
    // The row is saved as PENDING; the reconciler enqueues it once the broker is back.
    return {
      tone: "warn",
      text: "Guardado. La cola no responde ahora; se procesará automáticamente.",
    };
  }
  // A snapshot of the upload, not live status: the document card shows the progress.
  return { tone: "ok", text: "Subido y en cola para procesar." };
}
