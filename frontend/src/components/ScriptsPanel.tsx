"use client";
import React from "react";
import { api } from "@/lib/api";
import type { ScriptSupport } from "@/types/api";

/**
 * Script support matrix, computed live by the backend (GET /api/scripts).
 * A historical script is shown as supported only when a measured
 * evaluation record exists whose checkpoint hash matches a checkpoint
 * file on disk; otherwise the specific missing evidence is the reason.
 */
export function ScriptsPanel() {
  const [scripts, setScripts] = React.useState<ScriptSupport[] | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  React.useEffect(() => { api.scripts().then(setScripts).catch((e) => setErr(String(e))); }, []);
  if (err) return null;
  if (!scripts) return null;
  return (
    <section aria-labelledby="scripts-h" className="rounded border p-4">
      <h2 id="scripts-h" className="font-semibold">Script support (computed live — never assumed)</h2>
      <ul className="mt-2 space-y-1 text-sm">
        {scripts.map((s) => (
          <li key={s.id} className="flex gap-2">
            <span aria-hidden>{s.status === "supported" ? "●" : "○"}</span>
            <span>
              <strong>{s.name}</strong> ({s.script}): {s.status}
              {s.status === "supported" && s.evaluation
                ? <> — engine {s.engine}; measured CER {s.evaluation.cer} on {s.evaluation.test_set ?? "recorded test set"}</>
                : s.reason ? <> — {s.reason}</> : null}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
