"""Pure-Python fallback translation metrics.

Used ONLY when sacrebleu is not installed, and labelled as fallbacks in
every report they feed: the chrF here is the standard character n-gram
F-score (beta=2, up to 6-grams, no word-order component, so it is chrF,
not chrF++), and the BLEU is a plain modified-precision corpus BLEU
with brevity penalty (an approximation of SacreBLEU, not identical
tokenization). When sacrebleu is available the harness uses it and says
so; scores from the two implementations are never mixed in one table
without the implementation being named.
"""
from __future__ import annotations
import math
from collections import Counter


def _char_ngrams(text: str, n: int) -> Counter:
    return Counter(text[i:i + n] for i in range(len(text) - n + 1)) if len(text) >= n else Counter()


def chrf_sentence(hypothesis: str, reference: str, max_n: int = 6, beta: float = 2.0) -> float:
    """Sentence-level chrF (0..1) over whitespace-normalised strings."""
    hyp = " ".join((hypothesis or "").split())
    ref = " ".join((reference or "").split())
    if not hyp and not ref:
        return 1.0
    if not hyp or not ref:
        return 0.0
    precisions, recalls = [], []
    for n in range(1, max_n + 1):
        hyp_grams = _char_ngrams(hyp, n)
        ref_grams = _char_ngrams(ref, n)
        if not hyp_grams and not ref_grams:
            continue
        match = sum((hyp_grams & ref_grams).values())
        precisions.append(match / sum(hyp_grams.values()) if hyp_grams else 0.0)
        recalls.append(match / sum(ref_grams.values()) if ref_grams else 0.0)
    if not precisions:
        return 0.0
    p = sum(precisions) / len(precisions)
    r = sum(recalls) / len(recalls)
    if p == 0.0 or r == 0.0:
        return 0.0
    return (1 + beta ** 2) * p * r / (beta ** 2 * p + r)


def corpus_chrf(hypotheses: list[str], references: list[str]) -> float:
    """Corpus chrF as the mean of sentence chrF (fallback definition)."""
    if not hypotheses:
        return 0.0
    return sum(chrf_sentence(h, r) for h, r in zip(hypotheses, references)) / len(hypotheses)


def corpus_bleu(hypotheses: list[str], references: list[str], max_n: int = 4) -> float:
    """Plain corpus BLEU (0..1), whitespace tokenization, with BP."""
    matches = [0] * max_n
    totals = [0] * max_n
    hyp_len = ref_len = 0
    for hyp, ref in zip(hypotheses, references):
        h = (hyp or "").split()
        r = (ref or "").split()
        hyp_len += len(h)
        ref_len += len(r)
        for n in range(1, max_n + 1):
            hg = Counter(tuple(h[i:i + n]) for i in range(len(h) - n + 1)) if len(h) >= n else Counter()
            rg = Counter(tuple(r[i:i + n]) for i in range(len(r) - n + 1)) if len(r) >= n else Counter()
            totals[n - 1] += sum(hg.values())
            matches[n - 1] += sum((hg & rg).values())
    if hyp_len == 0:
        return 0.0
    precisions = []
    for i in range(max_n):
        if totals[i] == 0:
            precisions.append(0.0)
        else:
            precisions.append(matches[i] / totals[i])
    if min(precisions) == 0.0:
        # Smoothing: replace zero precisions with a small epsilon so the
        # geometric mean is defined (documented fallback behaviour).
        precisions = [p if p > 0 else 1e-9 for p in precisions]
    log_avg = sum(math.log(p) for p in precisions) / max_n
    bp = 1.0 if hyp_len > ref_len else math.exp(1 - ref_len / max(hyp_len, 1))
    return bp * math.exp(log_avg)
