"""Whitespace/punctuation tokenization shared by training and runtime.

This is the single canonical tokenizer for the project: the dataset
preparation code (training/datasets/tokenize.py) re-exports these
functions, and the backend translation adapters use them at inference
time, so a trained model always sees the same token stream it was
trained on.

Rules (documented, deliberately simple and reversible enough):
- Hebrew source: the maqqef (U+05BE) is a word joiner in the corpus text
  but the corpus word index stores maqqef-joined words separately, so
  tokenization splits at the maqqef and drops the character itself.
- Punctuation characters become separate tokens. Combining marks
  (niqqud, cantillation, dagesh) are NEVER stripped here — the vocalized
  view is the canonical training/inference view. The consonantal view
  is produced separately via normalize_nodiac and is a distinct,
  labelled training view only.
- English target: punctuation becomes separate tokens, except an
  apostrophe between two letters (don't, God's) stays inside the word.
- Detokenization of English output rejoins punctuation to the preceding
  token and restores capital spacing for sentence punctuation.
"""
from __future__ import annotations
import re

MAQQEF = "־"
# Sof pasuq, paseq, and common ASCII/Latin punctuation.
_PUNCT = set("׃׀.,;:!?()[]{}\"'«»“”‘’")
_PUNCT_RE = re.compile(r"([׃׀\.,;:!\?\(\)\[\]\{\}<>\"«»“”‘’])")
_WS = re.compile(r"\s+")

def _split_punct(text: str) -> list[str]:
    spaced = _PUNCT_RE.sub(r" \1 ", text or "")
    return [tok for tok in _WS.sub(" ", spaced).strip().split(" ") if tok]

def tokenize_source(text: str) -> list[str]:
    """Tokenize Hebrew-script source text (vocalized view; marks kept)."""
    t = (text or "").replace(MAQQEF, " ")
    return _split_punct(t)

def tokenize_target(text: str) -> list[str]:
    """Tokenize English target text; apostrophes inside words are kept."""
    out: list[str] = []
    for tok in _split_punct(text or ""):
        out.append(tok)
    # Rejoin apostrophes that sit between letters (split out above as the
    # ASCII apostrophe is not in the punctuation class, but the curly
    # apostrophe is; normalise curly to straight first for stability).
    joined: list[str] = []
    for tok in out:
        if tok in ("'", "’") and joined and joined[-1][-1:].isalpha():
            joined[-1] = joined[-1] + "'"
        elif joined and joined[-1].endswith("'") and tok[:1].isalpha():
            joined[-1] = joined[-1] + tok
        else:
            joined.append(tok.replace("’", "'"))
    return joined

def detokenize_target(text: str) -> str:
    """Best-effort detokenization of model output on the English side."""
    t = text or ""
    t = re.sub(r"\s+([.,;:!?%])", r"\1", t)
    t = re.sub(r"([\(\[\{])\s+", r"\1", t)
    t = re.sub(r"\s+([\)\]\}])", r"\1", t)
    t = re.sub(r"\s+([\"“”])\s+", r' \1', t)  # quotes: conservative, keep spacing simple
    t = re.sub(r"\s+'\s*(s|t|re|ve|ll|d|m)\b", r"'\1", t)
    t = _WS.sub(" ", t).strip()
    return t

def tokenize_source_line(text: str) -> str:
    return " ".join(tokenize_source(text))

def tokenize_target_line(text: str) -> str:
    return " ".join(tokenize_target(text))
