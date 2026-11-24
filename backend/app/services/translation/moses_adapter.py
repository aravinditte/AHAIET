"""Moses SMT inference adapter (real subprocess integration).

The adapter resolves the exported artifact directory for one manifest
entry (moses.ini + phrase table + language model + model card, checked
by model_artifacts.resolve_entry), then runs the locally installed
`moses` decoder binary with the tokenized source text on stdin. The
decoder is invoked per request: Moses loads its tables on startup, so
this favours correctness and simplicity over latency on CPU; the model
vocabulary used for OOV reporting is loaded once and cached.

Training happens outside the backend (training/smt/train_smt.py, a
WSL2-first workflow); runtime inference never requires WSL2 — only a
locally installed moses binary (AHAIET_MOSES_CMD or PATH).
"""
from __future__ import annotations
import shutil
import subprocess

from app.core.config import Settings
from app.core.errors import AppError, UnavailableError
from app.services.language.tokenize import detokenize_target, tokenize_source_line
from . import model_artifacts
from .model_artifacts import ArtifactResolution


def resolve(settings: Settings, entry: dict) -> ArtifactResolution:
    return model_artifacts.resolve_entry(entry)


def run(entry: dict, text: str, settings: Settings) -> dict:
    resolution = model_artifacts.resolve_entry(entry)
    if not resolution.ok:
        raise UnavailableError(
            "moses_unavailable",
            "The Moses SMT artifact for this language profile is incomplete, so no translation was produced.",
            "Missing: " + "; ".join(resolution.missing) +
            f" (artifact directory: {resolution.artifact_dir}). "
            "Train and export a model first (docs/TRAINING.md), then update artifacts/manifests/models.json.")
    exe = settings.moses_cmd if settings and settings.moses_cmd else "moses"
    if not _is_executable(exe):
        raise UnavailableError(
            "moses_unavailable",
            "The Moses decoder binary was not found, so no translation was produced.",
            f"Looked for '{exe}'. Install Moses locally or set AHAIET_MOSES_CMD to the decoder path.")
    ini = model_artifacts.card_file(resolution, ("config",), ("moses.ini",))
    tokenized = tokenize_source_line(text)
    try:
        proc = subprocess.run([exe, "-f", str(ini)], input=tokenized + "\n",
                              capture_output=True, text=True,
                              timeout=settings.translation_timeout_s if settings else 120.0)
    except subprocess.TimeoutExpired:
        raise AppError(504, "translation_timeout",
                       "The Moses decoder exceeded the configured translation timeout.",
                       f"timeout={settings.translation_timeout_s if settings else 120.0}s")
    if proc.returncode != 0:
        raise UnavailableError("moses_failed", "The Moses decoder exited with an error.",
                               (proc.stderr or "")[:500])
    english = detokenize_target(proc.stdout.strip())
    coverage = model_artifacts.compute_coverage(text, resolution)
    return _result(resolution, english, coverage)


def _is_executable(exe: str) -> bool:
    return shutil.which(exe) is not None


def _result(resolution: ArtifactResolution, english: str, coverage: dict | None) -> dict:
    warnings: list[str] = []
    if coverage is None:
        warnings.append("No source vocabulary artifact was exported with this model, "
                        "so out-of-vocabulary coverage could not be computed.")
    elif coverage["oov_words"]:
        warnings.append("Out-of-vocabulary source words (reported, never silently dropped): "
                        + ", ".join(coverage["oov_words"]))
    return {"english_translation": english, "engine": "moses",
            "model_version": resolution.model_version,
            "artifact_sha256": resolution.artifact_sha256,
            "evaluation_state": resolution.evaluation_state,
            "coverage": coverage, "warnings": warnings}
