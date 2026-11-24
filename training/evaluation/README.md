# Evaluation

Two harnesses live here:

- `evaluate_ocr.py` runs the backend OCR service over the fixtures in
  training/ocr/fixtures/ and writes measured CER/WER + raw output to
  training/ocr/fixtures/ocr_measurement.json. It produces nothing until
  run on a machine with a provisioned Tesseract binary; no scores are
  recorded anywhere before that run.
- `evaluate_translation.py` runs every available translation engine
  (dictionary gloss baseline, Moses SMT, Marian NMT, verified retrieval)
  over the SAME held-out test split for one profile and writes
  `artifacts/benchmarks/<profile>-translation-eval.json` + a Markdown
  report: SacreBLEU, chrF++, latency, coverage, failure examples, and
  the winning-engine selection record. Unavailable engines are listed
  with their reason — never zero-filled. See docs/MODEL_EVALUATION.md.

Supporting modules: `dictionary_baseline.py` (the word-by-word
lemma/Strong's gloss baseline, labelled "not a sentence translation"
wherever it appears), `text_metrics.py` (labelled pure-Python fallback
metrics used only when sacrebleu is absent), and
`human_review_template.md` (the linguistic rubric that accompanies any
automatic score).
