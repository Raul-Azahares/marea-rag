import { SendHorizontal } from "lucide-react";
import { useId, useState, type FormEvent, type KeyboardEvent } from "react";

const MAX_LENGTH = 1000; // same limit as the API

interface Props {
  disabled: boolean;
  hint?: string;
  onSubmit: (question: string) => void;
}

export function Composer({ disabled, hint, onSubmit }: Props) {
  const id = useId();
  const [value, setValue] = useState("");
  const question = value.trim();
  const canSend = !disabled && question.length >= 3;

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!canSend) return;
    onSubmit(question);
    setValue("");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter adds a line; never while an IME composition is open.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form onSubmit={submit} className="border-t border-line bg-surface px-4 py-3">
      <div className="mx-auto max-w-3xl">
        <label htmlFor={id} className="sr-only">
          Pregunta
        </label>
        <div className="flex items-end gap-2 rounded-xl border border-line bg-bg px-3 py-2 focus-within:border-primary">
          <textarea
            id={id}
            rows={2}
            maxLength={MAX_LENGTH}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={handleKeyDown}
            aria-describedby={`${id}-help`}
            placeholder="Escribe tu pregunta sobre las pólizas…"
            className="max-h-40 min-h-10 flex-1 resize-none bg-transparent text-sm outline-none placeholder:text-muted"
          />
          <button
            type="submit"
            disabled={!canSend}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-on-primary hover:bg-primary-strong disabled:cursor-not-allowed disabled:opacity-50"
          >
            <SendHorizontal className="size-4" aria-hidden />
            Preguntar
          </button>
        </div>
        <p id={`${id}-help`} className="mt-1.5 flex justify-between gap-3 text-xs text-muted">
          {hint ? (
            <span>{hint}</span>
          ) : (
            // Keyboard shortcuts mean nothing on a touch keyboard.
            <span className="hidden sm:inline">Intro para enviar · Mayús + Intro para una línea nueva</span>
          )}
          <span className="ml-auto tabular-nums">
            {value.length}/{MAX_LENGTH}
          </span>
        </p>
      </div>
    </form>
  );
}
