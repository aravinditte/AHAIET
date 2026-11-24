export interface ApiErrorBody { error: { code: string; message: string; detail: string | null } }
export interface UploadMeta { id: string; format: string; width: number; height: number; size_bytes: number; sha256: string }
export interface LanguageProfile { id: string; name: string; script: string | null; status: string; translation_status: string; note?: string }
export interface SourceReference {
  passage_id: string; reference: string; book: string; language_profile: string;
  match_type: "exact" | "normalized" | "normalized_variant";
  source_edition: string; translation_edition: string; license: string; provenance: string;
  source_text: string; english_text: string; warning?: string; overlap?: number;
}
export interface UncertainSpan { text: string; conf: number; line: number; left: number; top: number; width: number; height: number }
export interface OcrResult {
  request_id: string; status: string; original_ocr_text: string;
  uncertain_spans: UncertainSpan[]; mean_confidence: number | null; word_count: number;
  ocr_engine: string; ocr_lang: string; ocr_profile: string; ocr_profile_note: string; psm: number;
  preprocessing: { profile: string; steps: { step: string; applied: boolean; note?: string }[] };
  processing_time_ms: number;
}
export interface Capabilities {
  db_ok: boolean;
  upload: { status: string; max_bytes: number; max_pixels: number; formats: string[] };
  preprocessing: { status: string; pillow: boolean; opencv: boolean; profiles: string[]; note: string | null };
  ocr: { status: string; tesseract: { available: boolean; path: string | null; traineddata: { lang: string; available: boolean; prefix: string | null }; reason: string | null }; kraken: { available: boolean; reason: string | null } };
  corpus: { status: string; passages: number; by_language: Record<string, number>; words: number; reason: string | null };
  morphology: { status: string; reason: string | null };
  translation: { status: string; verified_reference: boolean; reason: string | null };
  languages: string[];
}
export interface TranslationResult {
  request_id: string; status: string; detected_language: string | null; selected_language: string | null;
  script: string | null; original_ocr_text: string | null; corrected_source_text: string | null;
  english_translation: string | null; translation_method: string | null; source_references: SourceReference[];
  uncertain_spans: unknown[]; warnings: string[]; model_versions: Record<string, unknown>; processing_time_ms: number;
}
