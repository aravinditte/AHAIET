import { describe, it, expect } from "vitest";
import { buildCombinedTxt, buildJsonExport } from "./export";
const HEBREW = "\u05d1\u05b0\u05bc\u05e8\u05b5\u05d0\u05e9\u05b4\u05c1\u05d9\u05ea";
describe("export formatting", () => {
  it("round-trips Hebrew Unicode in TXT and JSON", () => {
    const s = { rawOcrText: HEBREW, correctedSourceText: HEBREW, englishTranslation: "", languageProfile: "biblical_hebrew", uploadId: null };
    expect(buildCombinedTxt(s)).toContain(HEBREW);
    const parsed = JSON.parse(buildJsonExport(s));
    expect(parsed.corrected_source_text).toBe(HEBREW);
    expect(parsed.english_translation).toBe("");
  });
  it("keeps raw OCR and corrected text as separate sections", () => {
    const txt = buildCombinedTxt({ rawOcrText: "raw", correctedSourceText: "fixed", englishTranslation: "eng", languageProfile: null, uploadId: null });
    expect(txt.indexOf("raw")).toBeLessThan(txt.indexOf("fixed"));
    expect(txt).toContain("SECTION B");
  });
});
