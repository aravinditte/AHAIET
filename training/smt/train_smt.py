"""Moses SMT training orchestrator (one language profile per run).

Pipeline, in order, each step logged and aborting the run on failure:
  1. corpus preparation      training/datasets/prepare_parallel.py
  2. tokenization            Moses tokenizer.perl when MOSES_HOME is set
                             (English target; the Hebrew-script source
                             always uses the repository tokenizer, and
                             every substitution is written to the log),
                             otherwise the repository tokenizer for both
  3. corpus cleaning         Moses clean-corpus-n.perl when available,
                             otherwise the repository length/ratio filter
  4. language model          KenLM lmplz on the English training side
                             (+ build_binary when present). If KenLM is
                             missing the run STOPS with an actionable
                             message — a language model is never faked.
  5. translation model       Moses train-model.perl (GIZA++ alignment,
                             phrase extraction, lexicalised reordering)
  6. tuning                  MERT (tuning/mert-moses.pl) on the
                             validation split when the Moses binary and
                             tuning script are present; otherwise the
                             untuned model is exported and the skip is
                             recorded in the model card
  7. export                  artifact directory under
                             artifacts/models/smt/<profile>/ with the
                             configuration rewritten to the exported
                             file names, vocabulary.source.txt, and a
                             model_card.json; the models manifest entry
                             is flipped to provisioned only after this

This is a WSL2-first workflow on Windows (docs/TRAINING.md gives the
exact apt installs and the PowerShell wrapper scripts/smt-train.ps1).
Runtime inference does NOT use this script and does NOT need WSL2: the
backend adapter runs a locally installed moses binary directly.

Exit codes: 0 success; 2 data leakage (from corpus preparation);
3 a prerequisite tool is missing (actionable message printed);
4 insufficient training data for this profile.
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
    update_manifest_entry, write_model_card)

PROFILES = ("biblical_hebrew", "biblical_aramaic")
SHORT = {"biblical_hebrew": "hebrew", "biblical_aramaic": "aramaic"}
DEFAULT_MIN_TRAIN_PAIRS = 50
SOURCE_VIEW = "vocalized"  # canonical training view; see prepare_parallel


class StepError(Exception):
    def __init__(self, message: str, code: int = 3):
        super().__init__(message)
        self.code = code


class Logger:
    def __init__(self, log_path: Path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = log_path.open("w", encoding="utf-8")

    def log(self, message: str) -> None:
        print(message, flush=True)
        self._fh.write(message + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def run_step(logger: Logger, name: str, cmd: list[str], *, cwd: Path | None = None,
             env: dict | None = None) -> str:
    logger.log(f"\n=== STEP {name} ===\n$ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if proc.stdout:
        logger.log(proc.stdout.rstrip())
    if proc.stderr:
        logger.log("[stderr] " + proc.stderr.rstrip())
    if proc.returncode != 0:
        raise StepError(f"step '{name}' failed with exit code {proc.returncode}: "
                        f"{' '.join(cmd)}")
    return proc.stdout or ""


def repo_tokenize(logger: Logger, mode: str, src: Path, dest: Path, view: str = "vocalized") -> None:
    """Tokenize one file with the repository tokenizer (logged substitution)."""
    script = REPO_ROOT / "training" / "datasets" / "tokenize.py"
    with src.open(encoding="utf-8") as fin, dest.open("w", encoding="utf-8") as fout:
        proc = subprocess.run([sys.executable, str(script), "--mode", mode, "--view", view],
                              stdin=fin, stdout=fout, capture_output=True, text=True)
    if proc.returncode != 0:
        raise StepError(f"repository tokenizer failed on {src}: {proc.stderr[:400]}")
    logger.log(f"tokenized {src.name} -> {dest.name} (repository tokenizer)")


def clean_corpus(logger: Logger, src: Path, tgt: Path, out_prefix: Path,
                 min_len: int = 1, max_len: int = 80, max_ratio: float = 3.0) -> int:
    """Repository equivalent of Moses clean-corpus-n.perl length/ratio
    filtering, used (and logged) when the Moses scripts are absent."""
    src_lines = src.read_text(encoding="utf-8").splitlines()
    tgt_lines = tgt.read_text(encoding="utf-8").splitlines()
    # AHAIET-049: never zip-truncate silently. Unequal line counts are
    # a hard alignment failure; every discarded pair is counted with
    # its reason and line number in the training log.
    if len(src_lines) != len(tgt_lines):
        raise StepError(
            f"clean-corpus: source has {len(src_lines)} lines but target has "
            f"{len(tgt_lines)} lines — the parallel corpus is misaligned and "
            "cleaning refuses to drop the excess silently.")
    kept_src, kept_tgt = [], []
    dropped: dict[str, int] = {}
    for i, (s_line, t_line) in enumerate(zip(src_lines, tgt_lines), start=1):
        ns, nt = len(s_line.split()), len(t_line.split())
        reason = None
        if ns == 0 and nt == 0:
            reason = "both_blank"
        elif ns == 0 or nt == 0:
            reason = "one_side_blank"
        elif not (min_len <= ns <= max_len and min_len <= nt <= max_len):
            reason = "length_out_of_bounds"
        elif max(ns, nt) / max(min(ns, nt), 1) > max_ratio:
            reason = "length_ratio"
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
            logger.log(f"clean-corpus: dropped line {i} ({reason})")
            continue
        kept_src.append(s_line)
        kept_tgt.append(t_line)
    Path(str(out_prefix) + ".src").write_text("".join(l + "\n" for l in kept_src), encoding="utf-8")
    Path(str(out_prefix) + ".en").write_text("".join(l + "\n" for l in kept_tgt), encoding="utf-8")
    logger.log(f"clean-corpus (repository filter): kept {len(kept_src)}, "
               f"dropped {sum(dropped.values())} by reason {dropped}")
    return len(kept_src)


def find_tool(explicit: str | None, env_names: tuple[str, ...], path_names: tuple[str, ...]) -> str | None:
    if explicit:
        return explicit
    for name in env_names:
        if os.getenv(name):
            return os.environ[name]
    for name in path_names:
        found = shutil.which(name)
        if found:
            return found
    return None


def prepare_data(logger: Logger, profile: str, prepared_dir: Path, skip: bool) -> dict:
    if not skip:
        run_step(logger, "corpus preparation",
                 [sys.executable, str(REPO_ROOT / "training" / "datasets" / "prepare_parallel.py"),
                  "--out-dir", str(prepared_dir), "--profiles", profile])
    card_path = prepared_dir / profile / "dataset_card.json"
    if not card_path.exists():
        raise StepError(f"dataset card not found: {card_path}. Run without --skip-prep, or run "
                        "training/datasets/prepare_parallel.py first.")
    return load_json(card_path)


def export_model(logger: Logger, profile: str, work: Path, final_ini: Path,
                 lm_file: Path, prepared_dir: Path, dataset_card: dict,
                 tool_versions: dict, tuning: dict) -> Path:
    artifact_dir = REPO_ROOT / "artifacts" / "models" / "smt" / SHORT[profile]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    model_dir = work / "model"
    copied: list[Path] = []
    # Phrase table (+ binarised form when train-model/binarize produced one)
    for candidate in sorted(model_dir.glob("phrase-table*")):
        dest = artifact_dir / candidate.name
        shutil.copy2(candidate, dest)
        copied.append(dest)
    for candidate in sorted(model_dir.glob("reordering-table*")):
        dest = artifact_dir / candidate.name
        shutil.copy2(candidate, dest)
        copied.append(dest)
    lm_dest = artifact_dir / lm_file.name
    shutil.copy2(lm_file, lm_dest)
    copied.append(lm_dest)
    if not any(p.name.startswith("phrase-table") for p in copied):
        raise StepError(f"no phrase table found under {model_dir}; training did not produce one")
    # Rewrite the configuration so every path is ABSOLUTE and points
    # inside the exported artifact directory (NEW-13): the runtime
    # adapter launches the decoder with cwd=artifact_dir, and absolute
    # paths additionally make the exported config resolve identically
    # from any working directory. The training work tree is
    # disposable; the artifact directory is the runtime contract.
    ini_text = final_ini.read_text(encoding="utf-8")
    replacements = {str(model_dir): str(artifact_dir), str(work): str(artifact_dir),
                    str(lm_file): str(lm_dest)}
    for old, new in replacements.items():
        ini_text = ini_text.replace(old, new)
    ini_dest = artifact_dir / "moses.ini"
    ini_dest.write_text(ini_text, encoding="utf-8")
    # Export verification (AHAIET-050): parse every path referenced by
    # the exported moses.ini and verify each file exists INSIDE the
    # export directory. The report is written next to the artifact;
    # any unresolved reference fails the export loudly.
    import re as _re
    unresolved: list[str] = []
    resolved: list[str] = []
    for raw_line in ini_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for token in _re.split(r"\s+", line):
            token = token.strip()
            if not token or token.startswith("-"):
                continue
            looks_like_path = ("/" in token or "\\" in token or token.endswith(
                (".gz", ".binary", ".arpa", ".ini", ".txt", ".bin")))
            if not looks_like_path:
                continue
            candidate = (artifact_dir / token).resolve() if not Path(token).is_absolute() \
                else Path(token).resolve()
            if artifact_dir.resolve() in candidate.parents or candidate == artifact_dir.resolve():
                if candidate.exists():
                    resolved.append(token)
                else:
                    unresolved.append(token)
            elif not candidate.exists():
                unresolved.append(token)
    report_path = artifact_dir / "export_verification.json"
    import json as _json
    report_path.write_text(_json.dumps(
        {"moses_ini": "moses.ini", "resolved": sorted(set(resolved)),
         "unresolved": sorted(set(unresolved)),
         "resolution_basis": "exported paths are absolute (NEW-13); each was resolved "
                             "and existence-checked without reference to the process "
                             "working directory, and the runtime adapter additionally "
                             "launches the decoder with cwd set to the artifact directory"}, indent=2), encoding="utf-8")
    if unresolved:
        raise StepError(
            "SMT export verification failed: moses.ini references files that do not "
            f"resolve inside the export directory: {sorted(set(unresolved))}. "
            f"See {report_path}.")
    vocab_src = prepared_dir / profile / "vocabulary.source.txt"
    files = [describe_file(ini_dest, "config")]
    for p in copied:
        role = ("phrase_table" if p.name.startswith("phrase-table")
                else "reordering_table" if p.name.startswith("reordering-table")
                else "language_model")
        files.append(describe_file(p, role))
    if vocab_src.exists():
        vocab_dest = artifact_dir / "vocabulary.source.txt"
        shutil.copy2(vocab_src, vocab_dest)
        files.append(describe_file(vocab_dest, "vocabulary_source"))
    model_version = f"moses-smt-{SHORT[profile]}-{dataset_card['corpus']['input_sha256'][:8]}"
    card = write_model_card(
        artifact_dir, engine="moses", language_profile=profile,
        model_version=model_version, primary_file=ini_dest, files=files,
        dataset_card_sha256=sha256_file(prepared_dir / profile / "dataset_card.json"),
        dataset_id=f"parallel-{SHORT[profile]}", tool_versions=tool_versions,
        license_text="; ".join(dataset_card.get("licenses", [])),
        provenance="Trained by training/smt/train_smt.py from the prepared parallel corpus "
                   f"(dataset card sha256 recorded); tuning: {tuning.get('status')}.",
        extra={"tuning": tuning, "source_view": SOURCE_VIEW,
               "train_pairs": dataset_card["splits"]["train"]["pairs"]})
    update_manifest_entry(
        manifest_entry_id("moses", profile), status="provisioned", path=artifact_dir,
        checksum=card["artifact_sha256"], version=model_version,
        notes=f"Moses SMT exported by training/smt/train_smt.py; see {artifact_dir.name}/model_card.json.")
    logger.log(f"exported artifact: {artifact_dir} (model version {model_version})")
    return artifact_dir


def train_profile(profile: str, args) -> int:
    prepared_dir = args.prepared_dir
    work = REPO_ROOT / "training" / "smt" / "work" / SHORT[profile]
    work.mkdir(parents=True, exist_ok=True)
    logger = Logger(work / "train.log")
    try:
        dataset_card = prepare_data(logger, profile, prepared_dir, args.skip_prep)
        train_pairs = dataset_card["splits"]["train"]["pairs"]
        if train_pairs == 0:
            raise StepError(
                f"profile {profile} has 0 training pairs under the recorded split strategy "
                "(see the dataset card and prep report). SMT training cannot proceed: revise "
                "the split strategy deliberately or import more data for this profile first.", code=4)
        if train_pairs < args.min_train_pairs and not args.allow_small:
            raise StepError(
                f"profile {profile} has {train_pairs} training pairs, below the configured "
                f"minimum of {args.min_train_pairs} for phrase extraction. Re-run with "
                "--allow-small to train a measurement-only baseline anyway.", code=4)
        if dataset_card["small_corpus"]["statement"]:
            logger.log("SMALL CORPUS: " + dataset_card["small_corpus"]["statement"])
        prof_dir = prepared_dir / profile
        src_raw = prof_dir / f"train.source.{SOURCE_VIEW}.txt"
        tgt_raw = prof_dir / "train.target.txt"
        val_src_raw = prof_dir / f"validation.source.{SOURCE_VIEW}.txt"
        val_tgt_raw = prof_dir / "validation.target.txt"

        moses_home = Path(args.moses_home) if args.moses_home else (
            Path(os.environ["MOSES_HOME"]) if os.getenv("MOSES_HOME") else None)
        scripts = (moses_home / "scripts") if moses_home else None
        tokenizer_perl = scripts / "tokenizer" / "tokenizer.perl" if scripts else None
        clean_perl = scripts / "training" / "clean-corpus-n.perl" if scripts else None
        train_model_perl = scripts / "training" / "train-model.perl" if scripts else None

        tok_dir = work / "tokenized"
        tok_dir.mkdir(exist_ok=True)
        # Source side: always the repository tokenizer (Moses ships no
        # Hebrew-script tokenizer); the substitution is logged.
        logger.log("tokenizer: repository tokenizer for the Hebrew-script source side "
                   "(Moses has no Hebrew tokenizer; substitution logged, not silent)")
        repo_tokenize(logger, "source", src_raw, tok_dir / "train.src", SOURCE_VIEW)
        repo_tokenize(logger, "source", val_src_raw, tok_dir / "validation.src", SOURCE_VIEW)
        if tokenizer_perl and tokenizer_perl.exists():
            for raw, out in ((tgt_raw, tok_dir / "train.en"), (val_tgt_raw, tok_dir / "validation.en")):
                with raw.open(encoding="utf-8") as fin, out.open("w", encoding="utf-8") as fout:
                    proc = subprocess.run(["perl", str(tokenizer_perl), "-l", "en"],
                                          stdin=fin, stdout=fout, capture_output=True, text=True)
                if proc.returncode != 0:
                    raise StepError(f"Moses tokenizer.perl failed on {raw}: {proc.stderr[:400]}")
            logger.log("tokenizer: Moses tokenizer.perl for the English target side")
        else:
            logger.log("tokenizer: MOSES_HOME/tokenizer.perl not found; repository tokenizer "
                       "used for the English target side as well (substitution logged)")
            repo_tokenize(logger, "target", tgt_raw, tok_dir / "train.en")
            repo_tokenize(logger, "target", val_tgt_raw, tok_dir / "validation.en")

        corpus_dir = work / "corpus"
        corpus_dir.mkdir(exist_ok=True)
        if clean_perl and clean_perl.exists():
            run_step(logger, "clean-corpus-n.perl",
                     ["perl", str(clean_perl), str(tok_dir / "train"), "src", "en",
                      str(corpus_dir / "train.clean"), "1", "80"])
        else:
            logger.log("clean-corpus-n.perl not found; repository length/ratio filter used "
                       "(substitution logged)")
            clean_corpus(logger, tok_dir / "train.src", tok_dir / "train.en", corpus_dir / "train.clean")
        clean_src, clean_tgt = corpus_dir / "train.clean.src", corpus_dir / "train.clean.en"
        if not clean_src.exists() or not clean_tgt.exists():
            raise StepError("cleaning produced no corpus files; see the training log")

        lmplz = find_tool(args.kenlm_bin, ("KENLM_BIN",), ("lmplz",))
        if not lmplz:
            raise StepError(
                "KenLM lmplz was not found, so no language model can be built and the run "
                "stops here (a language model is never faked). Install KenLM "
                "(docs/TRAINING.md: git clone https://github.com/kpu/kenlm, build, then set "
                "KENLM_BIN or pass --kenlm-bin), then re-run.")
        lm_dir = work / "lm"
        lm_dir.mkdir(exist_ok=True)
        lm_arpa = lm_dir / "lm.arpa"
        with clean_tgt.open(encoding="utf-8") as fin, lm_arpa.open("w", encoding="utf-8") as fout:
            proc = subprocess.run([lmplz, "-o", "3"], stdin=fin, stdout=fout,
                                  capture_output=True, text=True)
        if proc.returncode != 0:
            raise StepError(f"lmplz failed: {proc.stderr[:400]}")
        logger.log(f"language model (KenLM lmplz, order 3): {lm_arpa}")
        lm_file = lm_arpa
        build_binary = shutil.which("build_binary")
        kenlm_dir = Path(lmplz).parent
        if (kenlm_dir / "build_binary").exists():
            build_binary = str(kenlm_dir / "build_binary")
        if build_binary:
            lm_binary = lm_dir / "lm.binary"
            run_step(logger, "kenlm build_binary", [build_binary, str(lm_arpa), str(lm_binary)])
            lm_file = lm_binary
        else:
            logger.log("kenlm build_binary not found; the ARPA language model is exported "
                       "and referenced from moses.ini (KenLM reads ARPA; noted, not hidden)")

        if not train_model_perl or not train_model_perl.exists():
            raise StepError(
                "Moses train-model.perl was not found (MOSES_HOME is unset or incomplete), so "
                "the translation model cannot be trained. Install Moses in WSL2 "
                "(docs/TRAINING.md), set MOSES_HOME, and re-run. Corpus preparation, "
                "tokenization, cleaning, and the language model above are real and kept in "
                f"{work}.")
        lm_arg = f"0:3:{lm_file}"
        train_cmd = ["perl", str(train_model_perl), "-root-dir", str(work),
                     "-corpus", str(corpus_dir / "train.clean"), "-f", "src", "-e", "en",
                     "-alignment", "grow-diag-final-and",
                     "-reordering", "msd-bidirectional-fe", "-lm", lm_arg]
        external_bin = args.external_bin_dir or os.getenv("MOSES_EXTERNAL_BIN_DIR")
        if external_bin:
            train_cmd += ["--external-bin-dir", external_bin]
        run_step(logger, "train-model.perl (GIZA++ alignment, phrase extraction, reordering)",
                 train_cmd)
        trained_ini = work / "model" / "moses.ini"
        if not trained_ini.exists():
            raise StepError(f"train-model.perl finished but {trained_ini} is missing")

        tuning = {"status": "not_run", "reason": None}
        final_ini = trained_ini
        moses_bin = find_tool(args.moses_bin, ("MOSES_BIN",), ("moses",))
        mert_perl = scripts / "tuning" / "mert-moses.pl" if scripts else None
        if args.skip_tuning:
            tuning["reason"] = "--skip-tuning was passed"
        elif not (moses_bin and mert_perl and mert_perl.exists()):
            tuning["reason"] = ("moses binary and/or mert-moses.pl not available; the untuned "
                                "model is exported and this skip is recorded")
            logger.log("MERT skipped: " + tuning["reason"])
        else:
            mert_dir = work / "mert-work"
            mert_dir.mkdir(exist_ok=True)
            run_step(logger, "MERT tuning on the validation split",
                     ["perl", str(mert_perl), str(tok_dir / "validation.src"),
                      str(tok_dir / "validation.en"), moses_bin, str(trained_ini),
                      "--working-dir", str(mert_dir), "--decoder-flags", "-threads 1"])
            tuned_ini = mert_dir / "moses.ini"
            if tuned_ini.exists():
                final_ini = tuned_ini
                tuning = {"status": "completed", "reason": None,
                          "validation_pairs": dataset_card["splits"]["validation"]["pairs"]}
            else:
                tuning["reason"] = "MERT produced no tuned moses.ini; untuned model exported"
                logger.log("MERT: " + tuning["reason"])
        tool_versions = {"moses_home": str(moses_home) if moses_home else None,
                         "kenlm_lmplz": lmplz, "train_model_perl": str(train_model_perl)}
        if moses_bin:
            ver = subprocess.run([moses_bin, "--version"], capture_output=True, text=True)
            tool_versions["moses_decoder"] = (ver.stderr or ver.stdout or "").strip().splitlines()[0:1]
        export_model(logger, profile, work, final_ini, lm_file, prepared_dir,
                     dataset_card, tool_versions, tuning)
        logger.log("SMT training run complete.")
        return 0
    except StepError as e:
        logger.log(f"STOPPED: {e}")
        print(f"\nSMT training stopped for {profile}: {e}", file=sys.stderr)
        return e.code
    finally:
        logger.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train a Moses SMT model for one profile (see module docstring)")
    ap.add_argument("--profile", choices=PROFILES, required=True)
    ap.add_argument("--prepared-dir", type=Path,
                    default=REPO_ROOT / "training" / "datasets" / "prepared")
    ap.add_argument("--skip-prep", action="store_true", help="reuse an existing prepared dataset")
    ap.add_argument("--moses-home", default=None, help="Moses installation root (or MOSES_HOME)")
    ap.add_argument("--moses-bin", default=None, help="moses decoder binary (for tuning/version)")
    ap.add_argument("--kenlm-bin", default=None, help="KenLM lmplz binary (or KENLM_BIN)")
    ap.add_argument("--external-bin-dir", default=None,
                    help="directory with mgiza/mgiza++ for train-model.perl (or MOSES_EXTERNAL_BIN_DIR)")
    ap.add_argument("--min-train-pairs", type=int, default=DEFAULT_MIN_TRAIN_PAIRS)
    ap.add_argument("--allow-small", action="store_true",
                    help="train even below the minimum pair count (measurement-only baseline)")
    ap.add_argument("--skip-tuning", action="store_true")
    args = ap.parse_args(argv)
    return train_profile(args.profile, args)


if __name__ == "__main__":
    raise SystemExit(main())
