import { CloudUpload } from "lucide-react";
import { useId, useState, type DragEvent } from "react";

import { MAX_UPLOAD_MB } from "../../config";
import { rejectionReason } from "../../lib/upload";

interface RejectedFile {
  name: string;
  reason: string;
}

export function UploadDropzone({ onFiles }: { onFiles: (files: File[]) => void }) {
  const inputId = useId();
  const [dragging, setDragging] = useState(false);
  const [rejected, setRejected] = useState<RejectedFile[]>([]);

  function accept(list: FileList | null) {
    if (!list) return;
    const files = Array.from(list);
    setRejected(
      files.flatMap((file) => {
        const reason = rejectionReason(file);
        return reason ? [{ name: file.name, reason }] : [];
      }),
    );
    const valid = files.filter((file) => rejectionReason(file) === null);
    if (valid.length > 0) onFiles(valid);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    accept(event.dataTransfer.files);
  }

  return (
    <div>
      <label
        htmlFor={inputId}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`flex cursor-pointer flex-col items-center gap-1 rounded-lg border-2 border-dashed px-4 py-4 text-center transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-primary ${
          dragging ? "border-primary bg-primary-soft" : "border-line hover:border-primary hover:bg-sunk"
        }`}
      >
        <CloudUpload className="size-6 text-primary" aria-hidden />
        <span className="text-sm font-medium">
          Arrastra PDFs aquí o <span className="text-primary underline">elige archivos</span>
        </span>
        <span className="text-xs text-muted">
          Pólizas en PDF con texto · hasta {MAX_UPLOAD_MB} MB cada una
        </span>
      </label>
      <input
        id={inputId}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        className="sr-only"
        onChange={(event) => {
          accept(event.target.files);
          event.target.value = ""; // allow picking the same file again
        }}
      />
      {rejected.length > 0 && (
        <ul role="alert" className="mt-2 space-y-0.5 text-xs text-danger">
          {rejected.map((file) => (
            <li key={file.name}>
              <span className="font-medium">{file.name}</span>: {file.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
