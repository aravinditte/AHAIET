# Provisioning state machine (AHAIET-056)

One explicit sequence from a bare checkout to a verified offline
installation. Each state is reached only by running its verification
command and seeing the stated result — no state is inferred from a
file merely existing, and setup-time network use (package managers,
the corpus importer's `--download`) is separate from runtime, which
makes no network calls at all (docs/OFFLINE_OPERATION.md).

`GET /api/capabilities` exposes a `provisioning_state` summary computed
from the live checks for the first five states. The last state is
recorded only by an actual offline benchmark run.

| State | Meaning | Verification command | Expected evidence |
|---|---|---|---|
| `not_installed` | Nothing provisioned | `python -m app.offline_check` (backend) | static offline proof passes; capabilities show OCR unusable |
| `binary_present` | Tesseract binary installed | `tesseract --version` | version prints; capabilities `ocr.tesseract.binary_available: true` |
| `traineddata_verified` | Hebrew traineddata usable by the binary | `tesseract --list-langs` | `heb` listed; capabilities `language_data_available: true`, `usable: true` (Windows: `scripts\provision-ocr.ps1 -Install` performs the install, the check, a fixture smoke OCR, and persists settings to `ahaiet.local.env`) |
| `corpus_imported` | Reference corpus in the database | `python -m app.corpus.import_morphhb --import-db` then `GET /api/capabilities` | `corpus.status: available` with per-language passage counts; `corpus_revision` increments on every import |
| `model_trained` | A real trained artifact is exported and resolves complete (checksums verified) | `GET /api/models` | the entry's `ok: true` with empty `missing[]` |
| `model_evaluated` | The artifact has a comparable, harness-recorded evaluation (evaluation-run record with test-set sha256 + metric signature) | run `training/evaluation/evaluate_translation.py --profile <profile>` | a benchmark report whose status is `evaluated` (not `insufficient_test_data`) and a selection record written by that run |
| `offline_benchmark_passed` | The full image -> OCR -> correction -> translation path ran with networking disabled and produced recorded results | run the opt-in acceptance test `backend/tests/test_real_pipeline_acceptance.py` with networking disabled (developer-run) | a recorded run of that test passing; until then this state is **not** claimed anywhere |

Current recorded state of this repository: `not_installed` on the
build machine (traineddata files were downloaded in an earlier build
but the Tesseract binary is absent), no trained model, no evaluation
run, no offline benchmark. See docs/BUILD_STATE.md.
