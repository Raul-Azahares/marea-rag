import { FileText, RotateCcw, X } from "lucide-react";
import { useRef, useState } from "react";

import { useRetryDocument, useUploadDocument, useUploadVersion } from "../../api/hooks";
import { isActive, type DocumentGroup } from "../../lib/documents";
import { describeUpload, type NoticeTone } from "../../lib/upload";
import { DocumentCard } from "./DocumentCard";
import { UploadDropzone } from "./UploadDropzone";

interface Notice {
  id: number;
  name: string;
  tone: NoticeTone;
  text: string;
}

const TONE_CLASSES: Record<NoticeTone, string> = {
  info: "text-muted",
  ok: "text-ok",
  warn: "text-warn",
  error: "text-danger",
};

const messageOf = (error: unknown): string =>
  error instanceof Error ? error.message : "Error inesperado.";

interface Props {
  /** Below lg only one panel is shown at a time. */
  mobileHidden?: boolean;
  groups: DocumentGroup[];
  isLoading: boolean;
  loadError: Error | null;
  onReload: () => void;
  selected: ReadonlySet<string>;
  onToggleSelected: (lineageId: string) => void;
}

export function DocumentsPanel({
  mobileHidden = false,
  groups,
  isLoading,
  loadError,
  onReload,
  selected,
  onToggleSelected,
}: Props) {
  const upload = useUploadDocument();
  const uploadVersion = useUploadVersion();
  const retry = useRetryDocument();
  const [notices, setNotices] = useState<Notice[]>([]);
  const lastNoticeId = useRef(0);

  function pushNotice(name: string, tone: NoticeTone, text: string): number {
    const id = ++lastNoticeId.current;
    setNotices((previous) => [{ id, name, tone, text }, ...previous].slice(0, 5));
    return id;
  }

  function updateNotice(id: number, tone: NoticeTone, text: string) {
    setNotices((previous) => previous.map((n) => (n.id === id ? { ...n, tone, text } : n)));
  }

  async function handleFiles(files: File[]) {
    // One at a time: predictable order and gentle on the server.
    for (const file of files) {
      const id = pushNotice(file.name, "info", "Subiendo…");
      try {
        const { tone, text } = describeUpload(await upload.mutateAsync(file));
        updateNotice(id, tone, text);
      } catch (error) {
        updateNotice(id, "error", messageOf(error));
      }
    }
  }

  async function handleNewVersion(documentId: string, file: File) {
    const id = pushNotice(file.name, "info", "Subiendo nueva versión…");
    try {
      const result = await uploadVersion.mutateAsync({ documentId, file });
      const { tone, text } = describeUpload(result);
      updateNotice(id, tone, result.deduplicated ? text : `Versión ${result.version}. ${text}`);
    } catch (error) {
      updateNotice(id, "error", messageOf(error));
    }
  }

  function handleRetry(documentId: string) {
    retry.mutate(documentId, {
      onError: (error) => pushNotice("Reintento", "error", messageOf(error)),
    });
  }

  const inProgress = groups.filter((group) => group.versions.some(isActive)).length;

  return (
    <section
      aria-labelledby="documents-title"
      className={`${mobileHidden ? "hidden lg:flex" : "flex"} min-h-0 flex-1 flex-col lg:border-r lg:border-line`}
    >
      <div className="space-y-3 border-b border-line bg-surface p-4">
        <div className="flex items-baseline justify-between gap-2">
          <h2 id="documents-title" className="text-base font-semibold">
            Documentos
          </h2>
          <p className="text-xs text-muted" aria-live="polite">
            {groups.length} {groups.length === 1 ? "documento" : "documentos"}
            {inProgress > 0 && ` · ${inProgress} en proceso`}
          </p>
        </div>
        <UploadDropzone onFiles={(files) => void handleFiles(files)} />
        {notices.length > 0 && (
          <ul aria-label="Resultado de las subidas" aria-live="polite" className="space-y-1">
            {notices.map((notice) => (
              <li key={notice.id} className="flex items-start gap-2 text-xs">
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{notice.name}</span>
                  <span className={` ${TONE_CLASSES[notice.tone]}`}> · {notice.text}</span>
                </span>
                <button
                  type="button"
                  aria-label={`Descartar el aviso de ${notice.name}`}
                  onClick={() => setNotices((previous) => previous.filter((n) => n.id !== notice.id))}
                  className="rounded p-0.5 text-muted hover:bg-sunk hover:text-ink"
                >
                  <X className="size-3" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-4">
        {isLoading ? (
          <p className="text-sm text-muted">Cargando documentos…</p>
        ) : loadError ? (
          <div role="alert" className="space-y-2 rounded-lg bg-danger-soft p-3 text-sm">
            <p className="text-danger">No se pudo cargar la lista: {loadError.message}</p>
            <button
              type="button"
              onClick={onReload}
              className="inline-flex items-center gap-1 rounded-md border border-line bg-surface px-2 py-1 text-xs hover:bg-sunk"
            >
              <RotateCcw className="size-3" aria-hidden />
              Reintentar
            </button>
          </div>
        ) : groups.length === 0 ? (
          <div className="space-y-1.5 py-6 text-center text-sm text-muted">
            <FileText className="mx-auto size-6" aria-hidden />
            <p>Todavía no hay documentos.</p>
            <p className="text-xs">
              Sube un PDF de póliza para empezar. Hay ejemplos sintéticos en la carpeta{" "}
              <code className="rounded bg-sunk px-1">samples/</code>.
            </p>
          </div>
        ) : (
          groups.map((group) => (
            <DocumentCard
              key={group.lineageId}
              group={group}
              selected={selected.has(group.lineageId)}
              onToggleSelected={onToggleSelected}
              onRetry={handleRetry}
              onNewVersion={(documentId, file) => void handleNewVersion(documentId, file)}
            />
          ))
        )}
      </div>
    </section>
  );
}
