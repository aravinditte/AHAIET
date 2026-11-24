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
  // AHAIET-047: manual refresh + refresh on window focus.
  const load = React.useCallback(() => {
    api.scripts().then(setScripts).catch((e) => setErr(String(e)));
  }, []);
  React.useEffect(() => {
    load();
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [load]);
  if (err) return null;
  if (!scripts) return null;
  return (
    <section aria-labelledby="scripts-h" className="rounded border p-4">
      <h2 id="scripts-h" className="font-semibold">Script support (computed live — never assumed)</h2>
      <button type="button" onClick={load} className="mt-1 rounded border px-2 py-0.5 text-sm">Refresh script support</button>
      <ul className="mt-2 space-y-1 text-sm">
        {scripts.map((s) => (
          <li key={s.id} className="flex gap-2">
            <span aria-hidden>{s.status === "supported" ? "●" : "○"}</span>
            <span>
              <strong>{s.name}</strong> ({s.script}): {s.status}{s.tier ? <> — tier: {s.tier}</> : null}
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
