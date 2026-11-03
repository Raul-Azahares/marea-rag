import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DocumentOut } from "../../api/types";
import { groupByLineage } from "../../lib/documents";
import { makeDocument } from "../../test/fixtures";
import { DocumentCard } from "./DocumentCard";

function renderCard(versions: DocumentOut[], selected = false) {
  const handlers = { onToggleSelected: vi.fn(), onRetry: vi.fn(), onNewVersion: vi.fn() };
  const [group] = groupByLineage(versions);
  if (!group) throw new Error("no group");
  render(<DocumentCard group={group} selected={selected} {...handlers} />);
  return handlers;
}

describe("DocumentCard", () => {
  it("shows the ingestion stage and progress while processing", () => {
    renderCard([makeDocument({ status: "processing", stage: "embedding", progress: 60 })]);

    expect(screen.getByText("Procesando")).toBeInTheDocument();
    expect(screen.getByText("Calculando embeddings")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "60");
    // Not answerable yet, so it cannot be used to scope questions.
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("explains a failure and lets the user retry it", async () => {
    const { onRetry } = renderCard([
      makeDocument({
        id: "doc-9",
        status: "failed",
        error_code: "PDF_NO_TEXT",
        error_message: "El PDF no contiene texto extraíble (¿es un escaneo?).",
      }),
    ]);

    expect(screen.getByText("El PDF no contiene texto extraíble (¿es un escaneo?).")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(onRetry).toHaveBeenCalledWith("doc-9");
  });

  it("marks the current version and keeps the replaced ones one click away", () => {
    renderCard([
      makeDocument({ id: "v1", version: 1, superseded: true }),
      makeDocument({ id: "v2", version: 2 }),
    ]);

    expect(screen.getByText("Vigente")).toBeInTheDocument();
    expect(screen.getByText("Versiones anteriores (1)")).toBeInTheDocument();
    expect(screen.getByText("Reemplazada")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
    expect(screen.getByText("v1")).toBeInTheDocument();
  });

  it("toggles the document in or out of the question scope", async () => {
    const { onToggleSelected } = renderCard([makeDocument()]);

    await userEvent.click(screen.getByRole("checkbox", { name: "Acotar" }));

    expect(onToggleSelected).toHaveBeenCalledWith("lineage-1");
  });

  it("uploads a new version of the latest document", async () => {
    const { onNewVersion } = renderCard([makeDocument({ id: "v1" })]);
    const file = new File(["%PDF-1.7"], "poliza-2026.pdf", { type: "application/pdf" });

    await userEvent.upload(screen.getByLabelText(/Nueva versión de/), file);

    expect(onNewVersion).toHaveBeenCalledWith("v1", file);
  });
});
