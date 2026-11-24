"use client";
import React from "react";
import { UploadPanel } from "@/components/UploadPanel";
import { LanguageSelector } from "@/components/LanguageSelector";
import { ReadinessPanel } from "@/components/ReadinessPanel";
import { SourceEditor } from "@/components/SourceEditor";
import { TranslationPanel } from "@/components/TranslationPanel";
import { ScriptsPanel } from "@/components/ScriptsPanel";
import { ExportButtons } from "@/components/ExportButtons";
import { api, ApiClientError } from "@/lib/api";
import type { LanguageProfile, OcrResult, ScriptSupport, TranslationResult, UploadMeta } from "@/types/api";

export default function Home() {
  const [file, setFile] = React.useState<File | null>(null);
  const [localPreview, setLocalPreview] = React.useState<string | null>(null);
  const [uploadMeta, setUploadMeta] = React.useState<UploadMeta | null>(null);
  const [languages, setLanguages] = React.useState<LanguageProfile[]>([]);
  const [language, setLanguage] = React.useState("");
  const [preprocessing, setPreprocessing] = React.useState("conservative");
  const [ocrEngine, setOcrEngine] = React.useState("auto");
  const [scriptProfile, setScriptProfile] = React.useState("hebrew_square");
  const [scriptRows, setScriptRows] = React.useState<ScriptSupport[]>([]);
  const [ocrResult, setOcrResult] = React.useState<OcrResult | null>(null);
  const [rawOcr, setRawOcr] = React.useState("");
  const [corrected, setCorrected] = React.useState("");
  const [translationResult, setTranslationResult] = React.useState<TranslationResult | null>(null);
  const [status, setStatus] = React.useState<string>("");
  const [error, setError] = React.useState<string | null>(null);
  const [dark, setDark] = React.useState(false);

  React.useEffect(() => { api.languages().then(setLanguages).catch(() => {}); }, []);
  React.useEffect(() => { api.scripts().then(setScriptRows).catch(() => {}); }, []);
  React.useEffect(() => { document.documentElement.classList.toggle("dark", dark); }, [dark]);
  React.useEffect(() => {
    if (!file) { setLocalPreview(null); return; }
    const url = URL.createObjectURL(file); setLocalPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const onFile = async (f: File | null) => {
    setFile(f); setError(null); setUploadMeta(null); setRawOcr(""); setCorrected(""); setOcrResult(null); setTranslationResult(null);
    if (!f) return;
    setStatus("Uploading to backend for content validation…");
    try { const meta = await api.upload(f); setUploadMeta(meta); setStatus("Image validated and stored by the backend."); }
    catch (e) { setError(e instanceof ApiClientError ? e.message : String(e)); setStatus(""); }
  };
  const extract = async () => {
    if (!uploadMeta) { setError("Upload an image first."); return; }
    setError(null); setStatus("Running OCR…");
    try {
      const r = await api.ocr(uploadMeta.id, language || undefined, preprocessing, ocrEngine, scriptProfile);
      setOcrResult(r); setRawOcr(r.original_ocr_text); setCorrected(r.original_ocr_text);
      setStatus(`OCR complete (${r.ocr_engine}, profile ${r.ocr_profile}, ${r.word_count} words). Review and correct the text, then translate.`);
    }
    catch (e) { setError(e instanceof ApiClientError ? e.message : String(e)); setStatus(""); }
  };
  const translate = async () => {
    if (!corrected.trim()) { setError("There is no corrected source text to translate."); return; }
    setError(null); setStatus("Checking the verified corpus and local models…");
    try {
      const r = await api.translate(corrected, language || undefined);
      setTranslationResult(r);
      setStatus(r.status === "partial"
        ? "Partial translation: some lines translated, some unavailable — see the per-line breakdown."
        : r.translation_method === "verified_reference"
        ? "Verified corpus match found — the cited edition's English is shown with its provenance."
        : "Translation complete.");
    }
    catch (e) { setTranslationResult(null); setError(e instanceof ApiClientError ? e.message : String(e)); setStatus(""); }
  };
  const reset = () => { setFile(null); setUploadMeta(null); setRawOcr(""); setCorrected(""); setOcrResult(null); setTranslationResult(null); setError(null); setStatus(""); setLanguage(""); };
  const preview = uploadMeta ? api.uploadUrl(uploadMeta.id) : localPreview;
  const translation = translationResult?.english_translation ?? "";

  return (
    <main className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">AHAIET — Ancient Hebrew &amp; Ancient Aramaic Image-to-English Translator</h1>
          <p className="mt-1">Upload an image of Biblical Hebrew or Biblical Aramaic, review and correct the captured text, then translate it into English. Translation is a verified corpus reference where one matches, or a provisioned local model; otherwise the app says so plainly. Everything runs locally and offline once provisioned; readiness below is reported honestly, never assumed.</p>
        </div>
        <button type="button" onClick={() => setDark(!dark)} aria-pressed={dark} className="rounded border px-3 py-1">{dark ? "Light" : "Dark"} theme</button>
      </header>
      <ReadinessPanel />
      <ScriptsPanel />
      <UploadPanel file={file} previewUrl={preview} onFile={onFile} uploadMeta={uploadMeta} />
      <section aria-labelledby="proc-h" className="rounded border p-4">
        <h2 id="proc-h" className="font-semibold">Step 2 — Language &amp; extraction</h2>
        <div className="mt-2"><LanguageSelector languages={languages} value={language} onChange={setLanguage} /></div>
        <div className="mt-3">
          <label htmlFor="preproc" className="font-semibold">Preprocessing profile</label>
          <select id="preproc" value={preprocessing} onChange={(e) => setPreprocessing(e.target.value)} className="ml-2 rounded border p-1 dark:bg-neutral-800">
            <option value="conservative">Conservative (preserves small marks; no deskew/median)</option>
            <option value="enhanced">Enhanced (deskew + adaptive contrast; median only when safe)</option>
          </select>
          <p className="text-sm">The uploaded original is never modified; preprocessing works on a derived copy and reports every step.</p>
        </div>
        <div className="mt-3">
          <label htmlFor="ocr-engine" className="font-semibold">OCR engine</label>
          <select id="ocr-engine" value={ocrEngine} onChange={(e) => setOcrEngine(e.target.value)} className="ml-2 rounded border p-1 dark:bg-neutral-800">
            <option value="auto">Auto (Tesseract for Hebrew square script)</option>
            <option value="tesseract">Tesseract</option>
            <option value="kraken">Kraken (historical scripts, when supported)</option>
          </select>
          <label htmlFor="script-profile" className="ml-4 font-semibold">Script</label>
          <select id="script-profile" value={scriptProfile} onChange={(e) => setScriptProfile(e.target.value)} className="ml-2 rounded border p-1 dark:bg-neutral-800">
            {scriptRows.length ? scriptRows.map((s) => (
              <option key={s.id} value={s.id}>{s.name} — {s.status}</option>
            )) : <option value="hebrew_square">Hebrew square script</option>}
          </select>
          <p className="text-sm">Historical scripts are recognised only when the support matrix below computes them as supported (trained checkpoint + measured evaluation record). Unsupported choices fail with an explicit error — the app never silently substitutes another engine.</p>
        </div>
        <button type="button" onClick={extract} disabled={!uploadMeta} className="mt-3 rounded bg-blue-700 px-4 py-2 text-white disabled:opacity-40">Process / Extract Text (OCR)</button>
      </section>
      <SourceEditor rawOcr={rawOcr} corrected={corrected} onCorrected={setCorrected}
        uncertainSpans={ocrResult?.uncertain_spans ?? []} meanConfidence={ocrResult?.mean_confidence ?? null}
        ocrNote={ocrResult ? `OCR profile: ${ocrResult.ocr_profile}${ocrResult.ocr_lang ? ` (${ocrResult.ocr_lang} traineddata)` : ""}. ${ocrResult.ocr_profile_note}` : null} />
      <section aria-labelledby="trbtn-h" className="rounded border p-4">
        <h2 id="trbtn-h" className="font-semibold">Step 4 — Translate the confirmed transcription</h2>
        <button type="button" onClick={translate} disabled={!corrected.trim()} className="mt-2 rounded bg-blue-700 px-4 py-2 text-white disabled:opacity-40">Translate</button>
      </section>
      <TranslationPanel result={translationResult} />
      {status && <p role="status" className="rounded border p-2">{status}</p>}
      {error && <p role="alert" className="rounded border border-red-500 p-2">{error}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <ExportButtons state={{ rawOcrText: rawOcr, correctedSourceText: corrected, englishTranslation: translation, languageProfile: language || null, uploadId: uploadMeta?.id ?? null, translationMethod: translationResult?.translation_method ?? null, sourceReferences: translationResult?.source_references ?? [], engine: translationResult?.engine ?? null, modelVersion: translationResult?.model_version ?? null, artifactSha256: translationResult?.artifact_sha256 ?? null, coverage: translationResult?.coverage ?? null, verification: translationResult?.verification ?? null, provenance: translationResult?.provenance ?? null }} />
        <button type="button" onClick={reset} className="rounded border px-3 py-1">Clear / reset</button>
      </div>
    </main>
  );
}
