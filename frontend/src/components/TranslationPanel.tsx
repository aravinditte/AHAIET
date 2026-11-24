"use client";
import type { TranslationResult } from "@/types/api";
import { VerificationPanel } from "@/components/VerificationPanel";

export function TranslationPanel({ result }: { result: TranslationResult | null }) {
  const translation = result?.english_translation ?? "";
  const refs = result?.source_references ?? [];
  const segments = result?.segments ?? [];
  const timings = result?.stage_timings_ms ?? {};
  return (
    <section aria-labelledby="tr-h" className="rounded border p-4">
      <h2 id="tr-h" className="font-semibold">Step 5 — Complete English translation</h2>
      {result?.status === "partial" && (
        <p role="status" className="mt-2 rounded border border-amber-500 p-2 text-sm">
          Partial translation: some lines were translated and some were not. Untranslated lines are
          shown empty below with their reason — nothing was invented for them.
        </p>
      )}
      <div dir="ltr" lang="en" data-testid="translation-output" aria-live="polite" className="mt-2 min-h-16 whitespace-pre-wrap rounded border p-2">
        {translation || <span className="text-sm opacity-70">No translation yet. A translation appears only for a verified corpus match or a real provisioned local model — never a dictionary gloss or example.</span>}
      </div>
      {result?.provenance && (
        <p className="mt-2 text-sm" aria-label="Provenance">
          Provenance: engine <strong>{result.provenance.engine ?? "—"}</strong>
          {result.provenance.model_version ? <> · version {result.provenance.model_version}</> : null}
          {result.provenance.artifact_sha256 ? <> · artifact sha256 {result.provenance.artifact_sha256.slice(0, 12)}…</> : null}
          {result.provenance.evaluation_state ? <> · evaluation: {result.provenance.evaluation_state}</> : null}
          {result.provenance.retrieval_citation ? <> · citation: {result.provenance.retrieval_citation.reference} ({result.provenance.retrieval_citation.match_type})</> : null}
          {result.cached ? <> · <strong>served from the translation cache</strong> (same engine provenance)</> : null}
          {result.unevaluated_model ? <> · <strong>unevaluated model</strong>: no harness-recorded metrics exist for this model</> : null}
        </p>
      )}
      {segments.length > 1 && (
        <div className="mt-3" aria-label="Passage segments">
          <h3 className="font-medium">Passage lines</h3>
          <ol className="mt-1 space-y-2 text-sm">
            {segments.map((s) => (
              <li key={s.index} className="rounded border p-2">
                <div dir="rtl" lang="he" className="whitespace-pre-wrap">{s.source_text}</div>
                {s.english_translation
                  ? <div dir="ltr" lang="en" className="mt-1 whitespace-pre-wrap">{s.english_translation}</div>
                  : <div className="mt-1 opacity-80">Not translated — {s.error ?? "unavailable"}</div>}
                <div className="mt-1 opacity-70">status: {s.status}{s.method ? ` · method: ${s.method}` : ""}</div>
                {s.warnings.length > 0 && <ul className="list-disc pl-5">{s.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
              </li>
            ))}
          </ol>
        </div>
      )}
      <VerificationPanel report={result?.verification} />
      {Object.keys(timings).length > 0 && (
        <details className="mt-3 text-sm">
          <summary>Stage timings (measured on this machine, milliseconds)</summary>
          <ul className="mt-1 space-y-1">
            {Object.entries(timings).map(([k, v]) => <li key={k}>{k}: {v} ms</li>)}
          </ul>
        </details>
      )}
      {result?.translation_method && (
        <p className="mt-2 text-sm">Method: <strong>{result.translation_method}</strong>
          {result.translation_method === "verified_reference" ? " — the English below is the cited edition's text for the matched passage, not a generated paraphrase." : ""}</p>
      )}
      {result && (result.translation_method === "moses" || result.translation_method === "marian") && (
        <p className="mt-2 text-sm" aria-label="Model details">
          Engine: <strong>{result.engine ?? result.translation_method}</strong>
          {result.model_version ? <> · model version: {result.model_version}</> : null}
          {result.artifact_sha256 ? <> · artifact sha256: {result.artifact_sha256.slice(0, 12)}…</> : null}
          {typeof result.model_versions?.evaluation_state === "string"
            ? <> · evaluation state: {result.model_versions.evaluation_state}</> : null}
          {result.coverage
            ? <> · source-token coverage: {Math.round(result.coverage.coverage_ratio * 100)}%
                ({result.coverage.known_tokens}/{result.coverage.source_tokens} tokens;
                out-of-vocabulary: {result.coverage.oov_words.length
                  ? result.coverage.oov_words.join(", ") : "none"})</>
            : null}
        </p>
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
