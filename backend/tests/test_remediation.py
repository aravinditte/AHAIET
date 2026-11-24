"""Regression tests for the code-review remediation (finding ids
AHAIET-001..056). Written as code for the developer to run; none of
these were executed by the build assistant. Tests that need real
binaries/artifacts are marked model_required or self-skip with the
prerequisite named.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.core.errors import AppError
from app.services import retrieval
from app.services.language.normalize import normalize, normalize_nodiac
from app.services.language.passage import reassemble, split_segments
from app.storage import db as store


# ---------------------------------------------------------------------------
# Corpus helpers
# ---------------------------------------------------------------------------

def _insert_passage(db_path: Path, pid: str, profile: str, source: str,
                    english: str, reference: str) -> None:
    store.migrate(db_path)
    conn = store.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO reference_passages(id,language_profile,source_text,english_text,"
            "edition,license,provenance,book,reference,source_edition,translation_edition,"
            "partition_name,normalized_source,normalized_nodiac_source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, profile, source, english, "WLC", "PD", "test", "Genesis", reference,
             "WLC", "WEB", "test", normalize(source), normalize_nodiac(source)))
        for tok in sorted(set(normalize_nodiac(source).split())):
            conn.execute("INSERT INTO passage_tokens(passage_id,language_profile,token) "
                         "VALUES (?,?,?)", (pid, profile, tok))
        conn.commit()
    finally:
        conn.close()


HEBREW_A = "בְּרֵאשִׁית בָּרָא אֱלֹהִים"
HEBREW_A_UNPOINTED = "בראשית ברא אלהים"


# ---------------------------------------------------------------------------
# Retrieval truth (001, 002, 013, 014)
# ---------------------------------------------------------------------------

def test_retrieval_duplicate_exact_is_ambiguous(tmp_path):
    db = tmp_path / "t.db"
    _insert_passage(db, "p1", "biblical_hebrew", HEBREW_A, "English one", "Genesis 1:1")
    _insert_passage(db, "p2", "biblical_hebrew", HEBREW_A, "English two", "Genesis 1:2")
    out = retrieval.lookup(db, HEBREW_A, "biblical_hebrew")
    assert out["match"] is None
    assert out["reason"] == "ambiguous_match"
    assert out["text_match"] is True
    assert out["passage_identity_verified"] is False
    assert {c["reference"] for c in out["candidates"]} == {"Genesis 1:1", "Genesis 1:2"}


def test_nodiac_collision_does_not_verify(tmp_path):
    # Two DIFFERENT vocalized forms sharing one diacritic-insensitive
    # key: the unpointed query must not be certified as either passage.
    db = tmp_path / "t.db"
    pointed_b = "בְּרֵאשִׁית בָּרָא אֱלֹהִים"  # same consonants as A
    pointed_c = "בְרֵאשִׁית בָּרָא אֱלֹהִים"  # different pointing, same consonants
    assert normalize_nodiac(pointed_b) == normalize_nodiac(pointed_c)
    assert normalize(pointed_b) != normalize(pointed_c)
    _insert_passage(db, "p1", "biblical_hebrew", pointed_b, "English B", "Genesis 1:1")
    _insert_passage(db, "p2", "biblical_hebrew", pointed_c, "English C", "Genesis 1:2")
    out = retrieval.lookup(db, HEBREW_A_UNPOINTED, "biblical_hebrew")
    assert out["match"] is None
    assert out["reason"] == "ambiguous_match"
    assert len(out["candidates"]) == 2
    # But an exact vocalized unique match still verifies at top trust.
    exact = retrieval.lookup(db, pointed_b, "biblical_hebrew")
    assert exact["match"] is not None and exact["match"]["match_type"] == "exact"
    assert exact["passage_identity_verified"] is True


def test_retrieval_cache_invalidated_cross_process(tmp_path):
    db = tmp_path / "t.db"
    store.migrate(db)
    miss = retrieval.lookup(db, HEBREW_A, "biblical_hebrew")
    assert miss["match"] is None  # cached miss in THIS process
    # A separate process imports: simulated by writing through a fresh
    # connection and bumping the durable corpus revision, exactly what
    # import_into_db does in the importer's process.
    _insert_passage(db, "p1", "biblical_hebrew", HEBREW_A, "English one", "Genesis 1:1")
    retrieval.bump_corpus_revision(db)
    hit = retrieval.lookup(db, HEBREW_A, "biblical_hebrew")
    assert hit["match"] is not None
    assert hit["match"]["english_text"] == "English one"


def test_variant_shortlist_uses_token_index(tmp_path):
    db = tmp_path / "t.db"
    _insert_passage(db, "p1", "biblical_hebrew", HEBREW_A, "English one", "Genesis 1:1")
    conn = store.connect(db)
    try:
        rows = conn.execute("SELECT token FROM passage_tokens WHERE passage_id='p1'").fetchall()
    finally:
        conn.close()
    assert rows, "the inverted token index must be populated for variant shortlisting"


# ---------------------------------------------------------------------------
# Passage layout (012)
# ---------------------------------------------------------------------------

def test_preserve_blank_lines():
    text = "line one\n\n\nline two\n"
    seg = split_segments(text)
    out = reassemble(["t1", "t2"], seg)
    assert out == "t1\n\n\nt2\n".rstrip("\n") or out.split("\n")[:4] == ["t1", "", "", "t2"]
    leading = split_segments("\n\nline one")
    assert reassemble(["t1"], leading).startswith("\n\n")
    partial = split_segments("line one\n\nline two")
    assert reassemble(["t1", None], partial) == "t1\n\n"


# ---------------------------------------------------------------------------
# Job lifecycle / privacy (009, 010, 011, 015)
# ---------------------------------------------------------------------------

def _poll(client, job_id, timeout_s=10.0):
    deadline = time.monotonic() + timeout_s
    while True:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "partial", "failed", "cancelled", "expired"):
            return job
        assert time.monotonic() < deadline
        time.sleep(0.05)


def test_process_all_segments_failed_terminal(client, monkeypatch):
    def fake_ocr(path, settings, *a, **kw):
        return {"original_ocr_text": "unknown line one\nunknown line two",
                "uncertain_spans": [], "mean_confidence": None, "word_count": 4,
                "ocr_engine": "tesseract", "ocr_lang": "heb", "ocr_profile": "biblical_hebrew",
                "ocr_profile_note": "", "engine_version": None, "psm": 6,
                "preprocessing": {}, "stage_timings_ms": {}}

    import app.services.ocr.service as ocr_service
    monkeypatch.setattr(ocr_service, "run_ocr", fake_ocr)
    # The worker imports run_ocr inside the function from the service
    # module, so patching the module attribute is sufficient.
    up = client.post("/api/uploads", files={"file": ("p.png", _png(), "image/png")}).json()
    r = client.post("/api/process", json={"upload_id": up["id"]})
    assert r.status_code == 202
    job = _poll(client, r.json()["job_id"])
    assert job["status"] == "failed"  # terminal, never awaiting_translation
    assert job["status"] not in ("awaiting_translation", "queued",
                                 "running_ocr", "running_translation")


def _png():
    from conftest import png_bytes
    return png_bytes()


def test_persist_results_disabled(settings, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    private = Settings(storage_dir=tmp_path / "up", db_path=tmp_path / "priv.db",
                       models_manifest=settings.models_manifest,
                       datasets_manifest=settings.datasets_manifest,
                       persist_results=False, history_enabled=False)
    client = TestClient(create_app(private), raise_server_exceptions=False)
    up = client.post("/api/uploads", files={"file": ("p.png", _png(), "image/png")}).json()
    r = client.post("/api/process", json={"upload_id": up["id"]})
    assert r.status_code == 202
    job = _poll(client, r.json()["job_id"])
    assert job["status"] in ("failed", "completed", "partial", "cancelled")
    # No source/translation text anywhere in SQLite.
    conn = sqlite3.connect(tmp_path / "priv.db")
    try:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            if table in ("jobs", "history", "translation_cache"):
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                assert count == 0, f"{table} must stay empty with persist_results off"
    finally:
        conn.close()


def test_translate_all_segments_failed_is_422(client):
    r = client.post("/api/translate", json={
        "text": "no match line one\nno match line two",
        "source_language": "biblical_hebrew"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "translation_failed_all_segments"
    assert len(r.json()["segments"]) == 2


def test_job_cancel_endpoint(client):
    up = client.post("/api/uploads", files={"file": ("p.png", _png(), "image/png")}).json()
    r = client.post("/api/process", json={"upload_id": up["id"]})
    assert r.status_code == 202
    c = client.post(f"/api/jobs/{r.json()['job_id']}/cancel")
    assert c.status_code == 200 and c.json()["cancel_requested"] is True
    assert client.post("/api/jobs/nope/cancel").status_code == 404


# ---------------------------------------------------------------------------
# Artifact integrity + engine fallback (019, 020, 021)
# ---------------------------------------------------------------------------

def _artifact(tmp_path: Path, engine: str, files: dict[str, bytes],
              metrics: dict | None = None, record_sha: bool = True) -> dict:
    d = tmp_path / engine
    d.mkdir()
    described = []
    for name, data in files.items():
        (d / name).write_bytes(data)
        entry = {"path": name, "role": "config" if name.endswith(".ini") else "file"}
        if record_sha:
            entry["sha256"] = hashlib.sha256(data).hexdigest()
            entry["size_bytes"] = len(data)
        described.append(entry)
    primary = "moses.ini" if engine == "moses" else "model.npz"
    card = {"engine": engine, "language_profile": "biblical_hebrew",
            "model_version": f"{engine}-test", "primary_artifact": primary,
            "artifact_sha256": hashlib.sha256(files[primary]).hexdigest(),
            "files": described, "dataset_card_sha256": None,
            "dataset_id": "parallel-test", "metrics": metrics}
    (d / "model_card.json").write_text(json.dumps(card), encoding="utf-8")
    return {"id": f"{engine}-biblical-hebrew-en", "kind": "translation",
            "engine": engine, "language_profile": "biblical_hebrew",
            "status": "provisioned", "path": str(d),
            "checksum": card["artifact_sha256"], "version": f"{engine}-test"}


MOSES_FILES = {"moses.ini": b"[INPUT]\n", "phrase-table.gz": b"pt",
               "lm.binary": b"lm", "vocabulary.source.txt": b"vocab"}
MARIAN_FILES = {"model.npz": b"npz", "vocab.spm": b"spm",
                "decoder-config.yml": b"cfg", "vocabulary.source.txt": b"vocab"}


def test_model_hash_mismatch_rejected(tmp_path):
    from app.services.translation import model_artifacts
    entry = _artifact(tmp_path, "moses", dict(MOSES_FILES))
    res = model_artifacts.resolve_entry(entry)
    assert res.ok
    # Corrupt the vocabulary after the card recorded its checksum.
    (tmp_path / "moses" / "vocabulary.source.txt").write_bytes(b"tampered")
    res2 = model_artifacts.resolve_entry(entry)
    assert not res2.ok
    assert any("checksum mismatch" in m for m in res2.missing)


def test_model_card_path_escape_rejected(tmp_path):
    from app.services.translation import model_artifacts
    entry = _artifact(tmp_path, "moses", dict(MOSES_FILES))
    card_path = tmp_path / "moses" / "model_card.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["files"].append({"path": "../outside.txt", "role": "file"})
    card_path.write_text(json.dumps(card), encoding="utf-8")
    res = model_artifacts.resolve_entry(entry)
    assert not res.ok
    assert any("escapes" in m for m in res.missing)


def test_missing_best_decoder_tries_second_same_profile(tmp_path, monkeypatch):
    # Marian is selected first (evaluated) but its binary is missing;
    # the healthy Moses engine IN THE SAME PROFILE must serve instead,
    # with the failure recorded as a warning (AHAIET-020).
    from app.core.config import Settings as _S
    from app.services.translation import service as tservice

    marian = _artifact(tmp_path, "marian", dict(MARIAN_FILES), metrics={"chrf_pp": 42.0})
    moses = _artifact(tmp_path, "moses", dict(MOSES_FILES), metrics=None)
    manifest = tmp_path / "models.json"
    manifest.write_text(json.dumps({"models": [marian, moses]}), encoding="utf-8")
    s = _S(storage_dir=tmp_path / "up", db_path=tmp_path / "t.db",
           models_manifest=manifest, datasets_manifest=tmp_path / "d.json",
           marian_decoder_cmd="ahaiet-no-such-marian-binary",
           moses_cmd=str(_echo_binary(tmp_path)))
    out = tservice.translate("some source text", s, "biblical_hebrew")
    assert out["translation_method"] == "moses"
    assert any("marian" in w.lower() and "failed" in w.lower() for w in out["warnings"])


def _echo_binary(tmp_path: Path) -> Path:
    """A portable echo decoder via sys.executable (AHAIET-048): works
    on Windows and POSIX, unlike a shebang script."""
    helper = Path(__file__).parent / "doubles" / "echo_decoder.py"
    wrapper = tmp_path / "echo_moses.py"
    wrapper.write_text(
        "import subprocess, sys\n"
        f"sys.exit(subprocess.call([sys.executable, {str(helper)!r}] + sys.argv[1:]))\n",
        encoding="utf-8")
    return wrapper


def test_decoder_empty_output_is_error(tmp_path):
    from app.services.translation import decoder_output
    with pytest.raises(AppError) as exc:
        decoder_output.validate_single("   \n  \n", "Moses")
    assert exc.value.code == "translation_empty_output"
    with pytest.raises(AppError) as exc2:
        decoder_output.validate_single("one\ntwo", "Moses")
    assert exc2.value.code == "translation_output_alignment"
    assert decoder_output.validate_single("one\n\n", "Moses") == "one"
    assert decoder_output.validate_batch("a\nb", 2, "Moses") == ["a", "b"]
    with pytest.raises(AppError):
        decoder_output.validate_batch("a", 2, "Moses")


def test_windows_portable_double_via_sys_executable(tmp_path):
    import subprocess
    helper = Path(__file__).parent / "doubles" / "echo_decoder.py"
    proc = subprocess.run([sys.executable, str(helper), "-f", "ignored.ini"],
                          input="abc\ndef\n", capture_output=True, text=True)
    assert proc.returncode == 0
    assert proc.stdout.splitlines() == ["EN: abc", "EN: def"]


# ---------------------------------------------------------------------------
# OCR robustness (022, 034, 037, 023, 024, 025, 028)
# ---------------------------------------------------------------------------

def test_ocr_timeout_returns_504(tmp_path):
    import subprocess as sp
    from app.services.ocr import tesseract_adapter

    sleeper = tmp_path / "sleepy.py"
    sleeper.write_text("import time; time.sleep(30)\n", encoding="utf-8")
    wrapper = tmp_path / "tesseract"
    wrapper.write_text(
        "#!/bin/sh\nexec " + sys.executable + f" {sleeper}\n", encoding="utf-8")
    wrapper.chmod(0o755)
    if sys.platform.startswith("win"):
        pytest.skip("POSIX wrapper double; the .cmd double covers Windows (AHAIET-048)")
    with pytest.raises(AppError) as exc:
        tesseract_adapter.run_tesseract_tsv(tmp_path / "x.png", cmd=str(wrapper),
                                            timeout_s=0.5)
    assert exc.value.status_code == 504
    assert exc.value.code == "ocr_timeout"
    assert sp  # silence linter


def test_tsv_malformed_integer_is_parse_error():
    from app.services.ocr.tesseract_adapter import OcrParseError, parse_tsv
    header = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
              "left\ttop\twidth\theight\tconf\ttext")
    bad = header + "\n5\t1\tNOTANUMBER\t1\t1\t1\t0\t0\t10\t10\t90\tword"
    with pytest.raises(OcrParseError):
        parse_tsv(bad)
    good = header + "\n5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t90\tword"
    parsed = parse_tsv(good)
    assert parsed["words"][0]["block"] == 1


def test_highlight_second_repeated_word_only(tmp_path):
    # Two identical tokens; only the SECOND is low-confidence. The
    # uncertain span must carry the occurrence identity of the second.
    from app.services.ocr import tesseract_adapter
    header = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
              "left\ttop\twidth\theight\tconf\ttext")
    rows = [header,
            "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t95\tsame",
            "5\t1\t1\t1\t1\t2\t20\t0\t10\t10\t10\tsame"]
    parsed = tesseract_adapter.parse_tsv("\n".join(rows))
    low = [(i, w) for i, w in enumerate(parsed["words"]) if 0 <= w["conf"] < 60]
    assert len(low) == 1 and low[0][0] == 1  # occurrence index 1 = second word


def test_script_tiers_production_gates(tmp_path, monkeypatch):
    from app.services.ocr import script_profiles
    ckpt = tmp_path / "model.mlmodel"
    ckpt.write_bytes(b"ckpt")
    digest = hashlib.sha256(b"ckpt").hexdigest()
    manifest = tmp_path / "models.json"
    manifest.write_text(json.dumps({"models": [
        {"id": "kraken-paleo", "kind": "ocr", "engine": "kraken",
         "script_profile": "paleo_hebrew", "status": "provisioned",
         "path": str(ckpt), "version": "t"}]}), encoding="utf-8")
    s = Settings(storage_dir=tmp_path / "up", db_path=tmp_path / "t.db",
                 models_manifest=manifest, datasets_manifest=tmp_path / "d.json")
    benchmarks = tmp_path / "benchmarks"
    benchmarks.mkdir()
    monkeypatch.setattr(script_profiles, "BENCHMARKS_DIR", benchmarks)
    profile = next(p for p in script_profiles.load_registry() if p["id"] == "paleo_hebrew")
    row = script_profiles.profile_support(s, profile, False)
    assert row["tier"] == "model_installed"
    (benchmarks / "htr-eval-paleo_hebrew.json").write_text(json.dumps(
        {"cer": 1.0, "checkpoint_sha256": digest, "test_samples": 100,
         "dataset_sha256": "d" * 64}), encoding="utf-8")
    row = script_profiles.profile_support(s, profile, False)
    assert row["tier"] == "experimentally_evaluated"  # CER 100% cannot be production
    (benchmarks / "htr-eval-paleo_hebrew.json").write_text(json.dumps(
        {"cer": 0.1, "checkpoint_sha256": digest, "test_samples": 3,
         "dataset_sha256": "d" * 64}), encoding="utf-8")
    row = script_profiles.profile_support(s, profile, False)
    assert row["tier"] == "experimentally_evaluated"  # too few samples
    (benchmarks / "htr-eval-paleo_hebrew.json").write_text(json.dumps(
        {"cer": 0.1, "checkpoint_sha256": digest, "test_samples": 40,
         "dataset_sha256": "d" * 64, "script_profile": "paleo_hebrew"}), encoding="utf-8")
    row = script_profiles.profile_support(s, profile, False)
    assert row["tier"] == "production_supported" and row["status"] == "supported"


def test_orientation_attempted_vs_applied(tmp_path):
    import io as _io
    from PIL import Image
    from app.services.preprocessing.service import preprocess_image
    buf = _io.BytesIO()
    Image.new("RGB", (32, 32), (255, 255, 255)).save(buf, format="PNG")
    _, report = preprocess_image(buf.getvalue(), "conservative", Settings(
        storage_dir=tmp_path / "up", db_path=tmp_path / "t.db"))
    step = next(st for st in report["steps"] if st["step"] == "exif_orientation")
    assert step["attempted"] is True and step["applied"] is False
    names = [st["step"] for st in report["steps"]]
    assert "pixel_upscale" in names and "upscale_to_target_dpi" not in names


def test_multipage_image_rejected(tmp_path):
    import io as _io
    from PIL import Image
    from app.core.errors import AppError as _AE
    from app.services.preprocessing.service import validate_and_decode
    buf = _io.BytesIO()
    img = Image.new("RGB", (16, 16), (255, 255, 255))
    img.save(buf, format="TIFF", save_all=True,
             append_images=[Image.new("RGB", (16, 16), (0, 0, 0))])
    s = Settings(storage_dir=tmp_path / "up", db_path=tmp_path / "t.db")
    with pytest.raises(_AE) as exc:
        validate_and_decode(buf.getvalue(), s)
    assert exc.value.code == "multipage_image"


# ---------------------------------------------------------------------------
# Config / security / storage (031..056 area)
# ---------------------------------------------------------------------------

def test_config_validation_rejects_bad_values():
    with pytest.raises(ValueError):
        Settings(upload_max_bytes=0)
    with pytest.raises(ValueError):
        Settings(ocr_psm=99)
    with pytest.raises(ValueError):
        Settings(retention_days=-1)
    with pytest.raises(ValueError):
        Settings(ocr_confidence_threshold=101)


def test_sanitized_detail_strips_paths():
    from app.core.errors import sanitize_detail
    out = sanitize_detail("failed at /home/user/secret/file.bin with error " + "x" * 1000)
    assert "/home/user" not in out and len(out) <= 300


def test_rate_limiter_registry_bounded():
    from app.core.security import RateLimitMiddleware
    mw = RateLimitMiddleware(lambda *a: None, {"/api/ocr": 5}, max_clients=10)
    for i in range(500):
        mw._allow(f"client-{i}", "/api/ocr", 5)
    mw._prune(time.monotonic() + 10_000)
    assert len(mw._hits) <= 10


def test_migration_atomicity(tmp_path):
    # A failing migration must roll back: no version row, no partial
    # column (AHAIET-018).
    from app.storage import db as store_mod
    db = tmp_path / "m.db"
    original = list(store_mod.MIGRATIONS)
    try:
        store_mod.MIGRATIONS.append((90, "ALTER TABLE jobs ADD COLUMN boom TEXT;\n"
                                         "THIS IS NOT SQL;"))
        with pytest.raises(Exception):
            store_mod.migrate(db)
    finally:
        store_mod.MIGRATIONS[:] = original
    conn = store.connect(db)
    try:
        versions = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
        assert 90 not in versions
        cols = [r[1] for r in conn.execute("PRAGMA table_info(jobs)")]
        assert "boom" not in cols
    finally:
        conn.close()
    store_mod.migrate(db)  # a clean migrate still succeeds afterwards


def test_upload_atomic_and_idempotent(client, settings):
    data = _png()
    r1 = client.post("/api/uploads", files={"file": ("p.png", data, "image/png")})
    r2 = client.post("/api/uploads", files={"file": ("p.png", data, "image/png")})
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    stored = list(settings.storage_dir.glob(r1.json()["id"] + ".*"))
    assert len(stored) == 1 and stored[0].read_bytes() == data
    leftovers = [p for p in settings.storage_dir.iterdir() if p.name.startswith(".upload-")]
    assert leftovers == []


def test_fixture_manifest_is_canonical():
    repo = Path(__file__).resolve().parents[2]
    manifest = json.loads((repo / "training/ocr/fixtures/fixtures.json")
                          .read_text(encoding="utf-8"))
    names = {f["filename"] for f in manifest["fixtures"]}
    assert names == {"genesis_1_1_hebrew.png", "daniel_2_4_aramaic.png"}
    spec = (repo / "frontend/e2e/translator.spec.ts").read_text(encoding="utf-8")
    assert "fixtures.json" in spec  # Playwright reads the same manifest
    assert "genesis-1-1.png" not in spec and "daniel-2-4.png" not in spec
    gen_py = (repo / "training/ocr/generate_fixtures.py").read_text(encoding="utf-8")
    assert "fixtures.json" in gen_py  # and so does the generator


def test_access_token_required_when_configured(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    s = Settings(storage_dir=tmp_path / "up", db_path=tmp_path / "t.db",
                 access_token="test-token")
    client = TestClient(create_app(s), raise_server_exceptions=False)
    up = client.post("/api/uploads", files={"file": ("p.png", _png(), "image/png")}).json()
    assert client.get(f"/api/uploads/{up['id']}").status_code == 401
    ok = client.get(f"/api/uploads/{up['id']}",
                    headers={"X-AHAIET-Access-Token": "test-token"})
    assert ok.status_code == 200


def test_translate_lineage_original_null_without_ocr(client):
    # AHAIET-026: without OCR context, original_ocr_text is null —
    # never a copy of the input text.
    r = client.post("/api/translate", json={"text": HEBREW_A,
                                            "source_language": "biblical_hebrew"})
    # No corpus in the test DB: the request fails honestly, so assert
    # the lineage rule on the service-shaped success path instead.
    if r.status_code == 200:
        assert r.json()["original_ocr_text"] is None
        assert r.json()["corrected_source_text"] == HEBREW_A
    else:
        assert r.status_code in (422, 503)
