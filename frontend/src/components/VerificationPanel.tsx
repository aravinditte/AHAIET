"use client";
import type { VerificationReport } from "@/types/api";

const STATUS_LABEL: Record<string, string> = {
  pass: "pass", warn: "warning", fail: "flagged", not_applicable: "not applicable",
};

/**
 * Deterministic verification checks for a candidate translation.
 * These checks flag risks — missing numbers, dropped negations,
 * uncovered source words — they do NOT prove a translation is correct,
 * and the panel says so in plain language.
 */
export function VerificationPanel({ report }: { report: VerificationReport | null | undefined }) {
  if (!report) return null;
  const uncertainty = Object.entries(report.empirical_uncertainty ?? {});
  return (
    <section aria-labelledby="ver-h" className="mt-3 rounded border p-3">
      <h3 id="ver-h" className="font-medium">Verification checks — overall: {report.overall_status.replaceAll("_", " ")}</h3>
      <p className="mt-1 text-sm">{report.note}</p>
      <ul className="mt-2 space-y-1 text-sm" aria-label="Verification checks">
        {report.checks.map((c) => (
          <li key={c.name} className="flex gap-2">
            <span aria-hidden>{c.status === "pass" ? "●" : c.status === "not_applicable" ? "○" : "▲"}</span>
            <span><strong>{c.name.replaceAll("_", " ")}:</strong> {STATUS_LABEL[c.status] ?? c.status} — {c.detail}</span>
          </li>
        ))}
      </ul>
      {uncertainty.length > 0 && (
        <div className="mt-2 text-sm" aria-label="Measured uncertainty inputs">
          <h4 className="font-medium">Measured inputs (from the engines, not computed here)</h4>
          <ul className="mt-1 space-y-1">
            {uncertainty.map(([k, v]) => (
              <li key={k}>{k.replaceAll("_", " ")}: {typeof v === "object" ? JSON.stringify(v) : String(v)}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
