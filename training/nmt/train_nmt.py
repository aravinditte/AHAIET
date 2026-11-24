"""Marian NMT training orchestrator (one language profile per run).

Steps, each logged and aborting on failure:
  1. corpus preparation   training/datasets/prepare_parallel.py
  2. DATA GATE            the profile's training-pair count is checked
                          against a configurable minimum (default 500).
                          Below it, the run writes a not-ready report
                          (JSON + Markdown) into the profile's artifact
                          directory and exits with code 3 — an explicit,
                          expected outcome, not a crash. With the
                          present corpus this is the outcome for
                          Biblical Aramaic (its passages are all in the
                          held-out test partition) and the report says
                          exactly that.
  3. vocabulary           ONE joint SentencePiece model trained on the
                          concatenated source+target training text
                          (documented choice: a tiny corpus benefits
                          from shared subwords for names/numbers, and
                          one vocabulary halves the embedding cost).
  4. training             the `marian` binary with the profile's
                          configuration template (CPU by default;
                          --config-variant gpu selects the GPU variant).
                          A locally supplied pretrained checkpoint can
                          be fine-tuned with --pretrained (local file
                          only; this script never downloads anything).
  5. export               best checkpoint + vocabulary + a generated
                          decoder configuration into
                          artifacts/models/nmt/<profile>/ with a
                          model_card.json; the models manifest entry is
                          flipped to provisioned only after this.

Exit codes: 0 success; 2 data leakage (from corpus preparation);
3 not ready / prerequisite missing (see the printed reason and report);
4 reserved for parity with the SMT orchestrator's data errors.
"""
from __future__ import annotations
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from training.common.manifest import (  # noqa: E402
    REPO_ROOT, describe_file, load_json, manifest_entry_id, sha256_file,
    update_manifest_entry, write_json, write_model_card)
from training.smt.train_smt import Logger, StepError, run_step  # noqa: E402

PROFILES = ("biblical_hebrew", "biblical_aramaic")
SHORT = {"biblical_hebrew": "hebrew", "biblical_aramaic": "aramaic"}
DEFAULT_MIN_TRAIN_PAIRS = 500
DEFAULT_VOCAB_SIZE = 4000
SOURCE_VIEW = "vocalized"


def write_not_ready(profile: str, train_pairs: int, min_pairs: int,
                    dataset_card: dict, reason: str) -> Path:
    artifact_dir = REPO_ROOT / "artifacts" / "models" / "nmt" / SHORT[profile]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "not_ready",
        "engine": "marian",
        "language_profile": profile,
        "train_pairs": train_pairs,
        "min_train_pairs": min_pairs,
        "reason": reason,
        "dataset_card": f"training/datasets/prepared/{SHORT[profile]}/dataset_card.json",
        "small_corpus_statement": dataset_card.get("small_corpus", {}).get("statement"),
        "what_would_change_this": [
            "More aligned training data for this profile (additional imported books or a "
            "deliberately revised split strategy), or",
            "a lower --min-train-pairs value chosen deliberately by the developer, accepting "
            "that a model trained on fewer pairs is a measurement baseline only.",
        ],
    }
    write_json(artifact_dir / "not_ready.json", report)
    md = (f"# Marian NMT — not ready for {profile}\n\n"
          f"- Training pairs available: {train_pairs}\n"
          f"- Configured minimum: {min_pairs}\n"
          f"- Reason: {reason}\n\n"
          "No training was started and no checkpoint exists for this profile. "
          "This report is the expected outcome of the data gate, not an error.\n")
    (artifact_dir / "not_ready.md").write_text(md, encoding="utf-8")
    return artifact_dir


def train_sentencepiece(logger, work: Path, prof_dir: Path, vocab_size: int) -> Path:
    combined = work / "vocab-train.txt"
    src = (prof_dir / f"train.source.{SOURCE_VIEW}.txt").read_text(encoding="utf-8")
    tgt = (prof_dir / "train.target.txt").read_text(encoding="utf-8")
    combined.write_text(src + tgt, encoding="utf-8")
    prefix = work / "vocab"
    try:
        import sentencepiece as spm
    except Exception:
        spm = None
    if spm is not None:
        effective = vocab_size
        spm.SentencePieceTrainer.train(
            input=str(combined), model_prefix=str(prefix), vocab_size=effective,
            model_type="bpe", character_coverage=1.0,
            bos_id=0, pad_id=1, eos_id=2, unk_id=3,
            user_defined_symbols=["<sep>"])
        logger.log(f"SentencePiece joint vocabulary trained via the sentencepiece Python "
                   f"package (vocab_size={effective})")
    elif shutil.which("spm_train"):
        run_step(logger, "spm_train (joint vocabulary)",
                 ["spm_train", f"--input={combined}", f"--model_prefix={prefix}",
                  f"--vocab_size={vocab_size}", "--model_type=bpe",
                  "--character_coverage=1.0", "--bos_id=0", "--pad_id=1",
                  "--eos_id=2", "--unk_id=3"])
    else:
        raise StepError(
            "SentencePiece is not available (neither the Python package nor the spm_train "
            "binary), so the vocabulary cannot be built. Install it with "
            "pip install sentencepiece (see training/requirements.txt), then re-run.")
    model_file = Path(str(prefix) + ".model")
    if not model_file.exists():
        raise StepError(f"SentencePiece finished but {model_file} is missing")
    return model_file


def vocab_size_of(spm_model: Path) -> int:
    vocab_txt = spm_model.with_suffix(".vocab")
    if vocab_txt.exists():
        return sum(1 for _ in vocab_txt.open(encoding="utf-8"))
    return 0


def render_config(profile: str, variant: str, work: Path, prof_dir: Path,
                  model_dir: Path, spm_model: Path, seed: int,
                  pretrained: Path | None) -> Path:
    template_name = f"config-{SHORT[profile]}" + ("-gpu" if variant == "gpu" else "") + ".yml"
    template = (REPO_ROOT / "training" / "nmt" / template_name).read_text(encoding="utf-8")
    values = {
        "{{MODEL_PATH}}": str(model_dir / "model.npz"),
        "{{VOCAB_SPM}}": str(spm_model),
        "{{TRAIN_SRC}}": str(prof_dir / f"train.source.{SOURCE_VIEW}.txt"),
        "{{TRAIN_TGT}}": str(prof_dir / "train.target.txt"),
        "{{VALID_SRC}}": str(prof_dir / f"validation.source.{SOURCE_VIEW}.txt"),
        "{{VALID_TGT}}": str(prof_dir / "validation.target.txt"),
        "{{VOCAB_SIZE}}": str(vocab_size_of(spm_model) or DEFAULT_VOCAB_SIZE),
        "{{SEED}}": str(seed),
        "{{LOG_PATH}}": str(model_dir / "train.log"),
        "{{PRETRAINED_LINE}}": f"pretrained-model: {pretrained}" if pretrained else "",
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(key, value)
    config_path = work / "config.yml"
    config_path.write_text(rendered, encoding="utf-8")
    return config_path


def _select_checkpoint(model_dir: Path) -> tuple[Path, str]:
    """Explicit best-checkpoint selection (AHAIET-051). Lexical-last
    iteration order is never used. Evidence order:
    1. model.npz.best — the best-checkpoint file/symlink Marian writes
       when validation-based selection is enabled; its target (or the
       file itself) is the selection.
    2. model.npz — Marian's own final/best export name.
    3. The validation history: parse train.log / *.log in the model
       dir for the iteration with the lowest recorded validation
       perplexity/ce-mean and select model.iter<that>.npz.
    No explicit evidence -> StepError; the export fails rather than
    guessing."""
    import re as _re
    best = model_dir / "model.npz.best"
    if best.exists():
        if best.is_symlink():
            target = best.resolve()
            if target.exists():
                return target, f"model.npz.best -> {target.name}"
        elif best.is_file():
            return best, "model.npz.best file (Marian best-checkpoint copy)"
    final = model_dir / "model.npz"
    if final.exists():
        return final, "model.npz (Marian final/best export)"
    logs = list(model_dir.glob("*.log")) + list(model_dir.glob("train.log"))
    best_iter, best_value = None, None
    pattern = _re.compile(r"iter[^0-9]{0,12}(\d+)[^\n]*?(?:ce-mean-words|perplexity|valid[^\n]*?)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", _re.I)
    for log_path in logs:
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in pattern.finditer(text):
            iteration, value = int(m.group(1)), float(m.group(2))
            if best_value is None or value < best_value:
                best_iter, best_value = iteration, value
    if best_iter is not None:
        for candidate in model_dir.glob(f"model.iter{best_iter}.npz"):
            return candidate, f"validation log best iteration {best_iter} (value {best_value})"
        for candidate in model_dir.glob("model.iter*.npz"):
            digits = _re.search(r"iter(\d+)", candidate.name)
            if digits and int(digits.group(1)) == best_iter:
                return candidate, f"validation log best iteration {best_iter} (value {best_value})"
    raise StepError(
        f"no explicit best-checkpoint evidence under {model_dir}: no model.npz.best, "
        "no model.npz, and no parseable validation history naming a best iteration. "
        "Refusing to select a checkpoint by lexical order (AHAIET-051).")


def export_model(logger, profile: str, work: Path, model_dir: Path,
                 spm_model: Path, prepared_dir: Path, dataset_card: dict,
                 tool_versions: dict, config_variant: str,
                 pretrained: Path | None) -> Path:
    artifact_dir = REPO_ROOT / "artifacts" / "models" / "nmt" / SHORT[profile]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    checkpoint, selection_evidence = _select_checkpoint(model_dir)
    logger.log(f"checkpoint selection: {selection_evidence}")
    ckpt_dest = artifact_dir / "model.npz"
    shutil.copy2(checkpoint, ckpt_dest)
    spm_dest = artifact_dir / "vocab.spm"
    shutil.copy2(spm_model, spm_dest)
    # NEW-13: absolute model/vocab paths, so the exported decoder
    # config resolves identically from any working directory (the
    # runtime adapter also launches with cwd=artifact_dir).
    decoder_config = (
        "# Generated by training/nmt/train_nmt.py for marian-decoder.\n"
        "# CPU execution: no devices key, so the CPU build decodes on CPU.\n"
        f"models:\n  - {ckpt_dest}\n"
        f"vocabs:\n  - {spm_dest}\n  - {spm_dest}\n"
        "beam-size: 6\nnormalize: 1.0\nword-penalty: 0\n"
        "mini-batch: 16\nmaxi-batch: 100\nworkspace: 512\n")
    decoder_path = artifact_dir / "decoder-config.yml"
    decoder_path.write_text(decoder_config, encoding="utf-8")
    vocab_src = prepared_dir / profile / "vocabulary.source.txt"
    files = [describe_file(ckpt_dest, "checkpoint"), describe_file(spm_dest, "vocabulary"),
             describe_file(decoder_path, "decoder_config")]
    if vocab_src.exists():
        vocab_dest = artifact_dir / "vocabulary.source.txt"
        shutil.copy2(vocab_src, vocab_dest)
        files.append(describe_file(vocab_dest, "vocabulary_source"))
    model_version = f"marian-nmt-{SHORT[profile]}-{dataset_card['corpus']['input_sha256'][:8]}"
    card = write_model_card(
        artifact_dir, engine="marian", language_profile=profile,
        model_version=model_version, primary_file=ckpt_dest, files=files,
        dataset_card_sha256=sha256_file(prepared_dir / profile / "dataset_card.json"),
        dataset_id=f"parallel-{SHORT[profile]}", tool_versions=tool_versions,
        license_text="; ".join(dataset_card.get("licenses", [])),
        provenance="Trained by training/nmt/train_nmt.py from the prepared parallel corpus "
                   f"(config variant: {config_variant}; pretrained checkpoint: "
                   f"{pretrained if pretrained else 'none — trained from scratch'}).",
        extra={"config_variant": config_variant, "checkpoint_selection": selection_evidence,
               "source_view": SOURCE_VIEW,
               "train_pairs": dataset_card["splits"]["train"]["pairs"],
               "vocabulary": "joint SentencePiece model for source and target"})
    update_manifest_entry(
        manifest_entry_id("marian", profile), status="provisioned", path=artifact_dir,
        checksum=card["artifact_sha256"], version=model_version,
        notes=f"Marian NMT exported by training/nmt/train_nmt.py; see {artifact_dir.name}/model_card.json.")
    logger.log(f"exported artifact: {artifact_dir} (model version {model_version})")
    return artifact_dir


def train_profile(profile: str, args) -> int:
    prepared_dir = args.prepared_dir
    work = REPO_ROOT / "training" / "nmt" / "work" / SHORT[profile]
    work.mkdir(parents=True, exist_ok=True)
    logger = Logger(work / "train.log")
    try:
        if not args.skip_prep:
            run_step(logger, "corpus preparation",
                     [sys.executable, str(REPO_ROOT / "training" / "datasets" / "prepare_parallel.py"),
                      "--out-dir", str(prepared_dir), "--profiles", profile])
        card_path = prepared_dir / profile / "dataset_card.json"
        if not card_path.exists():
            raise StepError(f"dataset card not found: {card_path}. Run without --skip-prep first.")
        dataset_card = load_json(card_path)
        train_pairs = dataset_card["splits"]["train"]["pairs"]
        pretrained = Path(args.pretrained) if args.pretrained else None
        if pretrained is not None and not pretrained.exists():
            raise StepError(f"--pretrained checkpoint does not exist: {pretrained}. "
                            "Fine-tuning uses a local file only; nothing is downloaded.")
        if train_pairs < args.min_train_pairs:
            reason = (f"profile {profile} has {train_pairs} training pairs, below the "
                      f"configured minimum of {args.min_train_pairs} for neural training")
            if profile == "biblical_aramaic" and train_pairs == 0:
                reason += (" — under the recorded split strategy every Aramaic passage is in "
                           "the held-out test partition, so there is no Aramaic training "
                           "split at all in the present corpus")
            reason += (". Training a neural model on this little data would produce a "
                       "checkpoint with no expected generalisation, so the run stops here "
                       "by design.")
            write_not_ready(profile, train_pairs, args.min_train_pairs, dataset_card, reason)
            logger.log("NOT READY (data gate): " + reason)
            print(f"\nMarian NMT not ready for {profile}: {reason}\n"
                  f"Report written under artifacts/models/nmt/{SHORT[profile]}/ (not_ready.json/.md).",
                  file=sys.stderr)
            return 3
        if dataset_card["small_corpus"]["statement"]:
            logger.log("SMALL CORPUS: " + dataset_card["small_corpus"]["statement"])
        prof_dir = prepared_dir / profile
        spm_model = train_sentencepiece(logger, work, prof_dir, args.vocab_size)
        model_dir = work / "model"
        model_dir.mkdir(exist_ok=True)
        config_path = render_config(profile, args.config_variant, work, prof_dir,
                                    model_dir, spm_model, args.seed, pretrained)
        logger.log(f"training configuration written: {config_path} (variant: {args.config_variant})")
        marian_bin = args.marian_bin or os.getenv("MARIAN_BIN") or shutil.which("marian")
        if not marian_bin:
            raise StepError(
                "The marian training binary was not found, so training cannot start. The "
                "vocabulary and the rendered configuration above are real and kept. Install "
                "Marian (docs/TRAINING.md), set MARIAN_BIN or pass --marian-bin, then re-run.")
        run_step(logger, "marian training", [marian_bin, "--config", str(config_path)])
        tool_versions = {"marian": marian_bin, "config_variant": args.config_variant}
        ver = subprocess.run([marian_bin, "--version"], capture_output=True, text=True)
        if ver.stdout or ver.stderr:
            tool_versions["marian_version_output"] = (ver.stdout or ver.stderr).strip().splitlines()[0:1]
        export_model(logger, profile, work, model_dir, spm_model, prepared_dir,
                     dataset_card, tool_versions, args.config_variant, pretrained)
        logger.log("NMT training run complete.")
        return 0
    except StepError as e:
        logger.log(f"STOPPED: {e}")
        print(f"\nMarian NMT training stopped for {profile}: {e}", file=sys.stderr)
        return e.code
    finally:
        logger.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train a Marian NMT model for one profile (see module docstring)")
    ap.add_argument("--profile", choices=PROFILES, required=True)
    ap.add_argument("--prepared-dir", type=Path,
                    default=REPO_ROOT / "training" / "datasets" / "prepared")
    ap.add_argument("--skip-prep", action="store_true")
    ap.add_argument("--min-train-pairs", type=int, default=DEFAULT_MIN_TRAIN_PAIRS,
                    help="data gate: below this many training pairs, write a not-ready report and stop")
    ap.add_argument("--vocab-size", type=int, default=DEFAULT_VOCAB_SIZE)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--config-variant", choices=["cpu", "gpu"], default="cpu")
    ap.add_argument("--marian-bin", default=None, help="marian training binary (or MARIAN_BIN)")
    ap.add_argument("--pretrained", default=None,
                    help="local pretrained checkpoint to fine-tune (local file only, never downloaded)")
    args = ap.parse_args(argv)
    return train_profile(args.profile, args)


if __name__ == "__main__":
    raise SystemExit(main())
