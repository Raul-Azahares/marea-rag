import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { api, ApiError } from "../../api/client";
import type { QueryResponse } from "../../api/types";
import { makeResponse } from "../../test/fixtures";
import { ChatPanel } from "./ChatPanel";

function renderPanel(props: Partial<Parameters<typeof ChatPanel>[0]> = {}) {
  render(
    <ChatPanel
      readyCount={1}
      scopeIds={[]}
      scopeLabel={null}
      onClearScope={() => {}}
      onOpenFragment={() => {}}
      {...props}
    />,
  );
}

describe("ChatPanel", () => {
  it("sends the question, shows that it is working, then shows the answer", async () => {
    let answer: (response: QueryResponse) => void = () => {};
    const ask = vi
      .spyOn(api, "ask")
      .mockReturnValue(new Promise<QueryResponse>((resolve) => (answer = resolve)));
    renderPanel({ scopeIds: ["doc-1"] });

    await userEvent.type(screen.getByLabelText("Pregunta"), "¿Qué franquicia tiene?{Enter}");

    expect(ask).toHaveBeenCalledWith("¿Qué franquicia tiene?", ["doc-1"]);
    expect(screen.getByRole("status")).toHaveTextContent("Buscando en los documentos");
    expect(screen.getByRole("button", { name: "Preguntar" })).toBeDisabled();

    answer(makeResponse());

    expect(await screen.findByRole("article", { name: "Respuesta del asistente" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows the error with its support reference and lets the user ask again", async () => {
    const ask = vi
      .spyOn(api, "ask")
      .mockRejectedValueOnce(
        new ApiError("El asistente tardó demasiado.", 504, "QUERY_TIMEOUT", "abc123"),
      )
      .mockResolvedValueOnce(makeResponse());
    renderPanel();

    await userEvent.click(screen.getByRole("button", { name: /segunda vivienda/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("El asistente tardó demasiado.");
    expect(screen.getByRole("link", { name: "abc123" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Volver a preguntar" }));

    expect(await screen.findByRole("article", { name: "Respuesta del asistente" })).toBeInTheDocument();
    expect(ask).toHaveBeenCalledTimes(2);
  });

  it("cannot be used until a document is ready", () => {
    renderPanel({ readyCount: 0 });

    expect(screen.getByRole("button", { name: "Preguntar" })).toBeDisabled();
    expect(screen.getByText("Sube y procesa al menos un documento para poder preguntar.")).toBeInTheDocument();
  });

  it("shows the active scope and lets the user clear it", async () => {
    const onClearScope = vi.fn();
    renderPanel({ scopeIds: ["doc-1"], scopeLabel: "Marea Hogar", onClearScope });

    expect(screen.getByText("Solo en: Marea Hogar")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Quitar el filtro de documentos" }));
    expect(onClearScope).toHaveBeenCalled();
  });

  it("keeps Shift+Enter for line breaks", async () => {
    const ask = vi.spyOn(api, "ask");
    renderPanel();

    await userEvent.type(screen.getByLabelText("Pregunta"), "Primera línea{Shift>}{Enter}{/Shift}segunda");

    expect(ask).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Pregunta")).toHaveValue("Primera línea\nsegunda");
  });
});
