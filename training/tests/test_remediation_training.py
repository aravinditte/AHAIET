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


def test_selection_requires_comparable_runs(tmp_path):
    # Two evaluated engines whose runs used DIFFERENT test sets:
    # selection must refuse rather than compare unlike scores.
    from app.core.config import Settings
    settings = Settings(storage_dir=tmp_path / "up", db_path=tmp_path / "t.db",
                        models_manifest=tmp_path / "models.json")
    (tmp_path / "models.json").write_text(json.dumps({"models": []}), encoding="utf-8")
    report = {
        "profile": "biblical_hebrew", "status": "evaluated", "date": "2026-01-01",
        "test_pairs": 50, "test_set_sha256": "a" * 64, "metric_signature": "sig-1",
        "engines": {
            "moses": {"status": "evaluated", "metrics": {"chrf_pp": 50.0},
                      "evaluation_run": {"test_set_sha256": "a" * 64,
                                         "metric_signature": "sig-1"}},
            "marian": {"status": "evaluated", "metrics": {"chrf_pp": 60.0},
                       "evaluation_run": {"test_set_sha256": "b" * 64,
                                          "metric_signature": "sig-1"}},
        },
    }
    assert evaluate_translation.write_selection(report, settings) is None


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
