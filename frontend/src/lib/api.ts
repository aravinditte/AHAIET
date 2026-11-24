import type { Capabilities, LanguageProfile, TranslationResult, UploadMeta } from "@/types/api";
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
export const api = {
  base: BASE,
  async capabilities(): Promise<Capabilities> { return parse(await fetch(`${BASE}/api/capabilities`)); },
  async languages(): Promise<LanguageProfile[]> { const d = await parse<{ languages: LanguageProfile[] }>(await fetch(`${BASE}/api/languages`)); return d.languages; },
  async upload(file: File): Promise<UploadMeta> { const fd = new FormData(); fd.append("file", file); return parse(await fetch(`${BASE}/api/uploads`, { method: "POST", body: fd })); },
  uploadUrl(id: string): string { return `${BASE}/api/uploads/${id}`; },
  async ocr(uploadId: string, languageProfile?: string): Promise<{ original_ocr_text: string }> {
    return parse(await fetch(`${BASE}/api/ocr`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ upload_id: uploadId, language_profile: languageProfile ?? null }) }));
  },
  async translate(text: string, sourceLanguage?: string): Promise<TranslationResult> {
    return parse(await fetch(`${BASE}/api/translate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, source_language: sourceLanguage ?? null }) }));
  },
};
