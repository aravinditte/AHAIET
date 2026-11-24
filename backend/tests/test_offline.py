"""Offline operation tests.

Two proofs, both as code for the developer to run:

1. Static: the offline self-check (app.offline_check) finds no
   outbound-call constructs in runtime code — only in the allowlisted
   setup-only corpus importer.

2. Runtime: with every socket connection blocked (monkeypatched to
   raise), the real request paths still work — health, capabilities,
   and a verified-reference translation served from the locally
   imported fixture corpus. The FastAPI TestClient talks to the app
   in-process, so blocking sockets blocks exactly the thing we want to
   prove the app never needs: outbound network access.

Nothing here downloads anything, and the fixture corpus is the
committed six-passage sample (real WLC/WEB passages with provenance).
"""
import json, socket, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.corpus.import_morphhb import import_into_db
from app.main import create_app
from app.offline_check import scan

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "training" / "datasets" / "fixtures" / "sample_passages.jsonl"


@pytest.fixture()
def no_network(monkeypatch):
    """Block all outbound socket connections for the duration of a test."""
    def _blocked(self, *args, **kwargs):
        raise OSError("network access is blocked by the offline test")
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", lambda self, *a, **k: 111)
    monkeypatch.setattr(socket, "create_connection",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("network blocked")))
    yield


@pytest.fixture()
def offline_client(settings, no_network):
    passages = []
    for line in SAMPLE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            passages.append(json.loads(line))
    import_into_db(settings.db_path, passages)
    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_static_scan_has_no_runtime_findings():
    report = scan()
    assert report["runtime_findings"] == [], report["runtime_findings"]
    # The one allowlisted file is the setup-only importer.
    assert any(f["file"] == "corpus/import_morphhb.py" for f in report["setup_only"])


def test_health_and_capabilities_offline(offline_client):
    r = offline_client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    caps = offline_client.get("/api/capabilities").json()
    assert caps["db_ok"] is True
    assert caps["corpus"]["status"] == "available"


def test_verified_reference_translation_offline(offline_client):
    gen = None
    for line in SAMPLE.read_text(encoding="utf-8").splitlines():
        p = json.loads(line)
        if p["reference"] == "Genesis 1:1":
            gen = p
    assert gen is not None
    r = offline_client.post("/api/translate", json={
        "text": gen["source_text"], "source_language": "biblical_hebrew"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["translation_method"] == "verified_reference"
    assert body["english_translation"] == gen["english_text"]
    assert body["source_references"][0]["reference"] == "Genesis 1:1"


def test_morphology_offline(offline_client):
    r = offline_client.post("/api/morphology", json={
        "text": "אֱלֹהִים", "language": "biblical_hebrew"})
    assert r.status_code == 200
    assert r.json()["words"][0]["status"] == "found"
