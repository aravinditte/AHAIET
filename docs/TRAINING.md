# Training
Nothing has been trained in Part 1. training/ contains only README placeholders per area (datasets, preprocessing, alignment, smt, nmt, ocr, evaluation, configs).
Plan (later parts, not implemented): Moses SMT baseline (WSL2 path documented in Part 4), Marian NMT fine-tune, Kraken OCR fine-tune; the engine with the best independently measured score per language profile wins — SMT is not assumed to beat NMT or vice versa. Training must use free/open-source data with recorded licences (docs/DATASETS.md); synthetic data must never be passed off as authentic scholarly data.
