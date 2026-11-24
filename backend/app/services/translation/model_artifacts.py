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
    # AHAIET-019/006: per-file verification results, the evaluation-run
    # record accompanying any recorded score, and staleness flags.
    file_checks: list = field(default_factory=list)
    evaluation_run: dict | None = None
    stale_metric: bool = False
    # NEW-14: a numeric score exists somewhere but no valid run record
    # accompanies it, so it was ignored.
    metric_without_run: bool = False

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
            "file_checks": self.file_checks,
            "evaluation_run": self.evaluation_run,
            "stale_metric": self.stale_metric,
            "metric_without_run": self.metric_without_run,
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


def _valid_run_record(run, artifact_sha: str | None) -> dict | None:
    """A run record is valid evidence (NEW-14) only when it carries
    ALL of: test-set sha256, sample count, metric implementation
    signature, artifact sha256, and a date — and, when the artifact's
    current hash is known, its artifact sha256 matches it. A bare
    number without this record is not a score."""
    if not isinstance(run, dict):
        return None
    sample_count = run.get("sample_count", run.get("test_pairs"))
    if not (run.get("test_set_sha256") and run.get("metric_signature")
            and isinstance(sample_count, int) and sample_count > 0
            and run.get("artifact_sha256") and run.get("date")):
        return None
    if artifact_sha and run["artifact_sha256"] != artifact_sha:
        return None
    return run


def _recorded_chrf(entry: dict, card: dict | None,
                   artifact_sha: str | None = None) -> tuple[float | None, bool]:
    """(recorded chrF++, saw_unaccompanied_score).

    NEW-14: a chrF++ value counts ONLY when accompanied by a valid
    evaluation-run record (see _valid_run_record). An isolated numeric
    chrf_pp — in a card, a manifest evaluation block, or a selection
    block — is ignored for readiness/selection and reported via the
    second return value so the state is visible, never silently
    trusted. A pure-Python fallback chrF value is stored under the key
    "chrf" (never "chrf_pp") and is deliberately NOT read here
    (AHAIET-006)."""
    candidates: list[tuple[object, object]] = [
        (((card or {}).get("metrics") or {}).get("chrf_pp"),
         (card or {}).get("evaluation_run")),
        (((entry.get("evaluation") or {}).get("chrf_pp")),
         (entry.get("evaluation") or {}).get("run")),
        (((entry.get("selection") or {}).get("value")
          if (entry.get("selection") or {}).get("metric") == "chrf_pp" else None),
         (entry.get("selection") or {}).get("run")),
    ]
    saw_bare = False
    for value, run in candidates:
        if not isinstance(value, (int, float)):
            continue
        if _valid_run_record(run, artifact_sha) is not None:
            return float(value), saw_bare
        saw_bare = True
    return None, saw_bare


def evaluation_run_of(entry: dict, card: dict | None) -> dict | None:
    """The evaluation-run record that must accompany a recorded score
    for the score to be comparable (AHAIET-006): run id, test-set
    sha256, sample count, metric implementation signature, artifact
    sha256, date. Looked for on the model card first, then the
    manifest entry's evaluation record."""
    for source in ((card or {}).get("evaluation_run"),
                   (entry.get("evaluation") or {}).get("run"),
                   (entry.get("selection") or {}).get("run"),
                   entry.get("evaluation_run")):
        if isinstance(source, dict) and source.get("test_set_sha256") \
                and source.get("metric_signature"):
            return source
    return None


# Resolution cache (AHAIET-019; NEW-27): keyed by the artifact
# directory plus a signature of the model card and every card-listed
# file (mtime + size) and the manifest entry itself. NEW-27: the
# signature alone cannot detect an in-place same-size edit with
# restored timestamps, so a cached verdict is served only within the
# integrity TTL (Settings.artifact_integrity_ttl_s, mirrored here from
# the environment for this settings-free module); past the TTL, on an
# entry/signature change, on startup, and on an explicit
# verify_artifacts() call, file contents are rehashed.
import os as _os
import time as _time
_INTEGRITY_TTL_S = float(_os.getenv("AHAIET_ARTIFACT_INTEGRITY_TTL_S", "300"))
_resolution_cache: dict[str, tuple[str, "ArtifactResolution", float]] = {}


def invalidate_resolution_cache() -> None:
    _resolution_cache.clear()


def _resolution_signature(entry: dict, artifact_dir: Path) -> str:
    import hashlib as _h
    parts = [json.dumps(entry, sort_keys=True, default=str)]
    card_path = artifact_dir / "model_card.json"
    watched = [card_path]
    card = _load_card(artifact_dir)
    for f in (card or {}).get("files", []) or []:
        if f.get("path"):
            watched.append(artifact_dir / f["path"])
    for path in watched:
        try:
            st = path.stat()
            parts.append(f"{path.name}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{path.name}:absent")
    return _h.sha256("|".join(parts).encode("utf-8")).hexdigest()


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
    # Resolution cache fast path (NEW-27): identical signature AND
    # within the integrity TTL. Anything else re-resolves (rehashing
    # every card-listed file that records a checksum).
    cache_key = str(artifact_dir)
    signature = _resolution_signature(entry, artifact_dir)
    cached_resolution = _resolution_cache.get(cache_key)
    if cached_resolution and cached_resolution[0] == signature \
            and (_time.monotonic() - cached_resolution[2]) < _INTEGRITY_TTL_S:
        return cached_resolution[1]
    card = _load_card(artifact_dir)
    missing: list[str] = []
    file_checks: list[dict] = []
    if card is None:
        missing.append("model_card.json (written by the training run; required for provenance)")
    else:
        base = artifact_dir.resolve()
        for f in card.get("files", []) or []:
            rel = f.get("path")
            if not rel:
                continue
            target = (artifact_dir / rel)
            # Path traversal: a card-listed file must stay inside the
            # artifact directory (AHAIET-019).
            try:
                resolved = target.resolve()
            except OSError:
                resolved = target
            if resolved != base and base not in resolved.parents:
                missing.append(f"model card file escapes the artifact directory: {rel}")
                file_checks.append({"path": rel, "ok": False, "reason": "path_escape"})
                continue
            if not target.exists():
                missing.append(f"model card file missing: {rel}")
                file_checks.append({"path": rel, "ok": False, "reason": "missing"})
                continue
            # Recompute SHA-256 + size and compare with the values the
            # model card recorded at export time, when it recorded
            # them (real training exports always do, via describe_file).
            check: dict = {"path": rel, "ok": True}
            actual_size = target.stat().st_size
            if f.get("size_bytes") is not None and int(f["size_bytes"]) != actual_size:
                check.update(ok=False, reason="size_mismatch",
                             recorded_size=f["size_bytes"], actual_size=actual_size)
                missing.append(f"model card file size mismatch: {rel}")
            if f.get("sha256"):
                actual_sha = _sha256_file(target)
                if actual_sha != f["sha256"]:
                    check.update(ok=False, reason="sha256_mismatch")
                    missing.append(f"model card file checksum mismatch: {rel}")
                else:
                    check["sha256"] = actual_sha
            file_checks.append(check)
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
    sha = (card or {}).get("artifact_sha256") or entry.get("checksum")
    if not sha:
        # Fall back to hashing the engine's primary configuration/checkpoint.
        primary = artifact_dir / ("moses.ini" if entry.get("engine") == "moses" else "model.npz")
        if primary.exists():
            sha = _sha256_file(primary)
    # NEW-14: the recorded score is read only together with its
    # evaluation-run record, validated against the artifact's current
    # hash — a bare chrf_pp number is not evidence.
    chrf, metric_without_run = _recorded_chrf(entry, card, artifact_sha=sha)
    # Verify the recorded primary-artifact checksum itself when the
    # card names its primary file (AHAIET-019).
    primary_name = (card or {}).get("primary_artifact")
    recorded_sha = (card or {}).get("artifact_sha256")
    if primary_name and recorded_sha and (artifact_dir / primary_name).exists():
        if _sha256_file(artifact_dir / primary_name) != recorded_sha:
            missing.append(f"primary artifact checksum mismatch: {primary_name}")
    # Stale metrics (AHAIET-006): a score whose evaluation run recorded
    # a different artifact hash than the artifact now on disk is
    # ignored for ranking and flagged, never silently trusted.
    run_record = evaluation_run_of(entry, card)
    stale = False
    if run_record and run_record.get("artifact_sha256") and sha \
            and run_record["artifact_sha256"] != sha:
        stale = True
        chrf = None
    state = "evaluated" if chrf is not None else "trained_but_not_evaluated"
    version = (card or {}).get("model_version") or entry.get("version")
    if metric_without_run:
        # The score was ignored; the run record (if any partial one
        # exists) is not presented as valid evidence either.
        run_record = None
    resolution = ArtifactResolution(entry=entry, ok=not missing, artifact_dir=artifact_dir,
                              missing=missing, card=card, evaluation_state=state,
                              artifact_sha256=sha, model_version=version, chrf_pp=chrf,
                              file_checks=file_checks, evaluation_run=run_record,
                              stale_metric=stale, metric_without_run=metric_without_run)
    _resolution_cache[cache_key] = (signature, resolution, _time.monotonic())
    return resolution


def verify_artifacts(settings, force: bool = True) -> list[dict]:
    """Explicit integrity verification (NEW-27).

    With force=True (the default) the resolution cache is dropped and
    every translation entry in the models manifest is re-resolved from
    disk, rehashing the CONTENT of every card-listed file that records
    a checksum — so an in-place same-size edit with restored mtime and
    size is caught here even though the cache signature cannot see it.
    Called at application startup and available to operators/tests.

    Recommended artifact layout (see docs/TRAINING.md): immutable
    artifact directories named by content hash
    (artifacts/models/<engine>/<profile>/<artifact_sha256-prefix>/)
    with activation done by pointing the manifest entry at the new
    directory — never by editing files in place."""
    if force:
        invalidate_resolution_cache()
    try:
        manifest = json.loads(Path(settings.models_manifest).read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for entry in manifest.get("models", []):
        if entry.get("kind") != "translation":
            continue
        resolution = resolve_entry(entry)
        out.append(resolution.summary())
    return out


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
