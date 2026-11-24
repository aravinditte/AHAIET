import type { CoverageInfo, SourceReference, TranslationProvenance, VerificationReport } from "@/types/api";
export interface ExportState {
  rawOcrText: string; correctedSourceText: string; englishTranslation: string;
  languageProfile: string | null; uploadId: string | null;
  translationMethod: string | null; sourceReferences: SourceReference[];
  // Present when a trained local model produced the translation.
  engine?: string | null; modelVersion?: string | null;
  artifactSha256?: string | null; coverage?: CoverageInfo | null;
  // Hybrid verification summary + provenance, when a translation ran.
  verification?: VerificationReport | null;
  provenance?: TranslationProvenance | null;
}
export function citationLines(refs: SourceReference[]): string[] {
  if (!refs.length) return [];
  const lines = ["", "SOURCE REFERENCES (verified corpus matches)"];
  for (const r of refs) {
    lines.push(`- ${r.reference} — match: ${r.match_type}; source edition: ${r.source_edition}; translation edition: ${r.translation_edition}; licence: ${r.license}; provenance: ${r.provenance}`);
  }
  return lines;
}
export function modelLines(s: ExportState): string[] {
  if (!s.engine && !s.modelVersion) return [];
  const lines = ["", `Engine: ${s.engine ?? s.translationMethod ?? ""}`];
  if (s.modelVersion) lines.push(`Model version: ${s.modelVersion}`);
  if (s.artifactSha256) lines.push(`Artifact sha256: ${s.artifactSha256}`);
  if (s.coverage) lines.push(`Source-token coverage: ${s.coverage.known_tokens}/${s.coverage.source_tokens} (${Math.round(s.coverage.coverage_ratio * 100)}%); out-of-vocabulary: ${s.coverage.oov_words.length ? s.coverage.oov_words.join(", ") : "none"}`);
  return lines;
}
export function verificationLines(s: ExportState): string[] {
  if (!s.verification) return [];
  const lines = ["", `VERIFICATION (deterministic checks — they flag risks, they do not prove correctness): overall ${s.verification.overall_status}`];
  for (const c of s.verification.checks) lines.push(`- ${c.name}: ${c.status} — ${c.detail}`);
  return lines;
}
export function provenanceLines(s: ExportState): string[] {
  if (!s.provenance) return [];
  const p = s.provenance;
  const lines = ["", `Provenance: engine ${p.engine ?? "—"}`];
  if (p.model_version) lines.push(`Model version: ${p.model_version}`);
  if (p.artifact_sha256) lines.push(`Artifact sha256: ${p.artifact_sha256}`);
  if (p.evaluation_state) lines.push(`Evaluation state: ${p.evaluation_state}`);
  if (p.dataset_card_sha256) lines.push(`Dataset card sha256: ${p.dataset_card_sha256}`);
  if (p.retrieval_citation) lines.push(`Retrieval citation: ${p.retrieval_citation.reference} (${p.retrieval_citation.match_type})`);
  if (p.cached) lines.push("Served from the translation cache (same engine provenance).");
  return lines;
}
export function buildCombinedTxt(s: ExportState): string {
  return ["SECTION A - CAPTURED ORIGINAL TEXT (raw OCR)", s.rawOcrText, "", "CORRECTED SOURCE TEXT", s.correctedSourceText, "", "SECTION B - COMPLETE ENGLISH TRANSLATION", s.englishTranslation,
    ...(s.translationMethod ? ["", `Translation method: ${s.translationMethod}`] : []),
    ...modelLines(s),
    ...provenanceLines(s),
    ...verificationLines(s),
    ...citationLines(s.sourceReferences), ""].join("\n");
}
export function buildJsonExport(s: ExportState): string {
  return JSON.stringify({ language_profile: s.languageProfile, upload_id: s.uploadId, raw_ocr_text: s.rawOcrText, corrected_source_text: s.correctedSourceText, english_translation: s.englishTranslation, translation_method: s.translationMethod, engine: s.engine ?? null, model_version: s.modelVersion ?? null, artifact_sha256: s.artifactSha256 ?? null, coverage: s.coverage ?? null, source_references: s.sourceReferences, provenance: s.provenance ?? null, verification: s.verification ? { overall_status: s.verification.overall_status, checks: s.verification.checks.map((c) => ({ name: c.name, status: c.status, detail: c.detail })), empirical_uncertainty: s.verification.empirical_uncertainty } : null }, null, 2);
}
export function downloadText(filename: string, text: string, type = "text/plain;charset=utf-8"): void {
  const blob = new Blob([text], { type }); const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
  // AHAIET-046: revoke after the download has had a tick to start —
  // synchronous revocation can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
