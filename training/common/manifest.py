"""Model-manifest and model-card helpers shared by the training tools.

The models manifest (artifacts/manifests/models.json) is the contract
between training and the running backend: an entry is flipped to
"provisioned" only by a training orchestrator after its export step has
written a real artifact directory with a model card. Nothing in this
module invents metrics, versions, or checksums — values come from the
files a run actually produced and from the tools' own version output.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_MANIFEST = REPO_ROOT / "artifacts" / "manifests" / "models.json"
DATASETS_MANIFEST = REPO_ROOT / "artifacts" / "manifests" / "datasets.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def describe_file(path: Path, role: str) -> dict:
    path = Path(path)
    return {"path": path.name, "role": role, "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size}


def write_model_card(artifact_dir: Path, *, engine: str, language_profile: str,
                     model_version: str, primary_file: Path,
                     files: list[dict], dataset_card_sha256: str | None,
                     dataset_id: str | None, tool_versions: dict,
                     license_text: str, provenance: str,
                     extra: dict | None = None) -> dict:
    """Write model_card.json into an exported artifact directory."""
    card = {
        "engine": engine,
        "language_profile": language_profile,
        "model_version": model_version,
        "artifact_sha256": sha256_file(primary_file),
        "primary_artifact": primary_file.name,
        "files": files,
        "dataset_card_sha256": dataset_card_sha256,
        "dataset_id": dataset_id,
        "tool_versions": tool_versions,
        "license": license_text,
        "provenance": provenance,
        "metrics": None,  # filled only by the evaluation harness after a real run
    }
    if extra:
        card.update(extra)
    write_json(Path(artifact_dir) / "model_card.json", card)
    return card


def update_manifest_entry(entry_id: str, *, status: str, path: Path,
                          checksum: str | None, version: str | None,
                          notes: str | None = None,
                          manifest_path: Path = MODELS_MANIFEST) -> dict:
    """Flip one manifest entry after a real export. Path is stored
    repo-relative so the backend can resolve it on any machine."""
    manifest = load_json(manifest_path)
    for entry in manifest.get("models", []):
        if entry.get("id") == entry_id:
            entry["status"] = status
            try:
                entry["path"] = str(Path(path).relative_to(REPO_ROOT))
            except ValueError:
                entry["path"] = str(path)
            entry["checksum"] = checksum
            entry["version"] = version
            if notes:
                entry["notes"] = notes
            write_json(manifest_path, manifest)
            return entry
    raise KeyError(f"models manifest has no entry with id '{entry_id}'")


def manifest_entry_id(engine: str, language_profile: str) -> str:
    short = {"biblical_hebrew": "biblical-hebrew", "biblical_aramaic": "biblical-aramaic"}
    return f"{engine}-{short[language_profile]}-en"
