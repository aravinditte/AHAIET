"use client";
import { buildCombinedTxt, buildJsonExport, downloadText, type ExportState } from "@/lib/export";
export function ExportButtons({ state }: { state: ExportState }) {
  const disabled = !state.rawOcrText && !state.correctedSourceText && !state.englishTranslation;
  const copy = async (t: string) => { try { await navigator.clipboard.writeText(t); } catch { /* clipboard unavailable */ } };
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Copy and export">
      <button type="button" disabled={disabled} onClick={() => copy(state.correctedSourceText)} className="rounded border px-3 py-1 disabled:opacity-40">Copy source</button>
      <button type="button" disabled={disabled} onClick={() => copy(state.englishTranslation)} className="rounded border px-3 py-1 disabled:opacity-40">Copy English</button>
      <button type="button" disabled={disabled} onClick={() => downloadText("ahaiet-source.txt", state.correctedSourceText)} className="rounded border px-3 py-1 disabled:opacity-40">Export source TXT</button>
      <button type="button" disabled={disabled} onClick={() => downloadText("ahaiet-translation.txt", state.englishTranslation)} className="rounded border px-3 py-1 disabled:opacity-40">Export English TXT</button>
      <button type="button" disabled={disabled} onClick={() => downloadText("ahaiet-result.txt", buildCombinedTxt(state))} className="rounded border px-3 py-1 disabled:opacity-40">Export combined TXT</button>
      <button type="button" disabled={disabled} onClick={() => downloadText("ahaiet-result.json", buildJsonExport(state), "application/json;charset=utf-8")} className="rounded border px-3 py-1 disabled:opacity-40">Export JSON</button>
    </div>
  );
}
