"""Marian NMT inference adapter (real subprocess integration).

The adapter resolves the exported artifact directory for one manifest
entry (model checkpoint + SentencePiece vocabulary + decoder
configuration + model card, checked by model_artifacts.resolve_entry),
then runs the locally installed `marian-decoder` binary with the
generated decoder configuration, feeding the raw source text on stdin
(SentencePiece inside Marian handles segmentation, so the backend does
not pre-tokenize for this engine). Execution is CPU-only unless the
exported decoder configuration itself selects a GPU device.

Training/fine-tuning happens outside the backend
(training/nmt/train_nmt.py); this adapter never downloads anything.
"""
from __future__ import annotations
import shutil
import subprocess

from app.core.config import Settings
from app.core.errors import AppError, UnavailableError
from . import model_artifacts
from .model_artifacts import ArtifactResolution


def resolve(settings: Settings, entry: dict) -> ArtifactResolution:
    return model_artifacts.resolve_entry(entry)


def run(entry: dict, text: str, settings: Settings) -> dict:
    resolution = model_artifacts.resolve_entry(entry)
    if not resolution.ok:
        raise UnavailableError(
            "marian_unavailable",
            "The Marian NMT artifact for this language profile is incomplete, so no translation was produced.",
            "Missing: " + "; ".join(resolution.missing) +
            f" (artifact directory: {resolution.artifact_dir}). "
            "Train and export a model first (docs/TRAINING.md), then update artifacts/manifests/models.json.")
    exe = settings.marian_decoder_cmd if settings and settings.marian_decoder_cmd else "marian-decoder"
    if shutil.which(exe) is None:
        raise UnavailableError(
            "marian_unavailable",
            "The marian-decoder binary was not found, so no translation was produced.",
            f"Looked for '{exe}'. Install Marian locally or set AHAIET_MARIAN_DECODER_CMD to the decoder path.")
    decoder_config = model_artifacts.card_file(
        resolution, ("decoder_config",), ("decoder-config.yml", "config-decoder.yml", "decoder_config.yml"))
    # Marian reads running text line by line; a passage is one line.
    single_line = " ".join((text or "").split())
    try:
        proc = subprocess.run([exe, "-c", str(decoder_config)], input=single_line + "\n",
                              capture_output=True, text=True,
                              timeout=settings.translation_timeout_s if settings else 120.0)
    except subprocess.TimeoutExpired:
        raise AppError(504, "translation_timeout",
                       "The Marian decoder exceeded the configured translation timeout.",
                       f"timeout={settings.translation_timeout_s if settings else 120.0}s")
    if proc.returncode != 0:
        raise UnavailableError("marian_failed", "The Marian decoder exited with an error.",
                               (proc.stderr or "")[:500])
    english = proc.stdout.strip()
    coverage = model_artifacts.compute_coverage(text, resolution)
    warnings: list[str] = []
    if coverage is None:
        warnings.append("No source vocabulary artifact was exported with this model, "
                        "so word-level coverage could not be computed.")
    elif coverage["oov_words"]:
        warnings.append("Source words absent from the training vocabulary "
                        "(SentencePiece will segment them; reported for transparency): "
                        + ", ".join(coverage["oov_words"]))
    return {"english_translation": english, "engine": "marian",
            "model_version": resolution.model_version,
            "artifact_sha256": resolution.artifact_sha256,
            "evaluation_state": resolution.evaluation_state,
            "coverage": coverage, "warnings": warnings}
