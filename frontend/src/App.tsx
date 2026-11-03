import { useMemo, useState } from "react";

import { useDocuments } from "./api/hooks";
import type { FragmentRef } from "./api/types";
import { ChatPanel } from "./components/chat/ChatPanel";
import { DocumentsPanel } from "./components/documents/DocumentsPanel";
import { FragmentDialog } from "./components/FragmentDialog";
import { Header } from "./components/Header";
import { groupByLineage } from "./lib/documents";

type MobileView = "documents" | "chat";

export function App() {
  const documents = useDocuments();
  const groups = useMemo(() => groupByLineage(documents.data?.items ?? []), [documents.data]);
  // Lineages the agent ticked to restrict questions to; empty = every current document.
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [fragment, setFragment] = useState<FragmentRef | null>(null);
  // Below the lg breakpoint the two panels do not fit side by side: one at a time.
  const [mobileView, setMobileView] = useState<MobileView>("chat");

  const readyGroups = groups.filter((group) => group.current !== null);
  const scoped = readyGroups.filter((group) => selected.has(group.lineageId));
  const scopeIds = scoped.flatMap((group) => (group.current ? [group.current.id] : []));
  const scopeLabel =
    scoped.length === 0 ? null : scoped.length === 1 ? (scoped[0]?.title ?? null) : `${scoped.length} documentos`;

  function toggleSelected(lineageId: string) {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(lineageId)) {
        next.delete(lineageId);
      } else {
        next.add(lineageId);
      }
      return next;
    });
  }

  return (
    <div className="flex h-full flex-col">
      <Header />
      <nav aria-label="Secciones" className="flex border-b border-line bg-surface lg:hidden">
        {(
          [
            ["documents", `Documentos (${groups.length})`],
            ["chat", "Preguntas"],
          ] as const
        ).map(([view, label]) => (
          <button
            key={view}
            type="button"
            aria-pressed={mobileView === view}
            onClick={() => setMobileView(view)}
            className={`flex-1 border-b-2 py-2.5 text-sm font-medium ${
              mobileView === view ? "border-primary text-primary" : "border-transparent text-muted"
            }`}
          >
            {label}
          </button>
        ))}
      </nav>
      <main className="flex min-h-0 flex-1 flex-col lg:grid lg:grid-cols-[minmax(320px,400px)_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)]">
        <DocumentsPanel
          mobileHidden={mobileView !== "documents"}
          groups={groups}
          isLoading={documents.isLoading}
          loadError={documents.error}
          onReload={() => void documents.refetch()}
          selected={selected}
          onToggleSelected={toggleSelected}
        />
        <ChatPanel
          mobileHidden={mobileView !== "chat"}
          readyCount={readyGroups.length}
          scopeIds={scopeIds}
          scopeLabel={scopeLabel}
          onClearScope={() => setSelected(new Set())}
          onOpenFragment={setFragment}
        />
      </main>
      <FragmentDialog fragment={fragment} onClose={() => setFragment(null)} />
    </div>
  );
}
