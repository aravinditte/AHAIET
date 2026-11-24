"""Translation resolution order:
1. Verified reference retrieval: if the (corrected) source text matches
   an imported corpus passage in the selected profile — exactly or by
   the diacritic-insensitive key — that edition's English is returned
   with translation_method='verified_reference' and full provenance.
2. A provisioned local Moses/Marian model artifact, if one exists.
3. Otherwise an honest unavailable error. The message distinguishes the
   two no-match cases: corpus present but no match, vs no corpus at all.
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

def load_models_manifest(settings: Settings) -> dict:
    p: Path = settings.models_manifest
    if not p.exists():
        return {"models": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"models": []}

def provisioned_models(settings: Settings, language: str | None = None) -> list[dict]:
    out = []
    for m in load_models_manifest(settings).get("models", []):
        if m.get("kind") != "translation":
            continue
        if m.get("status") != "provisioned":
            continue
        path = m.get("path")
        if not path or not Path(path).exists():
            continue
        if language and m.get("language_profile") not in (language, None):
            continue
        out.append(m)
    return out

def translate(text: str, settings: Settings, language: str | None = None) -> dict:
    if not text or not text.strip():
        raise ValidationAppError("empty_text", "Source text is empty; there is nothing to translate.")
    profiles = [language] if language else ["biblical_hebrew", "biblical_aramaic"]
    variant = None
    for profile in profiles:
        result = retrieval.lookup(settings.db_path, text, profile)
        if result["match"] is not None:
            match = result["match"]
            return {"english_translation": match["english_text"],
                    "translation_method": "verified_reference",
                    "model": {"id": "corpus-reference", "match_type": match["match_type"]},
                    "source_references": [match],
                    "matched_language": profile,
                    "variant_candidate": None}
        if variant is None and result["variant_candidate"] is not None:
            variant = result["variant_candidate"]
    models = provisioned_models(settings, language)
    if not models:
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
        err = UnavailableError("translation_model_unavailable",
            "No verified corpus match was found and a trained general translation model is not yet available, so no translation was produced. No paraphrase or dictionary gloss has been substituted.",
            detail)
        err.variant_candidate = variant  # type: ignore[attr-defined]
        raise err
    from .moses_adapter import run_moses
    from .marian_adapter import run_marian
    m = models[0]
    if m.get("engine") == "marian":
        result = run_marian(text, Path(m["path"]))
    else:
        result = run_moses(text, Path(m["path"]))
    return {"english_translation": result, "translation_method": m.get("engine"), "model": m,
            "source_references": [], "matched_language": language, "variant_candidate": variant}
