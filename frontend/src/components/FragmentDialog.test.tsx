import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { makeChunk } from "../test/fixtures";
import { renderWithClient } from "../test/render";
import { FragmentDialog } from "./FragmentDialog";

describe("FragmentDialog", () => {
  it("shows the source fragment with the cited quote highlighted", async () => {
    vi.spyOn(api, "getChunk").mockResolvedValue(makeChunk());
    renderWithClient(
      <FragmentDialog
        fragment={{ chunkId: "chunk-1", quote: "la franquicia aplicable será de 100 euros" }}
        onClose={() => {}}
      />,
    );

    const dialog = await screen.findByRole("dialog", { name: "Artículo 4. Daños por agua" });
    expect(dialog).toHaveAttribute("open");
    expect(dialog.querySelector("mark")).toHaveTextContent("la franquicia aplicable será de 100 euros");
    expect(screen.getByText(/Marea Hogar · Condicionado general 2026 · v2 · p\. 3/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Abrir el PDF en la página 3/ })).toHaveAttribute(
      "href",
      "/api/v1/documents/doc-1/file#page=3",
    );
    expect(api.getChunk).toHaveBeenCalledWith("chunk-1");
  });

  it("warns about superseded versions and suspected prompt injection", async () => {
    vi.spyOn(api, "getChunk").mockResolvedValue(
      makeChunk({ document_superseded: true, flags: ["suspected_prompt_injection"] }),
    );
    renderWithClient(<FragmentDialog fragment={{ chunkId: "chunk-1" }} onClose={() => {}} />);

    expect(await screen.findByText("versión reemplazada")).toBeInTheDocument();
    expect(screen.getByText(/posible inyección/)).toBeInTheDocument();
    expect(screen.queryByText(/coincide de forma aproximada/)).not.toBeInTheDocument();
  });

  it("explains why an approximate quote is not highlighted", async () => {
    vi.spyOn(api, "getChunk").mockResolvedValue(makeChunk());
    renderWithClient(
      <FragmentDialog fragment={{ chunkId: "chunk-1", quote: "franquicia de cien euros" }} onClose={() => {}} />,
    );

    expect(await screen.findByText(/coincide de forma aproximada/)).toBeInTheDocument();
    expect(screen.getByRole("dialog").querySelector("mark")).toBeNull();
  });

  it("reports the close so the parent can clear the selection", async () => {
    vi.spyOn(api, "getChunk").mockResolvedValue(makeChunk());
    const onClose = vi.fn();
    renderWithClient(<FragmentDialog fragment={{ chunkId: "chunk-1" }} onClose={onClose} />);

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: "Cerrar" }));

    expect(onClose).toHaveBeenCalled();
    expect(dialog).not.toHaveAttribute("open");
  });
});
