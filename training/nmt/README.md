# training/nmt — Marian NMT

`train_nmt.py` is the Marian training orchestrator: corpus preparation
→ data gate → joint SentencePiece vocabulary → Marian training →
export into `artifacts/models/nmt/<profile>/` with a model card.

Configurations: `config-hebrew.yml` / `config-aramaic.yml` (CPU) and
`config-hebrew-gpu.yml` / `config-aramaic-gpu.yml` (optional GPU
variants). They are templates — the orchestrator substitutes the real
dataset paths and writes the runnable copy into
`training/nmt/work/<profile>/config.yml`.

The data gate is part of the design: below the configured minimum
training-pair count (default 500) the orchestrator writes a not-ready
report into the profile's artifact directory and stops without
training. With the present corpus that is the expected outcome for
Biblical Aramaic (no Aramaic training split exists yet). Nothing has
been trained yet; the manifest entries are `not_provisioned`.

Fine-tuning: `--pretrained <local checkpoint>` fine-tunes a locally
supplied checkpoint (for example a Helsinki-NLP-style model you have
downloaded yourself). The code never downloads a checkpoint.
