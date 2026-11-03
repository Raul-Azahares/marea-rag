import { describe, expect, it } from "vitest";

import { findQuote, highlightSegments } from "./highlight";

const highlighted = (content: string, quote?: string) =>
  highlightSegments(content, quote)
    .filter((segment) => segment.highlighted)
    .map((segment) => segment.text);

describe("findQuote", () => {
  it("ignores case, accents, punctuation and spacing, like the backend validator", () => {
    const content = "El plazo, de  7 DÍAS naturales, empieza con el siniestro.";
    expect(highlighted(content, "plazo de 7 dias naturales")).toEqual(["plazo, de  7 DÍAS naturales"]);
  });

  it("maps the match back to the original text, line breaks included", () => {
    const content = "Daños por\nagua: cubiertos.";
    const range = findQuote(content, "daños por agua");
    expect(range).toEqual([0, 14]);
    expect(content.slice(...(range ?? [0, 0]))).toBe("Daños por\nagua");
  });

  it("returns null when the quote is not in the fragment verbatim", () => {
    expect(findQuote("La franquicia es de 100 euros.", "franquicia de 150 euros")).toBeNull();
  });

  it("refuses quotes too short to point anywhere meaningful", () => {
    expect(findQuote("a b c", "a")).toBeNull();
    expect(findQuote("...", "¡¿?!")).toBeNull();
  });
});

describe("highlightSegments", () => {
  it("splits the content around the quote", () => {
    expect(highlightSegments("Antes. La cita. Después.", "la cita")).toEqual([
      { text: "Antes. ", highlighted: false },
      { text: "La cita", highlighted: true },
      { text: ". Después.", highlighted: false },
    ]);
  });

  it("drops empty segments when the quote is at an edge", () => {
    expect(highlightSegments("Daños por agua", "daños por agua")).toEqual([
      { text: "Daños por agua", highlighted: true },
    ]);
  });

  it("leaves the content untouched without a quote or a match", () => {
    expect(highlightSegments("Texto", undefined)).toEqual([{ text: "Texto", highlighted: false }]);
    expect(highlightSegments("Texto", "otra cosa")).toEqual([{ text: "Texto", highlighted: false }]);
  });
});
