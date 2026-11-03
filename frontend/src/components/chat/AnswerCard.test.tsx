import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { makeCitation, makeFragment, makeResponse } from "../../test/fixtures";
import { AnswerCard } from "./AnswerCard";

describe("AnswerCard", () => {
  it("renders each statement with a clickable citation that opens its fragment", async () => {
    const onOpenFragment = vi.fn();
    render(<AnswerCard response={makeResponse()} onOpenFragment={onOpenFragment} />);

    expect(screen.getByText(/la franquicia es de 100 euros por siniestro/)).toBeInTheDocument();
    expect(screen.getByText("Confianza alta")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Ver cita 1/ }));

    expect(onOpenFragment).toHaveBeenCalledWith({
      chunkId: "chunk-1",
      quote: "la franquicia aplicable será de 100 euros por siniestro",
    });
  });

  it("lists the sources with document, version, page, section and the exact quote", () => {
    const response = makeResponse({
      citations: [makeCitation(), makeCitation({ ref: 2, chunk_id: "chunk-2", exact_match: false })],
      statements: [{ text: "Dos fuentes.", citation_refs: [1, 2] }],
    });
    render(<AnswerCard response={response} onOpenFragment={() => {}} />);

    const sources = within(screen.getByRole("list", { name: "Fuentes" }));
    expect(
      sources.getAllByText(
        "Marea Hogar · Condicionado general 2026 · v2 · p. 3 · Artículo 4. Daños por agua",
      ),
    ).toHaveLength(2);
    expect(sources.getAllByText("«la franquicia aplicable será de 100 euros por siniestro»")).toHaveLength(2);
    expect(sources.getAllByText("aprox.")).toHaveLength(1);
  });

  it("abstains visibly, without confidence, and opens the fragments for review", () => {
    const response = makeResponse({
      status: "insufficient_evidence",
      no_evidence: true,
      confidence: "none",
      answer: "No he encontrado información sobre esto en los documentos.",
      statements: [],
      citations: [],
      retrieved: [makeFragment({ cited: false, similarity: 0.12 })],
      validation: { passed: true, attempts: 0, degraded: false, issues: [] },
    });
    render(<AnswerCard response={response} onOpenFragment={() => {}} />);

    expect(screen.getByText("Sin evidencia suficiente")).toBeInTheDocument();
    expect(screen.getByText(response.answer)).toBeInTheDocument();
    expect(screen.queryByText(/Confianza/)).not.toBeInTheDocument();
    expect(screen.getByText("Fragmentos consultados (1)").closest("details")).toHaveAttribute("open");
  });

  it("flags partial answers and suspected prompt injection", () => {
    const response = makeResponse({
      status: "partial",
      confidence: "low",
      warnings: ["Uno de los fragmentos contiene instrucciones sospechosas y se trató como dato."],
      retrieved: [makeFragment({ flagged: true })],
    });
    render(<AnswerCard response={response} onOpenFragment={() => {}} />);

    expect(screen.getByText("Respuesta parcial")).toBeInTheDocument();
    expect(screen.getByText("Confianza baja")).toBeInTheDocument();
    expect(screen.getByText(/instrucciones sospechosas/)).toBeInTheDocument();
    expect(screen.getByText("posible inyección")).toBeInTheDocument();
    expect(screen.getByText("Fragmentos consultados (1)").closest("details")).not.toHaveAttribute("open");
  });

  it("links the technical details to the trace", async () => {
    render(<AnswerCard response={makeResponse()} onOpenFragment={() => {}} />);

    await userEvent.click(screen.getByText("Detalles técnicos"));

    expect(screen.getByText("Aprobada a la primera")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "0af7651916cd43dd8448eb211c80319c" })).toHaveAttribute(
      "href",
      "http://localhost:16686/trace/0af7651916cd43dd8448eb211c80319c",
    );
  });
});
