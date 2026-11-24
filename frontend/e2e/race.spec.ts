import { expect, test } from "@playwright/test";

// NEW-25 / NEW-06: deterministic frontend race test. All backend
// calls are intercepted; the translate response is held back by a
// gate promise and resolved only AFTER the user edits the corrected
// text. The stale result must be discarded silently (input
// fingerprint mismatch), and a second, current request must publish.
// No real backend and no timing sleeps are involved.

const PNG_1PX = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAwMCAO+ip1sAAAAASUVORK5CYII=",
  "base64");

const CAPS = {
  db_ok: true,
  upload: { status: "ok", max_bytes: 1000000, max_pixels: 1000000, formats: ["png"] },
  preprocessing: { status: "ok", pillow: true, opencv: false, profiles: ["conservative"], note: null },
  ocr: { status: "ok", tesseract: { available: true, usable: true, path: "/usr/bin/tesseract", traineddata: { lang: "heb", available: true, prefix: null }, reason: null },
         kraken: { available: false, reason: "not installed" } },
  corpus: { status: "ok", passages: 1, by_language: { biblical_hebrew: 1 }, words: 10, reason: null },
  morphology: { status: "ok", reason: null },
  translation: { status: "ok", verified_reference: true, reason: null },
  languages: ["biblical_hebrew"],
};

const OCR_RESULT = {
  request_id: "req-1", status: "ok", original_ocr_text: "בראשית ברא",
  uncertain_spans: [], mean_confidence: null, word_count: 2,
  ocr_engine: "tesseract", ocr_lang: "heb", ocr_profile: "conservative",
  ocr_profile_note: "", psm: null,
  preprocessing: { profile: "conservative", steps: [] }, processing_time_ms: 5,
};

function translationResult(english: string) {
  return {
    request_id: "tr-1", status: "completed", detected_language: "biblical_hebrew",
    selected_language: "biblical_hebrew", script: "Hebrew",
    original_ocr_text: null, corrected_source_text: "בראשית ברא",
    english_translation: english, translation_method: "verified_reference",
    source_references: [], uncertain_spans: [], warnings: [], model_versions: {},
    processing_time_ms: 5, engine: "verified_reference", model_version: null,
    artifact_sha256: null, coverage: null,
  };
}

test("stale translate response is discarded after an edit (NEW-06)", async ({ page }) => {
  let releaseTranslate: (() => void) | null = null;
  let translateCalls = 0;
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    if (path.endsWith("/api/capabilities")) return route.fulfill({ json: CAPS });
    if (path.endsWith("/api/languages")) return route.fulfill({ json: { languages: [
      { id: "biblical_hebrew", name: "Biblical Hebrew", script: "Hebrew", status: "supported", translation_status: "retrieval_available" },
      { id: "biblical_aramaic", name: "Biblical Aramaic", script: "Hebrew", status: "supported", translation_status: "not_provisioned" },
    ] } });
    if (path.endsWith("/api/scripts")) return route.fulfill({ json: { scripts: [
      { id: "hebrew_square", name: "Hebrew (square script)", script: "Hebrew", route: "tesseract", status: "supported", tier: "operational", reason: null, evaluation: null, checkpoint: null },
    ] } });
    if (path.endsWith("/api/uploads") && req.method() === "POST") {
      return route.fulfill({ json: { id: "up-1", format: "png", width: 10, height: 10, size_bytes: 68, sha256: "x" } });
    }
    if (path.includes("/api/uploads/") && req.method() === "GET") {
      return route.fulfill({ body: PNG_1PX, contentType: "image/png" });
    }
    if (path.endsWith("/api/ocr")) return route.fulfill({ json: OCR_RESULT });
    if (path.endsWith("/api/translate")) {
      translateCalls += 1;
      if (translateCalls === 1) {
        // Hold the first response until the test releases it.
        await new Promise<void>((resolve) => { releaseTranslate = resolve; });
        // The client aborts the request when the input changes; a
        // fulfill against the aborted request is a no-op error.
        try { return await route.fulfill({ json: translationResult("STALE RESULT") }); }
        catch { return; }
      }
      return route.fulfill({ json: translationResult("FRESH RESULT") });
    }
    return route.fulfill({ status: 404, json: { error: { code: "not_mocked", message: path, detail: null } } });
  });

  await page.goto("/");
  await page.getByTestId("file-input").setInputFiles({
    name: "page.png", mimeType: "image/png", buffer: PNG_1PX,
  });
  await expect(page.getByTestId("extract-button")).toBeEnabled();
  await page.getByTestId("extract-button").click();
  await expect(page.getByTestId("corrected-source")).toHaveValue("בראשית ברא");

  // Start a translation, then edit the text while it is in flight.
  await page.getByTestId("translate-button").click();
  await expect.poll(() => translateCalls).toBe(1);
  await page.getByTestId("corrected-source").fill("טקסט אחר לגמרי");
  releaseTranslate!();

  // The stale response arrives now, but its fingerprint no longer
  // matches the current inputs: it must never be published.
  await page.waitForTimeout(300);
  await expect(page.getByTestId("translation-output")).not.toContainText("STALE RESULT");
  await expect(page.getByTestId("translation-output")).toContainText("No translation yet");

  // A fresh request for the current input publishes normally.
  await page.getByTestId("translate-button").click();
  await expect(page.getByTestId("translation-output")).toContainText("FRESH RESULT");
});

test("starting OCR supersedes previous output and disables translation (NEW-07)", async ({ page }) => {
  let releaseOcr: (() => void) | null = null;
  let ocrCalls = 0;
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path.endsWith("/api/capabilities")) return route.fulfill({ json: CAPS });
    if (path.endsWith("/api/languages")) return route.fulfill({ json: { languages: [] } });
    if (path.endsWith("/api/scripts")) return route.fulfill({ json: { scripts: [] } });
    if (path.endsWith("/api/uploads") && req.method() === "POST") {
      return route.fulfill({ json: { id: "up-1", format: "png", width: 10, height: 10, size_bytes: 68, sha256: "x" } });
    }
    if (path.includes("/api/uploads/")) return route.fulfill({ body: PNG_1PX, contentType: "image/png" });
    if (path.endsWith("/api/ocr")) {
      ocrCalls += 1;
      if (ocrCalls === 2) await new Promise<void>((resolve) => { releaseOcr = resolve; });
      return route.fulfill({ json: OCR_RESULT });
    }
    return route.fulfill({ status: 404, json: { error: { code: "not_mocked", message: path, detail: null } } });
  });

  await page.goto("/");
  await page.getByTestId("file-input").setInputFiles({
    name: "page.png", mimeType: "image/png", buffer: PNG_1PX,
  });
  await page.getByTestId("extract-button").click();
  await expect(page.getByTestId("corrected-source")).toHaveValue("בראשית ברא");
  await expect(page.getByTestId("translate-button")).toBeEnabled();

  // Second OCR run: previous output is superseded immediately and
  // translation is disabled while the run is in flight.
  await page.getByTestId("extract-button").click();
  await expect(page.getByTestId("ocr-superseded-note")).toBeVisible();
  await expect(page.getByTestId("translate-button")).toBeDisabled();
  releaseOcr!();
  await expect(page.getByTestId("corrected-source")).toHaveValue("בראשית ברא");
  await expect(page.getByTestId("translate-button")).toBeEnabled();
});
