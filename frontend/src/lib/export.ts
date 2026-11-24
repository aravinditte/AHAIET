import type { SourceReference } from "@/types/api";
export interface ExportState {
  rawOcrText: string; correctedSourceText: string; englishTranslation: string;
  languageProfile: string | null; uploadId: string | null;
  translationMethod: string | null; sourceReferences: SourceReference[];
}
export function citationLines(refs: SourceReference[]): string[] {
  if (!refs.length) return [];
  const lines = ["", "SOURCE REFERENCES (verified corpus matches)"];
  for (const r of refs) {
    lines.push(`- ${r.reference} — match: ${r.match_type}; source edition: ${r.source_edition}; translation edition: ${r.translation_edition}; licence: ${r.license}; provenance: ${r.provenance}`);
  }
  return lines;
}
export function buildCombinedTxt(s: ExportState): string {
  return ["SECTION A - CAPTURED ORIGINAL TEXT (raw OCR)", s.rawOcrText, "", "CORRECTED SOURCE TEXT", s.correctedSourceText, "", "SECTION B - COMPLETE ENGLISH TRANSLATION", s.englishTranslation,
    ...(s.translationMethod ? ["", `Translation method: ${s.translationMethod}`] : []),
    ...citationLines(s.sourceReferences), ""].join("\n");
}
export function buildJsonExport(s: ExportState): string {
  return JSON.stringify({ language_profile: s.languageProfile, upload_id: s.uploadId, raw_ocr_text: s.rawOcrText, corrected_source_text: s.correctedSourceText, english_translation: s.englishTranslation, translation_method: s.translationMethod, source_references: s.sourceReferences }, null, 2);
}
export function downloadText(filename: string, text: string, type = "text/plain;charset=utf-8"): void {
  const blob = new Blob([text], { type }); const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url);
}
