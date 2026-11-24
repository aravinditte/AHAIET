"""Integration tests: real request flows across upload, OCR, correction,
retrieval, and translation, against temporary storage and databases.

Written to be run by the developer (docs/VERIFICATION.md).

Honesty rules for this file:
- Tests that need a real engine binary or a real trained artifact are
  marked `model_required` and skip with the exact missing prerequisite
  as the reason. CI's always-on job deselects them; the model-tests
  workflow runs them where prerequisites are provisioned.
- The one inference flow that always runs uses the clearly-labelled
  echo test-double binaries from tests/test_translation_models.py.
  Those doubles exercise the subprocess contract only; they are not
  models and prove nothing about translation quality.
- Everything else (upload/preview, correction precedence, verified
  reference lookup and translation) runs against the real code and the
  committed six-passage fixture corpus.
"""
import json, shutil, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.corpus.import_morphhb import import_into_db
from app.main import create_app
from app.services.ocr.tesseract_adapter import is_available as tesseract_available
from app.services.translation import selection
from conftest import png_bytes

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "training" / "datasets" / "fixtures" / "sample_passages.jsonl"


def _sample() -> dict[str, dict]:
    out = {}
    for line in SAMPLE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            p = json.loads(line)
            out[p["reference"]] = p
    return out


@pytest.fixture()
def corpus_client(settings):
    import_into_db(settings.db_path, list(_sample().values()))
    return TestClient(create_app(settings), raise_server_exceptions=False)


# ---------- Upload -> storage -> preview ----------

def test_upload_store_preview_roundtrip_is_byte_identical(client):
    data = png_bytes(24, 18)
    r = client.post("/api/uploads", files={"file": ("page.png", data, "image/png")})
    assert r.status_code == 200, r.text
    meta = r.json()
    preview = client.get(f"/api/uploads/{meta['id']}")
    assert preview.status_code == 200
    assert preview.content == data  # the stored original, byte for byte
    assert preview.headers["content-type"].startswith("image/png")


def test_upload_preview_unknown_id_is_404(client):
    r = client.get("/api/uploads/" + "0" * 64)
    assert r.status_code == 404 and r.json()["error"]["code"] == "upload_not_found"
    traversal = client.get("/api/uploads/..%2f..%2fetc")
    assert traversal.status_code in (400, 404)  # never a file outside storage


# ---------- OCR endpoint: real binary or an honest skip ----------

@pytest.mark.model_required
def test_ocr_with_real_tesseract_binary(client):
    if not tesseract_available("tesseract"):
        pytest.skip("prerequisite missing: Tesseract binary is not installed "
                    "(scripts/provision-ocr.ps1 / docs/OCR.md)")
    up = client.post("/api/uploads", files={"file": ("p.png", png_bytes(), "image/png")}).json()
    r = client.post("/api/ocr", json={"upload_id": up["id"]})
    # A blank fixture image yields the honest empty-transcription error,
    # which still proves the real engine ran end to end.
    assert r.status_code in (200, 422)
    if r.status_code == 422:
        assert r.json()["error"]["code"] == "empty_transcription"


def test_ocr_without_binary_is_honest_unavailable(client):
    if tesseract_available("tesseract"):
        pytest.skip("Tesseract is provisioned here; the unavailable path "
                    "is covered where it is absent")
    up = client.post("/api/uploads", files={"file": ("p.png", png_bytes(), "image/png")}).json()
    r = client.post("/api/ocr", json={"upload_id": up["id"]})
    assert r.status_code == 503 and "ocr" in r.json()["error"]["code"]


# ---------- Correction flow: corrected text is what gets translated ----------

def test_correction_flow_translates_the_corrected_text(corpus_client):
    gen = _sample()["Genesis 1:1"]
    garbled = "OCR-garbled placeholder text that matches nothing"
    r = corpus_client.post("/api/translate", json={
        "text": garbled,
        "corrected_source_text": gen["source_text"],
        "source_language": "biblical_hebrew",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # The corrected text — not the garbled raw text — produced the match.
    assert body["english_translation"] == gen["english_text"]
    assert body["translation_method"] == "verified_reference"
    # Both representations stay visible and separate in the response.
    assert body["original_ocr_text"] == garbled
    assert body["corrected_source_text"] == gen["source_text"]


def test_uncorrected_garbled_text_does_not_match(corpus_client):
    r = corpus_client.post("/api/translate", json={
        "text": "OCR-garbled placeholder text that matches nothing",
        "source_language": "biblical_hebrew",
    })
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "translation_model_unavailable"


# ---------- Passage lookup and end-to-end verified translation ----------

def test_passage_lookup_endpoint_exact(corpus_client):
    gen = _sample()["Genesis 1:1"]
    r = corpus_client.post("/api/retrieval", json={
        "text": gen["source_text"], "language": "biblical_hebrew"})
    assert r.status_code == 200
    match = r.json()["match"]
    assert match["reference"] == "Genesis 1:1" and match["match_type"] == "exact"
    assert match["source_edition"] and match["translation_edition"] and match["license"]


def test_end_to_end_verified_reference_translation(corpus_client):
    dan = _sample()["Daniel 2:5"]
    r = corpus_client.post("/api/translate", json={
        "text": dan["source_text"], "source_language": "biblical_aramaic"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["english_translation"] == dan["english_text"]
    assert body["provenance"]["engine"] == "verified_reference"
    assert body["source_references"][0]["reference"] == "Daniel 2:5"
    assert body["verification"] is not None  # deterministic checks attached


def test_unsupported_language_profile_errors(corpus_client):
    r = corpus_client.post("/api/retrieval", json={
        "text": "anything", "language": "classical_syriac"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_language"
    m = corpus_client.post("/api/morphology", json={
        "text": "anything", "language": "paleo_hebrew"})
    assert m.status_code == 400 and m.json()["error"]["code"] == "unsupported_language"


def test_missing_model_artifact_error_is_specific(corpus_client):
    # Corpus imported (so retrieval ran and missed) but no trained model
    # is provisioned: the error must say a model is unavailable, not
    # return a gloss or an empty success.
    r = corpus_client.post("/api/translate", json={
        "text": "טקסט שלא מופיע במאגר בכלל", "source_language": "biblical_hebrew"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "translation_model_unavailable"


# ---------- Trained-model inference through the labelled test doubles ----------

def test_trained_model_inference_with_echo_double(tmp_path):
    """Subprocess-contract integration via the echo test doubles from
    test_translation_models.py. The doubles are fixtures, not models."""
    from test_translation_models import _fake_binary, _settings, make_moses_artifact
    _, entry = make_moses_artifact(tmp_path)
    fake = _fake_binary(tmp_path, "fake-moses", "MOSES-OUT ")
    s = _settings(tmp_path, [entry], moses_cmd=str(fake))
    client = TestClient(create_app(s), raise_server_exceptions=False)
    r = client.post("/api/translate", json={
        "text": "בראשית אלהים", "source_language": "biblical_hebrew"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["engine"] == "moses"
    assert body["english_translation"].startswith("MOSES-OUT")
    assert body["unevaluated_model"] is True  # no recorded metrics on the double


# ---------- Real trained-model inference: only where an artifact exists ----------

@pytest.mark.model_required
def test_real_trained_model_inference(settings):
    chosen = selection.select_engine(settings, "biblical_hebrew")
    if chosen is None:
        pytest.skip("prerequisite missing: no complete trained translation "
                    "artifact is provisioned for biblical_hebrew "
                    "(train one first — docs/TRAINING.md)")
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    r = client.post("/api/translate", json={
        "text": "בראשית ברא אלהים", "source_language": "biblical_hebrew"})
    assert r.status_code == 200, r.text
    assert r.json()["engine"] == chosen.engine
