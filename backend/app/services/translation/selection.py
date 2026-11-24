"""Per-profile trained-model selection.

Selection is data-driven from the models manifest and the model cards
written by real training runs — never from hardcoded quality claims:

1. Among artifacts that resolve complete for the profile, an engine
   with evaluation metrics recorded by the shared evaluation harness
   wins; the higher recorded chrF++ on the shared held-out test split
   ranks first.
2. When no engine for the profile has recorded metrics, the documented
   default order applies: Moses SMT before Marian NMT (the statistical
   baseline is the conservative default for these tiny corpora).
3. When nothing resolves complete, there is no selection and the caller
   reports translation as unavailable for that profile.

Readiness is independent per language profile: a complete Hebrew model
says nothing about Aramaic.
"""
from __future__ import annotations
from app.core.config import Settings
from . import model_artifacts
from .model_artifacts import ArtifactResolution

DEFAULT_ENGINE_ORDER = ["moses", "marian"]
PROFILES = ["biblical_hebrew", "biblical_aramaic"]


def translation_entries(settings: Settings, profile: str | None = None) -> list[dict]:
    from .service import load_models_manifest
    out = []
    for entry in load_models_manifest(settings).get("models", []):
        if entry.get("kind") != "translation":
            continue
        if profile and entry.get("language_profile") != profile:
            continue
        out.append(entry)
    return out


def engine_states(settings: Settings, profile: str) -> list[dict]:
    """Live artifact state for every translation engine of one profile."""
    states = []
    for entry in translation_entries(settings, profile):
        resolution = model_artifacts.resolve_entry(entry)
        states.append(resolution.summary())
    return states


def _default_rank(r: ArtifactResolution) -> int:
    return DEFAULT_ENGINE_ORDER.index(r.engine) if r.engine in DEFAULT_ENGINE_ORDER else 99


def select_engines(settings: Settings, profile: str) -> list[ArtifactResolution]:
    """Return ALL complete artifact resolutions for a profile, in the
    order they should be tried (AHAIET-020): the translation service
    walks this list within the SAME profile, recording each failure,
    and never crosses to another profile silently.

    Ordering (AHAIET-006 comparability): engines whose recorded scores
    carry an evaluation-run record with an identical test-set sha256
    AND identical metric signature are comparable and rank by score;
    scores without a run record, or with a different test set /
    signature, are never compared against them — those engines follow
    in the documented default order, as do unevaluated engines."""
    complete: list[ArtifactResolution] = []
    for entry in translation_entries(settings, profile):
        resolution = model_artifacts.resolve_entry(entry)
        if resolution.ok:
            complete.append(resolution)
    if not complete:
        return []
    comparable = [r for r in complete if r.chrf_pp is not None and r.evaluation_run]
    if comparable:
        # The comparison set is the largest group sharing one
        # (test-set sha, metric signature); ties break toward the
        # group holding the highest recorded score.
        groups: dict[tuple, list[ArtifactResolution]] = {}
        for r in comparable:
            key = (r.evaluation_run.get("test_set_sha256"),
                   r.evaluation_run.get("metric_signature"))
            groups.setdefault(key, []).append(r)
        best_key = max(groups, key=lambda k: (len(groups[k]),
                                              max(x.chrf_pp or 0.0 for x in groups[k])))
        ranked = sorted(groups[best_key],
                        key=lambda r: (-(r.chrf_pp or 0.0), _default_rank(r)))
        rest = [r for r in complete if r not in ranked]
        rest.sort(key=_default_rank)
        return ranked + rest
    evaluated = [r for r in complete if r.chrf_pp is not None]
    if len(evaluated) == 1:
        rest = [r for r in complete if r is not evaluated[0]]
        rest.sort(key=_default_rank)
        return [evaluated[0]] + rest
    # Multiple recorded scores without run records are not comparable;
    # fall back to the documented default order rather than comparing
    # numbers that may come from different test sets or metrics.
    complete.sort(key=_default_rank)
    return complete


def select_engine(settings: Settings, profile: str) -> ArtifactResolution | None:
    """Return the winning complete artifact resolution for a profile
    (the head of select_engines)."""
    engines = select_engines(settings, profile)
    return engines[0] if engines else None


def per_profile_readiness(settings: Settings, corpus_by_language: dict | None = None) -> dict:
    """Readiness summary per profile for /api/capabilities and /api/models."""
    out: dict[str, dict] = {}
    corpus_by_language = corpus_by_language or {}
    for profile in PROFILES:
        selected = select_engine(settings, profile)
        states = engine_states(settings, profile)
        out[profile] = {
            "status": "available" if (selected or corpus_by_language.get(profile)) else "unavailable",
            "verified_reference": bool(corpus_by_language.get(profile)),
            "engine": selected.engine if selected else None,
            "evaluation_state": selected.evaluation_state if selected else None,
            "model_version": selected.model_version if selected else None,
            "engines": states,
        }
    return out
