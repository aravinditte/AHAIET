"""Translation resolution order:
1. Verified reference retrieval: if the (corrected) source text matches
   an imported corpus passage in the selected profile — exactly or by
   the diacritic-insensitive key — that edition's English is returned
   with translation_method='verified_reference' and full provenance.
2. A trained local model chosen per profile by the selection service
   (services/translation/selection.py): an engine with evaluation
   metrics recorded by the shared harness wins on recorded chrF++;
   otherwise Moses SMT precedes Marian NMT as the documented default.
   The response names the engine actually used, its model version and
   artifact hash, and carries OOV warnings plus source-token coverage.
3. Otherwise an honest unavailable error. The message distinguishes the
   two no-match cases: corpus present but no match, vs no corpus at all,
   and names any provisioned-but-incomplete artifacts with their missing
   pieces.
A variant candidate is never returned as a translation; it is reported
as a warning instead. No paraphrase or dictionary gloss is ever
substituted.
"""
from __future__ import annotations
import json
from pathlib import Path
from app.core.config import Settings
from app.core.errors import UnavailableError, ValidationAppError
from app.services import retrieval
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

def _run_selected(text: str, settings: Settings, profiles: list[str]) -> dict | None:
    """Try the selected trained engine per profile, in profile order."""
    from .moses_adapter import run as run_moses_engine
    from .marian_adapter import run as run_marian_engine
    last_error: UnavailableError | None = None
    for profile in profiles:
        chosen = selection.select_engine(settings, profile)
        if chosen is None:
            continue
        runner = run_marian_engine if chosen.engine == "marian" else run_moses_engine
        try:
            result = runner(chosen.entry, text, settings)
        except UnavailableError as e:
            # e.g. artifact complete but the decoder binary is absent:
            # record it and fall through to any other complete engine.
            last_error = e
            continue
        result.update({
            "translation_method": chosen.engine,
            "model": {**chosen.entry, "model_version": chosen.model_version,
                      "artifact_sha256": chosen.artifact_sha256,
                      "evaluation_state": chosen.evaluation_state},
            "source_references": [],
            "matched_language": profile,
            "variant_candidate": None,
        })
        return result
    if last_error is not None:
        raise last_error
    return None

def translate(text: str, settings: Settings, language: str | None = None) -> dict:
    if not text or not text.strip():
        raise ValidationAppError("empty_text", "Source text is empty; there is nothing to translate.")
    profiles = [language] if language else PROFILES
    variant = None
    for profile in profiles:
        result = retrieval.lookup(settings.db_path, text, profile)
        if result["match"] is not None:
            match = result["match"]
            return {"english_translation": match["english_text"],
                    "translation_method": "verified_reference",
                    "engine": "verified_reference",
                    "model": {"id": "corpus-reference", "match_type": match["match_type"]},
                    "model_version": None, "artifact_sha256": None,
                    "evaluation_state": None, "coverage": None, "warnings": [],
                    "source_references": [match],
                    "matched_language": profile,
                    "variant_candidate": None}
        if variant is None and result["variant_candidate"] is not None:
            variant = result["variant_candidate"]
    model_result = _run_selected(text, settings, profiles)
    if model_result is not None:
        model_result["variant_candidate"] = variant
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
