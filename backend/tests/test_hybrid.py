"""Tests for hybrid verification, reference-first routing refinements,
complete passages, the script support matrix, the Kraken adapter's
honest paths, and the translation cache / stage timings.

Written to be run by the developer (see docs/VERIFICATION.md). Test
doubles (echo decoder binaries, fabricated-in-test evaluation records
and checkpoint files) live only inside these tests and are labelled as
such; they are never referenced by any shipped manifest.
"""
import gzip, hashlib, json, sys
from dataclasses import replace
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.core.errors import UnavailableError
from app.corpus.import_morphhb import import_into_db
from app.main import create_app
from app.services.ocr import kraken_adapter, script_profiles
from app.services.translation.service import translate, translate_passage
from app.services.verification.service import verify_candidate
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
    import_into_db(settings.db_path, list(_sample().values()))
    return settings


@pytest.fixture()
def corpus_client(corpus_settings):
    return TestClient(create_app(corpus_settings), raise_server_exceptions=False)


def _check(report: dict, name: str) -> dict:
    return next(c for c in report["checks"] if c["name"] == name)


# ---------- verification checks ----------

def test_verification_negation_mismatch_warns(settings):
    # "You shall not steal" without the negation: counts differ -> warn.
    report = verify_candidate(settings.db_path, "לֹא תִּגְנֹב", "You shall steal",
                              "biblical_hebrew")
    chk = _check(report, "negation")
    assert chk["status"] == "warn"
    assert chk["evidence"]["source_negations"] == 1
    assert chk["evidence"]["candidate_negations"] == 0


def test_verification_negation_match_passes(settings):
    report = verify_candidate(settings.db_path, "לֹא תִּגְנֹב", "You shall not steal",
                              "biblical_hebrew")
    assert _check(report, "negation")["status"] == "pass"


def test_verification_numbers_mismatch_warns(settings):
    report = verify_candidate(settings.db_path, "שְׁנֵי לֻחֹת", "three tablets",
                              "biblical_hebrew")
    chk = _check(report, "numbers")
    assert chk["status"] == "warn"
    assert chk["evidence"]["missing_values"] == [2]
    assert chk["evidence"]["extra_values"] == [3]


def test_verification_numbers_match_passes(settings):
    report = verify_candidate(settings.db_path, "שְׁנֵי לֻחֹת", "two tablets",
                              "biblical_hebrew")
    assert _check(report, "numbers")["status"] == "pass"


def test_verification_coverage_with_fixture_corpus(corpus_settings):
    gen = _sample()["Genesis 1:1"]
    report = verify_candidate(corpus_settings.db_path, gen["source_text"],
                              gen["english_text"], "biblical_hebrew")
    chk = _check(report, "source_coverage")
    assert chk["status"] == "pass"
    assert chk["evidence"]["coverage_ratio"] >= 0.6
    assert report["overall_status"] in ("no_issues_found", "warnings")


def test_verification_coverage_flags_unrelated_candidate(corpus_settings):
    gen = _sample()["Genesis 1:1"]
    report = verify_candidate(corpus_settings.db_path, gen["source_text"],
                              "Preheat the oven and fold in the flour gently",
                              "biblical_hebrew")
    chk = _check(report, "source_coverage")
    assert chk["status"] in ("warn", "fail")
    assert chk["evidence"]["uncovered_tokens"]


def test_verification_reference_agreement_divergence_warns(corpus_settings):
    gen = _sample()["Genesis 1:1"]
    report = verify_candidate(corpus_settings.db_path, gen["source_text"],
                              "Preheat the oven and fold in the flour gently",
                              "biblical_hebrew",
                              context={"reference_english": gen["english_text"]})
    assert _check(report, "reference_agreement")["status"] == "warn"


def test_verification_without_corpus_is_not_applicable(settings):
    report = verify_candidate(settings.db_path, "בְּרֵאשִׁית", "In the beginning",
                              "biblical_hebrew")
    assert _check(report, "source_coverage")["status"] == "not_applicable"
    assert report["overall_status"] != "correct"  # the status vocabulary has no such value


def test_translate_response_carries_verification_and_provenance(corpus_client):
    gen = _sample()["Genesis 1:1"]
    r = corpus_client.post("/api/translate", json={"text": gen["source_text"],
                                                   "source_language": "biblical_hebrew"})
    assert r.status_code == 200
    body = r.json()
    assert body["verification"]["overall_status"] in ("no_issues_found", "warnings", "high_risk")
    assert any(c["name"] == "source_coverage" for c in body["verification"]["checks"])
    assert body["provenance"]["engine"] == "verified_reference"
    assert body["provenance"]["retrieval_citation"]["reference"] == "Genesis 1:1"
    assert body["cached"] is False


# ---------- routing order ----------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fake_binary(tmp_path: Path, name: str, prefix: str, counter: Path | None = None) -> Path:
    script = tmp_path / name
    lines = [f"#!{sys.executable}", "import sys"]
    if counter is not None:
        lines.append(f"open({str(counter)!r}, 'a').write('x')")
    lines += ["for line in sys.stdin:",
              f"    sys.stdout.write({prefix!r} + line)"]
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    script.chmod(0o755)
    return script


def _write_card(artifact_dir: Path, engine: str, files: list[dict],
                metrics: dict | None = None) -> dict:
    primary = artifact_dir / ("moses.ini" if engine == "moses" else "model.npz")
    card = {"engine": engine, "language_profile": "biblical_hebrew",
            "model_version": f"{engine}-test-1",
            "artifact_sha256": _sha(primary.read_bytes()), "primary_artifact": primary.name,
            "files": files, "dataset_card_sha256": "card-sha", "dataset_id": "parallel-test",
            "tool_versions": {}, "license": "test fixture", "provenance": "test fixture",
            "metrics": metrics}
    (artifact_dir / "model_card.json").write_text(json.dumps(card), encoding="utf-8")
    return card


def _moses_artifact(tmp_path: Path, metrics: dict | None = None) -> dict:
    d = tmp_path / "smt"; d.mkdir(exist_ok=True)
    (d / "moses.ini").write_text("[feature]\nPhraseDictionaryMemory path=phrase-table.gz\n", encoding="utf-8")
    with gzip.open(d / "phrase-table.gz", "wt", encoding="utf-8") as fh:
        fh.write("בראשית ||| in the beginning ||| 0.5 0.5 0.5 0.5\n")
    (d / "lm.binary").write_bytes(b"fake-lm-for-tests")
    (d / "vocabulary.source.txt").write_text("בראשית\n", encoding="utf-8")
    files = [{"path": "moses.ini", "role": "config"},
             {"path": "phrase-table.gz", "role": "phrase_table"},
             {"path": "lm.binary", "role": "language_model"},
             {"path": "vocabulary.source.txt", "role": "vocabulary_source"}]
    card = _write_card(d, "moses", files, metrics)
    return {"id": "moses-biblical-hebrew-en", "kind": "translation", "engine": "moses",
            "language_profile": "biblical_hebrew", "status": "provisioned",
            "path": str(d), "checksum": card["artifact_sha256"], "version": "moses-test-1"}


def _marian_artifact(tmp_path: Path, metrics: dict | None = None) -> dict:
    d = tmp_path / "nmt"; d.mkdir(exist_ok=True)
    (d / "model.npz").write_bytes(b"fake-checkpoint-for-tests")
    (d / "decoder-config.yml").write_text("models:\n  - model.npz\n", encoding="utf-8")
    (d / "vocab.spm").write_bytes(b"fake-spm-for-tests")
    (d / "vocabulary.source.txt").write_text("בראשית\n", encoding="utf-8")
    files = [{"path": "model.npz", "role": "checkpoint"},
             {"path": "decoder-config.yml", "role": "decoder_config"},
             {"path": "vocab.spm", "role": "vocabulary"},
             {"path": "vocabulary.source.txt", "role": "vocabulary_source"}]
    card = _write_card(d, "marian", files, metrics)
    return {"id": "marian-biblical-hebrew-en", "kind": "translation", "engine": "marian",
            "language_profile": "biblical_hebrew", "status": "provisioned",
            "path": str(d), "checksum": card["artifact_sha256"], "version": "marian-test-1"}


def _model_settings(tmp_path: Path, entries: list[dict], **overrides) -> Settings:
    from app.storage import db as store
    manifest = tmp_path / "models.json"
    manifest.write_text(json.dumps({"models": entries}), encoding="utf-8")
    base = Settings(storage_dir=tmp_path / "uploads", db_path=tmp_path / "test.db",
                    models_manifest=manifest, datasets_manifest=tmp_path / "datasets.json")
    store.migrate(base.db_path)  # direct service calls need the schema in place
    return replace(base, **overrides)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="shebang test doubles need POSIX")
def test_evaluated_engine_beats_unevaluated(tmp_path):
    moses = _moses_artifact(tmp_path)  # no metrics recorded
    marian = _marian_artifact(tmp_path, metrics={"chrf_pp": 20.0})
    s = _model_settings(tmp_path, [moses, marian],
                        moses_cmd=str(_fake_binary(tmp_path, "moses-double", "MOSES-OUT ")),
                        marian_decoder_cmd=str(_fake_binary(tmp_path, "marian-double", "MARIAN-OUT ")))
    result = translate("טקסט שלא נמצא בשום מקור", s, "biblical_hebrew")
    assert result["engine"] == "marian"
    assert result["unevaluated_model"] is False
    assert result["provenance"]["evaluation_state"] == "evaluated"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="shebang test doubles need POSIX")
def test_unevaluated_engine_is_flagged(tmp_path):
    moses = _moses_artifact(tmp_path)
    s = _model_settings(tmp_path, [moses],
                        moses_cmd=str(_fake_binary(tmp_path, "moses-double", "MOSES-OUT ")))
    result = translate("טקסט שלא נמצא בשום מקור", s, "biblical_hebrew")
    assert result["engine"] == "moses"
    assert result["unevaluated_model"] is True
    assert any("unevaluated_model" in w for w in result["warnings"])
    assert result["provenance"]["engine"] == "moses"
    assert result["provenance"]["dataset_card_sha256"] == "card-sha"


def test_variant_is_never_a_translation(corpus_client):
    gen = _sample()["Genesis 1:1"]
    variant = gen["source_text"].replace("אֱלֹהִים", "מַלְאָךְ")
    assert variant != gen["source_text"]
    r = corpus_client.post("/api/translate", json={"text": variant,
                                                   "source_language": "biblical_hebrew"})
    assert r.status_code == 503
    body = r.json()
    assert "english_translation" not in body
    if "variant_candidate" in body:
        assert body["variant_candidate"]["match_type"] == "normalized_variant"


# ---------- complete passages ----------

def test_passage_partial_status(corpus_settings):
    gen = _sample()["Genesis 1:1"]
    text = gen["source_text"] + "\n" + "משפט שאינו מופיע בשום מקור ידוע"
    result = translate_passage(text, corpus_settings, "biblical_hebrew")
    assert result["passage_status"] == "partial"
    assert result["segments"][0]["status"] == "translated"
    assert result["segments"][0]["english_translation"] == gen["english_text"]
    assert result["segments"][1]["status"] == "unavailable"
    assert result["segments"][1]["english_translation"] is None
    assert result["english_translation"].split("\n")[0] == gen["english_text"]


def test_passage_completed_status(corpus_settings):
    sample = _sample()
    text = sample["Genesis 1:1"]["source_text"] + "\n\n" + sample["Genesis 1:2"]["source_text"]
    result = translate_passage(text, corpus_settings, "biblical_hebrew")
    assert result["passage_status"] == "completed"
    assert len(result["segments"]) == 2


def test_passage_all_unavailable_is_failed_not_fabricated(corpus_settings):
    result = translate_passage("שורה אחת לא ידועה\nשורה שנייה לא ידועה",
                               corpus_settings, "biblical_hebrew")
    assert result["passage_status"] == "failed"
    assert result["english_translation"] is None
    assert all(s["english_translation"] is None for s in result["segments"])


def test_passage_limits_are_clear_errors(corpus_settings):
    s = replace(corpus_settings, max_segments=1)
    with pytest.raises(Exception) as exc:
        translate_passage("אחת\nשתיים", s, "biblical_hebrew")
    assert getattr(exc.value, "code", "") == "too_many_segments"


# ---------- script support matrix ----------

def test_scripts_endpoint_defaults_unsupported(client):
    r = client.get("/api/scripts")
    assert r.status_code == 200
    rows = {row["id"]: row for row in r.json()["scripts"]}
    for pid in ("paleo_hebrew", "imperial_aramaic",
                "jewish_babylonian_aramaic_script", "classical_syriac_estrangela"):
        assert rows[pid]["status"] == "unsupported"
        assert "evaluation record" in rows[pid]["reason"]


def test_script_support_requires_matching_evaluation_record(tmp_path, monkeypatch):
    # Test-local fabrication: a checkpoint file and an evaluation record
    # created inside this test only. Nothing shipped claims this support.
    ckpt = tmp_path / "model.mlmodel"
    ckpt.write_bytes(b"test-checkpoint-bytes")
    digest = hashlib.sha256(b"test-checkpoint-bytes").hexdigest()
    manifest = tmp_path / "models.json"
    manifest.write_text(json.dumps({"models": [
        {"id": "kraken-paleo-hebrew", "kind": "ocr", "engine": "kraken",
         "script_profile": "paleo_hebrew", "status": "provisioned",
         "path": str(ckpt), "version": "test"}]}), encoding="utf-8")
    s = Settings(storage_dir=tmp_path / "uploads", db_path=tmp_path / "t.db",
                 models_manifest=manifest, datasets_manifest=tmp_path / "d.json")
    benchmarks = tmp_path / "benchmarks"
    benchmarks.mkdir()
    monkeypatch.setattr(script_profiles, "BENCHMARKS_DIR", benchmarks)
    profile = next(p for p in script_profiles.load_registry() if p["id"] == "paleo_hebrew")
    row = script_profiles.profile_support(s, profile, False)
    assert row["status"] == "unsupported"  # no record yet
    (benchmarks / "htr-eval-paleo_hebrew.json").write_text(json.dumps(
        {"cer": 0.12, "wer": 0.3, "checkpoint_sha256": "0" * 64}), encoding="utf-8")
    row = script_profiles.profile_support(s, profile, False)
    assert row["status"] == "unsupported"  # hash does not match the file on disk
    (benchmarks / "htr-eval-paleo_hebrew.json").write_text(json.dumps(
        {"cer": 0.12, "wer": 0.3, "checkpoint_sha256": digest}), encoding="utf-8")
    row = script_profiles.profile_support(s, profile, False)
    assert row["status"] == "supported"
    assert row["engine"] == "kraken"
    assert row["evaluation"]["cer"] == 0.12


def test_ocr_historical_script_never_falls_back(client):
    up = client.post("/api/uploads", files={"file": ("p.png", png_bytes(), "image/png")}).json()
    r = client.post("/api/ocr", json={"upload_id": up["id"], "engine": "kraken",
                                      "script_profile": "paleo_hebrew"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "script_unsupported"
    r = client.post("/api/ocr", json={"upload_id": up["id"], "engine": "tesseract",
                                      "script_profile": "imperial_aramaic"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "script_unsupported"


def test_kraken_adapter_honest_paths(tmp_path, settings):
    st = kraken_adapter.status(settings)
    assert "available" in st and "checkpoints" in st
    missing = tmp_path / "nope.mlmodel"
    with pytest.raises(UnavailableError) as exc:
        kraken_adapter.recognize(tmp_path / "img.png", missing)
    assert exc.value.code in ("kraken_unavailable", "kraken_checkpoint_missing")


@pytest.mark.skipif(not kraken_adapter.is_available(), reason="kraken package not installed")
def test_kraken_adapter_incompatible_is_reported(tmp_path, monkeypatch):
    import importlib as _il
    real_import = _il.import_module
    def broken(name, *a, **kw):
        if name.startswith("kraken"):
            class _Empty:  # no documented callables at all
                pass
            return _Empty()
        return real_import(name, *a, **kw)
    monkeypatch.setattr(kraken_adapter.importlib, "import_module", broken)
    with pytest.raises(kraken_adapter.KrakenIncompatible):
        kraken_adapter._load_pipeline()


# ---------- cache + timings ----------

@pytest.mark.skipif(sys.platform.startswith("win"), reason="shebang test doubles need POSIX")
def test_translation_cache_labels_second_hit(tmp_path):
    counter = tmp_path / "counter.txt"
    moses = _moses_artifact(tmp_path)
    s = _model_settings(tmp_path, [moses],
                        moses_cmd=str(_fake_binary(tmp_path, "moses-double", "MOSES-OUT ",
                                                   counter=counter)))
    text = "טקסט שלא נמצא בשום מקור"
    first = translate(text, s, "biblical_hebrew")
    assert first["cached"] is False
    second = translate(text, s, "biblical_hebrew")
    assert second["cached"] is True
    assert second["provenance"]["cached"] is True
    assert second["provenance"]["engine"] == "moses"
    assert counter.read_text() == "x"  # the engine ran exactly once


def test_retrieval_is_never_served_from_translation_cache(corpus_settings):
    from app.storage import db as store
    gen = _sample()["Genesis 1:1"]
    for _ in range(2):
        result = translate(gen["source_text"], corpus_settings, "biblical_hebrew")
        assert result["translation_method"] == "verified_reference"
        assert result["cached"] is False
    conn = store.connect(corpus_settings.db_path)
    try:
        n = conn.execute("SELECT COUNT(*) c FROM translation_cache").fetchone()["c"]
    finally:
        conn.close()
    assert n == 0


def test_process_records_stage_timings(client):
    up = client.post("/api/uploads", files={"file": ("p.png", png_bytes(), "image/png")}).json()
    r = client.post("/api/process", json={"upload_id": up["id"]})
    assert r.status_code == 200
    assert "stage_timings_ms" in r.json()
    job = client.get(f"/api/jobs/{r.json()['job_id']}/result")
    assert "stage_timings_ms" in job.json()
