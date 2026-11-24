"""Tests for OCR plumbing, corpus retrieval, and morphology.

These tests are written to be run by the developer (see
docs/VERIFICATION.md for the exact commands and expected behaviour).
Corpus tests import the small committed fixture
training/datasets/fixtures/sample_passages.jsonl (real WLC/WEB passages
with provenance) into a temporary database. OCR-run tests skip with a
clear reason when no Tesseract binary is provisioned.
"""
import json, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.corpus.import_morphhb import import_into_db
from app.evaluation.metrics import cer, wer
from app.main import create_app
from app.services.language.normalize import normalize, normalize_nodiac
from app.services.ocr.tesseract_adapter import is_available
from app.services.preprocessing.service import preprocess_image
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
def corpus_settings(settings):
    passages = list(_sample().values())
    import_into_db(settings.db_path, passages)
    return settings

@pytest.fixture()
def corpus_client(corpus_settings):
    return TestClient(create_app(corpus_settings), raise_server_exceptions=False)

# ---------- normalization & metrics ----------

def test_normalize_keeps_diacritics_nodiac_removes():
    gen = _sample()["Genesis 1:1"]["source_text"]
    assert "ְ" in normalize(gen)  # shewa preserved in the exact key
    assert "ְ" not in normalize_nodiac(gen)
    assert normalize_nodiac(gen) != normalize(gen)

def test_metrics_known_values():
    assert cer("abc", "abc") == 0.0
    assert cer("abc", "abd") == pytest.approx(1 / 3)
    assert wer("a b c", "a b") == pytest.approx(1 / 3)
    assert cer("", "") == 0.0

# ---------- preprocessing ----------

def test_preprocessing_conservative_report():
    derived, report = preprocess_image(png_bytes(120, 40), "conservative")
    from PIL import Image
    import io
    with Image.open(io.BytesIO(derived)) as img:
        assert img.format == "PNG"
    assert report["profile"] == "conservative"
    steps = {s["step"]: s for s in report["steps"]}
    assert steps["median_noise_reduction"]["applied"] is False
    assert steps["deskew"]["applied"] is False

def test_preprocessing_enhanced_report():
    derived, report = preprocess_image(png_bytes(120, 40), "enhanced")
    assert report["profile"] == "enhanced"
    steps = {s["step"]: s for s in report["steps"]}
    assert "angle_degrees" in steps["deskew"]
    assert steps["adaptive_contrast"]["applied"] is True

def test_preprocessing_unknown_profile_400(client):
    up = client.post("/api/uploads", files={"file": ("p.png", png_bytes(), "image/png")}).json()
    r = client.post("/api/ocr", json={"upload_id": up["id"], "preprocessing_profile": "bogus"})
    # With no OCR engine the engine check fires first (503); with an engine
    # the unknown profile is a 400. Either way it must not succeed.
    assert r.status_code in (400, 503)

# ---------- retrieval / verified-reference translation ----------

def test_exact_hebrew_match_returns_web_english(corpus_client):
    gen = _sample()["Genesis 1:1"]
    r = corpus_client.post("/api/translate", json={"text": gen["source_text"], "source_language": "biblical_hebrew"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["translation_method"] == "verified_reference"
    assert body["english_translation"] == gen["english_text"]
    ref = body["source_references"][0]
    assert ref["reference"] == "Genesis 1:1" and ref["match_type"] == "exact"
    assert ref["source_edition"] and ref["translation_edition"] and ref["license"]

def test_normalized_match_without_diacritics(corpus_client):
    gen = _sample()["Genesis 1:1"]
    stripped = normalize_nodiac(gen["source_text"])
    r = corpus_client.post("/api/retrieval", json={"text": stripped, "language": "biblical_hebrew"})
    assert r.status_code == 200
    assert r.json()["match"]["match_type"] == "normalized"
    assert r.json()["match"]["reference"] == "Genesis 1:1"

def test_exact_aramaic_match(corpus_client):
    dan = _sample()["Daniel 2:4"]
    r = corpus_client.post("/api/translate", json={"text": dan["source_text"], "source_language": "biblical_aramaic"})
    assert r.status_code == 200, r.text
    assert r.json()["english_translation"] == dan["english_text"]
    assert r.json()["source_references"][0]["reference"] == "Daniel 2:4"

def test_variant_is_not_exact(corpus_client):
    gen = _sample()["Genesis 1:1"]
    words = gen["source_text"].split(" ")
    words[-2] = "שָׁמַיִם"  # change one word of the passage
    variant = " ".join(words)
    r = corpus_client.post("/api/retrieval", json={"text": variant, "language": "biblical_hebrew"})
    assert r.status_code == 200
    assert r.json()["match"] is None  # a variant must never come back as a verified match
    t = corpus_client.post("/api/translate", json={"text": variant, "source_language": "biblical_hebrew"})
    assert t.status_code == 503 and t.json()["error"]["code"] == "translation_model_unavailable"

def test_cross_language_lookup_returns_no_match(corpus_client):
    dan = _sample()["Daniel 2:4"]
    r = corpus_client.post("/api/retrieval", json={"text": dan["source_text"], "language": "biblical_hebrew"})
    assert r.status_code == 200 and r.json()["match"] is None
    gen = _sample()["Genesis 1:1"]
    r2 = corpus_client.post("/api/retrieval", json={"text": gen["source_text"], "language": "biblical_aramaic"})
    assert r2.status_code == 200 and r2.json()["match"] is None

def test_unseen_text_no_match(corpus_client):
    unseen = "מֶלֶךְ גָּדוֹל יָשַׁב עַל כִּסֵּא זָהָב בִּירוּשָׁלַיִם"
    r = corpus_client.post("/api/retrieval", json={"text": unseen, "language": "biblical_hebrew"})
    assert r.json()["match"] is None
    t = corpus_client.post("/api/translate", json={"text": unseen, "source_language": "biblical_hebrew"})
    assert t.status_code == 503

def test_corpus_capabilities(corpus_client):
    caps = corpus_client.get("/api/capabilities").json()
    assert caps["corpus"]["status"] == "available"
    assert caps["corpus"]["by_language"]["biblical_hebrew"] >= 3
    assert caps["corpus"]["by_language"]["biblical_aramaic"] >= 3
    assert caps["morphology"]["status"] == "available"

# ---------- morphology ----------

def test_morphology_known_hebrew_word(corpus_client):
    # Elohim (Genesis 1:1) — lemma/Strong's 430 in morphhb.
    r = corpus_client.post("/api/morphology", json={"text": "אֱלֹהִים", "language": "biblical_hebrew"})
    assert r.status_code == 200, r.text
    word = r.json()["words"][0]
    assert word["status"] == "found"
    assert any(e["strongs"] == "430" for e in word["entries"])
    assert all(e["word_language"] == "hebrew" for e in word["entries"])

def test_morphology_unknown_word_not_found(corpus_client):
    r = corpus_client.post("/api/morphology", json={"text": "xylophone", "language": "biblical_hebrew"})
    assert r.status_code == 200
    assert r.json()["words"][0]["status"] == "not_found"
    assert r.json()["words"][0]["entries"] == []

def test_morphology_aramaic_uses_aramaic_data_only(corpus_client):
    # 'malka' (the king) — Aramaic word of Daniel 2:4, morphhb A-coded.
    r = corpus_client.post("/api/morphology", json={"text": "מַלְכָּא", "language": "biblical_aramaic"})
    assert r.status_code == 200, r.text
    word = r.json()["words"][0]
    assert word["status"] == "found"
    assert all(e["word_language"] == "aramaic" for e in word["entries"])
    # The same surface must not be analysed through the Hebrew adapter.
    h = corpus_client.post("/api/morphology", json={"text": "מַלְכָּא", "language": "biblical_hebrew"})
    assert h.json()["words"][0]["status"] == "not_found"

def test_morphology_without_corpus_503(client):
    r = client.post("/api/morphology", json={"text": "אֱלֹהִים", "language": "biblical_hebrew"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "corpus_unavailable"

# ---------- OCR integration (runs only with a provisioned binary) ----------

# Lenient a-priori bound for clean rendered fixtures, chosen before any
# measurement exists; tighten it from a real developer-run measurement
# recorded in docs/VERIFICATION.md.
FIXTURE_CER_BOUND = 0.65

@pytest.fixture()
def ocr_client(settings):
    if not is_available(settings.tesseract_cmd):
        pytest.skip("Tesseract binary not provisioned (see docs/OCR.md / scripts/provision-ocr.ps1)")
    return TestClient(create_app(settings), raise_server_exceptions=False)

def _fixture_images():
    fixtures_dir = REPO / "training" / "ocr" / "fixtures"
    truth_path = fixtures_dir / "ground_truth.json"
    if not truth_path.exists():
        pytest.skip("OCR fixtures not generated: run training/ocr/generate_fixtures.py")
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    for fx in truth["fixtures"]:
        img = fixtures_dir / fx["image"]
        if not img.exists():
            pytest.skip(f"Fixture image missing: {img} — run training/ocr/generate_fixtures.py")
        yield fx, img

def test_ocr_hebrew_fixture(ocr_client):
    for fx, img in _fixture_images():
        if fx["language"] != "biblical_hebrew":
            continue
        up = ocr_client.post("/api/uploads", files={"file": (img.name, img.read_bytes(), "image/png")}).json()
        r = ocr_client.post("/api/ocr", json={"upload_id": up["id"], "language_profile": "biblical_hebrew"})
        assert r.status_code == 200, r.text
        body = r.json()
        text = body["original_ocr_text"]
        assert text.strip(), "OCR returned empty text for a labelled fixture"
        assert any("א" <= ch <= "ת" for ch in text), "OCR output has no Hebrew-script characters"
        assert body["ocr_profile"] == "biblical_hebrew" and body["ocr_lang"] == "heb"
        assert body["mean_confidence"] is not None
        assert cer(fx["ground_truth"], text) < FIXTURE_CER_BOUND

def test_ocr_aramaic_fixture_uses_hebrew_traineddata(ocr_client):
    for fx, img in _fixture_images():
        if fx["language"] != "biblical_aramaic":
            continue
        up = ocr_client.post("/api/uploads", files={"file": (img.name, img.read_bytes(), "image/png")}).json()
        r = ocr_client.post("/api/ocr", json={"upload_id": up["id"], "language_profile": "biblical_aramaic"})
        assert r.status_code == 200, r.text
        body = r.json()
        # Hebrew-script Aramaic is recognised with heb traineddata, never Syriac.
        assert body["ocr_lang"] == "heb" and body["ocr_profile"] == "biblical_aramaic"
        assert "Syriac" in body["ocr_profile_note"]
        assert body["original_ocr_text"].strip()

def test_ocr_blank_image_empty_transcription(ocr_client):
    up = ocr_client.post("/api/uploads", files={"file": ("blank.png", png_bytes(200, 80), "image/png")}).json()
    r = ocr_client.post("/api/ocr", json={"upload_id": up["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "empty_transcription"
