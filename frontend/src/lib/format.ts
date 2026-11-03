import type { IngestionStage } from "../api/types";

const decimal = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 2 });
const integer = new Intl.NumberFormat("es-ES");

export function formatPages(start: number, end: number): string {
  return start === end ? `p. ${start}` : `pp. ${start}–${end}`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${decimal.format(bytes / (1024 * 1024))} MB`;
}

export const formatDecimal = (value: number | null): string =>
  value === null ? "—" : decimal.format(value);

export const formatInteger = (value: number | null): string =>
  value === null ? "—" : integer.format(value);

export const STAGE_LABELS: Record<IngestionStage, string> = {
  extracting: "Extrayendo texto",
  chunking: "Dividiendo en fragmentos",
  embedding: "Calculando embeddings",
  indexing: "Indexando",
};

/** "Artículo 4. Daños por agua" when known, otherwise the pages. */
export function describeLocation(
  documentTitle: string,
  version: number,
  pageStart: number,
  pageEnd: number,
  section: string | null,
): string {
  return [documentTitle, `v${version}`, formatPages(pageStart, pageEnd), section]
    .filter(Boolean)
    .join(" · ");
}
