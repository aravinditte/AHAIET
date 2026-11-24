# OCR

## Engine and profiles
Baseline: Tesseract via subprocess (`backend/app/services/ocr/tesseract_adapter.py`). The adapter resolves the binary from `AHAIET_TESSERACT_CMD` (a path or a PATH name) and the traineddata directory from `TESSDATA_PREFIX` / `AHAIET_TESSDATA_PREFIX`, then runs:

```
tesseract <derived-image> stdout -l heb --psm 6 tsv
```

TSV output is parsed for per-word confidences: words below the threshold (`AHAIET_OCR_CONF_THRESHOLD`, default 60) are returned as `uncertain_spans` with their real confidence values, and `mean_confidence` is the mean of the engine's own word confidences. Text is rebuilt in TSV reading order (block/paragraph/line). An empty recognition result is an explicit `empty_transcription` error (HTTP 422), never an empty success.

Both Biblical Hebrew and Biblical Aramaic (in Hebrew script) use the **heb** traineddata; the selected profile is recorded on every result as `ocr_profile`. Syriac traineddata is never used for Hebrew-script Aramaic. Unsupported historical scripts remain `unsupported` in `/api/languages` until real models exist.

## Preprocessing
`/api/ocr` accepts `preprocessing_profile`: `conservative` (default) or `enhanced`. The stored original is never modified; preprocessing builds a derived PNG and returns a step report (see `backend/app/services/preprocessing/service.py`): EXIF orientation, grayscale, tile-based adaptive contrast, bounded projection-profile deskew (enhanced only), median noise reduction (enhanced only, and automatically skipped when fine-detail content suggests small marks such as niqqud/cantillation would be destroyed), upscale toward 300 DPI.

## Provisioning
- Windows: `.\scripts\provision-ocr.ps1` (winget UB-Mannheim build + traineddata download with hashes printed).
- Linux/macOS: `./scripts/provision-ocr.sh`.
- Manual: install Tesseract, place `heb.traineddata` (Apache-2.0, https://github.com/tesseract-ocr/tessdata) in a tessdata directory, set `TESSDATA_PREFIX`, restart the backend, and confirm `GET /api/capabilities` reports `ocr.status = available`.

Current state on the build machine: the heb and eng traineddata files are downloaded (checksums in `artifacts/manifests/models.json`), but the Tesseract **binary** could not be provisioned there (package lists were stale: `apt-get download tesseract-ocr` reported "Unable to locate package", and `apt-get update` did not complete). OCR therefore reports unavailable on that machine until the binary is installed. No OCR measurement has been run; see `docs/VERIFICATION.md` for the measurement commands and expected behaviour.

## Specialized engine
Kraken adapter (`kraken_adapter.py`) performs an honest import check; no Kraken model is provisioned, so it reports unavailable. A model file plus a successful load would be required before it can report ready.

## Fixtures and measurement
`training/ocr/generate_fixtures.py` renders labelled images (Genesis 1:1 in Hebrew, Daniel 2:4 in Aramaic, both real WLC text from the imported corpus sample) with a Hebrew serif font; ground truth and provenance live in `training/ocr/fixtures/ground_truth.json`. `training/evaluation/evaluate_ocr.py` runs the real OCR service over the fixtures and writes measured CER/WER (Levenshtein, `backend/app/evaluation/metrics.py`) plus raw OCR output to `training/ocr/fixtures/ocr_measurement.json`. No scores exist until that script is run on a machine with the binary.
