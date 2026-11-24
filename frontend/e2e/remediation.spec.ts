import { expect, test } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

// Frontend remediation specs (AHAIET-027/003). Fixture filenames come
// from the canonical manifest, as in translator.spec.ts.
const FIXTURES_DIR = path.resolve(__dirname, "../../training/ocr/fixtures");
const MANIFEST = JSON.parse(readFileSync(path.join(FIXTURES_DIR, "fixtures.json"), "utf-8")) as {
  fixtures: { id: string; filename: string }[];
};

test("test_switch_language_invalidates_translation", async ({ page }) => {
  const f = MANIFEST.fixtures.find((x) => x.id === "genesis-1-1-hebrew");
  if (!f) throw new Error("fixture missing from canonical manifest");
  const image = path.join(FIXTURES_DIR, f.filename);
  test.skip(!existsSync(image), `prerequisite missing: ${image} — run training/ocr/generate_fixtures.py`);
  await page.goto("/");
  await page.locator("#file-input").setInputFiles(image);
  await expect(page.getByTestId("ocr-run")).toBeEnabled();
  await page.getByTestId("ocr-run").click();
  const raw = await page.getByTestId("raw-ocr").textContent();
  test.skip(!raw || raw.includes("No OCR output yet"),
    "prerequisite missing: OCR produced no text — provision Tesseract per docs/OCR.md");
  await page.getByTestId("translate-run").click();
  await expect(page.getByTestId("translation-output")).not.toContainText("No translation yet", { timeout: 30_000 });
  // Switching the language profile must clear the displayed
  // translation: a Hebrew result may never sit under Aramaic.
  await page.getByLabel(/Language profile/).selectOption("biblical_aramaic");
  await expect(page.getByTestId("translation-output")).toContainText("No translation yet");
  // Editing the corrected text also invalidates.
  await page.getByLabel(/Language profile/).selectOption("biblical_hebrew");
  await page.getByTestId("translate-run").click();
  await expect(page.getByTestId("translation-output")).not.toContainText("No translation yet", { timeout: 30_000 });
  await page.getByTestId("corrected-source").fill("אחר");
  await expect(page.getByTestId("translation-output")).toContainText("No translation yet");
});
