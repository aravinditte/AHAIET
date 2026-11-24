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
  ocr_engine: string; ocr_lang: string | null; ocr_profile: string; ocr_profile_note: string; psm: number | null;
  preprocessing: { profile: string; steps: { step: string; applied: boolean; note?: string }[] };
  processing_time_ms: number;
  // Additive: engine routing + per-stage timings.
  script_profile?: string; engine_version?: string | null;
  lines?: { line: number; text: string; mean_confidence: number | null }[] | null;
  stage_timings_ms?: Record<string, number>;
}
export interface ScriptSupport {
  id: string; name: string; script: string; route: string; note?: string;
  status: "supported" | "unsupported"; engine: string | null; reason: string | null;
  evaluation: { cer: number; wer?: number | null; test_set?: string; evaluated_at?: string } | null;
  checkpoint: { id: string | null; path: string; sha256: string } | null;
}
export interface Capabilities {
  db_ok: boolean;
  upload: { status: string; max_bytes: number; max_pixels: number; formats: string[] };
  preprocessing: { status: string; pillow: boolean; opencv: boolean; profiles: string[]; note: string | null };
  ocr: { status: string; tesseract: { available: boolean; path: string | null; traineddata: { lang: string; available: boolean; prefix: string | null }; reason: string | null };
    kraken: { available: boolean; reason: string | null; version?: string | null; ketos_cli?: string | null;
      checkpoints?: { id: string | null; script_profile: string | null; path: string; sha256: string }[] };
    scripts?: ScriptSupport[] };
  corpus: { status: string; passages: number; by_language: Record<string, number>; words: number; reason: string | null };
  morphology: { status: string; reason: string | null };
  translation: { status: string; verified_reference: boolean; reason: string | null;
    per_profile?: Record<string, { status: string; verified_reference: boolean; engine: string | null;
      evaluation_state: string | null; model_version: string | null }> };
  languages: string[];
}
export interface CoverageInfo {
  source_tokens: number; known_tokens: number; coverage_ratio: number; oov_words: string[];
}
export interface VerificationCheck {
  name: string; status: "pass" | "warn" | "fail" | "not_applicable";
  detail: string; evidence: Record<string, unknown>;
}
export interface VerificationReport {
  overall_status: "no_issues_found" | "warnings" | "high_risk";
  checks: VerificationCheck[];
  empirical_uncertainty: Record<string, unknown>;
  note: string;
}
export interface PassageSegmentResult {
  index: number; source_text: string; status: string;
  english_translation: string | null; method: string | null;
  warnings: string[]; error: string | null;
}
export interface TranslationProvenance {
  engine: string | null; model_id: string | null; model_version: string | null;
  artifact_sha256: string | null; evaluation_state: string | null;
  dataset_card_sha256: string | null;
  retrieval_citation: { passage_id: string; reference: string; match_type: string;
    source_edition: string; translation_edition: string; license: string; provenance: string } | null;
  cached: boolean;
}
export interface TranslationResult {
  request_id: string; status: string; detected_language: string | null; selected_language: string | null;
  script: string | null; original_ocr_text: string | null; corrected_source_text: string | null;
  english_translation: string | null; translation_method: string | null; source_references: SourceReference[];
  uncertain_spans: unknown[]; warnings: string[]; model_versions: Record<string, unknown>; processing_time_ms: number;
  // Additive fields, populated when a trained local model produced the output.
  engine: string | null; model_version: string | null; artifact_sha256: string | null;
  coverage: CoverageInfo | null;
  // Additive hybrid-verification, passage, and performance fields.
  verification?: VerificationReport | null;
  provenance?: TranslationProvenance | null;
  segments?: PassageSegmentResult[];
  unevaluated_model?: boolean;
  cached?: boolean;
  stage_timings_ms?: Record<string, number>;
}
