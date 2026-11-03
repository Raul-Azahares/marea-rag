import type { DocumentOut } from "../api/types";

export const isActive = (document: DocumentOut): boolean =>
  document.status === "pending" || document.status === "processing";

export const hasActiveIngestion = (documents: DocumentOut[]): boolean =>
  documents.some(isActive);

/** All versions of one logical document (same lineage), newest first. */
export interface DocumentGroup {
  lineageId: string;
  title: string;
  versions: DocumentOut[];
  latest: DocumentOut;
  /** The version questions are answered from: READY and not superseded. */
  current: DocumentOut | null;
}

export function groupByLineage(documents: DocumentOut[]): DocumentGroup[] {
  const byLineage = new Map<string, DocumentOut[]>();
  for (const document of documents) {
    byLineage.set(document.lineage_id, [...(byLineage.get(document.lineage_id) ?? []), document]);
  }
  const groups: DocumentGroup[] = [];
  for (const [lineageId, versions] of byLineage) {
    versions.sort((a, b) => b.version - a.version);
    const latest = versions[0];
    if (!latest) continue;
    groups.push({
      lineageId,
      title: latest.title,
      versions,
      latest,
      current: versions.find((v) => v.status === "ready" && !v.superseded) ?? null,
    });
  }
  // Most recently uploaded first.
  return groups.sort((a, b) => b.latest.created_at.localeCompare(a.latest.created_at));
}
