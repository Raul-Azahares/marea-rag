import { describe, expect, it } from "vitest";

import { makeDocument } from "../test/fixtures";
import { groupByLineage, hasActiveIngestion } from "./documents";

describe("groupByLineage", () => {
  it("groups the versions of a document, newest first", () => {
    const v1 = makeDocument({ id: "v1", version: 1, superseded: true });
    const v2 = makeDocument({ id: "v2", version: 2, created_at: "2026-11-03T09:00:00Z" });

    const [group] = groupByLineage([v1, v2]);

    expect(group?.versions.map((v) => v.id)).toEqual(["v2", "v1"]);
    expect(group?.latest.id).toBe("v2");
    expect(group?.current?.id).toBe("v2");
  });

  it("keeps answering from the old version while the new one is being processed", () => {
    const v1 = makeDocument({ id: "v1", version: 1 });
    const v2 = makeDocument({ id: "v2", version: 2, status: "processing", progress: 40 });

    const [group] = groupByLineage([v2, v1]);

    expect(group?.latest.id).toBe("v2");
    expect(group?.current?.id).toBe("v1");
  });

  it("has no current version until one is ready", () => {
    const [group] = groupByLineage([makeDocument({ status: "failed" })]);
    expect(group?.current).toBeNull();
  });

  it("orders documents by their latest upload, most recent first", () => {
    const older = makeDocument({ id: "a", lineage_id: "a", created_at: "2026-11-01T10:00:00Z" });
    const newer = makeDocument({ id: "b", lineage_id: "b", created_at: "2026-11-02T10:00:00Z" });

    expect(groupByLineage([older, newer]).map((g) => g.lineageId)).toEqual(["b", "a"]);
  });
});

describe("hasActiveIngestion", () => {
  it("is true while any document is pending or processing", () => {
    expect(hasActiveIngestion([makeDocument(), makeDocument({ status: "pending" })])).toBe(true);
    expect(hasActiveIngestion([makeDocument(), makeDocument({ status: "failed" })])).toBe(false);
    expect(hasActiveIngestion([])).toBe(false);
  });
});
