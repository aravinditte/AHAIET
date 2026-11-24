import type { Capabilities, JobView, LanguageProfile, OcrResult, ScriptSupport, TranslationResult, UploadMeta } from "@/types/api";
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
export class ApiClientError extends Error { code: string; constructor(code: string, message: string) { super(message); this.code = code; } }
async function parse<T>(res: Response): Promise<T> {
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const e = (data as { error?: { code: string; message: string; detail: string | null } } | null)?.error;
    throw new ApiClientError(e?.code ?? "http_error", e ? `${e.message}${e.detail ? " " + e.detail : ""}` : `Request failed (${res.status})`);
  }
  return data as T;
}
// NEW-11: optional backend access token. The user pastes it into a
// settings field; it is stored ONLY in sessionStorage (gone when
// the tab closes), attached as a header by the API client, and never
// placed in a NEXT_PUBLIC_* variable or a URL query parameter.
const TOKEN_KEY = "ahaiet_access_token";
export function getAccessToken(): string {
  try { return sessionStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; }
}
export function setAccessToken(token: string): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch { /* sessionStorage unavailable: token applies to fetches only while set below */ }
}
function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getAccessToken();
  return token ? { ...extra, "X-AHAIET-Access-Token": token } : extra;
}
export const api = {
  base: BASE,
  async capabilities(): Promise<Capabilities> { return parse(await fetch(`${BASE}/api/capabilities`, { headers: authHeaders() })); },
  async languages(): Promise<LanguageProfile[]> { const d = await parse<{ languages: LanguageProfile[] }>(await fetch(`${BASE}/api/languages`, { headers: authHeaders() })); return d.languages; },
  async upload(file: File, signal?: AbortSignal): Promise<UploadMeta> { const fd = new FormData(); fd.append("file", file); return parse(await fetch(`${BASE}/api/uploads`, { method: "POST", body: fd, headers: authHeaders(), signal })); },
  uploadUrl(id: string): string { return `${BASE}/api/uploads/${id}`; },
  // NEW-11: the preview image is fetched as a Blob through an
  // authenticated request (an <img> tag cannot send the token
  // header) and shown via a revocable object URL.
  async uploadObjectUrl(id: string, signal?: AbortSignal): Promise<string> {
    const res = await fetch(`${BASE}/api/uploads/${id}`, { headers: authHeaders(), signal });
    if (!res.ok) throw new ApiClientError("preview_failed", `Image preview failed (${res.status})`);
    return URL.createObjectURL(await res.blob());
  },
  async ocr(uploadId: string, languageProfile?: string, preprocessingProfile = "conservative", engine = "auto", scriptProfile = "hebrew_square", signal?: AbortSignal): Promise<OcrResult> {
    return parse(await fetch(`${BASE}/api/ocr`, { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ upload_id: uploadId, language_profile: languageProfile ?? null, preprocessing_profile: preprocessingProfile, engine, script_profile: scriptProfile }), signal }));
  },
  async scripts(): Promise<ScriptSupport[]> { const d = await parse<{ scripts: ScriptSupport[] }>(await fetch(`${BASE}/api/scripts`, { headers: authHeaders() })); return d.scripts; },
  // AHAIET-026: raw OCR text (immutable), corrected text, the selected
  // profile, and the OCR request id travel as separate fields.
  async translate(args: { originalOcrText?: string | null; correctedSourceText: string; sourceLanguage?: string; ocrRequestId?: string | null }, signal?: AbortSignal): Promise<TranslationResult> {
    return parse(await fetch(`${BASE}/api/translate`, { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ text: args.correctedSourceText, corrected_source_text: args.correctedSourceText, original_ocr_text: args.originalOcrText ?? null, ocr_request_id: args.ocrRequestId ?? null, source_language: args.sourceLanguage ?? null }), signal }));
  },
  // AHAIET-009: asynchronous process jobs — submit (202), poll, cancel.
  async process(uploadId: string, languageProfile?: string, preprocessingProfile = "conservative", engine = "auto", scriptProfile = "hebrew_square"): Promise<JobView> {
    return parse(await fetch(`${BASE}/api/process`, { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ upload_id: uploadId, language_profile: languageProfile ?? null, preprocessing_profile: preprocessingProfile, engine, script_profile: scriptProfile }) }));
  },
  async job(jobId: string): Promise<JobView & Record<string, unknown>> {
    return parse(await fetch(`${BASE}/api/jobs/${jobId}`, { headers: authHeaders() }));
  },
  async jobResult(jobId: string): Promise<JobView> {
    return parse(await fetch(`${BASE}/api/jobs/${jobId}/result`, { headers: authHeaders() }));
  },
  async cancelJob(jobId: string): Promise<JobView> {
    return parse(await fetch(`${BASE}/api/jobs/${jobId}/cancel`, { method: "POST", headers: authHeaders() }));
  },
  async pollJob(jobId: string, onUpdate?: (j: JobView & Record<string, unknown>) => void, intervalMs = 500, timeoutMs = 600_000): Promise<JobView> {
    const terminal = new Set(["completed", "partial", "failed", "cancelled", "expired"]);
    const start = Date.now();
    for (;;) {
      const j = await api.job(jobId);
      onUpdate?.(j);
      if (terminal.has(j.status)) return api.jobResult(jobId);
      if (Date.now() - start > timeoutMs) throw new ApiClientError("job_poll_timeout", "Timed out waiting for the background job.");
      await new Promise((r) => setTimeout(r, intervalMs));
    }
  },
};
