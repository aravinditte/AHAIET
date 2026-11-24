from __future__ import annotations
from pathlib import Path
from app.core.errors import UnavailableError
def run_marian(text: str, artifact_path: Path) -> str:
    if not artifact_path.exists():
        raise UnavailableError("marian_unavailable", "Marian NMT model artifact is not available.", f"artifact={artifact_path}")
    try:
        from transformers import MarianMTModel, MarianTokenizer  # noqa: F401
    except Exception as e:
        raise UnavailableError("marian_unavailable", "Marian runtime (transformers/torch) is not installed.", str(e))
    raise UnavailableError("marian_unavailable", "Marian inference wiring is a Part 4 task; no translation was produced.", f"artifact={artifact_path}")
