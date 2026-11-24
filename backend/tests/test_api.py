import shutil
from conftest import png_bytes

HEBREW = "\u05d1\u05b0\u05bc\u05e8\u05b5\u05d0\u05e9\u05b4\u05c1\u05d9\u05ea"  # vocalized Hebrew word, used only as input text

def test_health(client):
    r = client.get("/api/health"); assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["db_ok"] is True

def test_capabilities_honesty(client):
    body = client.get("/api/capabilities").json()
    if shutil.which("tesseract") is None:
        assert body["ocr"]["status"] == "unavailable"
        assert body["ocr"]["tesseract"]["available"] is False
    assert body["translation"]["status"] == "unavailable"
    assert body["db_ok"] is True

def test_languages_distinct(client):
    langs = {l["id"]: l for l in client.get("/api/languages").json()["languages"]}
    assert "biblical_hebrew" in langs and "biblical_aramaic" in langs
    assert langs["biblical_aramaic"]["id"] != langs["biblical_hebrew"]["id"]
    assert langs["classical_syriac"]["status"] == "unsupported"

def test_models_not_provisioned(client):
    models = client.get("/api/models").json()["models"]
    assert models
    translation = [m for m in models if m.get("kind") == "translation"]
    assert translation and all(m["status"] == "not_provisioned" and m["path"] is None for m in translation)
    # The OCR entry honestly records that traineddata may be downloaded
    # while the binary is still missing; it must never claim a model path.
    ocr = [m for m in models if m.get("kind") == "ocr" and m.get("engine") == "tesseract"]
    assert ocr and all(m["path"] is None for m in ocr)

def test_valid_png_upload_and_preview(client):
    r = client.post("/api/uploads", files={"file": ("page.png", png_bytes(), "image/png")})
    assert r.status_code == 200, r.text
    meta = r.json(); assert meta["format"] == "PNG" and meta["width"] == 16 and meta["height"] == 16 and len(meta["sha256"]) == 64
    p = client.get(f"/api/uploads/{meta['id']}")
    assert p.status_code == 200 and p.content == png_bytes()

def test_fake_image_rejected(client):
    r = client.post("/api/uploads", files={"file": ("fake.png", b"this is plain text, not an image", "image/png")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_image"

def test_oversized_pixels_rejected(tmp_path, settings):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.main import create_app
    small = replace(settings, upload_max_pixels=100)
    c = TestClient(create_app(small), raise_server_exceptions=False)
    r = c.post("/api/uploads", files={"file": ("big.png", png_bytes(50, 50), "image/png")})
    assert r.status_code == 400 and r.json()["error"]["code"] in ("image_too_many_pixels",)

def test_translate_unavailable(client):
    r = client.post("/api/translate", json={"text": HEBREW, "source_language": "biblical_hebrew"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "translation_model_unavailable"

def test_translate_empty_400(client):
    r = client.post("/api/translate", json={"text": "   "})
    assert r.status_code == 400

def test_ocr_unavailable(client):
    if shutil.which("tesseract"):
        return
    up = client.post("/api/uploads", files={"file": ("p.png", png_bytes(), "image/png")}).json()
    r = client.post("/api/ocr", json={"upload_id": up["id"]})
    assert r.status_code == 503 and "ocr" in r.json()["error"]["code"]

def test_process_job_fails_honestly_when_ocr_missing(client):
    if shutil.which("tesseract"):
        return
    up = client.post("/api/uploads", files={"file": ("p.png", png_bytes(), "image/png")}).json()
    r = client.post("/api/process", json={"upload_id": up["id"]})
    assert r.status_code == 200
    job = client.get(f"/api/jobs/{r.json()['job_id']}").json()
    assert job["status"] == "failed" and job["error"]

def test_unknown_job_404(client):
    assert client.get("/api/jobs/does-not-exist").status_code == 404
    assert client.get("/api/jobs/does-not-exist").json()["error"]["code"] == "job_not_found"

def test_unknown_upload_404(client):
    assert client.get("/api/uploads/" + "a"*64).status_code == 404
    assert client.get("/api/uploads/..%2fsecret").status_code in (404, 400)

def test_unicode_text_handling(client):
    # Hebrew Unicode input must round-trip through validation/errors without mangling.
    r = client.post("/api/translate", json={"text": HEBREW, "source_language": "biblical_aramaic"})
    assert r.status_code == 503
    from app.services.language.service import suggest_language
    sug = suggest_language(HEBREW, None)
    assert sug["suggestion"] == "uncertain"  # never Hebrew-from-script-alone
    assert suggest_language(HEBREW, "biblical_aramaic")["suggestion"] == "biblical_aramaic"

def test_history_and_delete(client):
    up = client.post("/api/uploads", files={"file": ("p.png", png_bytes(), "image/png")}).json()
    client.post("/api/process", json={"upload_id": up["id"]})
    hist = client.get("/api/history").json()["history"]
    if hist:
        rid = hist[0]["id"]
        assert client.delete(f"/api/history/{rid}").status_code == 200
    assert client.delete("/api/history/999999").status_code == 404
