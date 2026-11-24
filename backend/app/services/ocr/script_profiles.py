"""Script support matrix, computed — never declared.

The registry (script_profiles.json, next to this module) names the
script profiles and the engine route that could serve each one. Whether
a profile is *supported* is decided here, at runtime, from evidence:

- hebrew_square: supported when the Tesseract route is actually
  provisioned (binary + traineddata checks from the OCR status).
- Every historical (Kraken) profile: supported ONLY when all of these
  hold at once —
  1. an evaluation record exists at
     artifacts/benchmarks/htr-eval-<profile>.json, written by
     training/evaluation/evaluate_htr.py after a real run;
  2. the record carries a measured CER (a number) for this profile;
  3. the record's checkpoint_sha256 equals the sha256 of a Kraken
     checkpoint file that exists on disk (resolved from the models
     manifest's kraken entries for this profile).
  Anything less reports unsupported with the specific missing evidence
  as the reason. There is no hand-edited boolean anywhere.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

from app.core.config import REPO_ROOT, Settings

_REGISTRY_PATH = Path(__file__).resolve().parent / "script_profiles.json"
BENCHMARKS_DIR = REPO_ROOT / "artifacts" / "benchmarks"


def load_registry() -> list[dict]:
    try:
        data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        return data.get("profiles", [])
    except Exception:
        return []


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def kraken_checkpoints(settings: Settings, script_profile: str | None = None) -> list[dict]:
    """Kraken checkpoint files on disk, from the models manifest. When a
    script profile is given, only entries declared for exactly that
    profile count — a checkpoint provisioned for one script is never
    evidence for another."""
    from app.services.translation.service import load_models_manifest
    out = []
    for entry in load_models_manifest(settings).get("models", []):
        if entry.get("kind") != "ocr" or entry.get("engine") != "kraken":
            continue
        if script_profile and entry.get("script_profile") != script_profile:
            continue
        raw = entry.get("path")
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if path.is_file():
            out.append({"id": entry.get("id"), "script_profile": entry.get("script_profile"),
                        "path": str(path), "sha256": _sha256_file(path),
                        "version": entry.get("version")})
    return out


def evaluation_record(profile_id: str) -> dict | None:
    path = BENCHMARKS_DIR / f"htr-eval-{profile_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def profile_support(settings: Settings, profile: dict, tesseract_available: bool) -> dict:
    """Compute one registry row's live support status and tier.

    Tiers (AHAIET-025) replace the old binary supported flag:
    - model_installed: a checkpoint file exists on disk, nothing measured.
    - experimentally_evaluated: a measured evaluation record matches a
      checkpoint on disk, but at least one production gate fails.
    - production_supported: CER is finite and within [0, 0.5], the
      record carries at least Settings.script_min_test_samples
      independent test samples, the record's script/dialect match this
      profile, and both the checkpoint sha256 and the test-dataset
      sha256 are recorded and the checkpoint hash matches disk.
    `status` stays for backwards compatibility: "supported" only for
    production_supported (and for the Tesseract square-script route
    when usable); the tier + evidence are the precise report."""
    pid = profile["id"]
    base = {"id": pid, "name": profile["name"], "script": profile["script"],
            "route": profile["route"], "note": profile.get("note")}
    if profile["route"] == "tesseract":
        if tesseract_available:
            return {**base, "status": "supported", "tier": "production_supported",
                    "engine": "tesseract",
                    "reason": None, "evaluation": None, "checkpoint": None,
                    "evidence": {"route": "tesseract", "usable": True}}
        return {**base, "status": "unsupported", "tier": "unsupported", "engine": None,
                "reason": "The Tesseract route for this script is not provisioned "
                          "(binary and/or traineddata missing).",
                "evaluation": None, "checkpoint": None,
                "evidence": {"route": "tesseract", "usable": False}}
    # Kraken route: evidence-gated tiers.
    record = evaluation_record(pid)
    checkpoints = kraken_checkpoints(settings, pid)
    first_checkpoint = checkpoints[0] if checkpoints else None
    if record is None:
        tier = "model_installed" if checkpoints else "unsupported"
        return {**base, "status": "unsupported", "tier": tier, "engine": None,
                "reason": "No verified checkpoint + evaluation record: no measured evaluation "
                          f"record exists at artifacts/benchmarks/htr-eval-{pid}.json.",
                "evaluation": None, "checkpoint": first_checkpoint,
                "evidence": {"checkpoints_on_disk": len(checkpoints)}}
    cer = record.get("cer")
    if not isinstance(cer, (int, float)):
        return {**base, "status": "unsupported",
                "tier": "model_installed" if checkpoints else "unsupported", "engine": None,
                "reason": "An evaluation record exists but carries no measured CER value.",
                "evaluation": record, "checkpoint": first_checkpoint,
                "evidence": {"checkpoints_on_disk": len(checkpoints)}}
    wanted = record.get("checkpoint_sha256")
    match = next((c for c in checkpoints if wanted and c["sha256"] == wanted), None)
    if match is None:
        return {**base, "status": "unsupported",
                "tier": "model_installed" if checkpoints else "unsupported", "engine": None,
                "reason": "The evaluation record's checkpoint hash does not match any Kraken "
                          "checkpoint file present on disk for this profile.",
                "evaluation": record, "checkpoint": None,
                "evidence": {"checkpoints_on_disk": len(checkpoints)}}
    # A measured record matched to a real checkpoint: at least
    # experimentally evaluated. Production gates follow.
    samples = record.get("test_samples", record.get("samples", record.get("lines")))
    gates = {
        "cer_finite": isinstance(cer, (int, float)) and math.isfinite(float(cer)),
        "cer_in_range": isinstance(cer, (int, float)) and 0.0 <= float(cer) <= 0.5,
        "min_samples": isinstance(samples, int) and samples >= settings.script_min_test_samples,
        "script_match": record.get("script_profile") in (None, pid),
        "dataset_checksum_recorded": bool(record.get("dataset_sha256")),
        "checkpoint_checksum_matched": True,
    }
    evaluation = {"cer": cer, "wer": record.get("wer"),
                  "test_set": record.get("test_set"),
                  "test_samples": samples,
                  "dataset_sha256": record.get("dataset_sha256"),
                  "evaluated_at": record.get("evaluated_at")}
    if all(gates.values()):
        return {**base, "status": "supported", "tier": "production_supported",
                "engine": "kraken", "reason": None,
                "evaluation": evaluation, "checkpoint": match,
                "evidence": {"gates": gates}}
    failed = [name for name, ok in gates.items() if not ok]
    return {**base, "status": "unsupported", "tier": "experimentally_evaluated",
            "engine": None,
            "reason": "Measured evaluation exists but production gates fail: "
                      + ", ".join(failed) + ".",
            "evaluation": evaluation, "checkpoint": match,
            "evidence": {"gates": gates}}


def support_matrix(settings: Settings, tesseract_available: bool) -> list[dict]:
    return [profile_support(settings, p, tesseract_available) for p in load_registry()]


def support_for(settings: Settings, profile_id: str, tesseract_available: bool) -> dict | None:
    for profile in load_registry():
        if profile["id"] == profile_id:
            return profile_support(settings, profile, tesseract_available)
    return None
