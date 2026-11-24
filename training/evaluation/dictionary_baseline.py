"""Dictionary/rule baseline for the translation evaluation harness.

LABEL (used everywhere this baseline appears, including reports):
    "dictionary_gloss_baseline — not a sentence translation"

What it does: each source word is looked up in the corpus word index
(the morphhb annotations carried by the canonical corpus JSONL) for the
SAME language profile, and replaced by its lemma/Strong's gloss
identifier — e.g. a word whose morphhb lemma is Strong's 430 is glossed
"H430". Unknown words are passed through unchanged, wrapped in ⟦ ⟧ so
they are visibly unglossed. Word order is the source order; no grammar,
no reordering, no function words are supplied.

Why the gloss is an identifier, not English: the imported morphhb data
provides lemmas and Strong's numbers but no English gloss strings, and
inventing a gloss dictionary would violate the project's truthfulness
rules. This baseline therefore measures the floor that pure lexical
lookup provides — its metric scores are expected to be very low, and
that is the honest result. It must never be presented as a translation
of a sentence, in the UI or anywhere else.
"""
from __future__ import annotations
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services.language.normalize import normalize_nodiac  # noqa: E402
from app.services.language.tokenize import tokenize_source  # noqa: E402

LABEL = "dictionary_gloss_baseline — not a sentence translation"
_WORD_LANG = {"biblical_hebrew": "hebrew", "biblical_aramaic": "aramaic"}


def _gloss_of(lemma: str, strongs: str) -> str:
    """Render one word's gloss from its morphhb lemma/Strong's data."""
    if strongs:
        return f"H{strongs}" if strongs.isdigit() else strongs
    lemma = (lemma or "").strip()
    if not lemma:
        return ""
    token = lemma.split()[0]
    if "/" in token:
        token = token.split("/")[-1]
    token = re.sub(r"\s*[a-z]$", "", token)
    return f"H{token}" if token.isdigit() else token


def build_lexicon(passages: list[dict], language_profile: str) -> dict[str, str]:
    """surface (diacritic-insensitive) -> gloss, from one profile's data only."""
    word_lang = _WORD_LANG[language_profile]
    counts: dict[str, Counter] = {}
    for p in passages:
        if p.get("language") != language_profile:
            continue
        for w in p.get("words", []):
            if w.get("word_language") != word_lang:
                continue
            gloss = _gloss_of(w.get("lemma", ""), w.get("strongs", ""))
            if not gloss:
                continue
            key = normalize_nodiac(w.get("surface", ""))
            if key:
                counts.setdefault(key, Counter())[gloss] += 1
    return {key: counter.most_common(1)[0][0] for key, counter in counts.items()}


def load_lexicon_from_corpus(corpus_path: Path, language_profile: str,
                             partitions: set[str] | None = None) -> dict[str, str]:
    """Build the lexicon from corpus rows. When `partitions` is given,
    only rows in those partitions contribute — the evaluation harness
    passes {"train"} so held-out test vocabulary can never leak into
    the baseline (AHAIET-004)."""
    passages = [json.loads(line) for line in Path(corpus_path).read_text(encoding="utf-8").splitlines()
                if line.strip()]
    if partitions is not None:
        passages = [p for p in passages if p.get("partition") in partitions]
    return build_lexicon(passages, language_profile)


def gloss_text(text: str, lexicon: dict[str, str]) -> tuple[str, dict]:
    """Gloss one source text. Returns (gloss, coverage-info)."""
    tokens = tokenize_source(text)
    out: list[str] = []
    hits = 0
    for tok in tokens:
        gloss = lexicon.get(normalize_nodiac(tok))
        if gloss:
            out.append(gloss)
            hits += 1
        else:
            out.append(f"⟦{tok}⟧")
    info = {"source_tokens": len(tokens), "known_tokens": hits,
            "coverage_ratio": round(hits / len(tokens), 4) if tokens else 1.0,
            "oov_words": sorted({tok for tok in tokens
                                 if normalize_nodiac(tok) not in lexicon})}
    return " ".join(out), info
