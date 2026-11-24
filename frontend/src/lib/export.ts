export interface ExportState { rawOcrText: string; correctedSourceText: string; englishTranslation: string; languageProfile: string | null; uploadId: string | null }
export function buildCombinedTxt(s: ExportState): string {
  return ["SECTION A - CAPTURED ORIGINAL TEXT (raw OCR)", s.rawOcrText, "", "CORRECTED SOURCE TEXT", s.correctedSourceText, "", "SECTION B - COMPLETE ENGLISH TRANSLATION", s.englishTranslation, ""].join("\n");
}
export function buildJsonExport(s: ExportState): string {
  return JSON.stringify({ language_profile: s.languageProfile, upload_id: s.uploadId, raw_ocr_text: s.rawOcrText, corrected_source_text: s.correctedSourceText, english_translation: s.englishTranslation }, null, 2);
}
export function downloadText(filename: string, text: string, type = "text/plain;charset=utf-8"): void {
  const blob = new Blob([text], { type }); const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url);
}
