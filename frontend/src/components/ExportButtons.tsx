"use client";
import React from "react";
import { buildCombinedTxt, buildJsonExport, downloadText, type ExportState } from "@/lib/export";
export function ExportButtons({ state }: { state: ExportState }) {
  // AHAIET-046: each action is disabled by ITS OWN content (no English
  // -> no English copy/export), and clipboard/download failures are
  // surfaced in the UI instead of being swallowed.
  const [feedback, setFeedback] = React.useState<string | null>(null);
  // NEW-19: the source payload is the corrected text when nonempty,
  // otherwise the raw OCR text — the buttons are enabled when EITHER
  // exists, so the payload must be the same fallback. (A separate
  // copy-raw action is unnecessary: when corrected is empty the
  // payload IS the raw text, and when corrected exists it is the
  // user-confirmed source. The raw text remains visible read-only in
  // the editor.)
  const sourceText = state.correctedSourceText || state.rawOcrText;
  const hasSource = Boolean(sourceText);
  const hasEnglish = Boolean(state.englishTranslation);
  const hasAny = hasSource || hasEnglish;
  const copy = async (t: string, label: string) => {
    try { await navigator.clipboard.writeText(t); setFeedback(`${label} copied.`); }
    catch { setFeedback(`Copy failed: the browser denied clipboard access for ${label}.`); }
  };
  const download = (fn: () => void, label: string) => {
    try { fn(); setFeedback(`${label} download started.`); }
    catch { setFeedback(`Download failed for ${label}.`); }
  };
  return (
    <div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Copy and export">
        <button type="button" disabled={!hasSource} onClick={() => copy(sourceText, "Source")} data-testid="copy-source" className="rounded border px-3 py-1 disabled:opacity-40">Copy source</button>
        <button type="button" disabled={!hasEnglish} onClick={() => copy(state.englishTranslation, "English")} data-testid="copy-english" className="rounded border px-3 py-1 disabled:opacity-40">Copy English</button>
        <button type="button" disabled={!hasSource} onClick={() => download(() => downloadText("ahaiet-source.txt", sourceText), "Source TXT")} className="rounded border px-3 py-1 disabled:opacity-40">Export source TXT</button>
        <button type="button" disabled={!hasEnglish} onClick={() => download(() => downloadText("ahaiet-translation.txt", state.englishTranslation), "English TXT")} className="rounded border px-3 py-1 disabled:opacity-40">Export English TXT</button>
        <button type="button" disabled={!hasAny} onClick={() => download(() => downloadText("ahaiet-result.txt", buildCombinedTxt(state)), "Combined TXT")} className="rounded border px-3 py-1 disabled:opacity-40">Export combined TXT</button>
        <button type="button" disabled={!hasAny} onClick={() => download(() => downloadText("ahaiet-result.json", buildJsonExport(state), "application/json;charset=utf-8"), "JSON")} data-testid="export-json" className="rounded border px-3 py-1 disabled:opacity-40">Export JSON</button>
      </div>
      {feedback && <p role="status" className="mt-1 text-sm">{feedback}</p>}
    </div>
  );
}
