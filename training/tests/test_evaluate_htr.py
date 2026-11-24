"""Tests for the Kraken HTR evaluation aggregation and data collection.

Written to be run by the developer (see docs/VERIFICATION.md):
  python -m pytest training/tests -q     (from the repository root)

Uses tiny synthetic line pairs created inside the tests. No Kraken
installation and no real checkpoint are involved: only the pure
score-aggregation and directory-collection functions are exercised.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO))

import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location("evaluate_htr", REPO / "training" / "evaluation" / "evaluate_htr.py")
htr = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(htr)


def test_scores_identical_text_is_zero():
    scores = htr.compute_htr_scores([("אבג דה", "אבג דה")])
    assert scores["cer"] == 0.0 and scores["wer"] == 0.0
    assert scores["lines"] == 1


def test_scores_known_values():
    # One character substitution in a 3-char reference -> CER 1/3.
    scores = htr.compute_htr_scores([("abc", "abd")])
    assert scores["cer"] == round(1 / 3, 4)
    # One word deleted from a 3-word reference -> WER 1/3.
    scores = htr.compute_htr_scores([("a b c", "a b")])
    assert scores["wer"] == round(1 / 3, 4)


def test_scores_aggregate_by_total_length():
    # Micro-average: distances and lengths are summed before dividing.
    scores = htr.compute_htr_scores([("ab", "ab"), ("abcd", "abce")])
    assert scores["reference_chars"] == 6
    assert scores["cer"] == round(1 / 6, 4)


def test_collect_pairs_and_problems(tmp_path):
    (tmp_path / "line1.png").write_bytes(b"not-a-real-png-but-collection-only-checks-names")
    (tmp_path / "line1.txt").write_text("transcription", encoding="utf-8")
    (tmp_path / "line2.png").write_bytes(b"orphan")
    pairs, problems = htr.collect_test_pairs(tmp_path)
    assert len(pairs) == 1 and pairs[0][1] == "transcription"
    assert any("line2" in p for p in problems)


def test_collect_pairs_missing_dir(tmp_path):
    pairs, problems = htr.collect_test_pairs(tmp_path / "nope")
    assert pairs == [] and problems
