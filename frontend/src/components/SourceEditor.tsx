"use client";
import React from "react";
import type { UncertainSpan } from "@/types/api";

function HighlightedRaw({ rawOcr, uncertain }: { rawOcr: string; uncertain: UncertainSpan[] }) {
  // AHAIET-028: highlight by token OCCURRENCE id, not by string
  // search. Each non-whitespace token is numbered in reading order;
  // a span marks exactly the occurrence its occurrence_id names, so a
  // repeated word is highlighted only where OCR was actually unsure.
  // Spans without an occurrence_id (older payloads) fall back to
  // consuming matching texts in order.
  const byOccurrence = new Map<string, UncertainSpan>();
  const fallbackQueue: string[] = [];
  for (const u of uncertain) {
    if (u.occurrence_id) byOccurrence.set(u.occurrence_id, u);
    else fallbackQueue.push(u.text);
  }
  const parts: React.ReactNode[] = [];
  let occurrence = 0;
  rawOcr.split(/(\s+)/).forEach((tok, i) => {
    if (!tok.trim()) { parts.push(<span key={i}>{tok}</span>); return; }
    const id = `w${occurrence}`;
    occurrence += 1;
    let marked = byOccurrence.has(id);
    if (!marked && !byOccurrence.size) {
      const idx = fallbackQueue.indexOf(tok);
      if (idx >= 0) { fallbackQueue.splice(idx, 1); marked = true; }
    }
    parts.push(marked
      ? <mark key={i} data-occurrence-id={id} className="bg-yellow-300 text-black dark:bg-yellow-600" title="Low OCR confidence word">{tok}</mark>
      : <span key={i}>{tok}</span>);
  });
  return <>{parts}</>;
}

export function SourceEditor({ rawOcr, corrected, onCorrected, uncertainSpans = [], meanConfidence = null, ocrNote = null }: {
  rawOcr: string; corrected: string; onCorrected: (v: string) => void;
  uncertainSpans?: UncertainSpan[]; meanConfidence?: number | null; ocrNote?: string | null;
}) {
  return (
    <section aria-labelledby="src-h" className="rounded border p-4">
      <h2 id="src-h" className="font-semibold">Step 3 — Captured original text</h2>
      <h3 className="mt-2 text-sm font-medium">Raw OCR output (read-only, exactly as recognised; low-confidence words highlighted)</h3>
      <div dir="rtl" lang="he" data-testid="raw-ocr" className="hebrew mt-1 min-h-16 whitespace-pre-wrap rounded border p-2 text-right">
        {rawOcr ? <HighlightedRaw rawOcr={rawOcr} uncertain={uncertainSpans} /> : <span className="text-sm opacity-70">No OCR output yet. OCR is shown as unavailable until a real engine is installed — no sample text is substituted.</span>}
      </div>
      {rawOcr && (
        <p className="mt-1 text-sm">
          {meanConfidence !== null ? <>Mean word confidence (Tesseract TSV): {meanConfidence}. </> : null}
          {uncertainSpans.length} low-confidence word(s) highlighted. {ocrNote ?? ""}
        </p>
      )}
      <h3 className="mt-3 text-sm font-medium"><label htmlFor="corrected">Corrected source text (edit this before translating)</label></h3>
      <textarea id="corrected" dir="rtl" lang="he" value={corrected} data-testid="corrected-source" onChange={(e) => onCorrected(e.target.value)}
        rows={6} className="hebrew mt-1 w-full rounded border p-2 text-right dark:bg-neutral-800"
        placeholder="Corrected transcription appears / is typed here" />
    </section>
  );
}
