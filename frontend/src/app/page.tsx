"use client";
// Main workflow: upload -> OCR -> edit -> translate -> compare/export.
//
// Race safety (NEW-06, NEW-07):
// - Every upstream input change (upload, raw/corrected text, language,
//   script, OCR engine, preprocessing) bumps the request sequence AND
//   aborts in-flight requests.
// - Before a result is published, the input fingerprint captured at
//   request start is compared with the current fingerprint; a
//   mismatch discards the result silently.
// - Starting an OCR run marks the previous OCR output superseded: it
//   is cleared from the active state (kept only as labelled history)
//   and translation stays disabled until the new run completes.
// - Changing the OCR engine, script profile or language profile
//   invalidates the current OCR state for the same reason.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiClientError, getAccessToken, setAccessToken } from "@/lib/api";
import type { Capabilities, JobView, LanguageProfile, OcrResult, ScriptSupport, TranslationResult, UploadMeta } from "@/types/api";
import { SourceEditor } from "@/components/SourceEditor";
import { TranslationPanel } from "@/components/TranslationPanel";
import { ExportButtons } from "@/components/ExportButtons";

function describeError(e: unknown): string {
  if (e instanceof ApiClientError) {
    if (e.code === "profile_choice_required") return "The text matches more than one language profile. Choose a profile to continue.";
    if (e.code === "ambiguous_match") return "The text matches multiple corpus passages. Narrow the selection or choose a profile.";
    if (e.code === "model_not_provisioned") return "No trained model is provisioned for this profile yet, and no verified reference match was found. This is an honest gap, not a hidden failure.";
    if (e.code === "unsupported_file_type" || e.code === "invalid_image") return "That file is not a readable image (JPEG, PNG, WebP, or TIFF, up to the configured size limits).";
    return e.message;
  }
  if (e instanceof DOMException && e.name === "AbortError") return "";
  return e instanceof Error ? e.message : "Unexpected error";
}

function Banner({ kind, message }: { kind: "error" | "info"; message: string }) {
  return (
    <p role={kind === "error" ? "alert" : "status"}
      className={kind === "error"
        ? "rounded border border-red-500 bg-red-50 p-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-200"
        : "rounded border p-2 text-sm"}>
      {message}
    </p>
  );
}

const TERMINAL_JOB = new Set(["completed", "partial", "failed", "cancelled", "expired"]);

export default function Page() {
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [profiles, setProfiles] = useState<LanguageProfile[]>([]);
  const [scriptSupport, setScriptSupport] = useState<ScriptSupport[]>([]);
  const [profileId, setProfileId] = useState<string>("");
  const [scriptProfile, setScriptProfile] = useState<string>("hebrew_square");
  const [ocrEngine, setOcrEngine] = useState<string>("auto");
  const [uploadMeta, setUploadMeta] = useState<UploadMeta | null>(null);
  const [localPreview, setLocalPreview] = useState<string | null>(null);
  const [serverPreview, setServerPreview] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string>("");
  const [uploadDims, setUploadDims] = useState<string>("");
  const [preprocessing, setPreprocessing] = useState<string>("conservative");
  const [ocrResult, setOcrResult] = useState<OcrResult | null>(null);
  const [supersededOcr, setSupersededOcr] = useState<OcrResult | null>(null);
  const [ocrRunning, setOcrRunning] = useState(false);
  const [rawOcr, setRawOcr] = useState("");
  const [corrected, setCorrected] = useState("");
  const [translation, setTranslation] = useState<TranslationResult | null>(null);
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [notice, setNotice] = useState<string>("");
  const [job, setJob] = useState<(JobView & Record<string, unknown>) | null>(null);
  const [accessToken, setAccessTokenState] = useState<string>("");

  const requestSeq = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const jobSeq = useRef(0);

  // The fingerprint of everything a result depends on (NEW-06).
  const fingerprint = useCallback(() => JSON.stringify({
    upload: uploadMeta?.id ?? null, raw: rawOcr, corrected,
    profile: profileId, script: scriptProfile, engine: ocrEngine,
    preprocessing,
  }), [uploadMeta, rawOcr, corrected, profileId, scriptProfile, ocrEngine, preprocessing]);
  const fingerprintRef = useRef(fingerprint());
  useEffect(() => { fingerprintRef.current = fingerprint(); }, [fingerprint]);

  const beginRequest = useCallback(() => {
    requestSeq.current += 1;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    return { seq: requestSeq.current, controller, fp: fingerprintRef.current };
  }, []);

  const isCurrent = useCallback((seq: number, fp: string) =>
    seq === requestSeq.current && fp === fingerprintRef.current, []);

  const invalidateOcrState = useCallback(() => {
    // NEW-07: previous OCR output is superseded — kept only as
    // labelled history, never as the active text.
    setOcrResult((prev) => { if (prev) setSupersededOcr(prev); return null; });
    setRawOcr("");
    setCorrected("");
    setTranslation(null);
  }, []);

  const onUpstreamChange = useCallback(() => {
    beginRequest();
    setJob(null); jobSeq.current += 1;
  }, [beginRequest]);

  useEffect(() => {
    setAccessTokenState(getAccessToken());
    api.capabilities().then(setCaps).catch(() => setCaps(null));
    api.languages().then(setProfiles).catch(() => setProfiles([]));
    api.scripts().then(setScriptSupport).catch(() => setScriptSupport([]));
  }, []);

  // NEW-11: preview via authenticated Blob fetch -> object URL,
  // revoked whenever the upload changes or the page unmounts.
  useEffect(() => {
    if (!uploadMeta) { setServerPreview(null); return; }
    const controller = new AbortController();
    let url: string | null = null;
    api.uploadObjectUrl(uploadMeta.id, controller.signal)
      .then((u) => { url = u; setServerPreview(u); })
      .catch(() => setServerPreview(null));
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [uploadMeta]);

  useEffect(() => () => { if (localPreview) URL.revokeObjectURL(localPreview); }, [localPreview]);

  async function onFile(file: File | null) {
    if (!file) return;
    onUpstreamChange();
    setError(""); setNotice("");
    invalidateOcrState();
    if (localPreview) URL.revokeObjectURL(localPreview);
    setLocalPreview(URL.createObjectURL(file));
    setFileName(file.name);
    setUploadDims("");
    setUploadMeta(null);
    setBusy("Uploading image…");
    try {
      const meta = await api.upload(file);
      setUploadMeta(meta);
      setUploadDims(`${meta.width} × ${meta.height}px · ${meta.format}`);
    } catch (e) { setError(describeError(e)); }
    finally { setBusy(""); }
  }

  function onLanguageChange(id: string) {
    onUpstreamChange();
    setProfileId(id);
    setTranslation(null);
    invalidateOcrState(); // NEW-07: profile change invalidates OCR state
  }

  function onScriptChange(id: string) {
    onUpstreamChange();
    setScriptProfile(id);
    invalidateOcrState();
  }

  function onEngineChange(id: string) {
    onUpstreamChange();
    setOcrEngine(id);
    invalidateOcrState();
  }

  function onPreprocessingChange(id: string) {
    onUpstreamChange();
    setPreprocessing(id);
    setTranslation(null);
  }

  function onCorrectedChange(text: string) {
    onUpstreamChange();
    setCorrected(text);
    setTranslation(null);
  }

  function onTokenChange(token: string) {
    setAccessTokenState(token);
    setAccessToken(token); // sessionStorage only (NEW-11)
  }

  async function extract() {
    if (!uploadMeta) return;
    // NEW-07: starting OCR supersedes the previous OCR output and
    // disables translation until this run completes.
    invalidateOcrState();
    setOcrRunning(true);
    const { seq, controller, fp } = beginRequest();
    setError(""); setNotice(""); setBusy("Running OCR…");
    try {
      const res = await api.ocr(uploadMeta.id, profileId || undefined, preprocessing, ocrEngine, scriptProfile, controller.signal);
      if (!isCurrent(seq, fp)) return; // stale: discard silently
      setOcrResult(res);
      setSupersededOcr(null);
      setRawOcr(res.original_ocr_text);
      setCorrected(res.original_ocr_text);
      if (res.original_ocr_text.trim() === "") setNotice("OCR produced no text. Try another preprocessing profile or a clearer image.");
    } catch (e) {
      if (seq === requestSeq.current) setError(describeError(e));
    } finally {
      if (seq === requestSeq.current) { setBusy(""); setOcrRunning(false); }
    }
  }

  async function translate() {
    if (!corrected.trim()) return;
    const { seq, controller, fp } = beginRequest();
    setError(""); setBusy("Translating…");
    try {
      const res = await api.translate({ correctedSourceText: corrected, originalOcrText: ocrResult ? rawOcr : null, ocrRequestId: ocrResult?.request_id ?? null, sourceLanguage: profileId || undefined }, controller.signal);
      if (!isCurrent(seq, fp)) return; // NEW-06: never publish stale results
      setTranslation(res);
    } catch (e) {
      if (seq === requestSeq.current) setError(describeError(e));
    } finally { if (seq === requestSeq.current) setBusy(""); }
  }

  async function processJob() {
    if (!uploadMeta) return;
    invalidateOcrState();
    setOcrRunning(true);
    const myJob = ++jobSeq.current;
    setError(""); setNotice(""); setBusy("Processing (background job)…");
    try {
      const started = await api.process(uploadMeta.id, profileId || undefined, preprocessing, ocrEngine, scriptProfile) as JobView & Record<string, unknown>;
      const jobId = String(started.job_id ?? started.id ?? "");
      for (let i = 0; i < 1200; i++) {
        if (jobSeq.current !== myJob) return;
        const view = await api.job(jobId);
        setJob(view);
        if (TERMINAL_JOB.has(view.status)) {
          if (view.status === "completed" || view.status === "partial") {
            const resultView = await api.jobResult(jobId);
            const payload = (resultView as Record<string, unknown>).result as { ocr?: OcrResult; translation?: TranslationResult | null } | undefined;
            if (jobSeq.current !== myJob) return;
            if (payload?.ocr) {
              setOcrResult(payload.ocr); setSupersededOcr(null);
              setRawOcr(payload.ocr.original_ocr_text);
              setCorrected(payload.ocr.original_ocr_text);
            }
            setTranslation(payload?.translation ?? null);
          } else {
            setError(`Background job ${view.status}${view.error ? `: ${view.error}` : ""}. You can retry, or use the step-by-step Extract text button.`);
          }
          setBusy("");
          return;
        }
        await new Promise((r) => setTimeout(r, 500));
      }
      setError("Background job did not finish in time. You can retry, or use the step-by-step Extract text button.");
      setBusy("");
    } catch (e) {
      if (jobSeq.current === myJob) { setError(describeError(e)); setBusy(""); }
    } finally {
      if (jobSeq.current === myJob) setOcrRunning(false);
    }
  }

  async function cancelJob() {
    if (!job) return;
    jobSeq.current += 1;
    const jobId = String(job.job_id ?? job.id ?? "");
    try { await api.cancelJob(jobId); } catch { /* surfaced via poll state */ }
    setJob(null); setBusy(""); setOcrRunning(false);
    setNotice("Background job cancelled.");
  }

  const activeScript = scriptSupport.find((s) => s.id === scriptProfile);
  const translationDisabled = !corrected.trim() || ocrRunning;
  const jobActive = job !== null && !TERMINAL_JOB.has(job.status);

  return (
    <main className="mx-auto max-w-6xl p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Ancient Hebrew &amp; Aramaic — Image to English</h1>
        <p className="text-sm text-gray-600 mt-1">Upload an image of Ancient Hebrew or Biblical Aramaic text. OCR runs locally; translation prefers a verified reference match, then an evaluated local model. Anything not provisioned is reported honestly — never faked.</p>
        {caps && (
          <p className="text-xs text-gray-500 mt-2" data-testid="capabilities-line">
            OCR: {caps.ocr.status} · Corpus passages: {caps.corpus.passages} · Translation: {caps.translation.status}
          </p>
        )}
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-gray-600">Backend access token (only if your backend requires one)</summary>
          <label className="block mt-2 max-w-md">
            <span className="sr-only">Access token</span>
            <input type="password" value={accessToken} onChange={(e) => onTokenChange(e.target.value)}
              placeholder="Paste access token" data-testid="access-token-input" autoComplete="off"
              className="w-full rounded border px-2 py-1" />
          </label>
          <p className="text-xs text-gray-500 mt-1">Stored only in this tab&apos;s session storage and sent as a request header. Never in the page source or a URL.</p>
        </details>
      </header>

      {error && <Banner kind="error" message={error} />}
      {notice && <Banner kind="info" message={notice} />}
      {busy && <Banner kind="info" message={busy} />}

      <section className="grid gap-6 md:grid-cols-2">
        <div className="space-y-4">
          <div>
            <label htmlFor="file" className="block text-sm font-medium">1. Upload image</label>
            <input id="file" data-testid="file-input" type="file" accept="image/png,image/jpeg,image/webp,image/tiff" onChange={(e) => onFile(e.target.files?.[0] ?? null)} className="mt-1 block w-full text-sm" />
            {fileName && <p className="text-xs text-gray-500 mt-1">{fileName}{uploadDims ? ` · ${uploadDims}` : ""}</p>}
          </div>
          {(localPreview || serverPreview) && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={localPreview ?? serverPreview ?? ""} alt="Uploaded manuscript page preview" data-testid="upload-preview" className="max-h-96 w-auto rounded border" />
          )}
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">Language profile
              <select value={profileId} onChange={(e) => onLanguageChange(e.target.value)} data-testid="language-select" className="mt-1 block w-full rounded border px-2 py-1">
                <option value="">Auto (detect from text)</option>
                {profiles.map((p) => (<option key={p.id} value={p.id}>{p.name}</option>))}
              </select>
            </label>
            <label className="block text-sm">Script profile
              <select value={scriptProfile} onChange={(e) => onScriptChange(e.target.value)} data-testid="script-select" className="mt-1 block w-full rounded border px-2 py-1">
                {scriptSupport.map((s) => (<option key={s.id} value={s.id}>{s.name}</option>))}
              </select>
            </label>
            <label className="block text-sm">Preprocessing
              <select value={preprocessing} onChange={(e) => onPreprocessingChange(e.target.value)} data-testid="preprocessing-select" className="mt-1 block w-full rounded border px-2 py-1">
                <option value="conservative">Conservative</option>
                <option value="enhanced">Enhanced (manuscripts)</option>
                <option value="none">None</option>
              </select>
            </label>
            <label className="block text-sm">OCR engine
              <select value={ocrEngine} onChange={(e) => onEngineChange(e.target.value)} data-testid="ocr-engine-select" className="mt-1 block w-full rounded border px-2 py-1">
                <option value="auto">Auto</option>
                <option value="tesseract">Tesseract</option>
                <option value="kraken">Kraken (HTR)</option>
              </select>
            </label>
          </div>
          {activeScript && (
            <p className="text-xs text-gray-600" data-testid="script-support-note">
              Script support: <strong>{activeScript.tier ?? activeScript.status}</strong>
              {activeScript.tier !== "validated_for_production" && activeScript.unmet_conditions?.length
                ? ` — not validated for production: ${activeScript.unmet_conditions.join("; ")}`
                : ""}
            </p>
          )}
          <div className="flex gap-2">
            <button type="button" onClick={extract} disabled={!uploadMeta || ocrRunning} data-testid="extract-button" className="rounded bg-black px-4 py-2 text-white disabled:opacity-40">2. Extract text (OCR)</button>
            <button type="button" onClick={processJob} disabled={!uploadMeta || ocrRunning} data-testid="process-button" className="rounded border px-4 py-2 disabled:opacity-40">Process in background</button>
            {jobActive && (
              <button type="button" onClick={cancelJob} data-testid="cancel-job-button" className="rounded border px-4 py-2">Cancel job</button>
            )}
          </div>
          {job && <p className="text-xs text-gray-600" data-testid="job-status">Job {String(job.job_id ?? job.id ?? "").slice(0, 8)}… — {job.status}{job.stage ? ` (${job.stage})` : ""}</p>}
          {supersededOcr && !ocrResult && (
            <p className="text-xs text-amber-700" data-testid="ocr-superseded-note">
              Previous OCR output superseded{ocrRunning ? " — new OCR run in progress" : ""}. It is kept out of the active text; run OCR to produce a fresh result.
            </p>
          )}
          {ocrResult && (
            <p className="text-xs text-gray-600">
              OCR engine: {ocrResult.ocr_engine}{ocrResult.engine_version ? ` (${ocrResult.engine_version})` : ""} · {ocrResult.original_ocr_text.length} characters
            </p>
          )}
        </div>
        <div className="space-y-4">
          <SourceEditor rawOcr={rawOcr} corrected={corrected} onCorrected={onCorrectedChange}
            uncertainSpans={ocrResult?.uncertain_spans ?? []}
            meanConfidence={ocrResult?.mean_confidence ?? null} />
          <button type="button" onClick={translate} disabled={translationDisabled} data-testid="translate-button" className="rounded bg-black px-4 py-2 text-white disabled:opacity-40">3. Translate to English</button>
          {ocrRunning && <p className="text-xs text-gray-500">Translation is disabled while OCR is running.</p>}
        </div>
      </section>

      <TranslationPanel result={translation} />
      <ExportButtons state={{ rawOcrText: rawOcr, correctedSourceText: corrected, englishTranslation: translation?.english_translation ?? "", languageProfile: profileId || translation?.detected_language || null, uploadId: uploadMeta?.id ?? null, translationMethod: translation?.translation_method ?? null, engine: translation?.engine ?? translation?.provenance?.engine ?? null, modelVersion: translation?.model_version ?? translation?.provenance?.model_version ?? null, artifactSha256: translation?.artifact_sha256 ?? translation?.provenance?.artifact_sha256 ?? null, coverage: translation?.coverage ?? null, sourceReferences: translation?.source_references ?? [], provenance: translation?.provenance ?? null, verification: translation?.verification ?? null }} />
    </main>
  );
}
