"""Resolution of trained-model artifacts described by the models manifest.

A manifest entry counts as a usable trained model only when ALL of the
following hold (anything less is reported, with the missing pieces named,
never silently treated as ready):
- the entry status marks it provisioned (the training orchestrators set
  this only after a real export step wrote the artifact directory);
- the artifact path exists on disk (relative paths resolve against the
  repository root);
- a model_card.json written by the training run is present and every
  file it lists is present;
- the engine's essential pieces are present:
  * Moses: the moses.ini configuration, a phrase table, a language-model
    file (roles taken from the model card when declared, filename globs
    otherwise);
  * Marian: the model checkpoint (model.npz or the card's checkpoint
    file), vocabulary file(s), and a decoder configuration.

Evaluation state is derived, never asserted: "evaluated" only when a
chrF++ value recorded by the evaluation harness exists in the model card
or in the manifest entry's evaluation record; otherwise a complete
artifact is "trained_but_not_evaluated".
"""
from __future__ import annotations
import gzip
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import REPO_ROOT, Settings
from app.services.language.tokenize import tokenize_source

PROVISIONED_STATUSES = {"provisioned", "trained_but_not_evaluated", "evaluated"}

# Engine essentials: (human-readable piece name, card roles, filename globs)
_MOSES_ESSENTIALS = [
    ("moses.ini configuration", ("config",), ("moses.ini",)),
    ("phrase table", ("phrase_table",), ("phrase-table*",)),
    ("language model", ("language_model",), ("*.binary", "*.arpa", "*.arpa.gz", "lm*")),
]
_MARIAN_ESSENTIALS = [
    ("model checkpoint", ("checkpoint", "model"), ("model.npz", "*.npz")),
    ("vocabulary", ("vocabulary", "vocab"), ("vocab*.spm", "vocab*.yml", "vocab*.yaml", "*.spm")),
    ("decoder configuration", ("decoder_config",), ("decoder-config.yml", "config-decoder.yml", "decoder_config.yml")),
]
VOCAB_ROLE = "vocabulary_source"
VOCAB_FILENAME = "vocabulary.source.txt"


@dataclass
class ArtifactResolution:
    entry: dict
    ok: bool
    artifact_dir: Path | None
    missing: list[str] = field(default_factory=list)
    card: dict | None = None
    evaluation_state: str = "not_provisioned"
    artifact_sha256: str | None = None
    model_version: str | None = None
    chrf_pp: float | None = None

    @property
    def engine(self) -> str | None:
        return self.entry.get("engine")

    @property
    def language_profile(self) -> str | None:
        return self.entry.get("language_profile")

    def summary(self) -> dict:
        return {
            "id": self.entry.get("id"), "engine": self.engine,
            "language_profile": self.language_profile,
            "artifact_state": self.evaluation_state if self.ok else (
                "provisioned_missing_files" if self.artifact_dir is not None else self.evaluation_state),
            "ok": self.ok, "missing": self.missing,
            "model_version": self.model_version, "artifact_sha256": self.artifact_sha256,
            "chrf_pp": self.chrf_pp,
            "selection": self.entry.get("selection"),
        }


def resolve_path(raw: str | Path) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else (REPO_ROOT / p)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_card(artifact_dir: Path) -> dict | None:
    card_path = artifact_dir / "model_card.json"
    if not card_path.exists():
        return None
    try:
        return json.loads(card_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _card_files_by_role(card: dict | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in (card or {}).get("files", []) or []:
        role = f.get("role")
        path = f.get("path")
        if role and path:
            out.setdefault(role, []).append(path)
    return out


def _recorded_chrf(entry: dict, card: dict | None) -> float | None:
    for source in ((card or {}).get("metrics") or {}, entry.get("evaluation") or {},
                   (entry.get("selection") or {})):
        value = source.get("chrf_pp")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def resolve_entry(entry: dict) -> ArtifactResolution:
    """Check one manifest translation entry against the disk."""
    if entry.get("status") not in PROVISIONED_STATUSES:
        return ArtifactResolution(entry=entry, ok=False, artifact_dir=None,
                                  evaluation_state="not_provisioned")
    raw_path = entry.get("path")
    if not raw_path:
        return ArtifactResolution(entry=entry, ok=False, artifact_dir=None,
                                  missing=["manifest entry has no artifact path"],
                                  evaluation_state="provisioned_missing_files")
    artifact_dir = resolve_path(raw_path)
    if not artifact_dir.is_dir():
        return ArtifactResolution(entry=entry, ok=False, artifact_dir=artifact_dir,
                                  missing=[f"artifact directory does not exist: {artifact_dir}"],
                                  evaluation_state="provisioned_missing_files")
    card = _load_card(artifact_dir)
    missing: list[str] = []
    if card is None:
        missing.append("model_card.json (written by the training run; required for provenance)")
    else:
        for f in card.get("files", []) or []:
            rel = f.get("path")
            if rel and not (artifact_dir / rel).exists():
                missing.append(f"model card file missing: {rel}")
    by_role = _card_files_by_role(card)
    essentials = _MOSES_ESSENTIALS if entry.get("engine") == "moses" else _MARIAN_ESSENTIALS
    for piece, roles, globs in essentials:
        found = False
        for role in roles:
            if any((artifact_dir / rel).exists() for rel in by_role.get(role, [])):
                found = True
                break
        if not found:
            for pattern in globs:
                if any(p.is_file() for p in artifact_dir.glob(pattern)):
                    found = True
                    break
        if not found:
            missing.append(piece)
    chrf = _recorded_chrf(entry, card)
    state = "evaluated" if chrf is not None else "trained_but_not_evaluated"
    sha = (card or {}).get("artifact_sha256") or entry.get("checksum")
    if not sha:
        # Fall back to hashing the engine's primary configuration/checkpoint.
        primary = artifact_dir / ("moses.ini" if entry.get("engine") == "moses" else "model.npz")
        if primary.exists():
            sha = _sha256_file(primary)
    version = (card or {}).get("model_version") or entry.get("version")
    return ArtifactResolution(entry=entry, ok=not missing, artifact_dir=artifact_dir,
                              missing=missing, card=card, evaluation_state=state,
                              artifact_sha256=sha, model_version=version, chrf_pp=chrf)


def card_file(resolution: ArtifactResolution, roles: tuple[str, ...],
              globs: tuple[str, ...]) -> Path | None:
    """Locate one artifact piece: model-card role first, filename glob second."""
    if resolution.artifact_dir is None:
        return None
    by_role = _card_files_by_role(resolution.card)
    for role in roles:
        for rel in by_role.get(role, []):
            p = resolution.artifact_dir / rel
            if p.exists():
                return p
    for pattern in globs:
        for p in sorted(resolution.artifact_dir.glob(pattern)):
            if p.is_file():
                return p
    return None


# ---------------------------------------------------------------------------
# Source vocabulary and out-of-vocabulary (OOV) reporting
# ---------------------------------------------------------------------------

_vocab_cache: dict[str, tuple[float, frozenset[str]]] = {}


def _phrase_table_source_tokens(table_path: Path) -> set[str]:
    tokens: set[str] = set()
    opener = gzip.open if table_path.suffix == ".gz" else open
    with opener(table_path, "rt", encoding="utf-8", errors="replace") as fh:  # type: ignore[arg-type]
        for line in fh:
            source_side = line.split("|||", 1)[0]
            tokens.update(source_side.split())
    return tokens


def load_source_vocabulary(resolution: ArtifactResolution) -> frozenset[str] | None:
    """Source-side vocabulary for OOV/coverage computation.

    Preference order: the exported vocabulary.source.txt (written by the
    dataset preparation step), then the Moses phrase table's source side.
    Returns None when neither exists — callers must then report coverage
    as unknown rather than guessing.
    """
    if resolution.artifact_dir is None:
        return None
    vocab_path = card_file(resolution, (VOCAB_ROLE,), (VOCAB_FILENAME,))
    table_path = None
    if vocab_path is None and resolution.engine == "moses":
        table_path = card_file(resolution, ("phrase_table",), ("phrase-table*",))
        vocab_path = table_path
    if vocab_path is None:
        return None
    key = str(vocab_path)
    mtime = vocab_path.stat().st_mtime
    cached = _vocab_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    if table_path is not None:
        vocab = frozenset(_phrase_table_source_tokens(table_path))
    else:
        vocab = frozenset(vocab_path.read_text(encoding="utf-8").split())
    _vocab_cache[key] = (mtime, vocab)
    return vocab


def compute_coverage(text: str, resolution: ArtifactResolution) -> dict | None:
    """Word-level source coverage of `text` against the model vocabulary.

    Returns {source_tokens, known_tokens, coverage_ratio, oov_words} or
    None when no vocabulary artifact exists. OOV words are reported to
    the caller so they surface as response warnings; they are never
    silently dropped from the request.
    """
    vocab = load_source_vocabulary(resolution)
    if vocab is None:
        return None
    tokens = tokenize_source(text)
    if not tokens:
        return {"source_tokens": 0, "known_tokens": 0, "coverage_ratio": 1.0, "oov_words": []}
    oov = sorted({tok for tok in tokens if tok not in vocab})
    known = sum(1 for tok in tokens if tok in vocab)
    return {"source_tokens": len(tokens), "known_tokens": known,
            "coverage_ratio": round(known / len(tokens), 4), "oov_words": oov}
