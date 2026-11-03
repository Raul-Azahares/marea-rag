import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { api } from "./api/client";
import { makeDocument, makeResponse } from "./test/fixtures";
import { renderWithClient } from "./test/render";

const HOGAR_V1 = makeDocument({ id: "hogar-v1", lineage_id: "hogar", version: 1, superseded: true });
const HOGAR_V2 = makeDocument({
  id: "hogar-v2",
  lineage_id: "hogar",
  version: 2,
  title: "Marea Hogar",
  created_at: "2026-11-03T09:00:00Z",
});
const AUTO = makeDocument({
  id: "auto-v1",
  lineage_id: "auto",
  title: "Marea Auto",
  status: "processing",
  stage: "chunking",
  progress: 30,
  created_at: "2026-11-03T10:00:00Z",
});

describe("App", () => {
  it("scopes a question to the current version of the ticked document", async () => {
    vi.spyOn(api, "listDocuments").mockResolvedValue({ items: [HOGAR_V1, HOGAR_V2, AUTO], total: 3 });
    const ask = vi.spyOn(api, "ask").mockResolvedValue(makeResponse());
    const user = userEvent.setup();
    renderWithClient(<App />);

    const hogar = await screen.findByRole("article", { name: "Marea Hogar" });
    // Only answerable documents can be used as a scope: Auto is still processing.
    expect(within(screen.getByRole("article", { name: "Marea Auto" })).queryByRole("checkbox")).toBeNull();

    await user.click(within(hogar).getByRole("checkbox", { name: "Acotar" }));
    expect(screen.getByText("Solo en: Marea Hogar")).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "Pregunta" }), "¿Qué franquicia tiene?{Enter}");

    // The current version's id, never the lineage id or the superseded version.
    expect(ask).toHaveBeenCalledWith("¿Qué franquicia tiene?", ["hogar-v2"]);
    expect(await screen.findByRole("article", { name: "Respuesta del asistente" })).toBeInTheDocument();
  });

  it("asks across every current document when nothing is ticked", async () => {
    vi.spyOn(api, "listDocuments").mockResolvedValue({ items: [HOGAR_V2], total: 1 });
    const ask = vi.spyOn(api, "ask").mockResolvedValue(makeResponse());
    const user = userEvent.setup();
    renderWithClient(<App />);

    await screen.findByRole("article", { name: "Marea Hogar" });
    expect(screen.getByText("En todos los documentos vigentes")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Pregunta" }), "¿Qué cubre?{Enter}");

    expect(ask).toHaveBeenCalledWith("¿Qué cubre?", []);
  });

  it("shows why the list could not be loaded and lets the user retry", async () => {
    const list = vi
      .spyOn(api, "listDocuments")
      .mockRejectedValueOnce(new Error("La API no responde."))
      .mockResolvedValueOnce({ items: [HOGAR_V2], total: 1 });
    const user = userEvent.setup();
    renderWithClient(<App />);

    expect(await screen.findByText(/La API no responde\./)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reintentar" }));

    expect(await screen.findByRole("article", { name: "Marea Hogar" })).toBeInTheDocument();
    expect(list).toHaveBeenCalledTimes(2);
  });
});
