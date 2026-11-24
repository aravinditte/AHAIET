import { expect, test, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

// End-to-end translator specs, split by honesty (AHAIET-003/029):
//
// - "smoke (honest unsupported)" specs assert the backend's explicit
//   unsupported/unavailable error state and its content. They pass on
//   an unprovisioned machine BECAUSE the error is the correct product
//   behaviour there; they never accept an error as a translation.
// - "acceptance (provisioned)" specs assert real OCR + verified
//   translation. They are gated by AHAIET_E2E_GATE=release: with the
//   gate set they FAIL (never skip) when fixtures or models are
//   absent; without the gate, local runs may skip with the exact
//   prerequisite named.
//
// Fixture filenames come from the ONE canonical manifest
// (training/ocr/fixtures/fixtures.json), the same file the fixture
// generator writes from — no hardcoded names here.

const FIXTURES_DIR = path.resolve(__dirname, "../../training/ocr/fixtures");
const MANIFEST = JSON.parse(readFileSync(path.join(FIXTURES_DIR, "fixtures.json"), "utf-8")) as {
  fixtures: { id: string; filename: string; reference: string; language_profile: string }[];
};
const SAMPLE = path.resolve(__dirname, "../../training/datasets/fixtures/sample_passages.jsonl");
const RELEASE_GATE = process.env.AHAIET_E2E_GATE === "release";

function fixtureById(id: string) {
  const f = MANIFEST.fixtures.find((x) => x.id === id);
  if (!f) throw new Error(`fixture ${id} missing from the canonical fixtures.json manifest`);
  return f;
}

function fixtureImage(id: string): string {
  const f = fixtureById(id);
  const p = path.join(FIXTURES_DIR, f.filename);
  if (!existsSync(p)) {
    const msg = `prerequisite missing: ${p} — generate it with training/ocr/generate_fixtures.py`;
    if (RELEASE_GATE) throw new Error(`release gate: ${msg}`);
    test.skip(true, msg);
  }
  return p;
}

function passage(reference: string) {
  const rows = readFileSync(SAMPLE, "utf-8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
  const found = rows.find((p) => p.reference === reference);
  if (!found) throw new Error(`fixture passage ${reference} missing from sample_passages.jsonl`);
  return found;
}

async function waitForOcrOutcome(page: Page) {
  await expect.poll(async () => {
    const raw = await page.getByTestId("raw-ocr").textContent();
    const alerted = (await page.getByRole("alert").count()) > 0;
    return raw && !raw.includes("No OCR output yet") ? "text" : alerted ? "error" : "pending";
  }, { timeout: 30_000 }).not.toBe("pending");
  return page.getByTestId("raw-ocr").textContent();
}

function requireOcrText(raw: string | null, what: string) {
  if (!raw || raw.includes("No OCR output yet")) {
    if (RELEASE_GATE) throw new Error(`release gate: ${what} produced no text — provisioning is absent`);
    test.skip(true, `prerequisite missing: ${what} produced no text — provision Tesseract (binary + Hebrew traineddata) per docs/OCR.md`);
  }
}

test.describe("smoke (honest unsupported)", () => {
  test("Aramaic without provisioned OCR reports the honest error, not a translation", async ({ page }) => {
    const image = fixtureImage("daniel-2-4-aramaic");
    await page.goto("/");
    await page.getByLabel(/Language profile/).selectOption("biblical_aramaic");
    await page.locator("#file-input").setInputFiles(image);
    await expect(page.getByTestId("upload-preview")).toBeVisible();
    await expect(page.getByTestId("ocr-run")).toBeEnabled();
    await page.getByTestId("ocr-run").click();
    const raw = await waitForOcrOutcome(page);
    if (!raw || raw.includes("No OCR output yet")) {
      // The honest-unsupported contract: an explicit alert naming the
      // missing OCR provisioning, and no translation output at all.
      const alert = page.getByRole("alert");
      await expect(alert).toBeVisible();
      await expect(alert).toContainText(/OCR|Tesseract/i);
      await expect(page.getByTestId("translation-output")).not.toContainText(/In the beginning/);
    }
  });
});

test.describe("acceptance (provisioned)", () => {
  test("Hebrew flow: upload, OCR, verified translation, copy, export", async ({ page }) => {
    const image = fixtureImage("genesis-1-1-hebrew");
    await page.goto("/");
    await page.locator("#file-input").setInputFiles(image);
    await expect(page.getByTestId("upload-preview")).toBeVisible();
    await expect(page.getByTestId("ocr-run")).toBeEnabled();
    await page.getByTestId("ocr-run").click();
    const raw = await waitForOcrOutcome(page);
    requireOcrText(raw, "OCR");
    await expect(page.getByTestId("corrected-source")).not.toHaveValue("");
    await page.getByTestId("translate-run").click();
    const gen = passage("Genesis 1:1");
    await expect(page.getByTestId("translation-output")).toContainText(gen.english_text.slice(0, 40), { timeout: 30_000 });
    await page.getByTestId("copy-english").click();
    const clipboard = await page.evaluate(() => navigator.clipboard.readText());
    expect(clipboard).toContain(gen.english_text.slice(0, 40));
    const downloadPromise = page.waitForEvent("download");
    await page.getByTestId("export-json").click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("ahaiet-result.json");
  });

  test("Aramaic flow: explicit Aramaic profile, verified translation required", async ({ page }) => {
    const image = fixtureImage("daniel-2-4-aramaic");
    await page.goto("/");
    await page.getByLabel(/Language profile/).selectOption("biblical_aramaic");
    await page.locator("#file-input").setInputFiles(image);
    await expect(page.getByTestId("upload-preview")).toBeVisible();
    await expect(page.getByTestId("ocr-run")).toBeEnabled();
    await page.getByTestId("ocr-run").click();
    const raw = await waitForOcrOutcome(page);
    requireOcrText(raw, "Aramaic OCR");
    await page.getByTestId("translate-run").click();
    // Acceptance means the verified Aramaic translation itself —
    // an alert is a failure here, never an accepted alternative.
    const dan = passage("Daniel 2:4");
    await expect(page.getByTestId("translation-output")).toContainText(dan.english_text.slice(0, 40), { timeout: 30_000 });
    await expect(page.getByRole("alert")).toHaveCount(0);
  });
});
