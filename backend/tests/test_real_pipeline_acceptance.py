"""Opt-in REAL-pipeline acceptance test (AHAIET-007/030, NEW-24).

This is the only test that exercises the complete promised workflow
with real artifacts: image -> real Tesseract OCR -> quality gate on
the UNCORRECTED output -> user correction -> real translation
(verified corpus reference), with all outbound sockets blocked.

Strengthened per NEW-24:
- BOTH fixture cases run: Hebrew (Genesis 1:1) and Aramaic
  (Daniel 2:4), from the canonical fixture manifest.
- The uncorrected OCR output is SCORED against the fixture ground
  truth with CER/WER and must pass the documented acceptance gate
  (CER <= 0.35, WER <= 0.50 for these clean rendered fixtures)
  before the correction/translation steps are checked. The gate
  itself is unit-tested below: a deliberately wrong OCR string
  fails it.
- The reference corpus is provisioned into the test database as an
  explicit fixture step (the committed fixture passages are imported
  with the real importer) — never a silent skip over an empty DB.
- Release-gate mode: with AHAIET_RELEASE_GATE=1 in the environment,
  every prerequisite skip becomes a FAILURE, so a release run
  cannot pass by skipping.

Nothing here fabricates an engine, a model, or an expected result:
expected English comes from the committed corpus fixture file. The
run itself belongs to the developer (see docs/VERIFICATION.md);
docs/ACCEPTANCE_AUDIT.md keeps NEW-03 blocked until a real run on a
provisioned machine exists.
"""
from __future__ import annotations
import json
import os
import socket
from pathlib import Path

import pytest

pytestmark = pytest.mark.model_required

REPO = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO / "training" / "ocr" / "fixtures"
SAMPLE = REPO / "training" / "datasets" / "fixtures" / "sample_passages.jsonl"

# Documented acceptance thresholds for the rendered fixture images
# (clean synthetic renders, printed square script, Tesseract heb).
CER_THRESHOLD = 0.35
WER_THRESHOLD = 0.50

RELEASE_GATE = os.environ.get("AHAIET_RELEASE_GATE") == "1"


def _require(condition: bool, message: str) -> None:
    """A prerequisite check: a skip normally, a failure in
    release-gate mode (NEW-24)."""
    if condition:
        return
    if RELEASE_GATE:
        pytest.fail(f"release gate: {message}")
    pytest.skip(message)


@pytest.fixture()
def blocked_sockets(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("outbound network use during the offline acceptance run")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


@pytest.fixture()
def provisioned_corpus(settings):
    """Explicit corpus provisioning (NEW-24): import the committed
    fixture passages into the test database with the real importer
    and assert the import landed."""
    from app.corpus.import_morphhb import import_into_db
    _require(SAMPLE.exists(), f"prerequisite missing: {SAMPLE}")
    rows = [json.loads(l) for l in SAMPLE.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    report = import_into_db(settings.db_path, rows)
    _require(report.get("imported", 0) > 0,
             f"corpus fixture import landed no passages: {report}")
    return rows


def ocr_quality_gate(hypothesis: str, reference: str) -> dict:
    """CER/WER of the uncorrected OCR output vs ground truth, with
    the acceptance thresholds applied. Returns the measurements and
    the verdict; the caller asserts on the verdict."""
    from app.evaluation.metrics import levenshtein
    ref_chars = list(reference)
    hyp_chars = list(hypothesis)
    cer = (levenshtein(ref_chars, hyp_chars) / len(ref_chars)) if ref_chars else 1.0
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    wer = (levenshtein(ref_words, hyp_words) / len(ref_words)) if ref_words else 1.0
    return {"cer": cer, "wer": wer,
            "passed": cer <= CER_THRESHOLD and wer <= WER_THRESHOLD}


def test_ocr_quality_gate_rejects_wrong_output():
    # Unit-level check of the scoring gate itself (NEW-24): perfect
    # output passes with zero error; a deliberately wrong string
    # fails, so the acceptance cases below cannot pass vacuously.
    ref = "בְּרֵאשִׁית בָּרָא אֱלֹהִים"
    good = ocr_quality_gate(ref, ref)
    assert good == {"cer": 0.0, "wer": 0.0, "passed": True}
    bad = ocr_quality_gate("zzzz qqqq xxxx", ref)
    assert bad["passed"] is False
    assert bad["cer"] > CER_THRESHOLD


def _fixture(fixture_id: str) -> dict:
    manifest = json.loads((FIXTURES_DIR / "fixtures.json").read_text(encoding="utf-8"))
    entry = next((f for f in manifest["fixtures"] if f["id"] == fixture_id), None)
    _require(entry is not None, f"prerequisite missing: fixture {fixture_id} not in fixtures.json")
    image = FIXTURES_DIR / entry["filename"]
    _require(image.exists(),
             f"prerequisite missing: {image} — run training/ocr/generate_fixtures.py")
    return {**entry, "image": image}


def _sample(reference: str) -> dict:
    for line in SAMPLE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row["reference"] == reference:
                return row
    pytest.fail(f"fixture corpus is missing {reference}")


def _run_case(client, settings, fixture_id: str):
    from app.services.ocr import tesseract_adapter

    probe = tesseract_adapter.readiness(settings.tesseract_cmd, settings.tesseract_lang,
                                        settings.tessdata_prefix)
    _require(probe["usable"],
             "prerequisite missing: Tesseract binary + Hebrew traineddata not usable "
             f"(binary_available={probe['binary_available']}, "
             f"probe_failed={probe.get('probe_failed')}, reason={probe.get('reason')})")
    fx = _fixture(fixture_id)
    gen = _sample(fx["reference"])
    image = fx["image"]
    up = client.post("/api/uploads",
                     files={"file": (image.name, image.read_bytes(), "image/png")})
    assert up.status_code == 200, up.text
    ocr = client.post("/api/ocr", json={"upload_id": up.json()["id"],
                                        "language_profile": fx["language_profile"]})
    assert ocr.status_code == 200, ocr.text
    raw = ocr.json()["original_ocr_text"]
    assert raw.strip(), "real OCR produced no text for the fixture image"

    # NEW-24: the UNCORRECTED OCR output is scored against the
    # fixture ground truth and must pass the acceptance gate.
    gate = ocr_quality_gate(raw, gen["source_text"])
    assert gate["passed"], (
        f"uncorrected OCR quality gate failed for {fx['reference']}: "
        f"CER={gate['cer']:.3f} (<= {CER_THRESHOLD}), "
        f"WER={gate['wer']:.3f} (<= {WER_THRESHOLD})")

    # Correction step: the user-corrected text is the known-good
    # corpus text (the correction UI's contract), sent with the raw
    # OCR text preserved separately (AHAIET-026 lineage).
    tr = client.post("/api/translate", json={
        "original_ocr_text": raw,
        "corrected_source_text": gen["source_text"],
        "source_language": fx["language_profile"],
        "ocr_request_id": ocr.json()["request_id"],
    })
    assert tr.status_code == 200, tr.text
    body = tr.json()
    assert body["original_ocr_text"] == raw
    assert body["corrected_source_text"] == gen["source_text"]
    assert body["english_translation"] == gen["english_text"]
    assert body["passage_identity_verified"] is True


def test_offline_full_real_pipeline_hebrew(client, settings, blocked_sockets,
                                           provisioned_corpus):
    """Named regression test: test_offline_full_real_pipeline (Hebrew case)."""
    _run_case(client, settings, "genesis-1-1-hebrew")


def test_offline_full_real_pipeline_aramaic(client, settings, blocked_sockets,
                                            provisioned_corpus):
    """The Aramaic case (NEW-24): Daniel 2:4 through the same gate."""
    _run_case(client, settings, "daniel-2-4-aramaic")
