"""Character/word error rates via Levenshtein distance.

These functions only compute; they assert nothing about quality. Scores
exist only when someone actually runs them against real OCR output and
real ground truth — see training/evaluation/evaluate_ocr.py.
"""
from __future__ import annotations

def levenshtein(a: list, b: list) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (0 if ca == cb else 1)))
        prev = cur
    return prev[-1]

def cer(reference: str, hypothesis: str) -> float:
    """Character error rate over Unicode code points of the raw strings."""
    ref = list(reference)
    if not ref:
        return 0.0 if not hypothesis else 1.0
    return levenshtein(ref, list(hypothesis)) / len(ref)

def wer(reference: str, hypothesis: str) -> float:
    """Word error rate over whitespace-separated tokens."""
    ref = reference.split()
    if not ref:
        return 0.0 if not hypothesis.split() else 1.0
    return levenshtein(ref, hypothesis.split()) / len(ref)

def evaluate(reference: str, hypothesis: str) -> dict:
    return {"cer": round(cer(reference, hypothesis), 4),
            "wer": round(wer(reference, hypothesis), 4),
            "reference_chars": len(reference), "hypothesis_chars": len(hypothesis),
            "reference_words": len(reference.split()), "hypothesis_words": len(hypothesis.split())}
