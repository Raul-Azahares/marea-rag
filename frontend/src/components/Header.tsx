import { Activity, CodeXml, ListChecks } from "lucide-react";

import { FLOWER_URL, JAEGER_URL } from "../config";

const TOOLS = [
  { label: "API", href: "/api/docs", Icon: CodeXml },
  { label: "Trazas", href: JAEGER_URL, Icon: Activity },
  { label: "Colas", href: FLOWER_URL, Icon: ListChecks },
];

export function Header() {
  return (
    <header className="flex items-center justify-between gap-4 border-b border-line bg-surface px-4 py-3 sm:px-6">
      <div className="flex items-center gap-3">
        <img src="/favicon.svg" alt="" className="size-9" />
        <div className="leading-tight">
          <p className="font-semibold tracking-tight">Marea Seguros</p>
          <p className="text-sm text-muted">Asistente de pólizas</p>
        </div>
      </div>
      <nav aria-label="Herramientas técnicas" className="flex flex-wrap gap-1 text-sm">
        {TOOLS.map(({ label, href, Icon }) => (
          <a
            key={label}
            href={href}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-muted hover:bg-sunk hover:text-ink"
          >
            <Icon className="size-4" aria-hidden />
            <span className="sr-only sm:not-sr-only">{label}</span>
          </a>
        ))}
      </nav>
    </header>
  );
}
