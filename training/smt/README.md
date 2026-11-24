# training/smt — Moses SMT

`train_smt.py` is the Moses training orchestrator: corpus preparation →
tokenization → cleaning → KenLM language model → train-model.perl
(GIZA++ alignment, phrase extraction, lexicalised reordering) → MERT
tuning on the validation split → export into
`artifacts/models/smt/<profile>/` with a model card, flipping the
models manifest entry to provisioned only after a real export.

Nothing has been trained yet: no artifact directory exists and the
manifest entries are `not_provisioned`. Moses training is a WSL2-first
workflow on Windows — see docs/TRAINING.md for the exact installs and
`scripts/smt-train.ps1`. Runtime inference never needs WSL2; the
backend adapter runs a locally installed `moses` binary against the
exported `moses.ini`.

Work files land in `training/smt/work/` (gitignored). Per-step logs are
kept at `training/smt/work/<profile>/train.log`.
