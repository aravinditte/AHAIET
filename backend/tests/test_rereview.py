"""Regression tests for the re-review findings (NEW-01..NEW-27).

Written to be run by the developer (see docs/VERIFICATION.md):
  python -m pytest tests/test_rereview.py -q     (from backend/)

Data-split tests (NEW-01/NEW-02) live in training/tests; the
frontend race/token tests (NEW-06/07/11/25) live in frontend/e2e.
Everything here is hermetic: decoder doubles are genuinely
executable scripts from tests/double_factory.py (NEW-05).
"""
import hashlib
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.services.ocr import script_profiles, tesseract_adapter
from app.services.translation import model_artifacts
from app.services.translation import service as tservice
from app.storage import db as store

from double_factory import echo_double, hanging_double, write_double
from test_remediation import MARIAN_FILES, MOSES_FILES, _artifact, _insert_passage


def _manifest(tmp_path, entries):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"models": entries}), encoding="utf-8")
    return path

HEBREW_A = "בראשית ברא אלהים"
HEBREW_B = "ויאמר אלהים יהי אור"


def _S(tmp_path, **over):
    base = Settings(storage_dir=tmp_path / "up", db_path=tmp_path / "t.db",
                    models_manifest=tmp_path / "models.json",
                    datasets_manifest=tmp_path / "d.json")
    return replace(base, **over)


# ---------------------------------------------------------------------------
# NEW-04: selection basis labelling (backend readiness)
# ---------------------------------------------------------------------------

def test_readiness_labels_single_evaluated_engine(tmp_path):
    moses = _artifact(tmp_path, "moses", dict(MOSES_FILES))
    marian = _artifact(tmp_path, "marian", dict(MARIAN_FILES),
                       metrics={"chrf_pp": 42.0})
    s = _S(tmp_path, models_manifest=_manifest(tmp_path, [moses, marian]))
    store.migrate(s.db_path)
    from app.services.translation.selection import per_profile_readiness
    readiness = per_profile_readiness(s)["biblical_hebrew"]
    assert readiness["selection_basis"] == "single_evaluated_engine"
    assert readiness["comparable"] is False


def test_readiness_metric_without_run_record_is_not_evaluated(tmp_path):
    # NEW-14: a bare score on the card, with no valid run record,
    # must not make the engine "evaluated".
    marian = _artifact(tmp_path, "marian", dict(MARIAN_FILES),
                       metrics={"chrf_pp": 42.0})
    # Strip the run record the fixture helper adds with metrics.
    card_path = Path(marian["path"]) / "model_card.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    del card["evaluation_run"]
    card_path.write_text(json.dumps(card), encoding="utf-8")
    res = model_artifacts.resolve_entry(marian)
    assert res.evaluation_state != "evaluated"
    assert res.chrf_pp is None
    assert res.metric_without_run is True


# ---------------------------------------------------------------------------
# NEW-08: cross-profile evidence requires a profile choice
# ---------------------------------------------------------------------------

def test_cross_profile_verified_plus_ambiguous_requires_choice(settings):
    # Verified exact match in Hebrew; the SAME consonantal text is
    # an ambiguous (2-candidate) normalized match in Aramaic. With
    # no profile selected the service must ask, not guess.
    _insert_passage(settings.db_path, "h1", "biblical_hebrew",
                    "אַבְג דֵה", "hebrew english", "Genesis 1:1")
    _insert_passage(settings.db_path, "a1", "biblical_aramaic",
                    "אָבֶג דָה", "aramaic english one", "Daniel 2:4")
    _insert_passage(settings.db_path, "a2", "biblical_aramaic",
                    "אֲבֵג דֵה", "aramaic english two", "Daniel 2:5")
    with pytest.raises(tservice.ProfileChoiceRequired):
        tservice.translate("אַבְג דֵה", settings, None)


# ---------------------------------------------------------------------------
# NEW-09: line structure routes to the passage flow; blanks preserved
# ---------------------------------------------------------------------------

def test_multiline_single_segment_uses_passage_flow(settings):
    _insert_passage(settings.db_path, "p1", "biblical_hebrew", HEBREW_A,
                    "In the beginning God created", "Genesis 1:1")
    _insert_passage(settings.db_path, "p2", "biblical_hebrew", HEBREW_B,
                    "And God said, let there be light", "Genesis 1:3")
    text = f"{HEBREW_A}\n\n{HEBREW_B}"
    out = tservice.translate_passage(text, settings, "biblical_hebrew")
    # Exact blank-line preservation (NEW-25): one blank line between.
    assert out["english_translation"] == \
        "In the beginning God created\n\nAnd God said, let there be light"
    assert len(out["segments"]) == 2


def test_single_line_keeps_direct_path(settings):
    _insert_passage(settings.db_path, "p1", "biblical_hebrew", HEBREW_A,
                    "In the beginning God created", "Genesis 1:1")
    out = tservice.translate_passage(HEBREW_A, settings, "biblical_hebrew")
    assert out["translation_method"] == "verified_reference"
    assert "segments" not in out or out.get("segments") in (None, [])


# ---------------------------------------------------------------------------
# NEW-10: categorized engine failures are preserved
# ---------------------------------------------------------------------------

def _two_engine_settings(tmp_path, moses_cmd, marian_cmd, **over):
    moses = _artifact(tmp_path, "moses", dict(MOSES_FILES))
    marian = _artifact(tmp_path, "marian", dict(MARIAN_FILES))
    return _S(tmp_path, models_manifest=_manifest(tmp_path, [moses, marian]),
              moses_cmd=moses_cmd, marian_decoder_cmd=marian_cmd, **over)


def test_all_engines_timeout_gives_504_with_attempts(tmp_path):
    hang_m = hanging_double(tmp_path, "hang-moses")
    hang_n = hanging_double(tmp_path, "hang-marian")
    s = _two_engine_settings(tmp_path, hang_m["vector"], hang_n["vector"],
                             translation_timeout_s=1.0)
    store.migrate(s.db_path)
    with pytest.raises(AppError) as ei:
        tservice.translate("unmatched source text", s, "biblical_hebrew")
    assert ei.value.status == 504
    assert ei.value.code == "translation_timeout"
    assert len(ei.value.attempts) == 2
    assert {a["engine"] for a in ei.value.attempts} == {"moses", "marian"}


def test_all_engines_unavailable_gives_503_not_model_not_provisioned(tmp_path):
    s = _two_engine_settings(tmp_path, "ahaiet-no-such-moses",
                             "ahaiet-no-such-marian")
    store.migrate(s.db_path)
    with pytest.raises(AppError) as ei:
        tservice.translate("unmatched source text", s, "biblical_hebrew")
    assert ei.value.status == 503
    assert ei.value.code != "model_not_provisioned"
    assert len(ei.value.attempts) == 2


def test_mixed_timeout_and_unavailable_gives_most_severe(tmp_path):
    hang = hanging_double(tmp_path, "hang-moses")
    s = _two_engine_settings(tmp_path, hang["vector"],
                             "ahaiet-no-such-marian",
                             translation_timeout_s=1.0)
    store.migrate(s.db_path)
    with pytest.raises(AppError) as ei:
        tservice.translate("unmatched source text", s, "biblical_hebrew")
    assert ei.value.status == 504
    assert ei.value.code == "translation_timeout"
    assert len(ei.value.attempts) == 2


# ---------------------------------------------------------------------------
# NEW-12: token guard matrix
# ---------------------------------------------------------------------------

def _token_client(tmp_path):
    s = Settings(storage_dir=tmp_path / "up", db_path=tmp_path / "t.db",
                 models_manifest=tmp_path / "m.json",
                 datasets_manifest=tmp_path / "d.json",
                 access_token="test-token-123")
    return TestClient(create_app(s), raise_server_exceptions=False)


def test_token_guard_matrix(tmp_path):
    c = _token_client(tmp_path)
    guarded = [
        ("POST", "/api/process"),
        ("GET", "/api/jobs/abc"),
        ("GET", "/api/jobs/abc/result"),
        ("POST", "/api/jobs/abc/cancel"),
        ("GET", "/api/history"),
        ("DELETE", "/api/history/abc"),
        ("GET", "/api/uploads/abc"),
    ]
    for method, path in guarded:
        r = c.request(method, path, json={} if method == "POST" else None)
        assert r.status_code == 401, (method, path, r.status_code)
        r = c.request(method, path,
                      headers={"X-AHAIET-Access-Token": "wrong"},
                      json={} if method == "POST" else None)
        assert r.status_code == 401, (method, path, "wrong token accepted")
        r = c.request(method, path,
                      headers={"X-AHAIET-Access-Token": "test-token-123"},
                      json={} if method == "POST" else None)
        assert r.status_code != 401, (method, path, "valid token rejected")


# ---------------------------------------------------------------------------
# NEW-15: job ownership, heartbeat, two-instance recovery
# ---------------------------------------------------------------------------

def test_recovery_fails_only_stale_heartbeat_jobs(settings):
    from app.services import job_runner
    manager_a = job_runner.JobManager(settings)
    manager_b = job_runner.JobManager(settings)
    try:
        job_runner.create_job(settings, manager_a, "job-stale", "up1", None)
        job_runner.create_job(settings, manager_b, "job-live", "up2", None)
        conn = store.connect(settings.db_path)
        try:
            conn.execute("UPDATE jobs SET heartbeat_at='2000-01-01 00:00:00' "
                         "WHERE id='job-stale'")
            conn.commit()
        finally:
            conn.close()
        recovered = job_runner.recover_orphaned_jobs(settings)
        assert recovered == 1
        stale = job_runner.get_job(settings, manager_a, "job-stale")
        live = job_runner.get_job(settings, manager_b, "job-live")
        assert stale["status"] == "failed"
        assert "worker_restarted" in (stale["error"] or "")
        assert live["status"] == "queued"
        assert live["owner_id"] == manager_b.worker_id
        assert stale["owner_id"] == manager_a.worker_id
    finally:
        manager_a.shutdown()
        manager_b.shutdown()


# ---------------------------------------------------------------------------
# NEW-16: OCR job deadline terminates a hanging worker
# ---------------------------------------------------------------------------

def test_job_ocr_deadline_terminates_hanging_worker(tmp_path):
    from app.services import job_runner
    from conftest import png_bytes
    smart = write_double(tmp_path, "hang-ocr",
                         "import sys, time\n"
                         "if '--list-langs' in sys.argv:\n"
                         "    print('List of available languages (1):')\n"
                         "    print('heb')\n"
                         "    sys.exit(0)\n"
                         "time.sleep(60)\n")
    s = _S(tmp_path, tesseract_cmd=str(smart["path"]),
           ocr_timeout_s=120.0, job_deadline_s=3.0)
    store.migrate(s.db_path)
    upload = tmp_path / "page.png"
    upload.write_bytes(png_bytes(64, 64))
    manager = job_runner.JobManager(s)
    try:
        job_runner.create_job(s, manager, "job-hang", "up1", "biblical_hebrew")
        started = time.monotonic()
        job_runner.run_process_job(s, manager, "job-hang", upload,
                                   {"language_profile": "biblical_hebrew",
                                    "engine": "tesseract",
                                    "script_profile": "hebrew_square"})
        elapsed = time.monotonic() - started
        view = job_runner.get_job(s, manager, "job-hang")
        assert view["status"] == "failed"
        assert "ocr_timeout" in (view["error"] or "")
        assert elapsed < 30, "deadline did not bound the job"
    finally:
        manager.shutdown()


# ---------------------------------------------------------------------------
# NEW-17: script production tiers
# ---------------------------------------------------------------------------

def _kraken_profile():
    return {"id": "paleo_hebrew", "name": "Paleo-Hebrew",
            "script": "Paleo-Hebrew", "route": "kraken", "note": None}


def _support_with_record(tmp_path, monkeypatch, record, dataset_dir=None):
    s = _S(tmp_path)
    ckpt_sha = record.get("checkpoint_sha256", "ab" * 32)
    monkeypatch.setattr(script_profiles, "evaluation_record",
                        lambda pid: record)
    monkeypatch.setattr(script_profiles, "kraken_checkpoints",
                        lambda settings, pid=None: [
                            {"id": "ck1", "script_profile": pid,
                             "path": str(tmp_path / "ck.mlmodel"),
                             "sha256": ckpt_sha}])
    return script_profiles.profile_support(s, _kraken_profile(), False)


def _production_record(tmp_path, **over):
    dataset = tmp_path / "evalset"
    dataset.mkdir(exist_ok=True)
    (dataset / "line1.txt").write_text("labelled line", encoding="utf-8")
    from app.services.ocr.script_profiles import _dataset_hash
    record = {"script_profile": "paleo_hebrew", "cer": 0.10, "wer": 0.25,
              "test_samples": 60, "test_set": str(dataset),
              "dataset_sha256": _dataset_hash(str(dataset)),
              "checkpoint_sha256": "ab" * 32,
              "evaluated_at": "2026-11-24"}
    record.update(over)
    return record


def test_tier_validated_for_production_when_all_gates_hold(tmp_path, monkeypatch):
    out = _support_with_record(tmp_path, monkeypatch,
                               _production_record(tmp_path))
    assert out["tier"] == "validated_for_production"
    assert out["unmet_conditions"] == []


def test_tier_high_cer_blocks_production(tmp_path, monkeypatch):
    out = _support_with_record(tmp_path, monkeypatch,
                               _production_record(tmp_path, cer=0.45))
    assert out["tier"] == "evaluated_on_dataset"
    assert "cer_within_limit" in out["unmet_conditions"]


def test_tier_absent_script_identity_blocks_production(tmp_path, monkeypatch):
    record = _production_record(tmp_path)
    del record["script_profile"]  # absent must NOT pass (NEW-17)
    out = _support_with_record(tmp_path, monkeypatch, record)
    assert out["tier"] == "evaluated_on_dataset"
    assert "script_identity_matches" in out["unmet_conditions"]


def test_tier_fake_dataset_hash_blocks_production(tmp_path, monkeypatch):
    out = _support_with_record(
        tmp_path, monkeypatch,
        _production_record(tmp_path, dataset_sha256="ff" * 32))
    assert out["tier"] == "evaluated_on_dataset"
    assert "dataset_hash_verified" in out["unmet_conditions"]


def test_tier_too_few_samples_blocks_production(tmp_path, monkeypatch):
    out = _support_with_record(tmp_path, monkeypatch,
                               _production_record(tmp_path, test_samples=12))
    assert out["tier"] == "evaluated_on_dataset"
    assert "min_samples" in out["unmet_conditions"]


# ---------------------------------------------------------------------------
# NEW-20: tesseract probe failure is not usability
# ---------------------------------------------------------------------------

def test_tesseract_probe_failure_not_usable_despite_traineddata(tmp_path):
    failing = write_double(tmp_path, "tess-fail", "import sys\nsys.exit(1)\n")
    prefix = tmp_path / "tessdata"
    prefix.mkdir()
    (prefix / "heb.traineddata").write_bytes(b"fake-traineddata")
    out = tesseract_adapter.readiness(cmd=str(failing["path"]), lang="heb",
                                      tessdata_prefix=prefix, ttl_s=0)
    assert out["probe_failed"] is True
    assert out["usable"] is False
    assert out["language_data_file_present"] is True
    assert out["language_data_available"] is False


# ---------------------------------------------------------------------------
# NEW-21: Tesseract token offsets are exact
# ---------------------------------------------------------------------------

def test_tsv_offsets_slice_back_to_words():
    header = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
              "left\ttop\twidth\theight\tconf\ttext")
    rows = [header]
    words = [("אב,", 90), ("אב.", 40), ("אב,", 95)]  # repeated, punctuated
    for i, (w, conf) in enumerate(words, start=1):
        rows.append("\t".join(["5", "1", "1", "1", "1", str(i), "0", "0",
                               "10", "10", str(conf), w]))
    parsed = tesseract_adapter.parse_tsv("\n".join(rows))
    text = parsed["text"]
    assert parsed["offset_encoding"] == "unicode_code_points"
    for w in parsed["words"]:
        assert text[w["char_start"]:w["char_end"]] == w["text"]
    starts = [w["char_start"] for w in parsed["words"]]
    assert starts == sorted(starts) and len(set(starts)) == 3


# ---------------------------------------------------------------------------
# NEW-23: Kraken grapheme-cluster confidence alignment
# ---------------------------------------------------------------------------

def test_grapheme_clusters_keep_niqqud_with_base_letters():
    from app.services.ocr.kraken_adapter import grapheme_clusters
    vocalized = "בְּרֵאשִׁית"  # 6 base letters + combining niqqud/cantillation
    clusters = grapheme_clusters(vocalized)
    assert len(clusters) == 6
    assert "".join(clusters) == vocalized
    assert grapheme_clusters("abc") == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# NEW-27: forced artifact verification catches stealth edits
# ---------------------------------------------------------------------------

def test_verify_artifacts_catches_same_size_edit_with_restored_mtime(tmp_path):
    entry = _artifact(tmp_path, "moses", dict(MOSES_FILES))
    s = _S(tmp_path, models_manifest=_manifest(tmp_path, [entry]),
           artifact_integrity_ttl_s=3600.0)
    first = model_artifacts.resolve_entry(entry)
    assert first.ok
    target = Path(entry["path"]) / "vocabulary.source.txt"
    original = target.read_bytes()
    stat = target.stat()
    target.write_bytes(b"X" * len(original))  # same size, different bytes
    os.utime(target, (stat.st_atime, stat.st_mtime))  # restored mtime
    results = model_artifacts.verify_artifacts(s, force=True)
    by_id = {r["id"]: r for r in results}
    assert by_id[entry["id"]]["ok"] is False


# ---------------------------------------------------------------------------
# NEW-18: /api/languages derives status from live state
# ---------------------------------------------------------------------------

def test_languages_status_reflects_corpus(settings, client):
    body = client.get("/api/languages").json()
    by_id = {p["id"]: p for p in body["languages"]}
    assert by_id["biblical_hebrew"]["translation_status"] == "not_provisioned"
    _insert_passage(settings.db_path, "p1", "biblical_hebrew", HEBREW_A,
                    "In the beginning God created", "Genesis 1:1")
    body = client.get("/api/languages").json()
    by_id = {p["id"]: p for p in body["languages"]}
    assert by_id["biblical_hebrew"]["translation_status"] == "retrieval_available"
    assert by_id["biblical_aramaic"]["translation_status"] == "not_provisioned"
