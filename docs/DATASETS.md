# Datasets

## Imported corpus (provenance recorded in artifacts/manifests/datasets.json)
- **Source text + morphology:** Open Scriptures Hebrew Bible (morphhb), Westminster Leningrad Codex OSIS XML for Genesis, Daniel, Ezra and Ruth. WLC text is **Public Domain**; morphhb annotations are **CC BY 4.0**. Files: `artifacts/corpora/morphhb/Gen.xml`, `Dan.xml`, `Ezra.xml`, `Ruth.xml` (gitignored; sha256 in the manifest).
- **English alignment:** World English Bible, **Public Domain**, verse-per-line archive from eBible.org (`artifacts/corpora/eng-web_vpl.zip`, sha256 in the manifest), aligned by book/chapter/verse.
- **The Comprehensive Aramaic Lexicon (cal.huc.edu)** is a research reference only; its terms do not permit copying/redistribution here, so nothing is taken from it.

## Canonical passage schema
`id, language, dialect, script, period, source_text, english_text, book, reference, source_edition, translation_edition, license, provenance, partition` — plus per-word morphology records (surface, lemma, Strong's number, morphhb morph code, word-level language flag from the morph-code prefix H/A).

## Language assignment
Genesis is Biblical Hebrew. Daniel follows the documented Biblical Aramaic range **Daniel 2:4b–7:28**; other Daniel verses are Hebrew. Daniel 2:4 straddles the boundary: the verse sits in the Aramaic range while its opening narration words carry Hebrew word-level flags from morphhb itself — both facts are kept, per-word.

## Alignment gaps (recorded, not papered over)
Five verses have no aligned English because verse numbering differs between WLC and WEB: Genesis 32:33, Daniel 3:31, Daniel 3:32, Daniel 3:33, Daniel 6:29. They import with `english_text` empty rather than a misaligned verse.

## Partitions (leakage-safe)
Book/chapter blocks, never random verse draws, assigned per language
profile (NEW-01/NEW-02): Genesis chapters 1–25 → train, 26–50 →
validation; Ezra (both languages) → train; Daniel Hebrew →
validation; Daniel Aramaic chapter 2 → validation, chapters 3–7 →
test; Ruth → test (an independent Hebrew book, held out entirely).
Group integrity is keyed by (language_profile, book, chapter), so
Daniel's mixed-language chapters are legal while chapter-level
checks remain in force within each profile. Deduplication key:
(language, reference, normalized source). Current recorded pairs —
Hebrew: train 906 / validation 996 / test 85; Aramaic: train 67 /
validation 46 / test 150. Both profiles have nonempty
train/validation/test partitions; the Aramaic training set (67,
Ezra only) remains far below the Marian 500-pair data gate, which
stays documented and unmet — verses are never duplicated to fill a
split.

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

## Ezra and Ruth additions (AHAIET-008, NEW-02)

The importer also parses `Ezra.xml` and `Ruth.xml` from the same
morphhb source (same licence handling; sha256 recorded in
`artifacts/manifests/datasets.json`). Biblical Aramaic ranges in Ezra:
4:8-6:18 and 7:12-26 (67 verses). Ruth (85 verses, all with aligned
English) is the held-out Hebrew test book: an independent document
that appears in no other partition. Current recorded parse: 2,255
verses, 2,250 with aligned English; Hebrew 1,988 verses, Aramaic 267;
0 duplicates, 0 validation errors, and the preparation step's
leakage checks (group integrity, exact and diacritic-insensitive
cross-split duplicates, near-duplicates) passed over this assignment
— see the import_report in the manifest. (The earlier Ezra-only
parse — 2,170 verses with an empty Hebrew test partition and an
empty Aramaic validation partition — is superseded; see the
changelog in docs/BUILD_STATE.md.)
