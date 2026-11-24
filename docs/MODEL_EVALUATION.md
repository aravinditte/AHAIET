# Model evaluation

No trained translation model has been measured yet, so no translation
scores are reported anywhere in this repository. This document defines
the harness that produces the first real ones, and the OCR evaluation
that already exists.

## Translation evaluation harness

`training/evaluation/evaluate_translation.py` runs every available
engine over the SAME held-out test split for one profile (Daniel —
book-level group split, so no near-identical verse appears in both
training and test data) and writes
`artifacts/benchmarks/<profile>-translation-eval.json` plus a Markdown
report of the same name.

```powershell
.\scripts\evaluate-translation.ps1 -Profile biblical_hebrew
.\scripts\evaluate-translation.ps1 -Profile biblical_aramaic -NoWriteSelection
```
```bash
./scripts/evaluate-translation.sh biblical_hebrew
python3 training/evaluation/evaluate_translation.py --profile biblical_hebrew
```

### Engines compared

1. **dictionary_gloss_baseline — not a sentence translation.** Word-by-
   word lemma/Strong's glossing from the corpus word index
   (`training/evaluation/dictionary_baseline.py`): each source word is
   replaced by its morphhb lemma/Strong's identifier (e.g. H430);
   unknown words pass through marked ⟦word⟧. The imported morphhb data
   carries lemmas and Strong's numbers but no English gloss strings, so
   this baseline's output is a gloss sequence, not English — its scores
   are the lexical floor and are expected to be very low. It exists to
   keep every other number honest, and it must never be shown to users
   as a translation.
2. **Moses SMT** — through the backend adapter code path, so the score
   measures exactly what the API would serve.
3. **Marian NMT** — through the backend adapter code path likewise.
4. **Retrieval baseline** — verified corpus lookup of each test source.
   **Upper-bound caveat (printed in every report):** the test verses
   come from the same corpus the retrieval index is built from, so
   retrieval coverage here is an upper-bound reference figure, not a
   measure of performance on unseen text. On genuinely unseen text the
   retrieval engine returns no match by design.

An engine whose artifact or binary is missing is listed as
`unavailable` with the reason; its scores are null, never zero-filled.

### Metrics

- **SacreBLEU** and **chrF++** from sacrebleu when installed
  (`pip install -r training/requirements.txt`). If sacrebleu is absent,
  the labelled pure-Python fallbacks in
  `training/evaluation/text_metrics.py` are used (chrF — no word-order
  component, so NOT chrF++ — and an approximate BLEU); the report names
  the implementation, and scores from the two are never mixed silently.
- **Latency**: per-engine mean and p95 wall-clock per verse, measured
  around the same adapter calls the backend makes (decoder startup per
  call is included — that is the real serving cost of the current
  adapters).
- **Source-token coverage**: for trained engines, the share of source
  tokens present in the exported source vocabulary (OOV words listed);
  for the baseline, lexicon hit rate; for retrieval, the match rate.
- **Failure examples**: the five lowest sentence-chrF verses per engine
  with source, reference, and hypothesis, quoted verbatim in the
  report.
- **Human review**: automatic metrics measure surface overlap, not
  exact meaning. `training/evaluation/human_review_template.md`
  provides the rubric (semantic accuracy, historical vocabulary,
  grammatical correctness, faithfulness to the source, unjustified
  interpretation) with blank scoring rows to be completed by a
  reviewer for any engine whose numbers will be cited.

### Selection record

Unless `--no-write-selection` is passed, the harness writes the
winning trained engine (highest recorded chrF++ on the shared test
split) into that engine's `model_card.json` (`metrics` + `selection`
blocks) and into its models-manifest entry (`evaluation` +
`selection`). The backend selection service reads exactly this record:
an evaluated engine outranks an unevaluated one, higher recorded chrF++
wins, and with no record the documented default is Moses before
Marian. The record carries the metric, value, date, test-pair count,
and the harness name — all from the run itself.

## OCR evaluation

Transcription accuracy is measured separately: CER/WER from
`backend/app/evaluation/metrics.py` over the fixtures in
`training/ocr/fixtures/`, run by `training/evaluation/evaluate_ocr.py`
(see docs/VERIFICATION.md). Language-identification accuracy and
reference-match precision are reported, when measured, with dataset,
partition, date, and the exact command recorded in
docs/BUILD_STATE.md. Fabricated or copied scores are prohibited by
docs/PROJECT_CONTRACT.md.
