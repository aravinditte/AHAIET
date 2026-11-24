export interface ApiErrorBody { error: { code: string; message: string; detail: string | null } }
export interface UploadMeta { id: string; format: string; width: number; height: number; size_bytes: number; sha256: string }
export interface LanguageProfile { id: string; name: string; script: string | null; status: string; translation_status: string; note?: string }
export interface Capabilities {
  db_ok: boolean;
  upload: { status: string; max_bytes: number; max_pixels: number; formats: string[] };
  preprocessing: { status: string; pillow: boolean; opencv: boolean; note: string | null };
  ocr: { status: string; tesseract: { available: boolean; path: string | null; reason: string | null }; kraken: { available: boolean; reason: string | null } };
  translation: { status: string; reason: string | null };
  languages: string[];
}
export interface TranslationResult {
  request_id: string; status: string; detected_language: string | null; selected_language: string | null;
  script: string | null; original_ocr_text: string | null; corrected_source_text: string | null;
  english_translation: string | null; translation_method: string | null; source_references: unknown[];
  uncertain_spans: unknown[]; warnings: string[]; model_versions: Record<string, unknown>; processing_time_ms: number;
}
