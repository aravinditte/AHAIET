"""Security tests: response headers, CORS restriction, rate limiting,
request body ceiling, retention maintenance, history opt-out.

Written to be run by the developer (docs/VERIFICATION.md). Everything
here runs against temporary directories/databases from the conftest
fixtures; nothing touches the developer's real data.
"""
import os, sys, time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import create_app
from app.maintenance import run_retention
from app.storage import db as store
from conftest import png_bytes


def _client(settings) -> TestClient:
    return TestClient(create_app(settings), raise_server_exceptions=False)


# ---------- Security response headers ----------

def test_security_headers_on_success_and_error(client):
    ok = client.get("/api/health")
    assert ok.headers["x-content-type-options"] == "nosniff"
    assert ok.headers["x-frame-options"] == "DENY"
    assert ok.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in ok.headers["content-security-policy"]
    err = client.get("/api/jobs/does-not-exist")
    assert err.status_code == 404
    assert err.headers["x-content-type-options"] == "nosniff"
    assert err.headers["x-frame-options"] == "DENY"


# ---------- CORS: configured local origins only ----------

def test_cors_allows_configured_local_origin(client):
    r = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_rejects_unconfigured_origin(client):
    r = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    pre = client.options("/api/translate", headers={
        "Origin": "http://evil.example",
        "Access-Control-Request-Method": "POST",
    })
    assert pre.headers.get("access-control-allow-origin") != "http://evil.example"


# ---------- Rate limiting ----------

def test_rate_limit_returns_structured_429(settings):
    limited = replace(settings, rate_limit_translate_per_min=3)
    c = _client(limited)
    body = {"text": "בראשית", "source_language": "biblical_hebrew"}
    statuses = [c.post("/api/translate", json=body).status_code for _ in range(3)]
    assert all(s != 429 for s in statuses)  # within budget: real responses (503 here)
    r = c.post("/api/translate", json=body)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1
    # Other endpoints keep their own budget.
    assert c.get("/api/health").status_code == 200


def test_rate_limit_is_per_endpoint(settings):
    limited = replace(settings, rate_limit_uploads_per_min=1)
    c = _client(limited)
    files = {"file": ("p.png", png_bytes(), "image/png")}
    assert c.post("/api/uploads", files=files).status_code == 200
    r = c.post("/api/uploads", files=files)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


# ---------- Request body ceiling ----------

def test_body_ceiling_returns_structured_413(settings):
    limited = replace(settings, request_max_bytes=64)
    c = _client(limited)
    r = c.post("/api/translate", json={"text": "x" * 500, "source_language": "biblical_hebrew"})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "request_too_large"


def test_body_ceiling_default_derives_from_upload_limit(settings):
    assert settings.effective_request_max_bytes == settings.upload_max_bytes + 1024 * 1024


# ---------- Retention maintenance ----------

def _seed_old_data(settings, days_old: int = 90):
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    upload = settings.storage_dir / ("a" * 64 + ".png")
    upload.write_bytes(png_bytes())
    old_ts = time.time() - days_old * 86400
    os.utime(upload, (old_ts, old_ts))
    fresh = settings.storage_dir / ("b" * 64 + ".png")
    fresh.write_bytes(png_bytes())
    store.migrate(settings.db_path)
    old_dt = (datetime.now(timezone.utc) - timedelta(days=days_old)).strftime("%Y-%m-%d %H:%M:%S")
    conn = store.connect(settings.db_path)
    try:
        conn.execute("INSERT INTO history(upload_id,language_profile,status,detail,created_at) "
                     "VALUES ('x','biblical_hebrew','failed',NULL,?)", (old_dt,))
        conn.execute("INSERT INTO history(upload_id,language_profile,status,detail) "
                     "VALUES ('y','biblical_hebrew','completed',NULL)")
        conn.commit()
    finally:
        conn.close()
    return upload, fresh


def test_retention_dry_run_reports_without_deleting(settings):
    upload, fresh = _seed_old_data(settings)
    report = run_retention(settings, dry_run=True)
    assert report["dry_run"] is True
    assert report["uploads_deleted"] == 1  # only the aged file
    assert report["history_deleted"] == 1  # only the aged row
    assert upload.exists() and fresh.exists()  # dry run deletes nothing
    conn = store.connect(settings.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) c FROM history").fetchone()["c"] == 2
    finally:
        conn.close()


def test_retention_sweep_deletes_only_aged_items(settings):
    upload, fresh = _seed_old_data(settings)
    report = run_retention(settings)
    assert report["uploads_deleted"] == 1 and report["history_deleted"] == 1
    assert not upload.exists() and fresh.exists()
    conn = store.connect(settings.db_path)
    try:
        rows = conn.execute("SELECT upload_id FROM history").fetchall()
        assert [r["upload_id"] for r in rows] == ["y"]
    finally:
        conn.close()


def test_retention_respects_custom_days(settings):
    upload, _ = _seed_old_data(settings, days_old=10)
    report = run_retention(settings, dry_run=True, days=30)
    assert report["uploads_deleted"] == 0  # 10 days old < 30-day retention
    report = run_retention(settings, dry_run=True, days=7)
    assert report["uploads_deleted"] == 1


# ---------- History opt-out ----------

def test_history_disabled_state_and_no_writes(settings):
    disabled = replace(settings, history_enabled=False)
    c = _client(disabled)
    body = c.get("/api/history").json()
    assert body["enabled"] is False and body["status"] == "disabled"
    assert body["history"] == []
    # A process run (which records history when enabled) writes nothing.
    up = c.post("/api/uploads", files={"file": ("p.png", png_bytes(), "image/png")}).json()
    c.post("/api/process", json={"upload_id": up["id"]})
    conn = store.connect(disabled.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) c FROM history").fetchone()["c"] == 0
    finally:
        conn.close()
    caps = c.get("/api/capabilities").json()
    assert caps["history"]["enabled"] is False


def test_history_enabled_by_default(client, settings):
    body = client.get("/api/history").json()
    assert body["enabled"] is True and body["status"] == "enabled"
