"""Opt-in REAL-pipeline acceptance test (AHAIET-007/030).

This is the only test that exercises the complete promised workflow
with real artifacts: image -> real Tesseract OCR -> user correction ->
real translation (verified corpus reference and/or a real trained
decoder), with all outbound sockets blocked for the whole run.

It is marked model_required and SKIPS with the exact missing
prerequisite named when any of these is absent:
- the Tesseract binary + Hebrew traineddata (usable readiness),
- the generated fixture image (training/ocr/fixtures/fixtures.json),
- the imported reference corpus in the test database.

Nothing here fabricates an engine, a model, or an expected result:
expected English comes from the committed corpus fixture file. The
run itself belongs to the developer (see docs/VERIFICATION.md); this
file is the coded gate, and docs/ACCEPTANCE_AUDIT.md records the
criterion as blocked until a real run exists.
"""
from __future__ import annotations
import json
import socket
from pathlib import Path

import pytest

pytestmark = pytest.mark.model_required

REPO = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO / "training" / "ocr" / "fixtures"
SAMPLE = REPO / "training" / "datasets" / "fixtures" / "sample_passages.jsonl"


@pytest.fixture()
def blocked_sockets(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("outbound network use during the offline acceptance run")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


def _fixture_image(fixture_id: str) -> Path:
    manifest = json.loads((FIXTURES_DIR / "fixtures.json").read_text(encoding="utf-8"))
    entry = next((f for f in manifest["fixtures"] if f["id"] == fixture_id), None)
    if entry is None:
        pytest.skip(f"prerequisite missing: fixture {fixture_id} not in fixtures.json")
    image = FIXTURES_DIR / entry["filename"]
    if not image.exists():
        pytest.skip(f"prerequisite missing: {image} — run training/ocr/generate_fixtures.py")
    return image


def _sample(reference: str) -> dict:
    for line in SAMPLE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row["reference"] == reference:
                return row
    pytest.skip(f"prerequisite missing: {reference} not in sample_passages.jsonl")


def test_offline_full_real_pipeline(client, settings, blocked_sockets):
    """Named regression test: test_offline_full_real_pipeline."""
    from app.services.ocr import tesseract_adapter

    probe = tesseract_adapter.readiness(settings.tesseract_cmd, settings.tesseract_lang,
                                        settings.tessdata_prefix)
    if not probe["usable"]:
        pytest.skip("prerequisite missing: Tesseract binary + Hebrew traineddata not usable "
                    f"(binary_available={probe['binary_available']}, "
                    f"language_data_available={probe['language_data_available']})")
    from app.services import retrieval
    if retrieval.corpus_counts(settings.db_path)["total"] == 0:
        pytest.skip("prerequisite missing: reference corpus not imported into the test "
                    "database (run the corpus importer)")

    gen = _sample("Genesis 1:1")
    image = _fixture_image("genesis-1-1-hebrew")
    up = client.post("/api/uploads",
                     files={"file": (image.name, image.read_bytes(), "image/png")})
    assert up.status_code == 200, up.text
    ocr = client.post("/api/ocr", json={"upload_id": up.json()["id"],
                                        "language_profile": "biblical_hebrew"})
    assert ocr.status_code == 200, ocr.text
    raw = ocr.json()["original_ocr_text"]
    assert raw.strip(), "real OCR produced no text for the fixture image"

    # Correction step: the user-corrected text is the known-good corpus
    # text (the correction UI's contract), sent with the raw OCR text
    # preserved separately (AHAIET-026 lineage).
    tr = client.post("/api/translate", json={
        "original_ocr_text": raw,
        "corrected_source_text": gen["source_text"],
        "source_language": "biblical_hebrew",
        "ocr_request_id": ocr.json()["request_id"],
    })
    assert tr.status_code == 200, tr.text
    body = tr.json()
    assert body["original_ocr_text"] == raw
    assert body["corrected_source_text"] == gen["source_text"]
    assert body["english_translation"] == gen["english_text"]
    assert body["passage_identity_verified"] is True
