import {
  CircleAlert,
  Info,
  ShieldAlert,
  TriangleAlert,
  Unplug,
  type LucideIcon,
} from "lucide-react";
import { useId } from "react";

import type {
  AnswerStatus,
  Citation,
  Confidence,
  FragmentRef,
  QueryResponse,
  RetrievedFragment,
} from "../../api/types";
import { traceUrl } from "../../config";
import { describeLocation, formatDecimal, formatInteger } from "../../lib/format";

type Tone = "warn" | "neutral" | "danger";

const BANNERS: Partial<Record<AnswerStatus, { title: string; body: string; tone: Tone; Icon: LucideIcon }>> = {
  partial: {
    title: "Respuesta parcial",
    body: "Los documentos solo cubren parte de la pregunta.",
    tone: "warn",
    Icon: TriangleAlert,
  },
  conflicting_evidence: {
    title: "Fuentes contradictorias",
    body: "Los documentos no coinciden. Revisa las citas antes de responder al cliente.",
    tone: "warn",
    Icon: CircleAlert,
  },
  insufficient_evidence: {
    title: "Sin evidencia suficiente",
    body: "Los documentos no contienen información que permita responder con seguridad.",
    tone: "neutral",
    Icon: Info,
  },
  llm_unavailable: {
    title: "Asistente no disponible",
    body: "El modelo no respondió. Puedes revisar los fragmentos encontrados.",
    tone: "danger",
    Icon: Unplug,
  },
};

const TONE_CLASSES: Record<Tone, string> = {
  warn: "bg-warn-soft text-warn",
  neutral: "bg-sunk text-ink",
  danger: "bg-danger-soft text-danger",
};

const CONFIDENCE: Record<Exclude<Confidence, "none">, { label: string; className: string }> = {
  high: { label: "Confianza alta", className: "bg-ok-soft text-ok" },
  medium: { label: "Confianza media", className: "bg-primary-soft text-primary" },
  low: { label: "Confianza baja", className: "bg-warn-soft text-warn" },
};

interface Props {
  response: QueryResponse;
  onOpenFragment: (fragment: FragmentRef) => void;
}

export function AnswerCard({ response, onOpenFragment }: Props) {
  const banner = BANNERS[response.status];
  const citationsByRef = new Map(response.citations.map((c) => [c.ref, c]));
  // With no usable answer, the retrieved fragments are what the agent should look at.
  const reviewFirst =
    response.status === "insufficient_evidence" || response.status === "llm_unavailable";

  return (
    <article
      aria-label="Respuesta del asistente"
      className="space-y-4 rounded-xl border border-line bg-surface p-4 shadow-sm"
    >
      {banner && (
        <div className={`flex gap-2.5 rounded-lg px-3 py-2.5 text-sm ${TONE_CLASSES[banner.tone]}`}>
          <banner.Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
          <div>
            <p className="font-medium">{banner.title}</p>
            <p className="opacity-90">{banner.body}</p>
          </div>
        </div>
      )}

      {response.statements.length > 0 ? (
        <div className="space-y-2 leading-relaxed">
          {response.statements.map((statement, index) => (
            <p key={index}>
              {statement.text}{" "}
              {statement.citation_refs.map((ref) => {
                const citation = citationsByRef.get(ref);
                return citation ? (
                  <CitationMarker key={ref} citation={citation} onOpen={onOpenFragment} />
                ) : null;
              })}
            </p>
          ))}
        </div>
      ) : (
        <p className="leading-relaxed">{response.answer}</p>
      )}

      {response.confidence !== "none" && (
        <span
          className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${CONFIDENCE[response.confidence].className}`}
        >
          {CONFIDENCE[response.confidence].label}
        </span>
      )}

      {response.citations.length > 0 && (
        <CitationList citations={response.citations} onOpen={onOpenFragment} />
      )}

      {response.warnings.length > 0 && (
        <ul className="space-y-1 text-xs text-warn">
          {response.warnings.map((warning) => (
            <li key={warning} className="flex gap-1.5">
              <ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {warning}
            </li>
          ))}
        </ul>
      )}

      {response.retrieved.length > 0 && (
        <RetrievedList
          fragments={response.retrieved}
          defaultOpen={reviewFirst}
          onOpen={onOpenFragment}
        />
      )}

      <TechnicalDetails response={response} />
    </article>
  );
}

function CitationMarker({
  citation,
  onOpen,
}: {
  citation: Citation;
  onOpen: (fragment: FragmentRef) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen({ chunkId: citation.chunk_id, quote: citation.quote })}
      aria-label={`Ver cita ${citation.ref}: ${citation.document_title}`}
      className="mx-0.5 inline-flex min-w-5 items-center justify-center rounded bg-primary-soft px-1 align-super text-[11px] leading-4 font-semibold text-primary hover:bg-primary hover:text-on-primary"
    >
      {citation.ref}
    </button>
  );
}

function CitationList({
  citations,
  onOpen,
}: {
  citations: Citation[];
  onOpen: (fragment: FragmentRef) => void;
}) {
  const headingId = useId();
  return (
    <div>
      <h3 id={headingId} className="mb-1.5 text-xs font-semibold tracking-wide text-muted uppercase">
        Fuentes
      </h3>
      <ol aria-labelledby={headingId} className="space-y-2">
        {citations.map((citation) => (
          <li key={citation.ref}>
            <button
              type="button"
              onClick={() => onOpen({ chunkId: citation.chunk_id, quote: citation.quote })}
              className="w-full rounded-lg border border-line p-2.5 text-left hover:border-primary"
            >
              <span className="flex items-start gap-2 text-xs text-muted">
                <span className="rounded bg-primary-soft px-1.5 font-semibold text-primary">
                  {citation.ref}
                </span>
                <span className="min-w-0 flex-1">
                  {describeLocation(
                    citation.document_title,
                    citation.document_version,
                    citation.page_start,
                    citation.page_end,
                    citation.section,
                  )}
                </span>
                {!citation.exact_match && (
                  <span title="La cita coincide de forma aproximada" className="shrink-0">
                    aprox.
                  </span>
                )}
              </span>
              <span className="mt-1.5 block text-sm">
                <mark className="rounded bg-mark px-0.5 text-mark-ink">«{citation.quote}»</mark>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

function RetrievedList({
  fragments,
  defaultOpen,
  onOpen,
}: {
  fragments: RetrievedFragment[];
  defaultOpen: boolean;
  onOpen: (fragment: FragmentRef) => void;
}) {
  return (
    <details open={defaultOpen}>
      <summary className="cursor-pointer text-xs font-medium text-muted hover:text-ink">
        Fragmentos consultados ({fragments.length})
      </summary>
      <ul className="mt-2 space-y-1">
        {fragments.map((fragment) => (
          <li key={fragment.chunk_id}>
            <button
              type="button"
              onClick={() => onOpen({ chunkId: fragment.chunk_id })}
              className="w-full rounded-md px-2 py-1.5 text-left hover:bg-sunk"
            >
              <span className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="font-medium">
                  {describeLocation(
                    fragment.document_title,
                    fragment.document_version,
                    fragment.page_start,
                    fragment.page_end,
                    fragment.section,
                  )}
                </span>
                {fragment.cited && (
                  <span className="rounded-full bg-primary-soft px-1.5 text-primary">citado</span>
                )}
                {fragment.flagged && (
                  <span className="rounded-full bg-warn-soft px-1.5 text-warn">posible inyección</span>
                )}
                <span className="ml-auto font-mono text-muted tabular-nums">
                  similitud {formatDecimal(fragment.similarity)}
                </span>
              </span>
              <span className="mt-0.5 line-clamp-2 block text-xs text-muted">{fragment.preview}</span>
            </button>
          </li>
        ))}
      </ul>
    </details>
  );
}

function describeValidation({ validation }: QueryResponse): string {
  if (validation.attempts === 0) return "No hizo falta llamar al modelo";
  if (validation.passed) {
    return validation.attempts === 1
      ? "Aprobada a la primera"
      : `Aprobada tras ${validation.attempts} intentos`;
  }
  return validation.degraded ? "No aprobada: se omitió lo que no se pudo verificar" : "No aprobada";
}

function TechnicalDetails({ response }: { response: QueryResponse }) {
  const { validation, usage } = response;
  return (
    <details className="text-xs text-muted">
      <summary className="cursor-pointer font-medium hover:text-ink">Detalles técnicos</summary>
      <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1">
        <dt>Validación de citas</dt>
        <dd>{describeValidation(response)}</dd>
        {validation.issues.length > 0 && (
          <>
            <dt>Incidencias</dt>
            <dd>
              <ul className="list-disc pl-4">
                {validation.issues.map((issue, index) => (
                  <li key={index}>{issue.detail}</li>
                ))}
              </ul>
            </dd>
          </>
        )}
        <dt>Modelo</dt>
        <dd className="font-mono">{usage.model ?? "—"}</dd>
        <dt>Tokens</dt>
        <dd className="tabular-nums">
          {formatInteger(usage.input_tokens)} de entrada · {formatInteger(usage.output_tokens)} de salida
        </dd>
        <dt>Tiempo</dt>
        <dd className="tabular-nums">{formatInteger(response.latency_ms)} ms</dd>
        {response.trace_id && (
          <>
            <dt>Traza</dt>
            <dd>
              <a
                href={traceUrl(response.trace_id)}
                target="_blank"
                rel="noreferrer"
                className="font-mono break-all text-primary hover:underline"
              >
                {response.trace_id}
              </a>
            </dd>
          </>
        )}
      </dl>
    </details>
  );
}
