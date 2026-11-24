"use client";
import React from "react";
import { api } from "@/lib/api";
import type { Capabilities } from "@/types/api";
export function ReadinessPanel() {
  const [caps, setCaps] = React.useState<Capabilities | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  React.useEffect(() => { api.capabilities().then(setCaps).catch((e) => setErr(String(e))); }, []);
  if (err) return <section aria-label="Model readiness" className="rounded border border-red-400 p-4"><h2 className="font-semibold">Model readiness</h2><p>Backend unreachable: {err}. Start it with scripts\start-backend.ps1.</p></section>;
  if (!caps) return <section aria-label="Model readiness" className="rounded border p-4">Loading capability state from the backend…</section>;
  const Row = ({ label, ok, detail }: { label: string; ok: boolean; detail: string }) => (
    <li className="flex gap-2"><span aria-hidden>{ok ? "●" : "○"}</span><span><strong>{label}:</strong> {ok ? "available" : "unavailable"} — {detail}</span></li>
  );
  const corpusDetail = caps.corpus.status === "available"
    ? `${caps.corpus.passages} passages imported (${Object.entries(caps.corpus.by_language).map(([k, v]) => `${k}: ${v}`).join(", ")}); verified-reference translation active`
    : (caps.corpus.reason ?? "not imported");
  return (
    <section aria-labelledby="ready-h" className="rounded border p-4">
      <h2 id="ready-h" className="font-semibold">Model readiness (live from /api/capabilities — nothing here is assumed)</h2>
      <ul className="mt-2 space-y-1 text-sm">
        <Row label="Image upload & validation" ok={caps.upload.status === "available"} detail={`${caps.upload.formats.join(", ")}; max ${caps.upload.max_bytes} bytes`} />
        <Row label="OCR (Tesseract)" ok={caps.ocr.tesseract.available} detail={caps.ocr.tesseract.available ? String(caps.ocr.tesseract.path) : "tesseract binary not found — install Tesseract + Hebrew traineddata (docs/OCR.md)"} />
        <Row label="OCR (Kraken)" ok={caps.ocr.kraken.available} detail={caps.ocr.kraken.reason ?? "installed"} />
        <Row label="OpenCV preprocessing" ok={caps.preprocessing.opencv} detail={caps.preprocessing.note ?? "installed"} />
        <Row label="Reference corpus" ok={caps.corpus.status === "available"} detail={corpusDetail} />
        <Row label="Morphology (corpus word index)" ok={caps.morphology.status === "available"} detail={caps.morphology.reason ?? `${caps.corpus.words} indexed words`} />
        <Row label="Translation models" ok={caps.translation.status === "available"} detail={caps.translation.reason ?? "verified reference retrieval and/or a provisioned local model"} />
        <Row label="Database" ok={caps.db_ok} detail={caps.db_ok ? "SQLite reachable" : "SQLite check failed"} />
      </ul>
    </section>
  );
}
