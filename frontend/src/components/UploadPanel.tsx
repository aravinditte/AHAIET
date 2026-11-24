"use client";
import React from "react";
export function UploadPanel({ file, previewUrl, onFile, uploadMeta }: {
  file: File | null; previewUrl: string | null; onFile: (f: File | null) => void;
  uploadMeta: { format: string; width: number; height: number; size_bytes: number } | null;
}) {
  const [drag, setDrag] = React.useState(false);
  return (
    <section aria-labelledby="upload-h" className="rounded border p-4">
      <h2 id="upload-h" className="font-semibold">Step 1 — Upload an image</h2>
      <div role="group" aria-label="Image upload: drop an image file here, or use the Choose an image file chooser"
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) onFile(f); }}
        className={`mt-3 rounded border-2 border-dashed p-6 text-center ${drag ? "border-blue-500" : "border-gray-400"}`}>
        <label htmlFor="file-input" className="cursor-pointer underline">Choose an image</label>
        <span> or drag and drop it here (PNG, JPEG, TIFF, WEBP, BMP). The backend validates file content, not the extension.</span>
        <input id="file-input" type="file" accept="image/png,image/jpeg,image/tiff,image/webp,image/bmp" className="sr-only"
          onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
      </div>
      {file && <p className="mt-2 text-sm">Selected: {file.name} ({file.size} bytes)</p>}
      {uploadMeta && <p className="mt-1 text-sm">Stored by backend: {uploadMeta.format}, {uploadMeta.width}×{uploadMeta.height}, {uploadMeta.size_bytes} bytes</p>}
      {previewUrl && (
        <figure className="mt-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={previewUrl} alt="Preview of the uploaded manuscript page" data-testid="upload-preview" className="max-h-96 rounded border" />
          <figcaption className="text-sm">Actual preview of your uploaded image.</figcaption>
        </figure>
      )}
    </section>
  );
}
