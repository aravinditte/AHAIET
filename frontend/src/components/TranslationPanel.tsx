"use client";
export function TranslationPanel({ translation }: { translation: string }) {
  return (
    <section aria-labelledby="tr-h" className="rounded border p-4">
      <h2 id="tr-h" className="font-semibold">Step 5 — Complete English translation</h2>
      <div dir="ltr" lang="en" className="mt-2 min-h-16 whitespace-pre-wrap rounded border p-2">
        {translation || <span className="text-sm opacity-70">No translation yet. A translation appears only when a real local model is provisioned — never a dictionary gloss or example.</span>}
      </div>
    </section>
  );
}
