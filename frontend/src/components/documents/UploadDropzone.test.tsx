import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { UploadDropzone } from "./UploadDropzone";

const pdf = (name: string) => new File(["%PDF-1.7"], name, { type: "application/pdf" });

describe("UploadDropzone", () => {
  it("passes the selected PDFs on", async () => {
    const onFiles = vi.fn();
    render(<UploadDropzone onFiles={onFiles} />);
    const files = [pdf("hogar.pdf"), pdf("auto.pdf")];

    await userEvent.upload(screen.getByLabelText(/Arrastra PDFs aquí/), files);

    expect(onFiles).toHaveBeenCalledWith(files);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("filters out what is not a PDF and says why", async () => {
    // applyAccept: false simulates a user picking "All files" in the native dialog.
    const user = userEvent.setup({ applyAccept: false });
    const onFiles = vi.fn();
    render(<UploadDropzone onFiles={onFiles} />);
    const valid = pdf("hogar.pdf");

    await user.upload(screen.getByLabelText(/Arrastra PDFs aquí/), [
      valid,
      new File(["hola"], "notas.txt", { type: "text/plain" }),
    ]);

    expect(onFiles).toHaveBeenCalledWith([valid]);
    expect(screen.getByRole("alert")).toHaveTextContent("notas.txt: No es un PDF.");
  });

  it("does not call onFiles when nothing valid was chosen", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const onFiles = vi.fn();
    render(<UploadDropzone onFiles={onFiles} />);

    await user.upload(
      screen.getByLabelText(/Arrastra PDFs aquí/),
      new File([""], "vacio.pdf", { type: "application/pdf" }),
    );

    expect(onFiles).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("vacio.pdf: El archivo está vacío.");
  });
});
