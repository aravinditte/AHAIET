"use client";
import type { LanguageProfile } from "@/types/api";
export function LanguageSelector({ languages, value, onChange }: { languages: LanguageProfile[]; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label htmlFor="lang" className="font-semibold">Language profile</label>
      <select id="lang" value={value} onChange={(e) => onChange(e.target.value)} className="ml-2 rounded border p-1 dark:bg-neutral-800">
        <option value="">Uncertain — do not auto-classify</option>
        {languages.map((l) => (
          <option key={l.id} value={l.id} disabled={l.status === "unsupported"}>
            {l.name}{l.status === "unsupported" ? " (unsupported — no models/corpus yet)" : ""}
          </option>
        ))}
      </select>
      <p className="text-sm">Hebrew script alone does not distinguish Biblical Hebrew from Biblical Aramaic — that is why manual selection matters.</p>
    </div>
  );
}
