"""Search normalization for Hebrew-script text.

Three representations are kept strictly separate:
- raw: the original string, never modified here (callers keep it).
- normalized: NFC, whitespace collapsed, punctuation spacing unified.
  Used for 'exact' corpus matching (diacritics still significant).
- normalized_nodiac: normalized with Hebrew combining marks (niqqud,
  cantillation, dagesh etc.) removed. Used only for 'normalized' matching
  and as a variant-detection key. It is a search key, never display text.
"""
from __future__ import annotations
import re
import unicodedata

# Hebrew combining marks: cantillation (0591-05BD etc.), niqqud, dagesh,
# shin/sin dots, meteg, maqaf is punctuation (05BE) and is kept as a char.
_DIACRITIC_RANGES = [(0x0591, 0x05BD), (0x05BF, 0x05C2), (0x05C4, 0x05C7), (0x05F3, 0x05F4)]
_PUNCT_SPACE = re.compile(r"\s*([:;,.!?])\s*")
_WS = re.compile(r"\s+")

def _is_diacritic(ch: str) -> bool:
    cp = ord(ch)
    return any(a <= cp <= b for a, b in _DIACRITIC_RANGES)

def normalize(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "")
    t = t.replace("׃", "׃")  # sof pasuq kept, spacing unified below
    t = _WS.sub(" ", t).strip()
    # Unify spacing around sof pasuq so OCR/copied variants compare equal.
    t = t.replace(" ׃", "׃")
    return t

def normalize_nodiac(text: str) -> str:
    t = normalize(text)
    t = "".join(ch for ch in t if not _is_diacritic(ch))
    # Final-letter forms are distinct consonants in pointed text keys;
    # fold them to regular forms only in the diacritic-insensitive key.
    fold = {"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"}
    t = "".join(fold.get(ch, ch) for ch in t)
    return _WS.sub(" ", t).strip()

def tokens(text: str) -> list[str]:
    return [tok for tok in normalize_nodiac(text).split(" ") if tok]
