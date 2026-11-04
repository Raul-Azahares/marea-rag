import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "../../api/client";
import type { DocumentOut } from "../../api/types";
import { groupByLineage } from "../../lib/documents";
import { makeDocument, makeUpload } from "../../test/fixtures";
import { renderWithClient } from "../../test/render";
import { DocumentsPanel } from "./DocumentsPanel";

const pdf = (name = "hogar.pdf") => new File([`%PDF-1.7 ${name}`], name, { type: "application/pdf" });

function panel(documents: DocumentOut[] = []) {
  return (
    <DocumentsPanel
      groups={groupByLineage(documents)}
      isLoading={false}
      loadError={null}
      onReload={() => {}}
      selected={new Set()}
      onToggleSelected={() => {}}
    />
  );
}

function setup() {
  return userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("upload notices", () => {
  it("drop the receipt once the document's card shows the outcome", async () => {
    vi.spyOn(api, "uploadDocument").mockResolvedValue(makeUpload({ id: "doc-9" }));
    const user = setup();
    const { rerender } = renderWithClient(panel());

    await user.upload(screen.getByLabelText(/Arrastra PDFs aquí/), pdf());
    expect(await screen.findByText(/Subido y en cola para procesar/)).toBeInTheDocument();

    // Still processing: the receipt stays, however long it takes.
    rerender(panel([makeDocument({ id: "doc-9", status: "processing", progress: 40 })]));
    act(() => vi.advanceTimersByTime(30_000));
    expect(screen.getByText(/Subido y en cola para procesar/)).toBeInTheDocument();

    // Processed: the card says "Listo", so the receipt goes.
    rerender(panel([makeDocument({ id: "doc-9", status: "ready" })]));
    act(() => vi.advanceTimersByTime(4_000));
    expect(screen.queryByText(/Subido y en cola para procesar/)).not.toBeInTheDocument();
  });

  it("keep errors and warnings until the user dismisses them", async () => {
    vi.spyOn(api, "uploadDocument")
      .mockRejectedValueOnce(
        new ApiError("El contenido no es un PDF válido.", 415, "UNSUPPORTED_MEDIA_TYPE", null),
      )
      .mockResolvedValueOnce(makeUpload({ id: "doc-2", queued: false }));
    const user = setup();
    const { rerender } = renderWithClient(panel());

    await user.upload(screen.getByLabelText(/Arrastra PDFs aquí/), [pdf("roto.pdf"), pdf("auto.pdf")]);
    expect(await screen.findByText(/no es un PDF válido/)).toBeInTheDocument();
    expect(await screen.findByText(/La cola no responde/)).toBeInTheDocument();

    rerender(panel([makeDocument({ id: "doc-2", status: "ready" })]));
    act(() => vi.advanceTimersByTime(60_000));
    expect(screen.getByText(/no es un PDF válido/)).toBeInTheDocument();
    expect(screen.getByText(/La cola no responde/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Descartar el aviso de roto.pdf" }));
    expect(screen.queryByText(/no es un PDF válido/)).not.toBeInTheDocument();
  });

  it("let the duplicate notice go after a few seconds", async () => {
    vi.spyOn(api, "uploadDocument").mockResolvedValue(
      makeUpload({ id: "doc-1", deduplicated: true, status: "ready" }),
    );
    const user = setup();
    renderWithClient(panel([makeDocument({ id: "doc-1" })]));

    await user.upload(screen.getByLabelText(/Arrastra PDFs aquí/), pdf());
    expect(await screen.findByText(/Ya estaba subido/)).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(6_000));
    expect(screen.queryByText(/Ya estaba subido/)).not.toBeInTheDocument();
  });
});
