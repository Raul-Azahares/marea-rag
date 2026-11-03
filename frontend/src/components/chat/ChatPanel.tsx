import { LoaderCircle, MessageSquareText, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { FragmentRef, QueryResponse } from "../../api/types";
import { traceUrl } from "../../config";
import { AnswerCard } from "./AnswerCard";
import { Composer } from "./Composer";

const SUGGESTIONS = [
  "¿La póliza cubre daños por agua en segunda vivienda?",
  "¿Qué franquicia se aplica a los daños por agua?",
  "¿En qué plazo hay que comunicar un siniestro?",
  "¿La asistencia en viaje funciona desde el kilómetro 0?",
];

type Turn = { id: number; question: string } & (
  | { status: "pending" }
  | { status: "done"; response: QueryResponse }
  | { status: "error"; error: ApiError }
);

interface Props {
  /** Below lg only one panel is shown at a time. */
  mobileHidden?: boolean;
  readyCount: number;
  scopeIds: string[];
  scopeLabel: string | null;
  onClearScope: () => void;
  onOpenFragment: (fragment: FragmentRef) => void;
}

export function ChatPanel({
  mobileHidden = false,
  readyCount,
  scopeIds,
  scopeLabel,
  onClearScope,
  onOpenFragment,
}: Props) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const lastId = useRef(0);
  const lastTurn = useRef<HTMLDivElement>(null);
  const waiting = turns.some((turn) => turn.status === "pending");
  const canAsk = !waiting && readyCount > 0;

  // Each question is sent on its own (no conversation memory): answers stay traceable to the
  // documents alone and a follow-up can never inherit an unverified claim.
  async function ask(question: string) {
    const id = ++lastId.current;
    setTurns((previous) => [...previous, { id, question, status: "pending" }]);
    let settled: Turn;
    try {
      settled = { id, question, status: "done", response: await api.ask(question, scopeIds) };
    } catch (error) {
      const apiError =
        error instanceof ApiError ? error : new ApiError("Error inesperado.", 0, "UNKNOWN", null);
      settled = { id, question, status: "error", error: apiError };
    }
    setTurns((previous) => previous.map((turn) => (turn.id === id ? settled : turn)));
  }

  // Bring the latest turn into view when it is asked and again when its answer arrives
  // (by then the content is tall enough to show the answer from its first line).
  const latestStatus = turns.at(-1)?.status;
  useEffect(() => {
    const smooth = !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    lastTurn.current?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
  }, [turns.length, latestStatus]);

  return (
    <section
      aria-labelledby="chat-title"
      className={`${mobileHidden ? "hidden lg:flex" : "flex"} min-h-0 flex-1 flex-col`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-surface px-4 py-3">
        <h2 id="chat-title" className="text-base font-semibold">
          Preguntas
        </h2>
        {scopeLabel ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-primary-soft py-1 pr-1 pl-2.5 text-xs text-primary">
            Solo en: {scopeLabel}
            <button
              type="button"
              onClick={onClearScope}
              aria-label="Quitar el filtro de documentos"
              className="rounded-full p-0.5 hover:bg-primary hover:text-on-primary"
            >
              <X className="size-3" aria-hidden />
            </button>
          </span>
        ) : (
          <span className="text-xs text-muted">En todos los documentos vigentes</span>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
        <div className="mx-auto max-w-3xl space-y-6">
          {turns.length === 0 ? (
            <Welcome readyCount={readyCount} disabled={!canAsk} onPick={(q) => void ask(q)} />
          ) : (
            turns.map((turn, index) => (
              <div
                key={turn.id}
                ref={index === turns.length - 1 ? lastTurn : undefined}
                className="scroll-mt-4"
              >
                <TurnView
                  turn={turn}
                  onOpenFragment={onOpenFragment}
                  onRetry={() => void ask(turn.question)}
                  retryDisabled={!canAsk}
                />
              </div>
            ))
          )}
        </div>
      </div>

      <Composer
        disabled={!canAsk}
        hint={readyCount === 0 ? "Sube y procesa al menos un documento para poder preguntar." : undefined}
        onSubmit={(question) => void ask(question)}
      />
    </section>
  );
}

function Welcome({
  readyCount,
  disabled,
  onPick,
}: {
  readyCount: number;
  disabled: boolean;
  onPick: (question: string) => void;
}) {
  return (
    <div className="space-y-5 py-8 text-center">
      <MessageSquareText className="mx-auto size-8 text-primary" aria-hidden />
      <div className="mx-auto max-w-xl space-y-1.5">
        <p className="font-medium">Pregunta sobre las pólizas cargadas</p>
        <p className="text-sm text-muted">
          Respondo solo con lo que dicen los documentos y cito cada afirmación. Cada pregunta se
          responde por separado, así que incluye el contexto necesario.
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((question) => (
          <button
            key={question}
            type="button"
            disabled={disabled}
            onClick={() => onPick(question)}
            className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            {question}
          </button>
        ))}
      </div>
      {readyCount === 0 && (
        <p className="text-xs text-muted">Aún no hay documentos listos para consultar.</p>
      )}
    </div>
  );
}

function TurnView({
  turn,
  onOpenFragment,
  onRetry,
  retryDisabled,
}: {
  turn: Turn;
  onOpenFragment: (fragment: FragmentRef) => void;
  onRetry: () => void;
  retryDisabled: boolean;
}) {
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-sm whitespace-pre-wrap text-on-primary">
          {turn.question}
        </p>
      </div>
      {turn.status === "pending" && <Thinking />}
      {turn.status === "done" && <AnswerCard response={turn.response} onOpenFragment={onOpenFragment} />}
      {turn.status === "error" && (
        <div role="alert" className="space-y-2 rounded-xl bg-danger-soft p-4 text-sm">
          <p className="font-medium text-danger">No se pudo responder</p>
          <p>{turn.error.message}</p>
          {turn.error.traceId && (
            <p className="text-xs text-muted">
              Referencia para soporte:{" "}
              <a
                href={traceUrl(turn.error.traceId)}
                target="_blank"
                rel="noreferrer"
                className="font-mono break-all hover:underline"
              >
                {turn.error.traceId}
              </a>
            </p>
          )}
          <button
            type="button"
            onClick={onRetry}
            disabled={retryDisabled}
            className="rounded-md border border-line bg-surface px-2.5 py-1 text-xs hover:bg-sunk disabled:opacity-50"
          >
            Volver a preguntar
          </button>
        </div>
      )}
    </div>
  );
}

function Thinking() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <p role="status" className="flex items-center gap-2 text-sm text-muted">
      <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
      Buscando en los documentos y verificando las citas…
      {seconds >= 3 && <span className="tabular-nums">{seconds} s</span>}
    </p>
  );
}
