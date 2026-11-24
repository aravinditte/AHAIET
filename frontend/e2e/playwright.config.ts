import { defineConfig } from "@playwright/test";

// Browser end-to-end tests for the translator flow. These are NOT part
// of always-on CI: they need a running backend, a provisioned
// Tesseract (binary + Hebrew traineddata), and the imported reference
// corpus. See e2e/README.md for the full prerequisite list and the
// exact commands. The config starts only the frontend dev server; the
// backend is started separately (docs/VERIFICATION.md).
export default defineConfig({
  testDir: ".",
  timeout: 60_000,
  use: {
    baseURL: process.env.AHAIET_E2E_BASE_URL ?? "http://localhost:3000",
    // The flows exercise the real copy buttons.
    permissions: ["clipboard-read", "clipboard-write"],
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
