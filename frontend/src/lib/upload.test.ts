import { describe, expect, it } from "vitest";

import { makeUpload } from "../test/fixtures";
import { describeUpload, rejectionReason } from "./upload";

function fileOf(name: string, type: string, size: number): File {
  const file = new File(["%PDF-1.7"], name, { type });
  Object.defineProperty(file, "size", { value: size }); // no need to allocate 20 MB
  return file;
}

describe("rejectionReason", () => {
  it("accepts PDFs by MIME type or by extension", () => {
    expect(rejectionReason(fileOf("poliza.pdf", "application/pdf", 1000))).toBeNull();
    expect(rejectionReason(fileOf("POLIZA.PDF", "", 1000))).toBeNull();
  });

  it("rejects other files, empty files and files over the limit", () => {
    expect(rejectionReason(fileOf("notas.docx", "application/msword", 1000))).toBe("No es un PDF.");
    expect(rejectionReason(fileOf("vacio.pdf", "application/pdf", 0))).toBe("El archivo está vacío.");
    expect(rejectionReason(fileOf("enorme.pdf", "application/pdf", 21 * 1024 * 1024))).toBe(
      "Supera el límite de 20 MB.",
    );
  });
});

describe("describeUpload", () => {
  it("tells apart a new upload, a duplicate and a broker outage", () => {
    expect(describeUpload(makeUpload())).toEqual({ tone: "ok", text: "Subido y en cola para procesar." });
    expect(describeUpload(makeUpload({ deduplicated: true })).tone).toBe("info");
    expect(describeUpload(makeUpload({ queued: false }))).toEqual({
      tone: "warn",
      text: "Guardado. La cola no responde ahora; se procesará automáticamente.",
    });
  });
});
