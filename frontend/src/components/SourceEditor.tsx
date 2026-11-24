"use client";
export function SourceEditor({ rawOcr, corrected, onCorrected }: { rawOcr: string; corrected: string; onCorrected: (v: string) => void }) {
  return (
    <section aria-labelledby="src-h" className="rounded border p-4">
      <h2 id="src-h" className="font-semibold">Step 3 — Captured original text</h2>
      <h3 className="mt-2 text-sm font-medium">Raw OCR output (read-only, exactly as recognised)</h3>
      <div dir="rtl" lang="he" data-testid="raw-ocr" className="hebrew mt-1 min-h-16 whitespace-pre-wrap rounded border p-2 text-right">
        {rawOcr || <span className="text-sm opacity-70">No OCR output yet. OCR is shown as unavailable until a real engine is installed — no sample text is substituted.</span>}
      </div>
      <h3 className="mt-3 text-sm font-medium"><label htmlFor="corrected">Corrected source text (edit this before translating)</label></h3>
      <textarea id="corrected" dir="rtl" lang="he" value={corrected} onChange={(e) => onCorrected(e.target.value)}
        rows={6} className="hebrew mt-1 w-full rounded border p-2 text-right dark:bg-neutral-800"
        placeholder="Corrected transcription appears / is typed here" />
    </section>
  );
}
