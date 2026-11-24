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
from pathlib import Path
from app.core.config import Settings
from app.core.errors import AppError, UnavailableError, ValidationAppError
from app.core.timing import StageTimer
from app.services import retrieval
from app.services.language.passage import reassemble, split_segments
from app.storage import cache as translation_cache
from . import model_artifacts, selection

PROFILES = ["biblical_hebrew", "biblical_aramaic"]

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


def _run_selected(text: str, settings: Settings, profiles: list[str]) -> dict | None:
    """Try the selected trained engine per profile, in profile order.

    Evaluated engines are preferred over unevaluated ones by the
    selection service; an unevaluated winner is flagged on the result.
    Results are served from / stored to the translation cache — the
    cache is consulted only here, i.e. only for trained-model output,
    never for verified retrieval."""
    from .moses_adapter import run as run_moses_engine
    from .marian_adapter import run as run_marian_engine
    last_error: UnavailableError | None = None
    for profile in profiles:
        chosen = selection.select_engine(settings, profile)
        if chosen is None:
            continue
        key = translation_cache.cache_key(profile, text, chosen.engine,
                                          chosen.artifact_sha256)
        cached = translation_cache.get(settings, key)
        if cached is not None:
            result = copy.deepcopy(cached)
            result["cached"] = True
            if isinstance(result.get("provenance"), dict):
                result["provenance"]["cached"] = True
            return result
        runner = run_marian_engine if chosen.engine == "marian" else run_moses_engine
        try:
            result = runner(chosen.entry, text, settings)
        except UnavailableError as e:
            # e.g. artifact complete but the decoder binary is absent:
            # record it and fall through to any other complete engine.
            last_error = e
            continue
        unevaluated = chosen.evaluation_state != "evaluated"
        warnings = list(result.get("warnings", []))
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
        translation_cache.put(settings, key, profile, chosen.engine,
                              chosen.artifact_sha256,
                              {k: v for k, v in result.items() if k != "_model_metrics"})
        return result
    if last_error is not None:
        raise last_error
    return None


def translate(text: str, settings: Settings, language: str | None = None,
              context: dict | None = None) -> dict:
    if not text or not text.strip():
        raise ValidationAppError("empty_text", "Source text is empty; there is nothing to translate.")
    timer = StageTimer()
    profiles = [language] if language else PROFILES
    variant = None
    with timer.stage("retrieval"):
        for profile in profiles:
            result = retrieval.lookup(settings.db_path, text, profile)
            if result["match"] is not None:
                match = result["match"]
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
            if variant is None and result["variant_candidate"] is not None:
                variant = result["variant_candidate"]
    with timer.stage("translation"):
        model_result = _run_selected(text, settings, profiles)
    if model_result is not None:
        model_result["variant_candidate"] = variant
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
    if not segmentation.is_multiline:
        result = translate(text, settings, language, context)
        only = segmentation.segments[0]
        result["segments"] = [{"index": only.index, "source_text": only.source_text,
                               "status": "translated",
                               "english_translation": result["english_translation"],
                               "method": result["translation_method"],
                               "warnings": list(result.get("warnings", [])), "error": None}]
        return result

    timer = StageTimer()
    segment_results: list[dict] = []
    english_parts: list[str | None] = []
    references: list[dict] = []
    warnings: list[str] = []
    methods: list[str] = []
    first_provenance: dict | None = None
    variant = None
    translated_count = 0
    for seg in segmentation.segments:
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
    english = reassemble(english_parts) if translated_count else None
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
