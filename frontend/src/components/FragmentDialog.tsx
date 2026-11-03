import { ExternalLink, LoaderCircle, ShieldAlert, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { documentFileUrl } from "../api/client";
import { useChunk } from "../api/hooks";
import type { FragmentRef } from "../api/types";
import { formatPages } from "../lib/format";
import { highlightSegments } from "../lib/highlight";

interface Props {
  fragment: FragmentRef | null;
  onClose: () => void;
}

/** The exact text a citation points to, with the quote highlighted. A native modal
 *  <dialog> gives focus trapping, Escape to close and an inert background for free. */
export function FragmentDialog({ fragment, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const highlight = useRef<HTMLElement>(null);
  // Close on a click that starts and ends on the backdrop: selecting text and releasing the
  // mouse outside must not close the viewer.
  const pressedBackdrop = useRef(false);
  const chunk = useChunk(fragment?.chunkId ?? null);
  const data = chunk.data;
  const segments = data ? highlightSegments(data.content, fragment?.quote) : [];
  const quoteFound = segments.some((segment) => segment.highlighted);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (fragment && !element.open) element.showModal();
    if (!fragment && element.open) element.close();
  }, [fragment]);

  useEffect(() => {
    highlight.current?.scrollIntoView({ block: "center" });
  }, [data, fragment?.quote]);

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      onPointerDown={(event) => {
        pressedBackdrop.current = event.target === dialog.current;
      }}
      onClick={(event) => {
        if (pressedBackdrop.current && event.target === dialog.current) dialog.current?.close();
      }}
      aria-labelledby="fragment-title"
      className="m-auto max-h-[min(40rem,calc(100dvh-2rem))] w-[min(44rem,calc(100vw-2rem))] rounded-xl border border-line bg-surface p-0 text-ink shadow-2xl"
    >
      <div className="flex max-h-[inherit] flex-col">
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0 space-y-0.5">
            <p className="text-xs text-muted">Fragmento fuente</p>
            <h2 id="fragment-title" className="font-semibold">
              {data?.section ?? (chunk.isLoading ? "Cargando…" : "Fragmento")}
            </h2>
            {data && (
              <p className="text-sm text-muted">
                {data.document_title} · v{data.document_version} ·{" "}
                {formatPages(data.page_start, data.page_end)}
                {data.document_superseded && (
                  <span className="ml-2 rounded-full bg-sunk px-2 py-0.5 text-xs">versión reemplazada</span>
                )}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={() => dialog.current?.close()}
            aria-label="Cerrar"
            className="rounded-md p-1.5 text-muted hover:bg-sunk hover:text-ink"
          >
            <X className="size-4" aria-hidden />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {chunk.isLoading && (
            <p className="flex items-center gap-2 text-sm text-muted">
              <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
              Cargando el fragmento…
            </p>
          )}
          {chunk.error && <p className="text-sm text-danger">{chunk.error.message}</p>}
          {data && (
            <>
              {data.flags.includes("suspected_prompt_injection") && (
                <p className="mb-3 flex gap-2 rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">
                  <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                  Este fragmento contiene texto con apariencia de instrucciones (posible inyección).
                  El asistente lo trata como un dato, nunca como una orden.
                </p>
              )}
              <p className="text-sm leading-relaxed whitespace-pre-wrap">
                {segments.map((segment, index) =>
                  segment.highlighted ? (
                    <mark key={index} ref={highlight} className="rounded bg-mark px-0.5 text-mark-ink">
                      {segment.text}
                    </mark>
                  ) : (
                    <span key={index}>{segment.text}</span>
                  ),
                )}
              </p>
              {fragment?.quote && !quoteFound && (
                <p className="mt-3 text-xs text-muted">
                  La cita coincide de forma aproximada con este texto, por eso no aparece resaltada.
                </p>
              )}
            </>
          )}
        </div>

        {data && (
          <footer className="flex justify-end border-t border-line px-5 py-3">
            <a
              href={documentFileUrl(data.document_id, data.page_start)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-on-primary hover:bg-primary-strong"
            >
              <ExternalLink className="size-4" aria-hidden />
              Abrir el PDF en la página {data.page_start}
            </a>
          </footer>
        )}
      </div>
    </dialog>
  );
}
