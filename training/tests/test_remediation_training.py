"""Regression tests for the training/evaluation remediation
(AHAIET-004/005/006/049/051). Code only — written for the developer
to run; nothing here was executed by the build assistant.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend"))

from training.evaluation import dictionary_baseline, evaluate_translation  # noqa: E402


def _passage(partition: str, source: str, words: list[dict], lang="biblical_hebrew"):
    return {"language": lang, "partition": partition, "source_text": source,
            "english_text": "english", "words": words}


def _word(surface: str, strongs: str):
    return {"surface": surface, "lemma": strongs, "strongs": strongs,
            "word_language": "hebrew"}


def test_dictionary_lexicon_train_only(tmp_path):
    # A word that appears ONLY in the test partition must be OOV for
    # the train-only baseline lexicon (AHAIET-004).
    corpus = tmp_path / "corpus.jsonl"
    rows = [
        _passage("train", "א ב", [_word("א", "1"), _word("ב", "2")]),
        _passage("test", "ג", [_word("ג", "3")]),
    ]
    corpus.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                      encoding="utf-8")
    lexicon = dictionary_baseline.load_lexicon_from_corpus(
        corpus, "biblical_hebrew", partitions={"train"})
    gloss, info = dictionary_baseline.gloss_text("ג", lexicon)
    assert info["known_tokens"] == 0
    assert gloss.startswith("⟦")


def test_zero_test_pairs_no_selection(tmp_path):
    # AHAIET-005: zero held-out pairs -> insufficient_test_data, no
    # scores, and write_selection refuses to write anything.
    from app.core.config import Settings
    settings = Settings(storage_dir=tmp_path / "up", db_path=tmp_path / "t.db",
                        models_manifest=tmp_path / "models.json")
    (tmp_path / "models.json").write_text(json.dumps({"models": []}), encoding="utf-8")
    report = evaluate_translation.evaluate(
        "biblical_hebrew", tmp_path / "prepared", tmp_path / "corpus.jsonl",
        tmp_path / "no.db", settings)
    assert report["status"] == "insufficient_test_data"
    assert all(e["status"] == "insufficient_test_data" for e in report["engines"].values())
    assert evaluate_translation.write_selection(report, settings) is None


def test_one_test_pair_no_selection(tmp_path):
    from app.core.config import Settings
    settings = Settings(storage_dir=tmp_path / "up", db_path=tmp_path / "t.db",
                        models_manifest=tmp_path / "models.json")
    (tmp_path / "models.json").write_text(json.dumps({"models": []}), encoding="utf-8")
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(json.dumps(_passage("test", "א", [_word("א", "1")]),
                                 ensure_ascii=False), encoding="utf-8")
    report = evaluate_translation.evaluate(
        "biblical_hebrew", tmp_path / "prepared", corpus, tmp_path / "no.db", settings)
    assert report["status"] == "insufficient_test_data"
    assert evaluate_translation.write_selection(report, settings) is None


def test_fallback_metric_is_chrf_not_chrf_pp():
    # AHAIET-006: the pure-Python fallback records chrf, never chrf_pp.
    out = evaluate_translation.score(["hello world"], ["hello world"], None)
    assert out["metric"] == "chrf" and "chrf" in out and "chrf_pp" not in out
    sig = evaluate_translation.metric_signature(None)
    assert "fallback" in sig


def _report_with_runs(moses_run_sha, marian_run_sha, tmp_path):
    from app.core.config import Settings
    settings = Settings(storage_dir=tmp_path / "up", db_path=tmp_path / "t.db",
                        models_manifest=tmp_path / "models.json")
    (tmp_path / "models.json").write_text(json.dumps({"models": [
        {"id": "moses-x", "kind": "translation", "engine": "moses",
         "language_profile": "biblical_hebrew", "status": "provisioned", "path": None},
        {"id": "marian-x", "kind": "translation", "engine": "marian",
         "language_profile": "biblical_hebrew", "status": "provisioned", "path": None},
    ]}), encoding="utf-8")
    report = {
        "run_id": "run-test", "profile": "biblical_hebrew", "status": "evaluated",
        "date": "2026-01-01", "metric_implementation": "sacrebleu-test",
        "test_pairs": 50, "test_set_sha256": "a" * 64, "metric_signature": "sig-1",
        "engines": {
            "moses": {"status": "evaluated",
                      "metrics": {"chrf_pp": 50.0, "sacrebleu": 10.0},
                      "evaluation_run": {"test_set_sha256": moses_run_sha,
                                         "metric_signature": "sig-1"}},
            "marian": {"status": "evaluated",
                       "metrics": {"chrf_pp": 60.0, "sacrebleu": 12.0},
                       "evaluation_run": {"test_set_sha256": marian_run_sha,
                                          "metric_signature": "sig-1"}},
        },
    }
    return settings, report


def test_selection_single_qualified_engine_labelled(tmp_path):
    # NEW-04 policy: Moses qualifies on this run's signature, Marian's
    # run used a DIFFERENT test set and does not qualify. The single
    # qualifying engine MAY be selected, but the record must say
    # selection_basis="single_evaluated_engine", comparable=False —
    # never a head-to-head claim.
    settings, report = _report_with_runs("a" * 64, "b" * 64, tmp_path)
    record = evaluate_translation.write_selection(report, settings)
    assert record is not None
    assert record["winner"] == "moses"
    assert record["selection_basis"] == "single_evaluated_engine"
    assert record["comparable"] is False
    manifest = json.loads((tmp_path / "models.json").read_text(encoding="utf-8"))
    winner = next(e for e in manifest["models"] if e["engine"] == "moses")
    assert winner["selection"]["selection_basis"] == "single_evaluated_engine"
    assert winner["selection"]["comparable"] is False


def test_selection_one_qualified_one_stale_competitor(tmp_path):
    # Follow-up case: one qualified engine + one competitor whose
    # recorded metrics are from an older run. The stale competitor's
    # metrics are archived as stale (NEW-14) and cannot win.
    settings, report = _report_with_runs("a" * 64, "b" * 64, tmp_path)
    manifest = json.loads((tmp_path / "models.json").read_text(encoding="utf-8"))
    marian = next(e for e in manifest["models"] if e["engine"] == "marian")
    marian["evaluation"] = {"chrf_pp": 99.0, "date": "2025-01-01",
                            "run": {"test_set_sha256": "b" * 64,
                                    "metric_signature": "sig-1"}}
    (tmp_path / "models.json").write_text(json.dumps(manifest), encoding="utf-8")
    record = evaluate_translation.write_selection(report, settings)
    assert record["winner"] == "moses"
    manifest = json.loads((tmp_path / "models.json").read_text(encoding="utf-8"))
    marian = next(e for e in manifest["models"] if e["engine"] == "marian")
    assert "evaluation" not in marian
    assert marian["metrics_history"][-1]["status"] == "stale"
    assert marian["metrics_history"][-1]["chrf_pp"] == 99.0


def test_selection_head_to_head_when_two_share_signature(tmp_path):
    # Follow-up case: two engines evaluated on the SAME split and
    # signature — a genuine head-to-head; the higher score wins and
    # the record says so.
    settings, report = _report_with_runs("a" * 64, "a" * 64, tmp_path)
    record = evaluate_translation.write_selection(report, settings)
    assert record is not None
    assert record["winner"] == "marian"  # 60.0 > 50.0 on the same run
    assert record["selection_basis"] == "head_to_head"
    assert record["comparable"] is True


def test_clean_corpus_misalignment_fails(tmp_path):
    # AHAIET-049: unequal source/target line counts are a hard failure,
    # never a silent zip truncation.
    from training.smt.train_smt import Logger, StepError, clean_corpus
    src = tmp_path / "a.src"
    tgt = tmp_path / "a.en"
    src.write_text("one\ntwo\nthree\n", encoding="utf-8")
    tgt.write_text("one\ntwo\n", encoding="utf-8")
    logger = Logger(tmp_path / "log.txt")
    try:
        with pytest.raises(StepError):
            clean_corpus(logger, src, tgt, tmp_path / "out")
    finally:
        logger.close()


def test_clean_corpus_counts_discards(tmp_path):
    from training.smt.train_smt import Logger, clean_corpus
    src = tmp_path / "a.src"
    tgt = tmp_path / "a.en"
    src.write_text("keep this line\n\n", encoding="utf-8")
    tgt.write_text("keep this line\n\n", encoding="utf-8")
    logger = Logger(tmp_path / "log.txt")
    try:
        kept = clean_corpus(logger, src, tgt, tmp_path / "out")
    finally:
        logger.close()
    assert kept == 1


def test_marian_checkpoint_selection_uses_best_evidence(tmp_path):
    # AHAIET-051: iterations 9, 10, 100 exist; lexical-last would pick
    # the wrong file. With model.npz.best present, it wins; without
    # any explicit evidence, selection fails loudly.
    from training.nmt.train_nmt import StepError, _select_checkpoint
    for name in ("model.iter9.npz", "model.iter10.npz", "model.iter100.npz"):
        (tmp_path / name).write_bytes(b"x")
    with pytest.raises(StepError):
        _select_checkpoint(tmp_path)
    best = tmp_path / "model.npz.best"
    best.write_bytes(b"x")
    (tmp_path / "model.npz").write_bytes(b"final")
    chosen, evidence = _select_checkpoint(tmp_path)
    assert "best" in evidence or chosen.name == "model.npz"


# ---------------------------------------------------------------------------
# Split integrity (NEW-01, NEW-02)
# ---------------------------------------------------------------------------

def _split_passage(lang, book, chapter, verse, partition, source):
    return {"language": lang, "book": book,
            "reference": f"{book} {chapter}:{verse}",
            "partition": partition, "source_text": source,
            "english_text": "english", "source_edition": "WLC",
            "translation_edition": "WEB", "license": "PD",
            "provenance": "test fixture"}


def test_group_integrity_mixed_language_daniel():
    # NEW-01: Daniel chapters 2 and 7 contain BOTH profiles with
    # different per-profile partitions. Keyed by (language, book,
    # chapter) the full corpus passes; the old (book, chapter) key
    # would have raised LeakageError.
    from training.datasets.prepare_parallel import check_group_integrity
    rows = [
        _split_passage("biblical_hebrew", "Daniel", 2, 1, "validation", "א"),
        _split_passage("biblical_aramaic", "Daniel", 2, 4, "validation", "ב"),
        _split_passage("biblical_hebrew", "Daniel", 7, 1, "validation", "ג"),
        _split_passage("biblical_aramaic", "Daniel", 7, 9, "test", "ד"),
        _split_passage("biblical_hebrew", "Ruth", 1, 1, "test", "ה"),
        _split_passage("biblical_aramaic", "Ezra", 4, 8, "train", "ו"),
    ]
    check_group_integrity(rows)  # must not raise


def test_group_integrity_still_catches_same_profile_span():
    # Chapter-level checks remain in force WITHIN a profile.
    from training.datasets.prepare_parallel import LeakageError, check_group_integrity
    rows = [
        _split_passage("biblical_hebrew", "Genesis", 1, 1, "train", "א"),
        _split_passage("biblical_hebrew", "Genesis", 1, 2, "validation", "ב"),
    ]
    with pytest.raises(LeakageError):
        check_group_integrity(rows)


def test_prepare_run_mixed_corpus_counts(tmp_path):
    # NEW-01/NEW-02 regression: prepare_parallel.run() over a mixed
    # corpus completes and reports the per-profile split counts.
    from training.datasets.prepare_parallel import run
    corpus = tmp_path / "corpus.jsonl"
    rows = [
        _split_passage("biblical_hebrew", "Genesis", 1, 1, "train", "א ב"),
        _split_passage("biblical_hebrew", "Genesis", 30, 1, "validation", "ג ד"),
        _split_passage("biblical_hebrew", "Ruth", 1, 1, "test", "ה ו"),
        _split_passage("biblical_aramaic", "Ezra", 4, 8, "train", "ז ח"),
        _split_passage("biblical_aramaic", "Daniel", 2, 4, "validation", "ט י"),
        _split_passage("biblical_aramaic", "Daniel", 3, 1, "test", "ך כ"),
    ]
    corpus.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                      encoding="utf-8")
    report = run(corpus, tmp_path / "prepared")
    assert report["profiles"]["biblical_hebrew"]["pairs_per_split"] == {
        "train": 1, "validation": 1, "test": 1}
    assert report["profiles"]["biblical_aramaic"]["pairs_per_split"] == {
        "train": 1, "validation": 1, "test": 1}
