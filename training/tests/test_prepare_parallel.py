"""Tests for the parallel-corpus preparation step.

Written to be run by the developer (see docs/VERIFICATION.md):
  python -m pytest training/tests -q     (from the repository root)

Uses the committed six-passage fixture plus synthetic rows built inside
the tests themselves. No network, no trained models involved.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "training" / "datasets"))
sys.path.insert(0, str(REPO))

import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location("prepare_parallel", REPO / "training" / "datasets" / "prepare_parallel.py")
prep = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(prep)

FIXTURE = REPO / "training" / "datasets" / "fixtures" / "sample_passages.jsonl"


def _fixture_rows() -> list[dict]:
    return [json.loads(l) for l in FIXTURE.read_text(encoding="utf-8").splitlines() if l.strip()]


def _row(reference: str, book: str, language: str, partition: str,
         source: str, english: str) -> dict:
    return {"id": f"test-{reference}", "language": language, "dialect": "biblical",
            "script": "Hebrew", "period": "biblical", "source_text": source,
            "english_text": english, "book": book, "reference": reference,
            "source_edition": "test edition", "translation_edition": "test English",
            "license": "test", "provenance": "synthetic test row", "partition": partition,
            "words": []}


def test_group_split_integrity_holds_for_fixture():
    prep.check_group_integrity(_fixture_rows())  # must not raise


def test_group_spanning_splits_is_rejected():
    rows = [_row("Genesis 1:1", "Genesis", "biblical_hebrew", "train", "א ב", "a b"),
            _row("Genesis 1:2", "Genesis", "biblical_hebrew", "test", "ג ד", "c d")]
    with pytest.raises(prep.LeakageError):
        prep.check_group_integrity(rows)


def test_planted_cross_split_duplicate_is_caught():
    rows = {"train": [_row("Genesis 1:1", "Genesis", "biblical_hebrew", "train",
                           "בְּרֵאשִׁית בָּרָא", "In the beginning")],
            "test": [_row("Daniel 1:1", "Daniel", "biblical_hebrew", "test",
                          "בְּרֵאשִׁית בָּרָא", "In the beginning")],
            "validation": []}
    with pytest.raises(prep.LeakageError):
        prep.check_leakage(rows)


def test_planted_nodiac_duplicate_is_caught():
    # Same verse with the pointing removed in the other split.
    rows = {"train": [_row("Genesis 1:1", "Genesis", "biblical_hebrew", "train",
                           "בְּרֵאשִׁית בָּרָא", "In the beginning")],
            "test": [_row("Daniel 1:1", "Daniel", "biblical_hebrew", "test",
                          "בראשית ברא", "In the beginning")],
            "validation": []}
    with pytest.raises(prep.LeakageError):
        prep.check_leakage(rows)


def test_empty_english_excluded_and_counted(tmp_path):
    rows = _fixture_rows() + [
        _row("Genesis 2:1", "Genesis", "biblical_hebrew", "train", "וַיְכֻלּוּ הַשָּׁמַיִם", "")]
    card = prep.prepare_profile("biblical_hebrew", rows, tmp_path / "hebrew")
    assert card["corpus"]["excluded_empty_english"] == 1
    assert card["corpus"]["excluded_empty_english_references"] == ["Genesis 2:1"]
    train_lines = (tmp_path / "hebrew" / "train.source.vocalized.txt").read_text(encoding="utf-8").splitlines()
    assert len(train_lines) == card["splits"]["train"]["pairs"] == 3


def test_views_vocalized_keeps_and_consonantal_strips_diacritics(tmp_path):
    card = prep.prepare_profile("biblical_hebrew", _fixture_rows(), tmp_path / "hebrew")
    vocalized = (tmp_path / "hebrew" / "train.source.vocalized.txt").read_text(encoding="utf-8")
    consonantal = (tmp_path / "hebrew" / "train.source.consonantal.txt").read_text(encoding="utf-8")
    assert "ְ" in vocalized          # shewa present in the canonical view
    assert "ְ" not in consonantal   # and stripped in the consonantal view
    assert card["splits"]["train"]["pairs"] == 3


def test_aramaic_card_states_small_corpus(tmp_path):
    card = prep.prepare_profile("biblical_aramaic", _fixture_rows(), tmp_path / "aramaic")
    assert card["splits"]["train"]["pairs"] == 0
    assert card["splits"]["test"]["pairs"] == 3
    assert card["small_corpus"]["is_small"] is True
    assert "not expected" in card["small_corpus"]["statement"]


def test_dataset_card_records_checksums_and_strategy(tmp_path):
    out = tmp_path / "hebrew"
    card = prep.prepare_profile("biblical_hebrew", _fixture_rows(), out)
    entry = card["splits"]["train"]["files"]["train.source.vocalized.txt"]
    data = (out / "train.source.vocalized.txt").read_bytes()
    import hashlib
    assert entry["sha256"] == hashlib.sha256(data).hexdigest()
    assert "Genesis" in card["split_strategy"] or "train" in card["split_strategy"]
    assert (out / "leakage_report.json").exists()
    assert (out / "test.references.jsonl").exists()
