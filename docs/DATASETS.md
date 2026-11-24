# Datasets

## Imported corpus (provenance recorded in artifacts/manifests/datasets.json)
- **Source text + morphology:** Open Scriptures Hebrew Bible (morphhb), Westminster Leningrad Codex OSIS XML for Genesis and Daniel. WLC text is **Public Domain**; morphhb annotations are **CC BY 4.0**. Files: `artifacts/corpora/morphhb/Gen.xml`, `Dan.xml` (gitignored; sha256 in the manifest).
- **English alignment:** World English Bible, **Public Domain**, verse-per-line archive from eBible.org (`artifacts/corpora/eng-web_vpl.zip`, sha256 in the manifest), aligned by book/chapter/verse.
- **The Comprehensive Aramaic Lexicon (cal.huc.edu)** is a research reference only; its terms do not permit copying/redistribution here, so nothing is taken from it.

## Canonical passage schema
`id, language, dialect, script, period, source_text, english_text, book, reference, source_edition, translation_edition, license, provenance, partition` — plus per-word morphology records (surface, lemma, Strong's number, morphhb morph code, word-level language flag from the morph-code prefix H/A).

## Language assignment
Genesis is Biblical Hebrew. Daniel follows the documented Biblical Aramaic range **Daniel 2:4b–7:28**; other Daniel verses are Hebrew. Daniel 2:4 straddles the boundary: the verse sits in the Aramaic range while its opening narration words carry Hebrew word-level flags from morphhb itself — both facts are kept, per-word.

## Alignment gaps (recorded, not papered over)
Five verses have no aligned English because verse numbering differs between WLC and WEB: Genesis 32:33, Daniel 3:31, Daniel 3:32, Daniel 3:33, Daniel 6:29. They import with `english_text` empty rather than a misaligned verse.

## Partitions (leakage-safe)
Book/chapter blocks, never random verse draws: Genesis chapters 1–25 → train, 26–50 → validation, Daniel → test. Deduplication key: (language, reference, normalized source).

## Importer
```
# Windows PowerShell
.\scripts\import-corpus.ps1
# bash
./scripts/import-corpus.sh
# or directly, from backend/
python -m app.corpus.import_morphhb --download --import-db
```
The importer is re-runnable (it replaces its own passages/words on each DB import), validates non-empty source and reference shape, writes the canonical JSONL to `artifacts/corpora/passages.jsonl`, and prints a parse report (verses parsed, aligned English count, per-language counts, duplicates skipped, validation errors). A small committed fixture — `training/datasets/fixtures/sample_passages.jsonl`, six real passages (Genesis 1:1–3, Daniel 2:4, Daniel 2:5, Daniel 7:9) with full provenance — backs the retrieval/morphology tests without the full download.

## Rules
Every corpus needs a named edition, a licence that permits the intended use, provenance (source + retrieval date), a recorded partition, and a checksum. Invented or unattributed "scholarly" entries must never be inserted. A reference translation may be returned only for a verified, identified corpus match within the selected language profile.
