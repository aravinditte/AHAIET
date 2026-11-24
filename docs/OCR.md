# OCR

## Engine and profiles
Baseline: Tesseract via subprocess (`backend/app/services/ocr/tesseract_adapter.py`). The adapter resolves the binary from `AHAIET_TESSERACT_CMD` (a path or a PATH name) and the traineddata directory from `TESSDATA_PREFIX` / `AHAIET_TESSDATA_PREFIX`, then runs:

```
tesseract <derived-image> stdout -l heb --psm 6 tsv
```

TSV output is parsed for per-word confidences: words below the threshold (`AHAIET_OCR_CONF_THRESHOLD`, default 60) are returned as `uncertain_spans` with their real confidence values, and `mean_confidence` is the mean of the engine's own word confidences. Text is rebuilt in TSV reading order (block/paragraph/line). An empty recognition result is an explicit `empty_transcription` error (HTTP 422), never an empty success.

Both Biblical Hebrew and Biblical Aramaic (in Hebrew script) use the **heb** traineddata; the selected profile is recorded on every result as `ocr_profile`. Syriac traineddata is never used for Hebrew-script Aramaic. Unsupported historical scripts remain `unsupported` in `/api/languages` until real models exist.

## Preprocessing
`/api/ocr` accepts `preprocessing_profile`: `conservative` (default) or `enhanced`. The stored original is never modified; preprocessing builds a derived PNG and returns a step report (see `backend/app/services/preprocessing/service.py`): EXIF orientation, grayscale, tile-based adaptive contrast, bounded projection-profile deskew (enhanced only), median noise reduction (enhanced only, and automatically skipped when fine-detail content suggests small marks such as niqqud/cantillation would be destroyed), pixel upscale toward 300 DPI (the step is reported as `pixel_upscale` with the scaler and the before/after pixel sizes — it adds no optical resolution; source DPI is reported separately).

## Provisioning
- Windows: `.\scripts\provision-ocr.ps1` (winget UB-Mannheim build + traineddata download with hashes printed).
- Linux/macOS: `./scripts/provision-ocr.sh`.
- Manual: install Tesseract, place `heb.traineddata` (Apache-2.0, https://github.com/tesseract-ocr/tessdata) in a tessdata directory, set `TESSDATA_PREFIX`, restart the backend, and confirm `GET /api/capabilities` reports `ocr.status = available`.

Current state on the build machine: the heb and eng traineddata files are downloaded (checksums in `artifacts/manifests/models.json`), but the Tesseract **binary** could not be provisioned there (package lists were stale: `apt-get download tesseract-ocr` reported "Unable to locate package", and `apt-get update` did not complete). OCR therefore reports unavailable on that machine until the binary is installed. No OCR measurement has been run; see `docs/VERIFICATION.md` for the measurement commands and expected behaviour.

## Specialized engine: Kraken (historical recognition)
The Kraken adapter (`backend/app/services/ocr/kraken_adapter.py`) is a real integration, not a stub: it detects the Kraken Python package and the `ketos` CLI (with the detected version), resolves checkpoints from the models manifest, and recognises through Kraken's documented pipeline — baseline segmentation (blla) followed by the `rpred` recognition iterator over a checkpoint loaded with `load_any`. Imports are version-tolerant across Kraken's documented module layouts; if an installed Kraken exposes none of them, the adapter returns `kraken_adapter_incompatible` with the detected version instead of crashing. Per-line text and character confidences come from the recognition records themselves.

### Script support matrix (computed, never declared)
`GET /api/scripts` returns the live support matrix, computed by `backend/app/services/ocr/script_profiles.py` from the registry in `script_profiles.json`:

- `hebrew_square` — tier `operational` when the Tesseract route's probe says usable (see probe honesty below); never `validated_for_production` without an evaluation record meeting the same bar as the Kraken route.
- Historical profiles — tier `validated_for_production` **only** when ALL gates hold at once (NEW-17): an evaluation record exists at `artifacts/benchmarks/htr-eval-<profile>.json`; the record's script identity EQUALS the profile id (an absent script field does not pass); its `dataset_sha256` is verified by recomputing the hash of the recorded dataset; it covers at least 50 independently labelled samples; its CER is finite and <= 0.20 AND a WER is recorded; and its `checkpoint_sha256` equals the hash of a Kraken checkpoint file present on disk for that profile. A measured record that fails any gate reports tier `evaluated_on_dataset` with the failed gates named in `unmet_conditions`. There is no hand-edited support boolean anywhere, and no historical script is supported by default.

`/api/ocr` accepts `engine` (`auto` | `tesseract` | `kraken`) and `script_profile`. Routing never substitutes silently: Tesseract refuses historical script profiles, Kraken refuses profiles the matrix does not compute as supported, and `auto` means Tesseract for `hebrew_square` only — each refusal is an explicit `script_unsupported` error (HTTP 422).

### Provisioning Kraken
- Windows: `.\scripts\provision-kraken.ps1` — checks for WSL2 and prints the exact in-WSL2 install commands (Kraken is Linux-first; native Windows is not a supported route here).
- Linux/WSL2: `./scripts/provision-kraken.sh` — installs the backend `kraken` extra into the venv.
- Manual: `pip install -e "backend[kraken]"`, then confirm `GET /api/capabilities` shows `ocr.kraken.available = true` with the detected version.

Installing Kraken alone changes no support status: a checkpoint and a measured evaluation record are also required.

### Training a Kraken checkpoint
`training/ocr/train_kraken.py` orchestrates `ketos train` over line-level ground truth:

```
<data-dir>/
  provenance.txt     (required: source + licence of images/transcripts)
  train/  line-0001.png + line-0001.txt  (paired line image + exact transcription)
  test/   held-out pairs for evaluation
```

```powershell
.\scripts\train-kraken.ps1 -Profile paleo_hebrew -DataDir D:\kraken-data\paleo
```
```bash
./scripts/train-kraken.sh paleo_hebrew /path/to/kraken-data/paleo
# fine-tune from an existing local checkpoint:
./scripts/train-kraken.sh paleo_hebrew /path/to/kraken-data/paleo /path/to/base.mlmodel
```

The run exports `artifacts/models/kraken/<profile>/model.mlmodel` plus `training_card.json` (data provenance, line count, tool version, checkpoint sha256) and flips the manifest entry to provisioned. Unprovenanced or unpaired data is refused.

### Evaluating a checkpoint
```bash
python training/evaluation/evaluate_htr.py --profile paleo_hebrew \
  --checkpoint artifacts/models/kraken/paleo_hebrew/model.mlmodel \
  --test-dir /path/to/kraken-data/paleo/test
```
This writes `artifacts/benchmarks/htr-eval-paleo_hebrew.json` with the measured CER/WER (micro-averaged Levenshtein) and the checkpoint hash — the record the support matrix reads. No checkpoint, no labelled data, and no scores currently exist, so every historical profile reports unsupported.

## Fixtures and measurement
`training/ocr/generate_fixtures.py` renders labelled images (Genesis 1:1 in Hebrew, Daniel 2:4 in Aramaic, both real WLC text from the imported corpus sample) with a Hebrew serif font; ground truth and provenance live in `training/ocr/fixtures/ground_truth.json`. `training/evaluation/evaluate_ocr.py` runs the real OCR service over the fixtures and writes measured CER/WER (Levenshtein, `backend/app/evaluation/metrics.py`) plus raw OCR output to `training/ocr/fixtures/ocr_measurement.json`. No scores exist until that script is run on a machine with the binary.

## Remediation notes

- Readiness is three distinct facts (AHAIET-034): `binary_available`,
  `language_data_available` (heb present in a bounded, TTL-cached
  `tesseract --list-langs` probe), and `usable` (both). The frontend
  readiness panel keys off `usable` and shows the distinct fields.
- Validation fully decodes the image (`load()` after `verify()`,
  decompression warnings treated as errors) and rejects multipage /
  animated inputs for the single-image pipeline (AHAIET-037). A
  decoded+intermediate byte budget (`AHAIET_PREPROCESSING_MAX_BYTES`)
  is enforced before heavy steps (AHAIET-038); median filtering uses
  Pillow's memory-bounded MedianFilter (AHAIET-023).
- Uncertain spans carry `index`, `occurrence_id`, `block`, `par`, and
  `line_id` from the TSV, so a repeated word's second occurrence can
  be highlighted exactly (AHAIET-028/040).
- Real-manuscript evaluation: `training/ocr/fixtures/manuscript_registry.json`
  registers rights-cleared manuscript images with ground truth
  (AHAIET-052). It ships empty — no images are fabricated. Entries
  require: a public-domain or explicitly licensed source image, a
  diplomatic ground-truth transcription, and script / diacritics /
  degradation stratum labels. `training/ocr/evaluate_ocr.py` scores
  registry entries per stratum alongside the synthetic stratum when
  entries exist.

## Probe honesty, offsets, and the job worker (NEW-20, NEW-21, NEW-16, NEW-23)

- **Probe honesty (NEW-20).** Readiness runs `tesseract --list-langs`.
  If the probe fails (nonzero exit, timeout, undecodable output), the
  report is `probe_failed: true`, `usable: false`, with the reason
  stated — regardless of traineddata files on disk. File presence is
  reported separately as `language_data_file_present` and never makes
  the engine usable on its own: a binary that cannot list its
  languages cannot be trusted to load them.
- **Token offsets (NEW-21).** OCR responses carry `tokens[]` with
  `char_start`/`char_end` code-point offsets into the raw text
  (`offset_encoding: "unicode_code_points"`), and uncertain spans
  carry the same offsets. Tesseract offsets come from TSV assembly
  order (exact); Kraken offsets come from line assembly order. The
  frontend highlights by slicing offsets; when offsets are absent it
  falls back to occurrence matching and labels the highlighting
  approximate.
- **Job worker (NEW-16).** On the /api/process path, OCR runs in a
  subprocess (`python -m app.services.ocr.worker_entry`) bounded by
  the job's remaining deadline; on expiry the process is terminated
  and the job ends `failed` with `ocr_timeout`. The synchronous
  /api/ocr path calls the engines in-process, bounded by
  AHAIET_OCR_TIMEOUT_S.
- **Kraken confidences (NEW-23).** Per-character confidences are
  aligned to grapheme clusters (base character + combining marks in
  categories Mn/Me/Mc + ZWJ sequences — a documented approximation of
  UAX #29), because Kraken reports confidences per grapheme while
  pointed Hebrew text has more code points than graphemes. When the
  counts cannot be reconciled, the result reports
  `confidence_unavailable` instead of misaligned numbers.
