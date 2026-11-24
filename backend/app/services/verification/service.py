"""Deterministic candidate verification + retrieval provenance checks.

Two distinct jobs live here:

1. verify_reference(match): the original rule-based provenance gate —
   a retrieval match may be presented as a verified reference only if
   it carries a passage identity, both edition names, a licence, and
   provenance. Variant candidates never verify.

2. verify_candidate(...): deterministic checks comparing a candidate
   English translation against its source text, using the imported
   corpus word index and morphology data as evidence. The checks FLAG
   RISKS — suspicious omissions, additions, number/negation/name
   mismatches, low corpus-evidenced coverage. They cannot and do not
   establish semantic correctness: the report's overall status is one
   of no_issues_found | warnings | high_risk, never "correct".

   Uncertainty information comes only from measured sources assembled
   by the caller (OCR engine confidence, retrieval match type, metrics
   a real evaluation run recorded on a model card). No probability of
   correctness is computed anywhere in this module.
"""
from __future__ import annotations
import re
from pathlib import Path

from app.services.language.normalize import normalize_nodiac
from app.services.language.numbers import ENGLISH_NUMBER_WORDS, lookup as number_lookup
from app.services.language.tokenize import tokenize_source, tokenize_target
from app.storage import db as store

# ---------------------------------------------------------------------------
# Retrieval provenance gate (unchanged behaviour)
# ---------------------------------------------------------------------------

def verify_reference(match: dict | None) -> dict:
    if not match:
        return {"verified": False, "checks": {"match_present": False}}
    checks = {
        "match_present": True,
        "match_type_verified": match.get("match_type") in ("exact", "normalized"),
        "has_reference": bool(match.get("reference")),
        "has_source_edition": bool(match.get("source_edition")),
        "has_translation_edition": bool(match.get("translation_edition")),
        "has_license": bool(match.get("license")),
        "has_provenance": bool(match.get("provenance")),
        "has_english_text": bool(match.get("english_text")),
    }
    return {"verified": all(checks.values()), "checks": checks}


def status() -> dict:
    return {"status": "available",
            "reason": "Reference verification is rule-based over retrieval provenance fields (no model required). "
                      "Candidate verification runs deterministic checks over the corpus word index when one is imported."}


# ---------------------------------------------------------------------------
# Candidate verification
# ---------------------------------------------------------------------------

_WORD_LANG = {"biblical_hebrew": "hebrew", "biblical_aramaic": "aramaic"}

# English function words excluded from content-word evidence. Content
# words are the only tokens used for coverage/agreement evidence, so a
# candidate cannot "cover" a source word merely by containing 'the'.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at",
    "by", "for", "with", "from", "as", "is", "was", "were", "are", "be",
    "been", "it", "its", "he", "she", "they", "them", "his", "her",
    "their", "him", "you", "your", "we", "our", "i", "my", "that",
    "this", "these", "those", "there", "here", "not", "no", "will",
    "shall", "let", "who", "whom", "which", "when", "where", "into",
    "over", "under", "upon", "out", "up", "down", "then", "so",
}

# Negation particles, in diacritic-insensitive key form. Hebrew:
# lo (לֹא), al (אַל, prohibitive), ein (אֵין, 'there is not').
# Aramaic: la (לָא), lah (לָהּ). The Aramaic form לה also occurs as a
# prepositional suffix; the check compares counts only and reports a
# mismatch as a risk flag for human review, which is the safe failure
# mode for that ambiguity.
_NEGATION = {
    "biblical_hebrew": {"לא", "אל", "אין"},
    "biblical_aramaic": {"לא", "לה"},
}
_CANDIDATE_NEGATION_RE = re.compile(r"\b(not|no|never|none|nothing|without)\b|n't\b", re.IGNORECASE)

# Expected candidate/source token-length band. English renderings of
# Biblical Hebrew/Aramaic are analytic (articles, auxiliaries, explicit
# subjects), so a faithful candidate is usually somewhat longer than
# the source; far outside this band is an omission/addition risk flag
# only — the band is a documented heuristic, not a quality threshold.
_LENGTH_BAND = (0.6, 2.4)

_PUNCT_TOKENS = {"׃", "׀", ".", ",", ";", ":", "!", "?", "(", ")", "[", "]", "{", "}", '"'}


def _content_words(english: str) -> set[str]:
    return {tok.lower() for tok in tokenize_target(english)
            if tok.lower() not in _STOPWORDS and any(ch.isalpha() for ch in tok)}


def _parse_morph(morph_code: str) -> list[dict]:
    """Parse an OSHB/morphhb morph code into segment dicts.

    Format (as stored in corpus_words.morph_code): a leading language
    char (H/A) on the first segment, segments separated by '/'. Each
    segment is a part-of-speech code possibly followed by grammatical
    features, e.g. 'Ncfsa' (noun, common, feminine, singular, absolute),
    'Np' (proper noun), 'Vqp3ms' (verb, qal, perfect, 3rd masc sing),
    'Td' (definite article), 'To' (object marker), 'C' (conjunction).
    Only the features the checks actually use are extracted.
    """
    segments: list[dict] = []
    for i, raw in enumerate((morph_code or "").split("/")):
        seg = raw
        if i == 0 and seg[:1] in ("H", "A"):
            seg = seg[1:]
        if not seg:
            continue
        info: dict = {"raw": seg, "pos": seg[0]}
        if seg.startswith("Np"):
            info["pos"] = "N"
            info["proper"] = True
        elif seg[0] == "N" and len(seg) >= 5:
            info.update({"noun_type": seg[1], "gender": seg[2],
                         "number": seg[3], "state": seg[4]})
        elif seg[0] == "V":
            m = re.match(r"V[a-z][a-z](\d)([fm])([sp])", seg)
            if m:
                info.update({"person": m.group(1), "gender": m.group(2),
                             "number": m.group(3)})
        segments.append(info)
    return segments


class _CorpusEvidence:
    """Per-token corpus/morphology evidence for one profile, loaded once
    per verification call. All queries stay inside the selected profile
    and the matching word-language rows (Hebrew data is never used as
    evidence for Aramaic text or vice versa)."""

    def __init__(self, db_path: Path, profile: str):
        self.profile = profile
        self.word_lang = _WORD_LANG[profile]
        self.conn = store.connect(db_path)
        self._entries_cache: dict[str, list[dict]] = {}
        self._lemma_english_cache: dict[str, set[str]] = {}
        self._lemma_capitalized_cache: dict[str, set[str]] = {}

    def close(self) -> None:
        self.conn.close()

    def entries_for(self, nodiac_token: str) -> list[dict]:
        if nodiac_token not in self._entries_cache:
            rows = self.conn.execute(
                "SELECT cw.surface, cw.lemma, cw.strongs, cw.morph_code, cw.passage_id "
                "FROM corpus_words cw WHERE cw.language_profile=? AND cw.word_language=? "
                "AND cw.surface_nodiac=? LIMIT 25",
                (self.profile, self.word_lang, nodiac_token)).fetchall()
            self._entries_cache[nodiac_token] = [dict(r) for r in rows]
        return self._entries_cache[nodiac_token]

    def _english_for_lemma(self, lemma: str, extract) -> set[str]:
        rows = self.conn.execute(
            "SELECT rp.english_text FROM corpus_words cw "
            "JOIN reference_passages rp ON rp.id = cw.passage_id "
            "WHERE cw.language_profile=? AND cw.lemma=? LIMIT 40",
            (self.profile, lemma)).fetchall()
        out: set[str] = set()
        for row in rows:
            out |= extract(row["english_text"])
        return out

    def lemma_content_words(self, lemma: str) -> set[str]:
        if lemma not in self._lemma_english_cache:
            self._lemma_english_cache[lemma] = self._english_for_lemma(lemma, _content_words)
        return self._lemma_english_cache[lemma]

    def lemma_capitalized_renderings(self, lemma: str) -> set[str]:
        """Capitalised non-sentence-initial English tokens attested in
        aligned verses containing this lemma — corpus evidence for how
        a proper noun is rendered, not a guess."""
        if lemma not in self._lemma_capitalized_cache:
            def caps(text: str) -> set[str]:
                found: set[str] = set()
                for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
                    words = sentence.split()
                    for word in words[1:]:
                        clean = word.strip(",;:()\"'")
                        if clean[:1].isupper() and any(ch.isalpha() for ch in clean):
                            found.add(clean)
                return found
            self._lemma_capitalized_cache[lemma] = self._english_for_lemma(lemma, caps)
        return self._lemma_capitalized_cache[lemma]


def _check(name: str, status: str, detail: str, evidence: dict | None = None) -> dict:
    return {"name": name, "status": status, "detail": detail, "evidence": evidence or {}}


def verify_candidate(db_path: Path, source_text: str, candidate: str,
                     language_profile: str, method: str | None = None,
                     context: dict | None = None) -> dict:
    """Run the deterministic checks. `context` may carry measured inputs
    only: ocr_mean_confidence (float), retrieval_match_type (str),
    reference_english (str, a verified edition text for the same source
    obtained independently of the candidate), model_metrics (dict of
    harness-recorded scores)."""
    context = context or {}
    checks: list[dict] = []
    source_tokens = [t for t in tokenize_source(source_text) if t not in _PUNCT_TOKENS]
    candidate_tokens = tokenize_target(candidate)
    candidate_content = _content_words(candidate)
    nodiac_tokens = [normalize_nodiac(t) for t in source_tokens]

    from app.services import morphology
    corpus_ok = language_profile in _WORD_LANG and morphology.corpus_available(db_path)
    evidence = _CorpusEvidence(db_path, language_profile) if corpus_ok else None

    # --- per-token corpus evidence -------------------------------------
    uncovered: list[str] = []
    no_evidence: list[str] = []
    proper_nouns: list[tuple[str, list[dict]]] = []
    construct_nouns: list[str] = []
    article_tokens: list[str] = []
    if evidence is not None:
        for surface, key in zip(source_tokens, nodiac_tokens):
            entries = evidence.entries_for(key)
            if not entries:
                no_evidence.append(surface)
                uncovered.append(surface)
                continue
            lemmas = {e["lemma"] for e in entries if e["lemma"]}
            words: set[str] = set()
            for lemma in lemmas:
                words |= evidence.lemma_content_words(lemma)
            if not (words & candidate_content):
                uncovered.append(surface)
            for entry in entries:
                for seg in _parse_morph(entry["morph_code"]):
                    if seg.get("proper"):
                        proper_nouns.append((surface, entries))
                    if seg.get("pos") == "N" and seg.get("state") == "c":
                        construct_nouns.append(surface)
                    if seg["raw"].startswith("Td"):
                        article_tokens.append(surface)

    # --- source coverage ------------------------------------------------
    if evidence is None:
        checks.append(_check("source_coverage", "not_applicable",
                             "No corpus word index is imported for this profile, so no corpus-evidenced "
                             "coverage can be computed. Nothing was estimated.",
                             {"reason": "corpus_unavailable"}))
    elif not source_tokens:
        checks.append(_check("source_coverage", "not_applicable",
                             "The source text has no analysable tokens.", {}))
    else:
        covered = len(source_tokens) - len(uncovered)
        ratio = covered / len(source_tokens)
        cov_status = "pass" if ratio >= 0.6 else ("warn" if ratio > 0 else "fail")
        checks.append(_check(
            "source_coverage", cov_status,
            f"{covered}/{len(source_tokens)} source tokens have corpus-lemma English evidence "
            f"appearing in the candidate (ratio {ratio:.2f}). Uncovered tokens are listed as "
            "evidence; a low ratio is an omission risk flag, not proof of error.",
            {"source_tokens": len(source_tokens), "covered_tokens": covered,
             "coverage_ratio": round(ratio, 4), "uncovered_tokens": uncovered,
             "tokens_without_corpus_evidence": no_evidence}))

    # --- omission / addition risk (length heuristics + coverage) --------
    if not source_tokens or not candidate_tokens:
        checks.append(_check("omission_risk", "not_applicable", "Empty source or candidate.", {}))
        checks.append(_check("addition_risk", "not_applicable", "Empty source or candidate.", {}))
    else:
        ratio_len = len(candidate_tokens) / len(source_tokens)
        lo, hi = _LENGTH_BAND
        omission_warn = ratio_len < lo or (evidence is not None and source_tokens
                                           and len(uncovered) / len(source_tokens) > 0.5)
        checks.append(_check(
            "omission_risk", "warn" if omission_warn else "pass",
            (f"Candidate/source token ratio is {ratio_len:.2f} (heuristic band {lo}–{hi}); "
             f"{len(uncovered)} source token(s) lack corpus-evidenced coverage."
             if omission_warn else
             f"Candidate/source token ratio is {ratio_len:.2f}, inside the heuristic band {lo}–{hi}."),
            {"length_ratio": round(ratio_len, 3), "band": [lo, hi],
             "uncovered_ratio": round(len(uncovered) / len(source_tokens), 3) if source_tokens else None}))
        addition_warn = ratio_len > hi
        checks.append(_check(
            "addition_risk", "warn" if addition_warn else "pass",
            (f"Candidate/source token ratio is {ratio_len:.2f}, above the heuristic band {lo}–{hi}; "
             "long additions relative to the source are an unsupported-addition risk flag."
             if addition_warn else
             f"Candidate/source token ratio is {ratio_len:.2f}, inside the heuristic band {lo}–{hi}."),
            {"length_ratio": round(ratio_len, 3), "band": [lo, hi]}))

    # --- named entities --------------------------------------------------
    if evidence is None:
        checks.append(_check("named_entities", "not_applicable",
                             "No corpus morphology data is available to identify proper nouns.", {}))
    elif not proper_nouns:
        checks.append(_check("named_entities", "not_applicable",
                             "No source token is tagged as a proper noun in the corpus morphology data.", {}))
    else:
        candidate_capitalized = {w.strip(",;:()\"'") for w in candidate.split()
                                 if w.strip(",;:()\"'")[:1].isupper()}
        missing = []
        seen: set[str] = set()
        for surface, entries in proper_nouns:
            if surface in seen:
                continue
            seen.add(surface)
            renderings: set[str] = set()
            for lemma in {e["lemma"] for e in entries if e["lemma"]}:
                renderings |= evidence.lemma_capitalized_renderings(lemma)
            if renderings and not (renderings & candidate_capitalized):
                missing.append({"source": surface, "attested_renderings": sorted(renderings)[:5]})
            elif not renderings and not candidate_capitalized:
                missing.append({"source": surface, "attested_renderings": []})
        checks.append(_check(
            "named_entities", "warn" if missing else "pass",
            ("Proper noun(s) without a capitalised or corpus-attested rendering in the candidate: "
             + ", ".join(m["source"] for m in missing)) if missing else
            "Every corpus-tagged proper noun has a capitalised/attested rendering in the candidate.",
            {"proper_nouns_checked": len(seen), "missing": missing}))

    # --- numbers ----------------------------------------------------------
    source_numbers: list[dict] = []
    for surface, key in zip(source_tokens, nodiac_tokens):
        entry = number_lookup(language_profile, key) if language_profile in _WORD_LANG else None
        if entry:
            source_numbers.append({"source": surface, "value": entry["value"]})
        elif re.fullmatch(r"\d+", surface):
            source_numbers.append({"source": surface, "value": int(surface)})
    candidate_numbers: list[int] = []
    for tok in candidate_tokens:
        low = tok.lower().strip(",.;:")
        if low in ENGLISH_NUMBER_WORDS:
            candidate_numbers.append(ENGLISH_NUMBER_WORDS[low])
        elif re.fullmatch(r"\d+", tok):
            candidate_numbers.append(int(tok))
    if not source_numbers and not candidate_numbers:
        checks.append(_check("numbers", "pass",
                             "No number expressions were detected in the source or the candidate.", {}))
    else:
        from collections import Counter
        src_counts, cand_counts = Counter(n["value"] for n in source_numbers), Counter(candidate_numbers)
        missing_vals = sorted((src_counts - cand_counts).elements())
        extra_vals = sorted((cand_counts - src_counts).elements())
        checks.append(_check(
            "numbers", "warn" if (missing_vals or extra_vals) else "pass",
            (f"Number value(s) in the source but not the candidate: {missing_vals}; "
             f"in the candidate but not the source: {extra_vals}.") if (missing_vals or extra_vals) else
            "Number values in the source and candidate agree.",
            {"source_numbers": source_numbers, "candidate_numbers": candidate_numbers,
             "missing_values": missing_vals, "extra_values": extra_vals}))

    # --- negation ---------------------------------------------------------
    neg_forms = _NEGATION.get(language_profile, set())
    source_neg = sum(1 for key in nodiac_tokens if key in neg_forms)
    candidate_neg = len(_CANDIDATE_NEGATION_RE.findall(candidate or ""))
    if not neg_forms:
        checks.append(_check("negation", "not_applicable",
                             f"No negation particle list is defined for profile '{language_profile}'.", {}))
    elif source_neg == 0 and candidate_neg == 0:
        checks.append(_check("negation", "pass", "No negation detected in the source or the candidate.",
                             {"source_negations": 0, "candidate_negations": 0}))
    else:
        checks.append(_check(
            "negation", "pass" if source_neg == candidate_neg else "warn",
            f"Source negation particle count ({source_neg}) vs candidate negation marker count "
            f"({candidate_neg})" + (" agree." if source_neg == candidate_neg else
            " differ — a possible dropped or added negation; human review advised."),
            {"source_negations": source_neg, "candidate_negations": candidate_neg}))

    # --- grammar observations (morphology-backed only) --------------------
    if evidence is None:
        checks.append(_check("grammar_construct_state", "not_applicable",
                             "No corpus morphology data is available.", {}))
        checks.append(_check("grammar_definite_article", "not_applicable",
                             "No corpus morphology data is available.", {}))
    else:
        checks.append(_check(
            "grammar_construct_state",
            "pass" if construct_nouns else "not_applicable",
            ("Source contains construct-state noun(s): " + ", ".join(sorted(set(construct_nouns)))
             + ". Recorded as evidence only: English construct renderings (typically 'of'-phrases) "
               "cannot be verified deterministically.") if construct_nouns else
            "No construct-state nouns were identified in the corpus morphology data for this source.",
            {"construct_state_nouns": sorted(set(construct_nouns))}))
        checks.append(_check(
            "grammar_definite_article",
            "pass" if article_tokens else "not_applicable",
            ("Source contains definite-article form(s) on: " + ", ".join(sorted(set(article_tokens)))
             + ". Recorded as evidence only.") if article_tokens else
            "No definite-article forms were identified in the corpus morphology data for this source.",
            {"article_tokens": sorted(set(article_tokens))}))
    checks.append(_check("grammar_tense_aspect", "not_applicable",
                         "Deterministic checks over morphology codes cannot establish tense/aspect "
                         "equivalence between the source and an English candidate; no claim is made.", {}))

    # --- reference agreement ----------------------------------------------
    reference_english = context.get("reference_english")
    if not reference_english:
        checks.append(_check("reference_agreement", "not_applicable",
                             "No independently verified reference text for this source was supplied, "
                             "so no agreement comparison was run.", {}))
    elif (candidate or "").strip() == reference_english.strip():
        checks.append(_check("reference_agreement", "pass",
                             "The candidate is the verified reference text itself; agreement is exact "
                             "by identity and adds no independent evidence.",
                             {"token_overlap": 1.0}))
    else:
        ref_words, cand_words = _content_words(reference_english), candidate_content
        overlap = (len(ref_words & cand_words) / len(ref_words | cand_words)) if (ref_words | cand_words) else 0.0
        checks.append(_check(
            "reference_agreement", "pass" if overlap >= 0.6 else "warn",
            f"Content-word overlap with the verified reference is {overlap:.2f}"
            + ("." if overlap >= 0.6 else
               " — the candidate diverges from the verified reference; this is a review flag, "
               "never an automatic rejection (a reference is one trustworthy rendering, not the only one)."),
            {"token_overlap": round(overlap, 3)}))

    if evidence is not None:
        evidence.close()

    # --- empirical uncertainty (measured inputs only) ----------------------
    uncertainty: dict = {"note": "Only measured inputs are reported; no probability of correctness is computed."}
    if context.get("ocr_mean_confidence") is not None:
        uncertainty["ocr_mean_confidence"] = context["ocr_mean_confidence"]
        uncertainty["ocr_mean_confidence_source"] = "OCR engine word confidences for the source text"
    if context.get("retrieval_match_type"):
        uncertainty["retrieval_match_type"] = context["retrieval_match_type"]
    if context.get("model_metrics"):
        uncertainty["model_metrics"] = context["model_metrics"]
        uncertainty["model_metrics_source"] = "Metrics recorded on the model card by a real evaluation run"

    statuses = {c["status"] for c in checks}
    overall = "high_risk" if "fail" in statuses else ("warnings" if "warn" in statuses else "no_issues_found")
    return {"overall_status": overall, "checks": checks,
            "empirical_uncertainty": uncertainty,
            "note": "Deterministic checks flag risks (omissions, additions, number/negation/name "
                    "mismatches). They cannot prove semantic correctness."}
