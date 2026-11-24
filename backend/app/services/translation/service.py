from __future__ import annotations
import json
from pathlib import Path
from app.core.config import Settings
from app.core.errors import UnavailableError, ValidationAppError

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
    models = provisioned_models(settings, language)
    if not models:
        raise UnavailableError("translation_model_unavailable",
            "No local translation model artifact is provisioned for this language profile, so no translation was produced. No dictionary gloss or example translation has been substituted.",
            "Provision a trained Moses SMT or Marian NMT model, record it with status 'provisioned' and a real artifact path in artifacts/manifests/models.json, then retry. See docs/TRAINING.md.")
    # Real adapters are selected here when a provisioned artifact exists.
    from .moses_adapter import run_moses
    from .marian_adapter import run_marian
    m = models[0]
    if m.get("engine") == "marian":
        result = run_marian(text, Path(m["path"]))
    else:
        result = run_moses(text, Path(m["path"]))
    return {"english_translation": result, "translation_method": m.get("engine"), "model": m}
