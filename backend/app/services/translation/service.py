"""Translation resolution with reference-first routing.

Strict routing order (per language profile, independently):
1. Verified reference retrieval: if the (corrected) source text matches
   an imported corpus passage in the selected profile — exactly or by
   the diacritic-insensitive key — that edition's English is returned
   with translation_method='verified_reference' and full provenance.
   A normalized_variant candidate is NEVER returned as the translation;
   it is only reported, with its warning, in the candidates channel.
2. A trained local model whose model card carries evaluation metrics
   recorded by the shared evaluation harness (evaluated beats
   unevaluated; among evaluated engines the higher recorded chrF++
   wins — see services/translation/selection.py).
3. A trained local model without recorded metrics. The response is
   flagged unevaluated_model=True with a warning, so unevaluated output
   is never presented as measured quality.
4. Otherwise an honest unavailable error. The message distinguishes the
   two no-match cases: corpus present but no match, vs no corpus at all,
   and names any provisioned-but-incomplete artifacts with their missing
   pieces.

Every successful result carries:
- provenance: engine, model id/version, artifact hash, dataset-card
  reference, and the retrieval citation when a corpus match produced
  the text;
- a deterministic verification report (services/verification) that
  flags risks against the source — it never claims correctness;
- stage timings measured on this machine.

Trained-model results are cached in SQLite (storage/cache.py), keyed
by profile + normalized source + engine + artifact hash. Verified
retrieval always runs live and is never served from that cache; cache
hits are labelled cached=True with the original engine provenance.

No paraphrase or dictionary gloss is ever substituted.
"""
from __future__ import annotations
import copy
import json
import threading
import time
from pathlib import Path
from app.core.config import Settings
from app.core.errors import AppError, UnavailableError, ValidationAppError
from app.core.timing import StageTimer
from app.services import retrieval
from app.services.language.passage import reassemble, split_segments
from app.storage import cache as translation_cache
from . import model_artifacts, selection

PROFILES = ["biblical_hebrew", "biblical_aramaic"]


class ProfileChoiceRequired(AppError):
    """AHAIET-036: no profile was selected and the evidence does not
    single out one profile, so the caller must choose explicitly. The
    structured response lists the candidate profiles and the evidence
    per profile; no profile is tried first-success."""

    def __init__(self, candidates: list[str], evidence: dict):
        super().__init__(422, "profile_choice_required",
                         "The language profile is ambiguous for this text and no profile "
                         "was selected, so no translation was attempted. Select one of "
                         "the candidate profiles explicitly.",
                         "Script alone cannot distinguish the Hebrew-script profiles; "
                         "the per-profile evidence is listed in the response.")
        self.candidates = candidates
        self.evidence = evidence


class AmbiguousMatchError(UnavailableError):
    """AHAIET-001/002: the text matches multiple passage identities (or
    a diacritic-insensitive key spanning differing vocalized forms), so
    no translation is certified as verified. The candidate list is
    attached for the caller to present."""

    def __init__(self, candidates: list[dict], profile: str):
        super().__init__("ambiguous_match",
                         "This text matches more than one stored passage identity, so no "
                         "single verified reference translation can be certified for it. "
                         "The candidates are listed; none was chosen silently.",
                         f"Ambiguous in profile {profile}: "
                         + ", ".join(c.get("reference", "?") for c in candidates))
        self.status_code = 422
        self.candidates = candidates


# Global concurrency bound for trained-model inference (AHAIET-033):
# one semaphore per configured limit value.
_translation_semaphores: dict[int, threading.BoundedSemaphore] = {}
_translation_semaphores_lock = threading.Lock()


def _translation_semaphore(settings: Settings) -> threading.BoundedSemaphore:
    limit = max(1, settings.max_concurrent_translation)
    with _translation_semaphores_lock:
        sem = _translation_semaphores.get(limit)
        if sem is None:
            sem = threading.BoundedSemaphore(limit)
            _translation_semaphores[limit] = sem
        return sem


def _remaining(deadline: float | None, settings: Settings) -> float:
    """Seconds of job budget left, capped by the per-call timeout."""
    cap = settings.translation_timeout_s
    if deadline is None:
        return cap
    left = deadline - time.monotonic()
    if left <= 0:
        raise AppError(504, "job_deadline_exceeded",
                       "The per-job total deadline was exceeded, so the request stopped "
                       "instead of running unbounded segment work.",
                       f"job_deadline_s={settings.job_deadline_s}")
    return min(cap, left)

def load_models_manifest(settings: Settings) -> dict:
    p: Path = settings.models_manifest
    if not p.exists():
        return {"models": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"models": []}

def provisioned_models(settings: Settings, language: str | None = None) -> list[dict]:
    """Manifest translation entries whose artifacts resolve complete."""
    out = []
    for profile in ([language] if language else PROFILES):
        for entry in selection.translation_entries(settings, profile):
            if model_artifacts.resolve_entry(entry).ok:
                out.append(entry)
    return out

def _incomplete_notes(settings: Settings, profiles: list[str]) -> list[str]:
    notes = []
    for profile in profiles:
        for entry in selection.translation_entries(settings, profile):
            resolution = model_artifacts.resolve_entry(entry)
            if not resolution.ok and resolution.evaluation_state != "not_provisioned":
                notes.append(f"{entry.get('id')}: missing " + "; ".join(resolution.missing))
    return notes


def _model_metrics(resolution) -> dict | None:
    """Harness-recorded metrics for the empirical-uncertainty section:
    the model card's metrics dict when a real evaluation run wrote one,
    otherwise the recorded chrF++ alone. None when nothing is recorded."""
    card = resolution.card or {}
    metrics = card.get("metrics")
    if isinstance(metrics, dict) and metrics:
        return metrics
    if resolution.chrf_pp is not None:
        return {"chrf_pp": resolution.chrf_pp}
    return None


def _attach_verification(result: dict, text: str, settings: Settings,
                         timer: StageTimer, context: dict | None = None) -> None:
    from app.services.verification.service import verify_candidate
    profile = result.get("matched_language") or (context or {}).get("language")
    vctx = dict(context or {})
    if result.get("translation_method") == "verified_reference":
        refs = result.get("source_references") or []
        if refs:
            vctx["retrieval_match_type"] = refs[0].get("match_type")
        # reference_agreement stays not_applicable for the reference
        # itself: the candidate IS the reference, so no independent
        # comparison exists.
    else:
        metrics = result.get("_model_metrics")
        if metrics:
            vctx["model_metrics"] = metrics
    with timer.stage("verification"):
        result["verification"] = verify_candidate(
            settings.db_path, text, result["english_translation"],
            profile or "biblical_hebrew", result.get("translation_method"), vctx)
    result.pop("_model_metrics", None)


def _finalize_model_result(chosen, result: dict, profile: str, text: str,
                           settings: Settings, extra_warnings: list[str]) -> dict:
    unevaluated = chosen.evaluation_state != "evaluated"
    warnings = list(extra_warnings) + list(result.get("warnings", []))
    if unevaluated:
        warnings.append(
            "This translation was produced by a trained model with no evaluation metrics "
            "recorded by the shared evaluation harness (unevaluated_model). Its quality has "
            "not been measured; review it against the source before relying on it.")
    provenance = {
        "engine": chosen.engine,
        "model_id": chosen.entry.get("id"),
        "model_version": chosen.model_version,
        "artifact_sha256": chosen.artifact_sha256,
        "evaluation_state": chosen.evaluation_state,
        "dataset_card_sha256": (chosen.card or {}).get("dataset_card_sha256"),
        "retrieval_citation": None,
        "cached": False,
    }
    result.update({
        "translation_method": chosen.engine,
        "model": {**chosen.entry, "model_version": chosen.model_version,
                  "artifact_sha256": chosen.artifact_sha256,
                  "evaluation_state": chosen.evaluation_state},
        "source_references": [],
        "matched_language": profile,
        "variant_candidate": None,
        "warnings": warnings,
        "unevaluated_model": unevaluated,
        "cached": False,
        "provenance": provenance,
        "_model_metrics": _model_metrics(chosen),
    })
    key = translation_cache.cache_key(profile, text, chosen.engine,
                                      chosen.artifact_sha256)
    translation_cache.put(settings, key, profile, chosen.engine,
                          chosen.artifact_sha256,
                          {k: v for k, v in result.items() if k != "_model_metrics"})
    return result


def _raise_for_attempts(attempts: list[dict]) -> None:
    """NEW-10: when engines existed but every attempt failed, the
    final categorized error is preserved — never a fall-through to
    'no trained model'. All-timeout -> 504 translation_timeout;
    all-unavailable -> the last 503; mixed -> the most severe
    categorized error (timeout > other AppError > unavailable), with
    per-engine attempt records attached for provenance."""
    def severity(a: dict) -> int:
        if a["status"] == 504 or a["code"] == "translation_timeout":
            return 3
        if a["status"] != 503:
            return 2
        return 1
    detail = "Engines attempted: " + " | ".join(
        f"{a['engine']} ({a['profile']}): {a['code']} — {a['message']}" for a in attempts)
    if all(a["status"] == 504 or a["code"] == "translation_timeout" for a in attempts):
        err = AppError(504, "translation_timeout",
                       "Every provisioned translation engine timed out, so no "
                       "translation was produced. A trained model IS provisioned; "
                       "the failure is decoder timeout, not absence.",
                       detail)
        err.attempts = attempts  # type: ignore[attr-defined]
        raise err
    worst = max(attempts, key=severity)
    if worst["status"] == 503:
        err = UnavailableError(worst["code"], worst["message"], detail)
    else:
        err = AppError(worst["status"], worst["code"], worst["message"], detail)
    err.attempts = attempts  # type: ignore[attr-defined]
    raise err


def _run_selected(text: str, settings: Settings, profiles: list[str],
                  deadline: float | None = None) -> dict | None:
    """Try the ordered trained engines per profile (AHAIET-020).

    For each profile, EVERY complete engine is tried in selection
    order within that same profile; each failure is recorded as a
    warning with provenance on the eventual result (or in the final
    error). Profiles are never crossed silently: with an explicit
    profile only that profile is tried; without one, the profile
    order is the documented PROFILES order and the matched profile is
    reported on the result. Results are served from / stored to the
    translation cache — consulted only here, never for retrieval.

    Returns None ONLY when no complete engine exists in any tried
    profile. When engines existed but all failed, the categorized
    error is raised (NEW-10)."""
    from .moses_adapter import run as run_moses_engine
    from .marian_adapter import run as run_marian_engine
    failures: list[str] = []
    attempts: list[dict] = []
    for profile in profiles:
        for chosen in selection.select_engines(settings, profile):
            key = translation_cache.cache_key(profile, text, chosen.engine,
                                              chosen.artifact_sha256)
            cached = translation_cache.get(settings, key)
            if cached is not None:
                result = copy.deepcopy(cached)
                result["cached"] = True
                if isinstance(result.get("provenance"), dict):
                    result["provenance"]["cached"] = True
                if failures:
                    result.setdefault("warnings", []).extend(failures)
                return result
            runner = run_marian_engine if chosen.engine == "marian" else run_moses_engine
            try:
                with _translation_semaphore(settings):
                    result = runner(chosen.entry, text, settings,
                                    timeout_s=_remaining(deadline, settings))
            except (UnavailableError, AppError) as e:
                # e.g. artifact complete but the decoder binary is
                # absent/broken, empty output, or a timeout: record it
                # and fall through to the next engine IN THIS PROFILE.
                failures.append(
                    f"Engine {chosen.engine} for {profile} failed ({e.code}: {e.message})")
                attempts.append({"engine": chosen.engine, "profile": profile,
                                 "code": e.code, "status": e.status_code,
                                 "message": e.message})
                continue
            return _finalize_model_result(chosen, result, profile, text, settings, failures)
    if attempts:
        _raise_for_attempts(attempts)
    return None


def _run_selected_batch(texts: list[str], settings: Settings, profile: str,
                        deadline: float | None = None) -> list[dict] | None:
    """Batch counterpart of _run_selected for one profile
    (AHAIET-035): one decoder invocation for the whole segment batch
    per engine, engines tried in selection order within the profile.
    Returns one finalized result per input text, or None when no
    engine in the profile exists. When engines existed but all
    failed, the categorized error is raised (NEW-10)."""
    from .moses_adapter import run_batch as run_moses_batch
    from .marian_adapter import run_batch as run_marian_batch
    failures: list[str] = []
    attempts: list[dict] = []
    for chosen in selection.select_engines(settings, profile):
        runner = run_marian_batch if chosen.engine == "marian" else run_moses_batch
        try:
            with _translation_semaphore(settings):
                results = runner(chosen.entry, texts, settings,
                                 timeout_s=_remaining(deadline, settings))
        except (UnavailableError, AppError) as e:
            failures.append(
                f"Engine {chosen.engine} for {profile} failed ({e.code}: {e.message})")
            attempts.append({"engine": chosen.engine, "profile": profile,
                             "code": e.code, "status": e.status_code,
                             "message": e.message})
            continue
        return [_finalize_model_result(chosen, result, profile, text, settings, failures)
                for result, text in zip(results, texts)]
    if attempts:
        _raise_for_attempts(attempts)
    return None


def translate(text: str, settings: Settings, language: str | None = None,
              context: dict | None = None) -> dict:
    if not text or not text.strip():
        raise ValidationAppError("empty_text", "Source text is empty; there is nothing to translate.")
    timer = StageTimer()
    profiles = [language] if language else PROFILES
    variant = None
    ambiguous: tuple[str, list[dict]] | None = None
    matches: list[tuple[str, dict]] = []
    evidence: dict[str, dict] = {}
    with timer.stage("retrieval"):
        for profile in profiles:
            result = retrieval.lookup(settings.db_path, text, profile)
            evidence[profile] = {
                "verified_match": result["match"] is not None,
                "ambiguous_candidates": len(result.get("candidates") or []),
                "variant_candidate": result["variant_candidate"] is not None,
            }
            if result["match"] is not None:
                matches.append((profile, result["match"]))
            if ambiguous is None and result.get("candidates"):
                ambiguous = (profile, result["candidates"])
            if variant is None and result["variant_candidate"] is not None:
                variant = result["variant_candidate"]
    # AHAIET-036: with no selected profile, evidence must single out
    # one profile. Matches in multiple profiles -> explicit choice.
    if language is None and len(matches) > 1:
        raise ProfileChoiceRequired([p for p, _ in matches], evidence)
    # NEW-08: a verified match in one profile does NOT settle the
    # profile when another profile holds an ambiguous candidate set
    # for the same text — credible cross-profile evidence of either
    # kind (verified OR ambiguous) requires an explicit choice. Only
    # clean single-profile evidence proceeds.
    if language is None and matches and ambiguous is not None \
            and ambiguous[0] != matches[0][0]:
        raise ProfileChoiceRequired(
            sorted({matches[0][0], ambiguous[0]}), evidence)
    if matches:
        profile, match = matches[0]
        out = {"english_translation": match["english_text"],
               "translation_method": "verified_reference",
               "engine": "verified_reference",
               "model": {"id": "corpus-reference", "match_type": match["match_type"]},
               "model_version": None, "artifact_sha256": None,
               "evaluation_state": None, "coverage": None, "warnings": [],
               "source_references": [match],
               "matched_language": profile,
               "variant_candidate": None,
               "unevaluated_model": False, "cached": False,
               "text_match": True, "passage_identity_verified": True,
               "candidates": [],
               "profile_evidence": {"basis": "user_selection" if language else
                                    "unique_verified_match", "profiles": evidence},
               "provenance": {
                   "engine": "verified_reference",
                   "model_id": "corpus-reference",
                   "model_version": None, "artifact_sha256": None,
                   "evaluation_state": None, "dataset_card_sha256": None,
                   "retrieval_citation": {
                       "passage_id": match["passage_id"],
                       "reference": match["reference"],
                       "match_type": match["match_type"],
                       "source_edition": match["source_edition"],
                       "translation_edition": match["translation_edition"],
                       "license": match["license"],
                       "provenance": match["provenance"]},
                   "cached": False}}
        _attach_verification(out, text, settings, timer, context)
        out["stage_timings_ms"] = timer.as_dict()
        return out
    # AHAIET-001/002: an ambiguous key match certifies nothing. When a
    # profile was selected, or the ambiguity is the only evidence,
    # surface the candidates instead of any translation.
    if ambiguous is not None:
        profile, candidates = ambiguous
        if language is not None or len(profiles) == 1 or \
                not any(evidence[p]["verified_match"] for p in evidence):
            raise AmbiguousMatchError(candidates, profile)
    if language is None:
        # No retrieval evidence singles out a profile. If trained
        # models exist for more than one profile, the choice is the
        # user's; if exactly one profile has a model, that is the
        # evidence used and it is stated on the result.
        model_profiles = [p for p in PROFILES if provisioned_models(settings, p)]
        if len(model_profiles) > 1:
            raise ProfileChoiceRequired(model_profiles, evidence)
        if len(model_profiles) == 1:
            profiles = model_profiles
    with timer.stage("translation"):
        model_result = _run_selected(text, settings, profiles)
    if model_result is not None:
        model_result["variant_candidate"] = variant
        model_result.setdefault("text_match", False)
        model_result.setdefault("passage_identity_verified", False)
        model_result.setdefault("candidates", [])
        model_result["profile_evidence"] = {
            "basis": "user_selection" if language else "single_provisioned_profile",
            "profiles": evidence}
        _attach_verification(model_result, text, settings, timer, context)
        model_result["stage_timings_ms"] = timer.as_dict()
        return model_result
    counts = retrieval.corpus_counts(settings.db_path)
    if counts["total"]:
        detail = ("The imported corpus holds "
                  f"{counts['total']} passages, but this text matches none of them "
                  "(exact and diacritic-insensitive keys were both checked), and no trained "
                  "general translation model (Moses/Marian) is provisioned yet.")
    else:
        detail = ("No corpus has been imported and no trained general translation model "
                  "(Moses/Marian) is provisioned yet. Import the corpus "
                  "(python -m app.corpus.import_morphhb) for verified reference matches.")
    incomplete = _incomplete_notes(settings, profiles)
    if incomplete:
        detail += " Provisioned but incomplete artifacts: " + " | ".join(incomplete)
    err = UnavailableError("translation_model_unavailable",
        "No verified corpus match was found and a trained general translation model is not yet available, so no translation was produced. No paraphrase or dictionary gloss has been substituted.",
        detail)
    err.variant_candidate = variant  # type: ignore[attr-defined]
    raise err


def translate_passage(text: str, settings: Settings, language: str | None = None,
                      context: dict | None = None) -> dict:
    """Translate a complete (possibly multiline) passage segment by
    segment. Each segment is routed independently through the same
    reference-first order as translate(); the reassembled output keeps
    the input's line structure, with untranslated segments left visibly
    empty. Status: completed (every segment translated), partial (at
    least one translated and at least one not), failed (none). A single
    segment delegates to translate() unchanged, preserving its error
    behaviour (an unavailable single segment raises, as before)."""
    if not text or not text.strip():
        raise ValidationAppError("empty_text", "Source text is empty; there is nothing to translate.")
    if len(text) > settings.max_passage_chars:
        raise ValidationAppError(
            "passage_too_long",
            f"Passage has {len(text)} characters; the configured limit is "
            f"{settings.max_passage_chars} (AHAIET_MAX_PASSAGE_CHARS).",
            "Split the passage into smaller requests, or raise the limit in configuration.")
    segmentation = split_segments(text)
    if len(segmentation.segments) > settings.max_segments:
        raise ValidationAppError(
            "too_many_segments",
            f"Passage has {len(segmentation.segments)} segments; the configured limit is "
            f"{settings.max_segments} (AHAIET_MAX_SEGMENTS).",
            "Split the passage into smaller requests, or raise the limit in configuration.")
    if not segmentation.contains_multiple_lines:
        result = translate(text, settings, language, context)
        only = segmentation.segments[0]
        result["segments"] = [{"index": only.index, "source_text": only.source_text,
                               "status": "translated",
                               "english_translation": result["english_translation"],
                               "method": result["translation_method"],
                               "warnings": list(result.get("warnings", [])), "error": None}]
        return result

    timer = StageTimer()
    deadline = time.monotonic() + settings.job_deadline_s
    # Batched model stage (AHAIET-035): with an explicit profile,
    # segments that have no verified retrieval match are decoded in
    # ONE decoder invocation per engine (line-in/line-out) instead of
    # one subprocess per segment. Segments the batch cannot resolve
    # fall through to the per-segment path below, which produces
    # their individual statuses/errors.
    batch_results: dict[int, dict] = {}
    if language is not None and len(segmentation.segments) > 1:
        pending = []
        for seg in segmentation.segments:
            look = retrieval.lookup(settings.db_path, seg.source_text, language)
            if look["match"] is None and not look.get("candidates"):
                pending.append(seg)
        if len(pending) > 1:
            try:
                with timer.stage("translation"):
                    batch = _run_selected_batch([seg.source_text for seg in pending],
                                                settings, language, deadline)
            except AppError:
                batch = None
            if batch:
                for seg, result in zip(pending, batch):
                    batch_results[seg.index] = result
    segment_results: list[dict] = []
    english_parts: list[str | None] = []
    references: list[dict] = []
    warnings: list[str] = []
    methods: list[str] = []
    first_provenance: dict | None = None
    variant = None
    translated_count = 0
    for seg in segmentation.segments:
        if seg.index in batch_results:
            result = batch_results[seg.index]
            translated_count += 1
            methods.append(result["translation_method"])
            references.extend(result.get("source_references", []))
            if first_provenance is None:
                first_provenance = result.get("provenance")
            for w in result.get("warnings", []):
                warnings.append(f"[segment {seg.index + 1}] {w}")
            segment_results.append({"index": seg.index, "source_text": seg.source_text,
                                    "status": "translated",
                                    "english_translation": result["english_translation"],
                                    "method": result["translation_method"],
                                    "warnings": list(result.get("warnings", [])), "error": None})
            english_parts.append(result["english_translation"])
            continue
        if time.monotonic() > deadline:
            segment_results.append({"index": seg.index, "source_text": seg.source_text,
                                    "status": "failed", "english_translation": None,
                                    "method": None, "warnings": [],
                                    "error": "job_deadline_exceeded: the per-job total "
                                             "deadline was exceeded before this segment ran"})
            english_parts.append(None)
            continue
        try:
            with timer.stage("translation"):
                result = translate(seg.source_text, settings, language, context)
        except UnavailableError as e:
            segment_results.append({"index": seg.index, "source_text": seg.source_text,
                                    "status": "unavailable", "english_translation": None,
                                    "method": None, "warnings": [],
                                    "error": f"{e.code}: {e.message}"})
            english_parts.append(None)
            if variant is None:
                variant = getattr(e, "variant_candidate", None)
            continue
        except AppError as e:
            segment_results.append({"index": seg.index, "source_text": seg.source_text,
                                    "status": "failed", "english_translation": None,
                                    "method": None, "warnings": [],
                                    "error": f"{e.code}: {e.message}"})
            english_parts.append(None)
            continue
        translated_count += 1
        methods.append(result["translation_method"])
        references.extend(result.get("source_references", []))
        if first_provenance is None:
            first_provenance = result.get("provenance")
        for w in result.get("warnings", []):
            warnings.append(f"[segment {seg.index + 1}] {w}")
        if variant is None and result.get("variant_candidate") is not None:
            variant = result["variant_candidate"]
        segment_results.append({"index": seg.index, "source_text": seg.source_text,
                                "status": "translated",
                                "english_translation": result["english_translation"],
                                "method": result["translation_method"],
                                "warnings": list(result.get("warnings", [])), "error": None})
        english_parts.append(result["english_translation"])

    if translated_count == 0:
        status = "failed"
    elif translated_count == len(segmentation.segments):
        status = "completed"
    else:
        status = "partial"
    english = reassemble(english_parts, segmentation) if translated_count else None
    out: dict = {
        "english_translation": english,
        "translation_method": methods[0] if len(set(methods)) == 1 else "passage_mixed",
        "engine": methods[0] if len(set(methods)) == 1 else "passage_mixed",
        "model": {"id": "passage", "segments": len(segmentation.segments)},
        "model_version": None, "artifact_sha256": None, "evaluation_state": None,
        "coverage": None, "warnings": warnings,
        "source_references": references,
        "matched_language": language,
        "variant_candidate": variant,
        "unevaluated_model": False, "cached": False,
        "provenance": first_provenance if len(set(methods)) <= 1 else {
            "engine": "passage_mixed", "model_id": None, "model_version": None,
            "artifact_sha256": None, "evaluation_state": None,
            "dataset_card_sha256": None, "retrieval_citation": None, "cached": False},
        "segments": segment_results,
        "passage_status": status,
    }
    if english is not None:
        joined_source = "\n".join(s.source_text for s in segmentation.segments)
        _attach_verification(out, joined_source, settings, timer, context)
    out["stage_timings_ms"] = timer.as_dict()
    return out
