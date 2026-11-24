# Limitations (stated plainly)

Rewritten from the current manifests and source for the re-review
remediation (findings NEW-01..NEW-27). Where a number appears, it is
the number recorded in `artifacts/manifests/datasets.json` /
`models.json`; `backend/tests/test_docs_consistency.py` fails if the
docs and the manifests drift apart again.

- **OCR does not run on a machine without a Tesseract binary (or a
  provisioned Kraken checkpoint):** the endpoints return 503 by
  design. The build machine has the heb/eng traineddata but not the
  binary. If the binary exists but its `--list-langs` probe fails,
  readiness reports `probe_failed` and the engine is NOT usable —
  traineddata file presence alone is never treated as evidence
  (NEW-20). No OCR output has ever been fabricated, and no CER/WER
  score exists yet: the measurement tooling is written but unrun.
- **General translation does not exist yet:** text that does not
  match an imported corpus passage gets an honest 503. Only verified
  corpus matches return English (the cited WEB text). No dictionary
  gloss, example sentence, or paraphrase is ever returned as a
  translation. All four translation model entries in the manifest
  (Moses and Marian, both profiles) are `not_provisioned` — nothing
  has been trained.
- **The corpus covers Genesis, Daniel, Ezra and Ruth** (morphhb/WLC,
  WEB-aligned): 2,255 verses parsed, 2,250 with aligned English,
  Hebrew 1,988 / Aramaic 267. Five verses have no aligned English
  (WLC/WEB numbering differences, listed in docs/DATASETS.md).
  Morphology is lookup over this corpus's word index: words outside
  these four books return not_found, and Daniel 2:4's Hebrew opening
  words are flagged Hebrew inside an Aramaic-range verse (that is
  what the source data says).
- **Training data is thin where it matters.** Per-profile pairs —
  Hebrew: train 906 / validation 996 / test 85 (Ruth, held out);
  Aramaic: train 67 (Ezra only) / validation 46 (Daniel ch. 2) /
  test 150 (Daniel chs. 3–7). The Marian data gate requires 500
  training pairs: Hebrew passes it, Aramaic (67) does not, and the
  whole biblical corpus holds only ~267 Aramaic verses, so the gate
  stays unmet unless a further licensed Aramaic source is added.
  Verses are never duplicated to fill a split.
- **Script support is tiered, and no historical script is validated
  for production.** Tiers: engine_installed / operational /
  evaluated_on_dataset / validated_for_production (NEW-17). The
  square-Hebrew Tesseract route is at most `operational` (the engine
  runs; that is not an accuracy claim). Paleo-Hebrew, Imperial
  Aramaic, Jewish Babylonian Aramaic script and Estrangela Syriac
  have no checkpoints and no measured evaluation records, so they
  report unsupported with the unmet conditions named.
- **Language identification is evidence-based but conservative:**
  with no profile selected, a verified match in one profile plus an
  ambiguous candidate set in another yields `profile_choice_required`
  (NEW-08) rather than a guess; with no evidence at all the request
  fails honestly.
- **Model selection may rest on a single evaluated engine.** When
  only one engine has a valid, comparable evaluation run, it may be
  selected, but the record is labelled
  `selection_basis="single_evaluated_engine"`, `comparable=false`
  (NEW-04). A recorded score without its run record (test-set hash,
  sample count, metric signature, artifact hash, date) is ignored
  (NEW-14).
- **Upload retention exists and is schedulable:** the maintenance
  CLI (`python -m app.maintenance`) and an optional startup sweep
  implement AHAIET_RETENTION_DAYS (default 30); nothing sweeps
  unless an operator runs the CLI or enables the sweep.
- **Access control is an optional single token,** off by default:
  when AHAIET_ACCESS_TOKEN is set, every document/result endpoint
  (uploads read, process, job read/result/cancel, history
  read/delete) requires the `X-AHAIET-Access-Token` header
  (NEW-12). It is a local-app safeguard, not user authentication.
- **OpenCV is optional;** without it, the Pillow/NumPy preprocessing
  pipeline is used and capabilities say so.
- **End-to-end proof is still outstanding (NEW-03):** no run of the
  real pipeline (real Tesseract + imported corpus + fixture images)
  has been executed by the build assistant; the strengthened
  acceptance test is coded (docs/VERIFICATION.md) and
  docs/ACCEPTANCE_AUDIT.md records the criterion as blocked until it
  is run on a provisioned machine.
- Single-user local app: not hardened for public deployment.
