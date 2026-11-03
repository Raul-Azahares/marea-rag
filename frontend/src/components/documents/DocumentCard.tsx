import { ExternalLink, FilePlus2, RotateCcw } from "lucide-react";
import { useRef } from "react";

import { documentFileUrl } from "../../api/client";
import type { DocumentOut } from "../../api/types";
import { traceUrl } from "../../config";
import type { DocumentGroup } from "../../lib/documents";
import { formatBytes, formatInteger, STAGE_LABELS } from "../../lib/format";
import { StatusBadge } from "../StatusBadge";

interface Props {
  group: DocumentGroup;
  selected: boolean;
  onToggleSelected: (lineageId: string) => void;
  onRetry: (documentId: string) => void;
  onNewVersion: (documentId: string, file: File) => void;
}

export function DocumentCard({ group, selected, onToggleSelected, onRetry, onNewVersion }: Props) {
  const versionInput = useRef<HTMLInputElement>(null);
  const older = group.versions.slice(1);
  const viewable = group.current ?? group.latest;
  const titleId = `document-${group.lineageId}`;

  return (
    <article aria-labelledby={titleId} className="rounded-lg border border-line bg-surface p-3.5">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 id={titleId} className="truncate text-sm font-medium" title={group.title}>
            {group.title}
          </h3>
          <p className="truncate text-xs text-muted" title={group.latest.filename}>
            {group.latest.filename} · {formatBytes(group.latest.size_bytes)}
          </p>
        </div>
        {group.current && (
          <label
            className="flex shrink-0 cursor-pointer items-center gap-1.5 text-xs text-muted hover:text-ink"
            title="Responder solo con los documentos marcados"
          >
            <input
              type="checkbox"
              className="size-3.5 accent-primary"
              checked={selected}
              onChange={() => onToggleSelected(group.lineageId)}
            />
            Acotar
          </label>
        )}
      </header>

      <VersionRow document={group.latest} isCurrent={group.current?.id === group.latest.id} onRetry={onRetry} />

      {older.length > 0 && (
        <details className="mt-2.5">
          <summary className="cursor-pointer text-xs text-muted hover:text-ink">
            Versiones anteriores ({older.length})
          </summary>
          <div className="mt-1 border-l-2 border-line pl-3">
            {older.map((version) => (
              <VersionRow
                key={version.id}
                document={version}
                isCurrent={group.current?.id === version.id}
                onRetry={onRetry}
              />
            ))}
          </div>
        </details>
      )}

      <footer className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <a
          href={documentFileUrl(viewable.id)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-primary hover:underline"
        >
          <ExternalLink className="size-3.5" aria-hidden />
          Abrir PDF
        </a>
        <button
          type="button"
          onClick={() => versionInput.current?.click()}
          className="inline-flex items-center gap-1 text-primary hover:underline"
        >
          <FilePlus2 className="size-3.5" aria-hidden />
          Subir nueva versión
        </button>
        <input
          ref={versionInput}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          aria-label={`Nueva versión de ${group.title}`}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onNewVersion(group.latest.id, file);
            event.target.value = "";
          }}
        />
      </footer>
    </article>
  );
}

function VersionRow({
  document,
  isCurrent,
  onRetry,
}: {
  document: DocumentOut;
  isCurrent: boolean;
  onRetry: (documentId: string) => void;
}) {
  return (
    <div className="mt-2.5 space-y-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="rounded bg-sunk px-1.5 py-0.5 font-mono text-[11px] text-muted">
          v{document.version}
        </span>
        <StatusBadge status={document.status} />
        {isCurrent && (
          <span className="rounded-full bg-ok-soft px-2 py-0.5 text-[11px] font-medium text-ok">
            Vigente
          </span>
        )}
        {document.superseded && (
          <span className="rounded-full bg-sunk px-2 py-0.5 text-[11px] text-muted">Reemplazada</span>
        )}
        {document.ingest_trace_id && (
          <a
            href={traceUrl(document.ingest_trace_id)}
            target="_blank"
            rel="noreferrer"
            className="ml-auto text-[11px] text-muted hover:text-primary"
            title="Ver la traza de la ingesta en Jaeger"
          >
            Traza
          </a>
        )}
      </div>
      <VersionDetail document={document} onRetry={onRetry} />
    </div>
  );
}

function VersionDetail({
  document,
  onRetry,
}: {
  document: DocumentOut;
  onRetry: (documentId: string) => void;
}) {
  switch (document.status) {
    case "pending":
      return <p className="text-xs text-muted">Esperando turno en la cola…</p>;
    case "processing":
      return (
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-muted">
            <span>{document.stage ? STAGE_LABELS[document.stage] : "Procesando"}</span>
            <span className="tabular-nums">{document.progress} %</span>
          </div>
          <div
            role="progressbar"
            aria-label={`Progreso de ${document.title}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={document.progress}
            className="h-1.5 overflow-hidden rounded-full bg-sunk"
          >
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-500 motion-reduce:transition-none"
              style={{ width: `${document.progress}%` }}
            />
          </div>
          {document.error_message && <p className="text-xs text-warn">{document.error_message}</p>}
        </div>
      );
    case "ready":
      return (
        <p className="text-xs text-muted">
          {formatInteger(document.page_count)} págs · {formatInteger(document.chunk_count)} fragmentos
        </p>
      );
    case "failed":
      return (
        <div className="flex flex-wrap items-start justify-between gap-2">
          <p className="min-w-0 flex-1 text-xs text-danger">
            {document.error_message ?? "La ingesta falló."}
          </p>
          <button
            type="button"
            onClick={() => onRetry(document.id)}
            className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs hover:bg-sunk"
          >
            <RotateCcw className="size-3" aria-hidden />
            Reintentar
          </button>
        </div>
      );
  }
}
