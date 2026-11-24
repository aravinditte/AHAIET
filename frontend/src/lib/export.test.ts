import { describe, it, expect } from "vitest";
import { buildCombinedTxt, buildJsonExport } from "./export";
import type { SourceReference } from "@/types/api";
const HEBREW = "\u05d1\u05b0\u05bc\u05e8\u05b5\u05d0\u05e9\u05b4\u05c1\u05d9\u05ea";
const base = { rawOcrText: HEBREW, correctedSourceText: HEBREW, englishTranslation: "", languageProfile: "biblical_hebrew", uploadId: null, translationMethod: null, sourceReferences: [] as SourceReference[] };
describe("export formatting", () => {
  it("round-trips Hebrew Unicode in TXT and JSON", () => {
    expect(buildCombinedTxt(base)).toContain(HEBREW);
    const parsed = JSON.parse(buildJsonExport(base));
    expect(parsed.corrected_source_text).toBe(HEBREW);
    expect(parsed.english_translation).toBe("");
  });
  it("keeps raw OCR and corrected text as separate sections", () => {
    const txt = buildCombinedTxt({ ...base, rawOcrText: "raw", correctedSourceText: "fixed", englishTranslation: "eng" });
    expect(txt.indexOf("raw")).toBeLessThan(txt.indexOf("fixed"));
    expect(txt).toContain("SECTION B");
  });
  it("includes trained-model engine fields in TXT and JSON exports when present", () => {
    const s = { ...base, englishTranslation: "MOSES-OUT text", translationMethod: "moses",
      engine: "moses", modelVersion: "moses-smt-hebrew-abcd1234",
      artifactSha256: "f".repeat(64),
      coverage: { source_tokens: 4, known_tokens: 3, coverage_ratio: 0.75, oov_words: ["מלך"] } };
    const parsed = JSON.parse(buildJsonExport(s));
    expect(parsed.engine).toBe("moses");
    expect(parsed.model_version).toBe("moses-smt-hebrew-abcd1234");
    expect(parsed.artifact_sha256).toBe("f".repeat(64));
    expect(parsed.coverage.oov_words).toEqual(["מלך"]);
    const txt = buildCombinedTxt(s);
    expect(txt).toContain("Engine: moses");
    expect(txt).toContain("Model version: moses-smt-hebrew-abcd1234");
    expect(txt).toContain("Source-token coverage: 3/4 (75%)");
  });
  it("includes verification summary and provenance in exports when present", () => {
    const s = { ...base, englishTranslation: "In the beginning",
      provenance: { engine: "verified_reference", model_id: null, model_version: null, artifact_sha256: null, evaluation_state: null, dataset_card_sha256: null, retrieval_citation: { passage_id: "p1", reference: "Genesis 1:1", match_type: "exact", source_edition: "WLC", translation_edition: "WEB", license: "Public Domain", provenance: "morphhb" }, cached: false },
      verification: { overall_status: "warnings" as const, note: "checks flag risks", empirical_uncertainty: { retrieval_match_type: "exact" },
        checks: [{ name: "negation", status: "pass" as const, detail: "counts match", evidence: {} }] } };
    const parsed = JSON.parse(buildJsonExport(s));
    expect(parsed.verification.overall_status).toBe("warnings");
    expect(parsed.verification.checks[0].name).toBe("negation");
    expect(parsed.provenance.retrieval_citation.reference).toBe("Genesis 1:1");
    const txt = buildCombinedTxt(s);
    expect(txt).toContain("VERIFICATION");
    expect(txt).toContain("Retrieval citation: Genesis 1:1 (exact)");
  });
  it("includes verified-reference citation and match fields when present", () => {
    const ref: SourceReference = { passage_id: "morphhb-gen-1-1", reference: "Genesis 1:1", book: "Genesis", language_profile: "biblical_hebrew", match_type: "exact", source_edition: "WLC via morphhb", translation_edition: "World English Bible (WEB)", license: "Public Domain", provenance: "morphhb OSIS Gen.xml", source_text: HEBREW, english_text: "In the beginning" };
    const s = { ...base, englishTranslation: "In the beginning", translationMethod: "verified_reference", sourceReferences: [ref] };
    const parsed = JSON.parse(buildJsonExport(s));
    expect(parsed.translation_method).toBe("verified_reference");
    expect(parsed.source_references[0].match_type).toBe("exact");
    expect(parsed.source_references[0].reference).toBe("Genesis 1:1");
    const txt = buildCombinedTxt(s);
    expect(txt).toContain("Genesis 1:1");
    expect(txt).toContain("match: exact");
  });
});
