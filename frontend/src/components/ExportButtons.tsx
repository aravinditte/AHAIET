"use client";
import React from "react";
import { buildCombinedTxt, buildJsonExport, downloadText, type ExportState } from "@/lib/export";
export function ExportButtons({ state }: { state: ExportState }) {
  // AHAIET-046: each action is disabled by ITS OWN content (no English
  // -> no English copy/export), and clipboard/download failures are
  // surfaced in the UI instead of being swallowed.
  const [feedback, setFeedback] = React.useState<string | null>(null);
  const hasSource = Boolean(state.correctedSourceText || state.rawOcrText);
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
        <button type="button" disabled={!hasSource} onClick={() => copy(state.correctedSourceText, "Source")} data-testid="copy-source" className="rounded border px-3 py-1 disabled:opacity-40">Copy source</button>
        <button type="button" disabled={!hasEnglish} onClick={() => copy(state.englishTranslation, "English")} data-testid="copy-english" className="rounded border px-3 py-1 disabled:opacity-40">Copy English</button>
        <button type="button" disabled={!hasSource} onClick={() => download(() => downloadText("ahaiet-source.txt", state.correctedSourceText), "Source TXT")} className="rounded border px-3 py-1 disabled:opacity-40">Export source TXT</button>
        <button type="button" disabled={!hasEnglish} onClick={() => download(() => downloadText("ahaiet-translation.txt", state.englishTranslation), "English TXT")} className="rounded border px-3 py-1 disabled:opacity-40">Export English TXT</button>
        <button type="button" disabled={!hasAny} onClick={() => download(() => downloadText("ahaiet-result.txt", buildCombinedTxt(state)), "Combined TXT")} className="rounded border px-3 py-1 disabled:opacity-40">Export combined TXT</button>
        <button type="button" disabled={!hasAny} onClick={() => download(() => downloadText("ahaiet-result.json", buildJsonExport(state), "application/json;charset=utf-8"), "JSON")} data-testid="export-json" className="rounded border px-3 py-1 disabled:opacity-40">Export JSON</button>
      </div>
      {feedback && <p role="status" className="mt-1 text-sm">{feedback}</p>}
    </div>
  );
}
