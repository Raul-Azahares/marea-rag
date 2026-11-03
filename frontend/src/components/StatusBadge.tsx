import { LoaderCircle } from "lucide-react";

import type { DocumentStatus } from "../api/types";

const STYLES: Record<DocumentStatus, { label: string; className: string }> = {
  pending: { label: "En cola", className: "bg-sunk text-muted" },
  processing: { label: "Procesando", className: "bg-primary-soft text-primary" },
  ready: { label: "Listo", className: "bg-ok-soft text-ok" },
  failed: { label: "Error", className: "bg-danger-soft text-danger" },
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const { label, className } = STYLES[status];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${className}`}
    >
      {status === "processing" && (
        <LoaderCircle className="size-3 animate-spin motion-reduce:animate-none" aria-hidden />
      )}
      {label}
    </span>
  );
}
