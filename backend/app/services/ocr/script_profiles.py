"""Script support matrix, computed — never declared.

The registry (script_profiles.json, next to this module) names the
script profiles and the engine route that could serve each one. Whether
a profile is *supported* is decided here, at runtime, from evidence:

- hebrew_square: operational when the Tesseract route's own probe
  reports it usable (binary + language data verified by the binary).
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


def _dataset_hash(test_set_value) -> str | None:
    """Recompute the evaluation dataset hash (NEW-17): sha256 over
    the sorted relative paths + bytes of every file under the
    recorded test-set directory (a single file hashes directly).
    Identical to training/evaluation/evaluate_htr.py's
    dataset_sha256. Returns None when the path cannot be resolved."""
    if not test_set_value:
        return None
    path = Path(str(test_set_value))
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        if path.is_file():
            return _sha256_file(path)
        if path.is_dir():
            h = hashlib.sha256()
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    h.update(str(child.relative_to(path)).encode("utf-8"))
                    h.update(child.read_bytes())
            return h.hexdigest()
    except OSError:
        return None
    return None


def profile_support(settings: Settings, profile: dict, tesseract_available: bool,
                    tesseract_probe: dict | None = None) -> dict:
    """Compute one registry row's live support status and tier.

    Tiers (NEW-17 — renamed and tightened; the old labels
    model_installed / experimentally_evaluated / production_supported
    are superseded):
    - engine_installed: an engine/checkpoint exists; nothing measured.
    - operational: the engine route is live and usable right now
      (the Tesseract square-script route when its probe says usable).
      Operational is NOT an accuracy claim.
    - evaluated_on_dataset: a measured evaluation record exists and
      its checkpoint hash matches a checkpoint on disk, but at least
      one production gate below is unmet.
    - validated_for_production: ALL gates hold —
      * the record's script identity EQUALS this profile id (an
        absent script field does not pass);
      * dataset_sha256 is present and VERIFIED by recomputing the
        hash of the recorded dataset;
      * at least Settings.script_production_min_samples (default 50)
        independently labelled samples;
      * CER finite and <= Settings.script_production_max_cer
        (default 0.20), and a WER is recorded;
      * the checkpoint sha256 matches a checkpoint on disk.
      The Tesseract square-Hebrew route is never
      validated_for_production without an evaluation record meeting
      the same bar; it reports operational when usable.
    `status` stays for backwards compatibility: "supported" only for
    validated_for_production (Kraken) and operational (Tesseract);
    `tier` + `unmet_conditions` are the precise report."""
    pid = profile["id"]
    base = {"id": pid, "name": profile["name"], "script": profile["script"],
            "route": profile["route"], "note": profile.get("note")}
    if profile["route"] == "tesseract":
        usable = bool((tesseract_probe or {}).get("usable", tesseract_available))
        if usable:
            return {**base, "status": "supported", "tier": "operational",
                    "engine": "tesseract",
                    "reason": None, "evaluation": None, "checkpoint": None,
                    "unmet_conditions": ["no measured evaluation record meeting the "
                                         "production bar exists for this route"],
                    "evidence": {"route": "tesseract", "usable": True,
                                 "note": "operational means the engine runs; it is "
                                         "not a measured-accuracy claim"}}
        return {**base, "status": "unsupported",
                "tier": "engine_installed" if tesseract_available else "unsupported",
                "engine": None,
                "reason": "The Tesseract route for this script is not usable "
                          "(binary probe / language data check failed).",
                "evaluation": None, "checkpoint": None,
                "unmet_conditions": ["tesseract_not_usable"],
                "evidence": {"route": "tesseract", "usable": False,
                             "probe_failed": (tesseract_probe or {}).get("probe_failed", False)}}
    # Kraken route: evidence-gated tiers.
    record = evaluation_record(pid)
    checkpoints = kraken_checkpoints(settings, pid)
    first_checkpoint = checkpoints[0] if checkpoints else None
    installed_tier = "engine_installed" if checkpoints else "unsupported"
    if record is None:
        return {**base, "status": "unsupported", "tier": installed_tier, "engine": None,
                "reason": "No measured evaluation record exists at "
                          f"artifacts/benchmarks/htr-eval-{pid}.json.",
                "evaluation": None, "checkpoint": first_checkpoint,
                "unmet_conditions": ["no_evaluation_record"],
                "evidence": {"checkpoints_on_disk": len(checkpoints)}}
    cer = record.get("cer")
    if not isinstance(cer, (int, float)):
        return {**base, "status": "unsupported", "tier": installed_tier, "engine": None,
                "reason": "An evaluation record exists but carries no measured CER value.",
                "evaluation": record, "checkpoint": first_checkpoint,
                "unmet_conditions": ["no_measured_cer"],
                "evidence": {"checkpoints_on_disk": len(checkpoints)}}
    wanted = record.get("checkpoint_sha256")
    match = next((c for c in checkpoints if wanted and c["sha256"] == wanted), None)
    if match is None:
        return {**base, "status": "unsupported", "tier": installed_tier, "engine": None,
                "reason": "The evaluation record's checkpoint hash does not match any Kraken "
                          "checkpoint file present on disk for this profile.",
                "evaluation": record, "checkpoint": None,
                "unmet_conditions": ["checkpoint_hash_mismatch"],
                "evidence": {"checkpoints_on_disk": len(checkpoints)}}
    # A measured record matched to a real checkpoint: at least
    # evaluated_on_dataset. Production gates follow (NEW-17).
    samples = record.get("test_samples", record.get("samples",
                         record.get("lines_evaluated", record.get("lines"))))
    wer = record.get("wer")
    dataset_sha = record.get("dataset_sha256")
    recomputed = _dataset_hash(record.get("test_set") or record.get("dataset_path"))
    gates = {
        "script_identity_matches": record.get("script_profile") == pid,
        "dataset_hash_verified": bool(dataset_sha) and recomputed is not None
                                 and recomputed == dataset_sha,
        "min_samples": isinstance(samples, int)
                       and samples >= settings.script_production_min_samples,
        "cer_within_limit": math.isfinite(float(cer))
                            and 0.0 <= float(cer) <= settings.script_production_max_cer,
        "wer_recorded": isinstance(wer, (int, float)),
        "checkpoint_checksum_matched": True,
    }
    evaluation = {"cer": cer, "wer": wer,
                  "test_set": record.get("test_set"),
                  "test_samples": samples,
                  "dataset_sha256": dataset_sha,
                  "dataset_sha256_verified": gates["dataset_hash_verified"],
                  "evaluated_at": record.get("evaluated_at")}
    if all(gates.values()):
        return {**base, "status": "supported", "tier": "validated_for_production",
                "engine": "kraken", "reason": None,
                "evaluation": evaluation, "checkpoint": match,
                "unmet_conditions": [],
                "evidence": {"gates": gates}}
    failed = [name for name, ok in gates.items() if not ok]
    return {**base, "status": "unsupported", "tier": "evaluated_on_dataset",
            "engine": None,
            "reason": "Measured evaluation exists but production gates fail: "
                      + ", ".join(failed) + ".",
            "evaluation": evaluation, "checkpoint": match,
            "unmet_conditions": failed,
            "evidence": {"gates": gates}}


def support_matrix(settings: Settings, tesseract_available: bool,
                   tesseract_probe: dict | None = None) -> list[dict]:
    return [profile_support(settings, p, tesseract_available, tesseract_probe)
            for p in load_registry()]


def support_for(settings: Settings, profile_id: str, tesseract_available: bool,
                tesseract_probe: dict | None = None) -> dict | None:
    for profile in load_registry():
        if profile["id"] == profile_id:
            return profile_support(settings, profile, tesseract_available, tesseract_probe)
    return None
