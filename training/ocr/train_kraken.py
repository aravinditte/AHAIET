"""Kraken historical-script recognition training orchestrator.

Trains (or fine-tunes) a Kraken recognition checkpoint for ONE script
profile from line-level ground truth, using Kraken's own `ketos train`.
This script never invents a model: if the data or the tool is missing
it stops with an actionable message and a non-zero exit code.

Ground-truth layout (documented, line level):

    <data-dir>/
      provenance.txt          # where the images/transcripts come from,
                              # their licence, and who labelled them
      train/
        line-0001.png         # line image
        line-0001.txt         # its exact transcription (UTF-8)
        ...
      test/                   # held out; used by evaluate_htr.py only

Pipeline:
  1. validate the data directory (paired image/transcript files,
     provenance present — unlabelled or unprovenanced data is refused);
  2. check `ketos` is installed (pip package `kraken`, Linux/WSL2-first);
  3. run ketos train (optionally initialised from an existing local
     checkpoint with --base-checkpoint for fine-tuning);
  4. export the best checkpoint to artifacts/models/kraken/<profile>/
     as model.mlmodel plus a training_card.json (data provenance, line
     counts, tool version, checkpoint sha256), and flip the models
     manifest entry to provisioned.

Exporting a checkpoint does NOT make the script profile "supported":
support additionally requires a measured evaluation record from
training/evaluation/evaluate_htr.py whose checkpoint hash matches
(see backend/app/services/ocr/script_profiles.py). That separation is
deliberate — a trained model with no measured accuracy is not support.

Exit codes: 0 success; 2 data problem; 3 prerequisite tool missing;
4 the ketos run itself failed.
"""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from training.common.manifest import (  # noqa: E402
    REPO_ROOT, load_json, sha256_file, update_manifest_entry, write_json)

IMAGE_SUFFIXES = (".png", ".tif", ".tiff", ".jpg", ".jpeg")


def registry_profiles() -> list[str]:
    registry = REPO_ROOT / "backend" / "app" / "services" / "ocr" / "script_profiles.json"
    data = load_json(registry)
    return [p["id"] for p in data.get("profiles", []) if p.get("route") == "kraken"]


def collect_pairs(directory: Path) -> tuple[list[Path], list[str]]:
    """Return (image files with transcripts, problems)."""
    images, problems = [], []
    if not directory.is_dir():
        return [], [f"directory does not exist: {directory}"]
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() in IMAGE_SUFFIXES:
            transcript = path.with_suffix(".txt")
            if not transcript.is_file():
                problems.append(f"image without transcript: {path.name}")
            elif not transcript.read_text(encoding="utf-8").strip():
                problems.append(f"empty transcript: {transcript.name}")
            else:
                images.append(path)
    if not images and not problems:
        problems.append(f"no line images found in {directory}")
    return images, problems


def ketos_version(ketos: str) -> str | None:
    try:
        proc = subprocess.run([ketos, "--version"], capture_output=True, text=True, timeout=60)
        return (proc.stdout or proc.stderr or "").strip().splitlines()[0] if (proc.stdout or proc.stderr) else None
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train a Kraken recognition checkpoint for one script profile")
    ap.add_argument("--profile", required=True,
                    help="script profile id from the OCR script registry (Kraken route only)")
    ap.add_argument("--data-dir", type=Path, required=True,
                    help="ground-truth root with provenance.txt and train/ line pairs")
    ap.add_argument("--output-dir", type=Path, default=None,
                    help="artifact directory (default artifacts/models/kraken/<profile>)")
    ap.add_argument("--base-checkpoint", type=Path, default=None,
                    help="existing local .mlmodel to initialise from (fine-tuning); never downloaded")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--ketos", default=None, help="ketos executable (default: PATH lookup / KRAKEN_KETOS env)")
    ap.add_argument("--extra-args", default="",
                    help="extra arguments passed through to ketos train, space-separated")
    args = ap.parse_args(argv)

    profiles = registry_profiles()
    if args.profile not in profiles:
        print(f"ERROR: '{args.profile}' is not a Kraken-route script profile. Known: {', '.join(profiles)}")
        return 2
    data_dir: Path = args.data_dir
    provenance_path = data_dir / "provenance.txt"
    if not provenance_path.is_file() or not provenance_path.read_text(encoding="utf-8").strip():
        print("ERROR: data provenance is required: create provenance.txt in the data directory "
              "describing the source of the images/transcriptions and their licence. "
              "Unprovenanced training data is refused.")
        return 2
    images, problems = collect_pairs(data_dir / "train")
    if problems:
        print("ERROR: ground-truth problems:\n  " + "\n  ".join(problems))
        return 2
    if args.base_checkpoint is not None and not args.base_checkpoint.is_file():
        print(f"ERROR: base checkpoint not found: {args.base_checkpoint}")
        return 2

    import os
    ketos = args.ketos or os.getenv("KRAKEN_KETOS") or shutil.which("ketos")
    if not ketos:
        print("ERROR: ketos (the Kraken training CLI) is not installed. Install the optional "
              "Kraken dependency — Linux/WSL2-first: pip install \"kraken>=4.3\" "
              "(or the backend extra: pip install -e \"backend[kraken]\"); "
              "see docs/OCR.md and scripts/provision-kraken.ps1.")
        return 3

    output_dir: Path = args.output_dir or (REPO_ROOT / "artifacts" / "models" / "kraken" / args.profile)
    work_dir = output_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    prefix = work_dir / "kraken-model"
    cmd = [ketos, "train", "--output", str(prefix), "--epochs", str(args.epochs)]
    if args.base_checkpoint is not None:
        cmd += ["--load", str(args.base_checkpoint)]
    if args.extra_args.strip():
        cmd += args.extra_args.split()
    for image in images:
        cmd += ["--training-files", str(image)]
    print(f"Training on {len(images)} line pairs from {data_dir / 'train'}")
    print("Running:", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("ERROR: ketos train failed.\n" + (proc.stderr or proc.stdout)[-2000:])
        return 4

    produced = sorted(work_dir.glob("*.mlmodel"), key=lambda p: p.stat().st_mtime)
    if not produced:
        print("ERROR: ketos train reported success but produced no .mlmodel checkpoint in "
              f"{work_dir}. Nothing was exported.")
        return 4
    best = produced[-1]
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = output_dir / "model.mlmodel"
    shutil.copyfile(best, checkpoint)
    checksum = sha256_file(checkpoint)
    version = f"kraken-{args.profile}-{checksum[:8]}"
    card = {
        "engine": "kraken",
        "script_profile": args.profile,
        "model_version": version,
        "checkpoint": {"path": checkpoint.name, "sha256": checksum,
                       "size_bytes": checkpoint.stat().st_size},
        "files": [{"path": checkpoint.name, "role": "checkpoint", "sha256": checksum,
                   "size_bytes": checkpoint.stat().st_size}],
        "data": {"directory": str(data_dir), "train_lines": len(images),
                 "provenance": provenance_path.read_text(encoding="utf-8").strip()},
        "base_checkpoint": str(args.base_checkpoint) if args.base_checkpoint else None,
        "tool_versions": {"ketos": ketos_version(ketos)},
        "license": "Checkpoint derives from the training data described in data.provenance; "
                   "Kraken itself is Apache-2.0.",
        "metrics": None,
    }
    write_json(output_dir / "training_card.json", card)
    entry_id = f"kraken-{args.profile.replace('_', '-')}"
    try:
        update_manifest_entry(entry_id, status="provisioned", path=output_dir,
                              checksum=checksum, version=version,
                              notes=f"Trained with training/ocr/train_kraken.py on {len(images)} "
                                    "line pairs; see training_card.json in the artifact directory. "
                                    "Support still requires a measured evaluation record "
                                    f"(artifacts/benchmarks/htr-eval-{args.profile}.json).")
    except KeyError:
        print(f"WARNING: models manifest has no entry '{entry_id}'; the checkpoint was exported "
              "but the manifest was not flipped.")
    print(json.dumps({"checkpoint": str(checkpoint), "sha256": checksum,
                      "training_card": str(output_dir / "training_card.json")}, indent=2))
    print("Next step: measure it — training/evaluation/evaluate_htr.py "
          f"--profile {args.profile} --checkpoint {checkpoint} --test-dir {data_dir / 'test'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
