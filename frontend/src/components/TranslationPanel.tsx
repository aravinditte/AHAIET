"use client";
import type { TranslationResult } from "@/types/api";

export function TranslationPanel({ result }: { result: TranslationResult | null }) {
  const translation = result?.english_translation ?? "";
  const refs = result?.source_references ?? [];
  return (
    <section aria-labelledby="tr-h" className="rounded border p-4">
      <h2 id="tr-h" className="font-semibold">Step 5 — Complete English translation</h2>
      <div dir="ltr" lang="en" className="mt-2 min-h-16 whitespace-pre-wrap rounded border p-2">
        {translation || <span className="text-sm opacity-70">No translation yet. A translation appears only for a verified corpus match or a real provisioned local model — never a dictionary gloss or example.</span>}
      </div>
      {result?.translation_method && (
        <p className="mt-2 text-sm">Method: <strong>{result.translation_method}</strong>
          {result.translation_method === "verified_reference" ? " — the English below is the cited edition's text for the matched passage, not a generated paraphrase." : ""}</p>
      )}
      {refs.length > 0 && (
        <div className="mt-2 rounded border p-2 text-sm" aria-label="Source references">
          <h3 className="font-medium">Source references</h3>
          <ul className="mt-1 space-y-1">
            {refs.map((r) => (
              <li key={r.passage_id}>
                <strong>{r.reference}</strong> — match: {r.match_type}; source edition: {r.source_edition};
                translation edition: {r.translation_edition}; licence: {r.license}; provenance: {r.provenance}
                {r.warning ? <> — {r.warning}</> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
      {result && result.warnings.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-sm" aria-label="Warnings">
          {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}
    </section>
  );
}
