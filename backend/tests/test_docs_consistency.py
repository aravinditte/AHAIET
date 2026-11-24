"""Docs-to-manifest consistency (NEW-26).

The docs must describe the repository as the manifests record it:
books covered, per-profile split counts, model statuses, and the
security controls named in docs/SECURITY.md must exist in code.
If a manifest changes, these tests fail until the docs catch up —
stale counts in prose are treated as defects, not flavour.

Run with the backend suite: python -m pytest tests/test_docs_consistency.py -q
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[2]
DATASETS = json.loads((REPO / "artifacts" / "manifests" / "datasets.json").read_text(encoding="utf-8"))
MODELS = json.loads((REPO / "artifacts" / "manifests" / "models.json").read_text(encoding="utf-8"))
BUILD_STATE = (REPO / "docs" / "BUILD_STATE.md").read_text(encoding="utf-8")
LIMITATIONS = (REPO / "docs" / "LIMITATIONS.md").read_text(encoding="utf-8")
DATASETS_DOC = (REPO / "docs" / "DATASETS.md").read_text(encoding="utf-8")
SECURITY_DOC = (REPO / "docs" / "SECURITY.md").read_text(encoding="utf-8")


def test_books_covered_match_manifest():
    ids = {d["id"] for d in DATASETS["datasets"]}
    for book in ("genesis", "daniel", "ezra", "ruth"):
        assert f"morphhb-wlc-{book}" in ids
        assert book.capitalize() in BUILD_STATE
        assert book.capitalize() in DATASETS_DOC


def test_split_counts_in_docs_match_manifest():
    pairs = DATASETS["import_report"]["by_partition_pairs"]
    for profile in ("biblical_hebrew", "biblical_aramaic"):
        for split in ("train", "validation", "test"):
            count = pairs[profile][split]
            assert str(count) in BUILD_STATE, (profile, split, count)
            assert str(count) in DATASETS_DOC, (profile, split, count)
    # The Marian data gate stays documented as unmet for Aramaic.
    assert pairs["biblical_aramaic"]["train"] < 500
    assert "500" in LIMITATIONS and "Aramaic" in LIMITATIONS


def test_model_statuses_in_docs_match_manifest():
    translation = [m for m in MODELS["models"] if m.get("kind") == "translation"]
    assert translation, "manifest lost its translation entries"
    for entry in translation:
        assert entry["status"] == "not_provisioned", entry["id"]
    assert "not_provisioned" in BUILD_STATE
    kraken = [m for m in MODELS["models"]
              if m.get("kind") == "ocr" and m.get("engine") == "kraken"]
    for entry in kraken:
        assert entry["status"] == "not_provisioned", entry["id"]


def test_security_controls_named_in_docs_exist_in_code():
    code = ""
    for path in (REPO / "backend" / "app").rglob("*.py"):
        if "__pycache__" not in str(path):
            code += path.read_text(encoding="utf-8")
    for control in ("SecurityHeadersMiddleware", "BodySizeLimitMiddleware",
                    "RateLimitMiddleware"):
        assert control in SECURITY_DOC, control
        assert control in code, control
    assert "X-AHAIET-Access-Token" in SECURITY_DOC
    assert "X-AHAIET-Access-Token" in code
    assert "_require_access" in code
