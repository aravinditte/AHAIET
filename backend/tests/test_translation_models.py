"""Tests for trained-model artifact resolution, selection, and inference.

Written to be run by the developer (see docs/VERIFICATION.md). The
decoder binaries are replaced by tiny local test doubles: executable
Python scripts that echo a marked transformation of their stdin. They
are test fixtures for the subprocess contract — NOT models, and they
are never referenced by any manifest outside these tests. The
subprocess stand-in tests assume a POSIX environment (Linux/WSL2/macOS)
where a shebang script is directly executable.
"""
import gzip, hashlib, json, sys
from dataclasses import replace
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app
from app.services.translation import marian_adapter, model_artifacts, moses_adapter, selection

VOCAB_WORDS = ["בראשית", "אלהים", "את", "השמים"]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fake_binary(tmp_path: Path, name: str, prefix: str) -> Path:
    # NEW-05: genuinely executable double (shebang + chmod on POSIX,
    # .cmd wrapper on Windows) from the shared factory.
    from double_factory import echo_double
    return echo_double(tmp_path, name, prefix)["path"]


def _write_card(artifact_dir: Path, engine: str, profile: str, files: list[dict],
                metrics: dict | None = None) -> dict:
    primary = artifact_dir / ("moses.ini" if engine == "moses" else "model.npz")
    card = {"engine": engine, "language_profile": profile, "model_version": f"{engine}-test-1",
            "artifact_sha256": _sha(primary.read_bytes()), "primary_artifact": primary.name,
            "files": files, "dataset_card_sha256": None, "dataset_id": "parallel-test",
            "tool_versions": {}, "license": "test fixture", "provenance": "test fixture",
            "metrics": metrics}
    if metrics and metrics.get("chrf_pp") is not None:
        # NEW-14: a recorded score counts only with a valid run
        # record; fixtures that mean "evaluated" must carry one.
        card["evaluation_run"] = {
            "run_id": "test-fixture-run", "test_set_sha256": "cd" * 32,
            "sample_count": 50, "metric_signature": "sacrebleu-test:CHRF(word_order=2)+BLEU",
            "artifact_sha256": card["artifact_sha256"], "date": "2026-11-24"}
    (artifact_dir / "model_card.json").write_text(json.dumps(card), encoding="utf-8")
    return card


def make_moses_artifact(tmp_path: Path, *, with_lm: bool = True,
                        metrics: dict | None = None) -> tuple[Path, dict]:
    d = tmp_path / "smt"
    d.mkdir()
    (d / "moses.ini").write_text("[feature]\nPhraseDictionaryMemory path=phrase-table.gz\n", encoding="utf-8")
    with gzip.open(d / "phrase-table.gz", "wt", encoding="utf-8") as fh:
        fh.write("בראשית ||| in the beginning ||| 0.5 0.5 0.5 0.5\n")
        fh.write("אלהים ||| god ||| 0.5 0.5 0.5 0.5\n")
    files = [{"path": "moses.ini", "role": "config"},
             {"path": "phrase-table.gz", "role": "phrase_table"}]
    if with_lm:
        (d / "lm.binary").write_bytes(b"fake-lm-for-tests")
        files.append({"path": "lm.binary", "role": "language_model"})
    (d / "vocabulary.source.txt").write_text("\n".join(VOCAB_WORDS) + "\n", encoding="utf-8")
    files.append({"path": "vocabulary.source.txt", "role": "vocabulary_source"})
    card = _write_card(d, "moses", "biblical_hebrew", files, metrics)
    entry = {"id": "moses-biblical-hebrew-en", "kind": "translation", "engine": "moses",
             "language_profile": "biblical_hebrew", "status": "provisioned",
             "path": str(d), "checksum": card["artifact_sha256"], "version": "moses-test-1"}
    return d, entry


def make_marian_artifact(tmp_path: Path, *, with_vocab: bool = True,
                         metrics: dict | None = None) -> tuple[Path, dict]:
    d = tmp_path / "nmt"
    d.mkdir()
    (d / "model.npz").write_bytes(b"fake-checkpoint-for-tests")
    (d / "decoder-config.yml").write_text("models:\n  - model.npz\n", encoding="utf-8")
    files = [{"path": "model.npz", "role": "checkpoint"},
             {"path": "decoder-config.yml", "role": "decoder_config"}]
    if with_vocab:
        (d / "vocab.spm").write_bytes(b"fake-spm-for-tests")
        files.append({"path": "vocab.spm", "role": "vocabulary"})
    (d / "vocabulary.source.txt").write_text("\n".join(VOCAB_WORDS) + "\n", encoding="utf-8")
    files.append({"path": "vocabulary.source.txt", "role": "vocabulary_source"})
    card = _write_card(d, "marian", "biblical_hebrew", files, metrics)
    entry = {"id": "marian-biblical-hebrew-en", "kind": "translation", "engine": "marian",
             "language_profile": "biblical_hebrew", "status": "provisioned",
             "path": str(d), "checksum": card["artifact_sha256"], "version": "marian-test-1"}
    return d, entry


def _settings(tmp_path: Path, entries: list[dict], **overrides) -> Settings:
    manifest = tmp_path / "models.json"
    manifest.write_text(json.dumps({"models": entries}), encoding="utf-8")
    base = Settings(storage_dir=tmp_path / "uploads", db_path=tmp_path / "test.db",
                    models_manifest=manifest,
                    datasets_manifest=tmp_path / "datasets.json")
    return replace(base, **overrides)


# ---------- artifact resolution ----------

def test_moses_artifact_complete_resolves(tmp_path):
    _, entry = make_moses_artifact(tmp_path)
    res = model_artifacts.resolve_entry(entry)
    assert res.ok and res.missing == []
    assert res.evaluation_state == "trained_but_not_evaluated"
    assert res.model_version == "moses-test-1" and res.artifact_sha256

def test_moses_artifact_missing_lm_is_listed(tmp_path):
    _, entry = make_moses_artifact(tmp_path, with_lm=False)
    res = model_artifacts.resolve_entry(entry)
    assert not res.ok
    assert any("language model" in m for m in res.missing)

def test_marian_artifact_missing_vocab_is_listed(tmp_path):
    _, entry = make_marian_artifact(tmp_path, with_vocab=False)
    res = model_artifacts.resolve_entry(entry)
    assert not res.ok
    assert any("vocabulary" in m for m in res.missing)

def test_not_provisioned_entry_never_resolves(tmp_path):
    _, entry = make_moses_artifact(tmp_path)
    entry = {**entry, "status": "not_provisioned", "path": None}
    res = model_artifacts.resolve_entry(entry)
    assert not res.ok and res.evaluation_state == "not_provisioned"

def test_evaluated_state_from_recorded_metrics(tmp_path):
    _, entry = make_moses_artifact(tmp_path, metrics={"chrf_pp": 21.5})
    res = model_artifacts.resolve_entry(entry)
    assert res.ok and res.evaluation_state == "evaluated" and res.chrf_pp == 21.5

# ---------- selection ----------

def test_selection_defaults_to_smt_without_metrics(tmp_path):
    _, moses_entry = make_moses_artifact(tmp_path)
    _, marian_entry = make_marian_artifact(tmp_path)
    s = _settings(tmp_path, [moses_entry, marian_entry])
    chosen = selection.select_engine(s, "biblical_hebrew")
    assert chosen is not None and chosen.engine == "moses"

def test_selection_prefers_higher_recorded_chrf(tmp_path):
    _, moses_entry = make_moses_artifact(tmp_path, metrics={"chrf_pp": 18.0})
    _, marian_entry = make_marian_artifact(tmp_path, metrics={"chrf_pp": 24.5})
    s = _settings(tmp_path, [moses_entry, marian_entry])
    chosen = selection.select_engine(s, "biblical_hebrew")
    assert chosen is not None and chosen.engine == "marian"

def test_selection_is_per_profile(tmp_path):
    _, moses_entry = make_moses_artifact(tmp_path)
    s = _settings(tmp_path, [moses_entry])
    assert selection.select_engine(s, "biblical_hebrew") is not None
    assert selection.select_engine(s, "biblical_aramaic") is None

# ---------- inference through the test-double binaries ----------

def test_moses_run_and_oov_coverage(tmp_path):
    _, entry = make_moses_artifact(tmp_path)
    fake = _fake_binary(tmp_path, "fake-moses", "MOSES-OUT ")
    s = _settings(tmp_path, [entry], moses_cmd=str(fake))
    result = moses_adapter.run(entry, "בראשית אלהים מלך", s)
    assert result["english_translation"].startswith("MOSES-OUT")
    assert result["engine"] == "moses" and result["model_version"] == "moses-test-1"
    cov = result["coverage"]
    assert cov["source_tokens"] == 3 and cov["known_tokens"] == 2
    assert cov["oov_words"] == ["מלך"]
    assert any("Out-of-vocabulary" in w for w in result["warnings"])

def test_marian_run(tmp_path):
    _, entry = make_marian_artifact(tmp_path)
    fake = _fake_binary(tmp_path, "fake-marian-decoder", "MARIAN-OUT ")
    s = _settings(tmp_path, [entry], marian_decoder_cmd=str(fake))
    result = marian_adapter.run(entry, "בראשית אלהים", s)
    assert result["english_translation"].startswith("MARIAN-OUT")
    assert result["coverage"]["coverage_ratio"] == 1.0

def test_missing_binary_is_honest_unavailable(tmp_path):
    _, entry = make_moses_artifact(tmp_path)
    s = _settings(tmp_path, [entry], moses_cmd=str(tmp_path / "no-such-binary"))
    with pytest.raises(Exception) as exc:
        moses_adapter.run(entry, "בראשית", s)
    assert getattr(exc.value, "code", "") == "moses_unavailable"

# ---------- end-to-end through the API ----------

def test_translate_endpoint_uses_trained_model(tmp_path):
    _, entry = make_moses_artifact(tmp_path)
    fake = _fake_binary(tmp_path, "fake-moses", "MOSES-OUT ")
    s = _settings(tmp_path, [entry], moses_cmd=str(fake))
    client = TestClient(create_app(s), raise_server_exceptions=False)
    r = client.post("/api/translate", json={"text": "בראשית מלך", "source_language": "biblical_hebrew"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["engine"] == "moses" and body["translation_method"] == "moses"
    assert body["english_translation"].startswith("MOSES-OUT")
    assert body["model_version"] == "moses-test-1"
    assert body["artifact_sha256"] == entry["checksum"]
    assert body["coverage"]["oov_words"] == ["מלך"]
    assert any("Out-of-vocabulary" in w for w in body["warnings"])
    caps = client.get("/api/capabilities").json()
    assert caps["translation"]["per_profile"]["biblical_hebrew"]["engine"] == "moses"
    assert caps["translation"]["per_profile"]["biblical_aramaic"]["status"] == "unavailable"
    models = client.get("/api/models").json()["models"]
    m = [x for x in models if x["id"] == "moses-biblical-hebrew-en"][0]
    assert m["artifact_state"] == "trained_but_not_evaluated" and m["ok"] is True
