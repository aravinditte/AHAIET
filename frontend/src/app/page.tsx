"use client";
import React from "react";
import { UploadPanel } from "@/components/UploadPanel";
import { LanguageSelector } from "@/components/LanguageSelector";
import { ReadinessPanel } from "@/components/ReadinessPanel";
import { SourceEditor } from "@/components/SourceEditor";
import { TranslationPanel } from "@/components/TranslationPanel";
import { ExportButtons } from "@/components/ExportButtons";
import { api, ApiClientError } from "@/lib/api";
import type { LanguageProfile, UploadMeta } from "@/types/api";

export default function Home() {
  const [file, setFile] = React.useState<File | null>(null);
  const [localPreview, setLocalPreview] = React.useState<string | null>(null);
  const [uploadMeta, setUploadMeta] = React.useState<UploadMeta | null>(null);
  const [languages, setLanguages] = React.useState<LanguageProfile[]>([]);
  const [language, setLanguage] = React.useState("");
  const [rawOcr, setRawOcr] = React.useState("");
  const [corrected, setCorrected] = React.useState("");
  const [translation, setTranslation] = React.useState("");
  const [status, setStatus] = React.useState<string>("");
  const [error, setError] = React.useState<string | null>(null);
  const [dark, setDark] = React.useState(false);

  React.useEffect(() => { api.languages().then(setLanguages).catch(() => {}); }, []);
  React.useEffect(() => { document.documentElement.classList.toggle("dark", dark); }, [dark]);
  React.useEffect(() => {
    if (!file) { setLocalPreview(null); return; }
    const url = URL.createObjectURL(file); setLocalPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const onFile = async (f: File | null) => {
    setFile(f); setError(null); setUploadMeta(null); setRawOcr(""); setCorrected(""); setTranslation("");
    if (!f) return;
    setStatus("Uploading to backend for content validation…");
    try { const meta = await api.upload(f); setUploadMeta(meta); setStatus("Image validated and stored by the backend."); }
    catch (e) { setError(e instanceof ApiClientError ? e.message : String(e)); setStatus(""); }
  };
  const extract = async () => {
    if (!uploadMeta) { setError("Upload an image first."); return; }
    setError(null); setStatus("Running OCR…");
    try { const r = await api.ocr(uploadMeta.id, language || undefined); setRawOcr(r.original_ocr_text); setCorrected(r.original_ocr_text); setStatus("OCR complete."); }
    catch (e) { setError(e instanceof ApiClientError ? e.message : String(e)); setStatus(""); }
  };
  const translate = async () => {
    if (!corrected.trim()) { setError("There is no corrected source text to translate."); return; }
    setError(null); setStatus("Translating with the local model…");
    try { const r = await api.translate(corrected, language || undefined); setTranslation(r.english_translation ?? ""); setStatus("Translation complete."); }
    catch (e) { setError(e instanceof ApiClientError ? e.message : String(e)); setStatus(""); }
  };
  const reset = () => { setFile(null); setUploadMeta(null); setRawOcr(""); setCorrected(""); setTranslation(""); setError(null); setStatus(""); setLanguage(""); };
  const preview = uploadMeta ? api.uploadUrl(uploadMeta.id) : localPreview;

  return (
    <main className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">AHAIET — Ancient Hebrew &amp; Ancient Aramaic Image-to-English Translator</h1>
          <p className="mt-1">Upload an image of Biblical Hebrew or Biblical Aramaic, review and correct the captured text, then translate it into English. Everything runs locally and offline once models are provisioned; readiness below is reported honestly, never assumed.</p>
        </div>
        <button type="button" onClick={() => setDark(!dark)} aria-pressed={dark} className="rounded border px-3 py-1">{dark ? "Light" : "Dark"} theme</button>
      </header>
      <ReadinessPanel />
      <UploadPanel file={file} previewUrl={preview} onFile={onFile} uploadMeta={uploadMeta} />
      <section aria-labelledby="proc-h" className="rounded border p-4">
        <h2 id="proc-h" className="font-semibold">Step 2 — Language &amp; extraction</h2>
        <div className="mt-2"><LanguageSelector languages={languages} value={language} onChange={setLanguage} /></div>
        <button type="button" onClick={extract} disabled={!uploadMeta} className="mt-3 rounded bg-blue-700 px-4 py-2 text-white disabled:opacity-40">Process / Extract Text (OCR)</button>
      </section>
      <SourceEditor rawOcr={rawOcr} corrected={corrected} onCorrected={setCorrected} />
      <section aria-labelledby="trbtn-h" className="rounded border p-4">
        <h2 id="trbtn-h" className="font-semibold">Step 4 — Translate the confirmed transcription</h2>
        <button type="button" onClick={translate} disabled={!corrected.trim()} className="mt-2 rounded bg-blue-700 px-4 py-2 text-white disabled:opacity-40">Translate</button>
      </section>
      <TranslationPanel translation={translation} />
      {status && <p role="status" className="rounded border p-2">{status}</p>}
      {error && <p role="alert" className="rounded border border-red-500 p-2">{error}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <ExportButtons state={{ rawOcrText: rawOcr, correctedSourceText: corrected, englishTranslation: translation, languageProfile: language || null, uploadId: uploadMeta?.id ?? null }} />
        <button type="button" onClick={reset} className="rounded border px-3 py-1">Clear / reset</button>
      </div>
    </main>
  );
}
