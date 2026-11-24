# Training — Moses SMT and Marian NMT

Nothing has been trained yet. This document describes the complete,
executable training infrastructure for the two general translation
engines and the exact commands to run it. Every step is local and
offline once the tools are installed; training data is the imported
morphhb/WLC + WEB corpus (docs/DATASETS.md), prepared per profile by
`training/datasets/prepare_parallel.py`.

## The data, stated plainly

Prepared splits (book-group strategy, AHAIET-008: whole books are
assigned to partitions, so no verse can leak across splits; the
leakage check still runs and fails the run on any cross-split
duplicate):

| Book group | Partition |
|---|---|
| Genesis chapters 1-25 (Hebrew) | train |
| Genesis chapters 26-50 (Hebrew) | validation |
| Ezra — Hebrew and Aramaic sections | train |
| Daniel — Hebrew verses | validation |
| Daniel — Aramaic verses | **test** (held-out book for Aramaic) |

Counts from the recorded importer parse (sha256 + full report in
`artifacts/manifests/datasets.json`):

| Profile | Train | Validation | Test |
|---|---|---|---|
| Biblical Hebrew | 906 verse pairs | 996 pairs (997 verses, 1 without aligned WEB English) | **0** |
| Biblical Aramaic | 67 verse pairs (Ezra) | 0 | 196 pairs (200 Daniel verses, 4 without aligned English) |

Consequences, stated plainly:
- Hebrew can train both engines (906 pairs is still a *small* corpus —
  the dataset card says so, and no generalisation claim may be made).
- Aramaic now HAS training data (Ezra's 67 pairs, above the Moses
  50-pair minimum, still below the Marian 500-pair gate). Daniel
  Aramaic remains a genuinely held-out test book: no Daniel Aramaic
  verse appears in train.
- **Hebrew now has NO test partition** (Daniel's Hebrew verses moved
  to validation, and Ezra is training data). A Hebrew evaluation
  therefore reports `insufficient_test_data` and selection refuses to
  write — by design — until a held-out Hebrew source is added as a
  documented data change. This is the deliberate price of the
  book-group strategy; do not "fix" it by moving verses across splits
  silently.

## Shared preparation (both engines)

```powershell
# PowerShell (repo root) — uses the Python on PATH
python training\datasets\prepare_parallel.py
```
```bash
# WSL2 / bash
python3 training/datasets/prepare_parallel.py
```

Outputs per profile under `training/datasets/prepared/<profile>/`:
tokenized train/validation/test files in two source views (vocalized —
canonical, diacritics preserved; consonantal — diacritic-stripped,
labelled derived view), `dataset_card.json` (counts, per-file sha256,
editions, licences, split strategy, seed 13), `leakage_report.json`,
and `test.references.jsonl` for the evaluation harness. Leakage rules:
exact or diacritic-insensitive duplicates across splits fail the run
(exit 2); near-duplicates are flagged in the report. Verses with empty
English are excluded and counted in the card.

Tokenization is the project's single canonical implementation
(`backend/app/services/language/tokenize.py`, CLI form in
`training/datasets/tokenize.py`): punctuation separated, maqqef split,
niqqud/cantillation never stripped in the vocalized view. Training and
runtime inference share it, so a model always sees the token stream it
was trained on.

Optional training-only Python dependencies (never needed by the
running backend):

```bash
pip install -r training/requirements.txt     # sacrebleu, sentencepiece
# or: pip install -e "backend[training]"
```

## Moses SMT — WSL2 workflow (primary on Windows)

Moses, GIZA++, and KenLM are Linux toolchains; on Windows they run
inside WSL2. Training inside WSL2 does not affect runtime: inference
uses a locally installed `moses` binary against the exported artifact
(see "Runtime integration" below).

### Install inside WSL2 (Ubuntu)

```bash
# In an Ubuntu (WSL2) shell, from the repository checkout inside WSL2
sudo apt-get update
sudo apt-get install -y build-essential git cmake perl \
  libboost-all-dev zlib1g-dev libbz2-dev liblzma-dev python3

# Moses decoder (contains the training scripts and the moses binary)
git clone https://github.com/moses-smt/mosesdecoder.git ~/mosesdecoder
cd ~/mosesdecoder
./bjam -j4 --with-kenlm=$HOME/kenlm   # after KenLM below, or without --with-kenlm
export MOSES_HOME=$HOME/mosesdecoder

# GIZA++ (alignment) — Moses' train-model.perl drives it via --external-bin-dir
git clone https://github.com/moses-smt/giza-pp.git ~/giza-pp
cd ~/giza-pp && make && make install   # binaries land in ~/giza-pp/bin or GIZA++-v2/
export MOSES_EXTERNAL_BIN_DIR=$HOME/giza-pp/GIZA++-v2

# KenLM (language model: lmplz + build_binary)
git clone https://github.com/kpu/kenlm.git ~/kenlm
cd ~/kenlm && mkdir build && cd build && cmake .. && make -j4
export KENLM_BIN=$HOME/kenlm/build/bin/lmplz
```

### Train

```powershell
# Windows PowerShell wrapper (checks WSL2, converts the path, runs inside WSL2)
.\scripts\smt-train.ps1 -Profile biblical_hebrew
.\scripts\smt-train.ps1 -Profile biblical_hebrew -AllowSmall   # only if you accept a measurement-only baseline
```
```bash
# Inside WSL2 directly
./scripts/smt-train.sh biblical_hebrew
python3 training/smt/train_smt.py --profile biblical_hebrew
```

Pipeline (each step logged to `training/smt/work/<profile>/train.log`,
run aborts on the first failing step): corpus preparation →
tokenization (Moses `tokenizer.perl` for the English side when
MOSES_HOME is set; the repository tokenizer for the Hebrew-script
source always, and for everything when Moses scripts are absent — every
substitution is logged) → cleaning (`clean-corpus-n.perl` or the
repository length/ratio filter) → KenLM `lmplz` order-3 language model
on the English training side (+ `build_binary` when present; if KenLM
is missing the run stops with instructions — an LM is never faked) →
`train-model.perl` (GIZA++ alignment `grow-diag-final-and`, phrase
extraction, lexicalised reordering `msd-bidirectional-fe`) → MERT
tuning on the validation split when the moses binary and
`mert-moses.pl` are available (otherwise the untuned model is exported
and the skip is recorded in the model card) → export.

Data guards: 0 training pairs stops the run (exit 4) with the split
explanation; below `--min-train-pairs` (default 50) also stops unless
`--allow-small` is passed.

### Exported artifact (per profile)

`artifacts/models/smt/<profile>/` (outside source control): `moses.ini`
(paths rewritten to the artifact directory), phrase table, reordering
table, LM file, `vocabulary.source.txt` (for OOV reporting), and
`model_card.json` — dataset-card sha256, tool versions recorded at
runtime, per-file sha256 + sizes, licence/provenance, tuning record.
The export step flips the manifest entry
(`moses-biblical-hebrew-en` / `moses-biblical-aramaic-en`) to
`provisioned` with the artifact path, checksum, and model version.

## Marian NMT

### Install

Marian is a C++ framework; install a CPU build (GPU optional) from
https://github.com/marian-nmt/marian (build with `-DCOMPILE_CPU=ON`,
add `-DCOMPILE_CUDA=ON` only for the GPU variant), or use a package for
your distribution. The orchestrator finds the binary via PATH or
`MARIAN_BIN`. SentencePiece comes from `training/requirements.txt`
(Python package) or an `spm_train` binary — the orchestrator uses
whichever it finds and logs which.

### Train / fine-tune

```powershell
.\scripts\nmt-train.ps1 -Profile biblical_hebrew
.\scripts\nmt-train.ps1 -Profile biblical_hebrew -Variant gpu
.\scripts\nmt-train.ps1 -Profile biblical_hebrew -Pretrained C:\models\<local-checkpoint>\model.npz
```
```bash
./scripts/nmt-train.sh biblical_hebrew
python3 training/nmt/train_nmt.py --profile biblical_hebrew
python3 training/nmt/train_nmt.py --profile biblical_hebrew --config-variant gpu
python3 training/nmt/train_nmt.py --profile biblical_hebrew --pretrained /path/to/local/model.npz
```

Data gate (before anything trains): the profile's training-pair count
is checked against `--min-train-pairs` (default 500). Below it, the
orchestrator writes `not_ready.json` + `not_ready.md` into
`artifacts/models/nmt/<profile>/` and exits 3 — an explicit expected
outcome, not a crash. For Biblical Aramaic with the present corpus
(0 training pairs) this is the outcome, and the report says why and
what would change it. Hebrew (693 pairs) passes the default gate; the
dataset card's small-corpus statement still applies — a model trained
on 693 verse pairs is a measurement baseline, and generalisation to
unseen historical documents must not be claimed.

Vocabulary choice (documented): ONE joint SentencePiece BPE model
trained on the concatenated source+target training text, used for both
sides. With a corpus this small, shared subwords keep proper names and
numbers aligned across the sides and halve the vocabulary parameters.

Configurations: `training/nmt/config-hebrew.yml` /
`config-aramaic.yml` (CPU, small transformer: 3+3 layers, dim 256,
early stopping on validation cross-entropy/perplexity/BLEU) and the
`-gpu` variants (device 0, larger batches/workspace; a GPU is never
required). The orchestrator substitutes dataset paths, seed (13), and
the optional `pretrained-model` line, writing the runnable copy to
`training/nmt/work/<profile>/config.yml`.

Fine-tuning: `--pretrained` accepts a LOCAL checkpoint file only (for
example a Helsinki-NLP-style model downloaded by hand). The code never
downloads a checkpoint. Without `--pretrained`, training is from
scratch, subject to the same data gate.

### Exported artifact (per profile)

`artifacts/models/nmt/<profile>/`: `model.npz` (best validation
checkpoint), `vocab.spm` (the joint vocabulary), `decoder-config.yml`
(generated for `marian-decoder`; no devices key → CPU decoding),
`vocabulary.source.txt`, and `model_card.json` (same contract as SMT).
The manifest entry is flipped to `provisioned` only after export.

## Runtime integration

The backend adapters (`backend/app/services/translation/`) resolve each
manifest entry against the disk: status provisioned + artifact
directory + model card + every card-listed file + engine essentials.
Incomplete artifacts produce an honest unavailable error naming the
missing pieces. Inference runs the local binaries directly —
`moses -f <artifact>/moses.ini` (AHAIET_MOSES_CMD) and
`marian-decoder -c <artifact>/decoder-config.yml`
(AHAIET_MARIAN_DECODER_CMD) — with the shared tokenizer applied for
Moses, a configurable timeout (`AHAIET_TRANSLATION_TIMEOUT_S`, default
120s), OOV warnings computed against the exported source vocabulary,
and per-profile selection: verified corpus retrieval first, then the
trained engine with the best recorded chrF++ from the evaluation
harness, then (with no recorded metrics) Moses before Marian as the
documented default. See docs/MODEL_EVALUATION.md for how the selection
record is produced.

## Reproducibility

- Splits are group-determined (book/chapter blocks) — no RNG in
  splitting; the recorded seed (13) governs tokenizer/vocab training
  order and Marian's `seed:` setting.
- Every dataset file and exported model file carries a sha256 in its
  dataset card / model card; tool versions are recorded at runtime from
  the tools themselves, never written by hand.
- Corpora and model binaries stay outside source control; manifests
  and cards are the provenance record.

## Decoder commands, working directory, and artifact layout (NEW-05, NEW-13, NEW-27)

- **Command forms.** `AHAIET_MOSES_CMD` / `AHAIET_MARIAN_DECODER_CMD`
  accept three forms, resolved by
  `backend/app/services/translation/command.py` with no shell: a plain
  program name/path, an shlex-split string (arguments allowed), or a
  JSON list in the environment / a list in settings — the command
  VECTOR form, e.g. `["/usr/bin/python3", "/path/to/decoder.py"]`.
  The vector form is what tests use with genuinely executable doubles
  (`backend/tests/double_factory.py` writes a shebang + chmod 0o755
  script on POSIX and a `.cmd` wrapper on Windows).
- **Working directory.** Both adapters launch the decoder with
  `cwd=<artifact_dir>`, so relative paths inside exported configs
  resolve against the artifact itself. Training exports additionally
  write ABSOLUTE paths (the exported `moses.ini` entries and the
  Marian `decoder-config.yml` model/vocab paths), and export
  verification resolves every referenced path from an unrelated
  working directory — an artifact must be movable as a directory.
- **Integrity.** Resolution results are cached only within the
  integrity TTL (`AHAIET_ARTIFACT_INTEGRITY_TTL_S`, default 300s) and
  only while the artifact signature is unchanged.
  `verify_artifacts(settings, force=True)` — run at startup and
  available to operators/tests — always rehashes file CONTENT, so a
  same-size in-place edit with a restored mtime is caught.
- **Recommended layout.** Immutable artifact directories named by
  content hash — `artifacts/models/<engine>/<profile>/<sha-prefix>/`
  — activated by pointing the manifest entry at the new directory,
  never by editing files in place inside a live artifact.
