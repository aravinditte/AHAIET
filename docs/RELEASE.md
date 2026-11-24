# Release — version 0.1.0

The version matches the version fields already in the project
(`backend/pyproject.toml`, the FastAPI application, and
`frontend/package.json` all say 0.1.0). This document states the
supported scope of this release narrowly and truthfully.

## What works with zero provisioning

- The application itself: backend API + frontend UI, locally, offline.
- Image upload with content validation, storage, and preview.
- Language profiles, script support matrix, model/readiness reporting
  — all computed from real state.
- Once the reference corpus is imported (one command, below):
  **verified-reference translation** for passages that match the
  corpus (exact or diacritic-insensitive), with full provenance;
  **morphological analysis** for Hebrew and Aramaic words in the
  corpus word index; deterministic translation verification.
- Copy and export (TXT/JSON) of source, translation, and provenance.

## What each provisioning step adds

| Step | Adds | Command (details in the linked doc) |
|---|---|---|
| Install Tesseract binary | OCR for Hebrew square script | docs/OCR.md |
| Provision traineddata | Hebrew OCR language data (already downloadable via script) | `scripts/provision-ocr.ps1` / `.sh` |
| Import the corpus | Verified retrieval, morphology, verification reference checks | `python -m app.corpus.import_morphhb --download --import-db` |
| Train a Moses model | Model translation for unfamiliar Hebrew passages | docs/TRAINING.md |
| Evaluate the model | Recorded chrF++/BLEU figures; evaluated-model selection | `training/evaluation/evaluate_translation.py` |
| Train a Kraken checkpoint + record a measured CER | Recognition for one historical script profile | docs/OCR.md (Kraken section) |

Anything not provisioned reports itself as unavailable with the
reason — that behaviour is part of the release, not a gap in it.

## Artifact readiness (copied from `artifacts/manifests/models.json`)

| Artifact | Engine / profile | Status |
|---|---|---|
| tesseract-heb | Tesseract OCR | `traineddata_downloaded_binary_missing` — traineddata present, binary not installed on the build machine |
| kraken-paleo-hebrew | Kraken, Paleo-Hebrew | `not_provisioned` (script unsupported) |
| kraken-imperial-aramaic | Kraken, Imperial Aramaic | `not_provisioned` (script unsupported) |
| kraken-jewish-babylonian-aramaic-script | Kraken, Jewish Babylonian Aramaic script | `not_provisioned` (script unsupported) |
| kraken-classical-syriac-estrangela | Kraken, Classical Syriac (Estrangela) | `not_provisioned` (script unsupported) |
| moses-biblical-hebrew-en | Moses SMT, Biblical Hebrew | `not_provisioned` |
| marian-biblical-hebrew-en | Marian NMT, Biblical Hebrew | `not_provisioned` |
| moses-biblical-aramaic-en | Moses SMT, Biblical Aramaic | `not_provisioned` |
| marian-biblical-aramaic-en | Marian NMT, Biblical Aramaic | `not_provisioned` |

No artifact becomes provisioned by editing the manifest; statuses
change only when the provisioning/training code writes them after
real artifacts exist.

## Corpus provenance summary

- Source text: Westminster Leningrad Codex via Open Scriptures
  morphhb (Genesis sha256 `0526e5c9…d86449`, Daniel sha256
  `bc69d0fa…18fc0d`). WLC text public domain; morphhb annotations
  CC BY 4.0.
- English: World English Bible (public domain, eBible.org).
- Imported corpus: 1,890 verses parsed, 1,885 with aligned English,
  0 duplicates, 0 validation errors. Hebrew 1,690 verses; Aramaic 200
  (Daniel 2:4b–7:28). Five verses have empty English because of
  WLC/WEB numbering differences (Genesis 32:33; Daniel 3:31–33; 6:29)
  — recorded, never silently misaligned. Full detail:
  docs/DATASETS.md and `artifacts/manifests/datasets.json`.
- Recorded split: Genesis 1–25 train, Genesis 26–50 validation,
  Daniel test. Consequence: Aramaic has no training pairs under this
  split (see docs/TROUBLESHOOTING.md).

## Windows setup + startup + provisioning (complete sequence)

PowerShell, from the repository root. (Not yet executed on Windows —
see docs/ACCEPTANCE_AUDIT.md, criterion 18.)

```powershell
# 1. Backend environment
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # if blocked: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
pip install -e ".[dev]"

# 2. OCR provisioning (traineddata) + corpus import
cd ..
scripts\provision-ocr.ps1
$env:TESSDATA_PREFIX = "$PWD\.tools\tessdata"
cd backend
python -m app.corpus.import_morphhb --download --import-db

# 3. Start the backend (terminal 1)
python -m uvicorn app.main:app --port 8000

# 4. Frontend (terminal 2, from the repository root)
cd frontend
npm install
npm run dev                      # http://localhost:3000
```

Optional, later: trained-model provisioning follows docs/TRAINING.md
(Moses training runs under WSL2 on Windows; the runtime backend never
needs WSL2).

## Release checks

- Security posture: docs/SECURITY.md.
- Offline proofs: docs/OFFLINE_OPERATION.md.
- Acceptance state: docs/ACCEPTANCE_AUDIT.md.
- Verification commands (all marked not-yet-run): docs/VERIFICATION.md.

## Dependency strategy (AHAIET-054)

Backend direct dependencies are pinned exactly in
`backend/pyproject.toml`; ranges remain only for transitive
dependencies. The pinned set (FastAPI 0.115.6, Pydantic 2.10.4,
Pillow 11.0.0, NumPy 2.2.1, uvicorn 0.34.0, python-multipart 0.0.20;
dev: pytest 8.3.4, httpx 0.28.1, ruff 0.8.4) is the set this code was
written and syntax-checked against. Historic build notes from a
different snapshot cite Pillow 13 / pytest 9; those versions were NOT
adopted because no code in this tree was verified against them —
upgrading is a deliberate, separately verified change. The frontend
installs with `npm ci` against the committed lockfile. CI runs
`pip-audit` and `npm audit` scan steps (report-only) — see
`.github/workflows/ci.yml`.

## Provisioning

The ordered provisioning states and their verification commands live
in docs/PROVISIONING.md.
