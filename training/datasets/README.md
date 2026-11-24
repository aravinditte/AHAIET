# Datasets
The corpus importer lives in the backend (backend/app/corpus/import_morphhb.py) so the running app and the tooling share one parser. fixtures/sample_passages.jsonl is the small committed test fixture: six real morphhb/WLC passages with WEB alignment and full provenance, exported by the importer from the downloaded corpus. Full corpus data lives outside source control (artifacts/corpora/); see docs/DATASETS.md and artifacts/manifests/datasets.json.

## Parallel-corpus preparation

`prepare_parallel.py` turns the canonical corpus JSONL into per-profile
Moses/Marian training data under `training/datasets/prepared/<profile>/`
(gitignored): train/validation/test source (vocalized + consonantal
views) and target files, one verse per line, plus a `dataset_card.json`
(counts, checksums, editions, licences, split strategy) and a
`leakage_report.json`. Splits reuse the importer's recorded book/chapter
group strategy — no random verse-level split. Verses with empty English
are excluded and counted, never silently dropped. Exact or
diacritic-insensitive duplicates across splits are a hard failure.

```bash
python training/datasets/prepare_parallel.py
python training/datasets/prepare_parallel.py --profiles biblical_hebrew
```

`tokenize.py` is the CLI form of the project's single canonical
tokenizer (backend `app/services/language/tokenize.py`); it is what the
SMT pipeline falls back to when the Moses tokenizer scripts are absent.
