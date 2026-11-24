from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent

def _int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    return int(v) if v not in (None, "") else default

def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v in (None, ""):
        return default
    return v.strip().lower() not in ("0", "false", "no", "off")

def _origins_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    v = os.getenv(name)
    if v in (None, ""):
        return default
    origins = tuple(o.strip() for o in v.split(",") if o.strip())
    return origins or default

@dataclass(frozen=True)
class Settings:
    upload_max_bytes: int = 10 * 1024 * 1024
    upload_max_pixels: int = 40_000_000
    storage_dir: Path = BACKEND_ROOT / "data" / "uploads"
    retention_days: int = 30
    db_path: Path = BACKEND_ROOT / "data" / "ahaiet.db"
    models_manifest: Path = REPO_ROOT / "artifacts" / "manifests" / "models.json"
    datasets_manifest: Path = REPO_ROOT / "artifacts" / "manifests" / "datasets.json"
    corpus_dir: Path = REPO_ROOT / "artifacts" / "corpora"
    tesseract_cmd: str = "tesseract"
    tesseract_lang: str = "heb"
    tessdata_prefix: Path | None = None
    ocr_confidence_threshold: float = 60.0
    ocr_psm: int = 6
    ocr_timeout_s: float = 120.0
    # Trained translation model inference (Moses SMT / Marian NMT). The
    # binaries are locally installed tools; runtime never needs WSL2.
    moses_cmd: str = "moses"
    marian_decoder_cmd: str = "marian-decoder"
    translation_timeout_s: float = 120.0
    # Complete-passage handling: a multiline text is translated segment
    # by segment; these limits bound that work per request.
    max_segments: int = 64
    max_passage_chars: int = 20000
    # Translation result cache (SQLite translation_cache table). Only
    # trained-model outputs are cached, keyed by profile + normalized
    # source + engine + artifact hash; verified retrieval always runs
    # live and is never served from this cache.
    translation_cache_enabled: bool = True
    # Kraken historical recognition: optional Python package / ketos CLI.
    kraken_cmd: str = "ketos"
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")
    # Security hardening (see docs/SECURITY.md):
    # - App-level request body ceiling, on top of the per-upload limits.
    #   0 means "derive": upload_max_bytes + 1 MiB of multipart/JSON slack.
    request_max_bytes: int = 0
    # - Per-client (per source IP) request budgets per minute for the
    #   expensive/write endpoints. In-process and best-effort by design:
    #   this is a single-operator local application, not a public service.
    rate_limit_uploads_per_min: int = 30
    rate_limit_ocr_per_min: int = 30
    rate_limit_translate_per_min: int = 60
    rate_limit_process_per_min: int = 30
    # - Processing-history opt-out. When False, history writes are no-ops
    #   and GET /api/history reports an explicit disabled state.
    history_enabled: bool = True
    # - Retention maintenance (app.maintenance): when True, one sweep
    #   runs at application startup. The CLI is the primary route.
    retention_sweep_on_startup: bool = False
    # - When True, retention overwrites an upload file's bytes with zeros
    #   before unlinking it. See app/maintenance.py for what that does
    #   and does not guarantee.
    secure_delete_overwrite: bool = False
    # Remediation settings (see docs/SECURITY.md / docs/API.md):
    # - persist_results is SEPARATE from history_enabled (AHAIET-015):
    #   when False, jobs/results/translation-cache are ephemeral
    #   (in-memory jobs with a TTL) and no source or translation text
    #   is written to SQLite at all.
    persist_results: bool = True
    # - Async job lifecycle (AHAIET-009/033): bounded background
    #   executor, ephemeral-result TTL, and a per-job total deadline.
    job_workers: int = 2
    job_result_ttl_s: int = 3600
    job_deadline_s: float = 600.0
    # - Global concurrency bounds (AHAIET-033).
    max_concurrent_ocr: int = 2
    max_concurrent_translation: int = 2
    # - Decoded + intermediate byte budget for preprocessing
    #   (AHAIET-023), checked before heavy steps.
    preprocessing_max_bytes: int = 512 * 1024 * 1024
    # - Historical-script production gate (AHAIET-025): minimum
    #   independent HTR test lines before a tier above
    #   experimentally_evaluated may be reported.
    script_min_test_samples: int = 20
    # - Rate limiter registry hygiene (AHAIET-043): hard cap on
    #   tracked clients, and X-Forwarded-For is trusted only when a
    #   trusted reverse proxy is explicitly configured.
    rate_limit_max_clients: int = 10000
    trust_forwarded_for: bool = False
    # - Local-only posture (AHAIET-045): when access_token is set,
    #   upload reads and history require the X-AHAIET-Access-Token
    #   header. Unset (default) = local single-operator mode. The
    #   backend is documented to bind to loopback (AHAIET_BIND note
    #   in docs/SECURITY.md); a content-hash upload id is a locator,
    #   not an authorization credential.
    access_token: str | None = None
    # - Tesseract readiness probe cache TTL (AHAIET-034).
    tesseract_probe_ttl_s: float = 30.0

    def __post_init__(self) -> None:
        """Central settings validation (AHAIET-055): invalid values
        fail at startup with a clear message instead of producing
        confusing errors deep inside a request."""
        problems: list[str] = []
        def need(cond: bool, msg: str) -> None:
            if not cond:
                problems.append(msg)
        need(self.upload_max_bytes > 0, "AHAIET_UPLOAD_MAX_BYTES must be > 0")
        need(self.upload_max_pixels > 0, "AHAIET_UPLOAD_MAX_PIXELS must be > 0")
        need(self.retention_days >= 0, "AHAIET_RETENTION_DAYS must be >= 0")
        need(self.translation_timeout_s > 0, "AHAIET_TRANSLATION_TIMEOUT_S must be > 0")
        need(self.ocr_timeout_s > 0, "AHAIET_OCR_TIMEOUT_S must be > 0")
        need(0 <= self.ocr_psm <= 13, "AHAIET_OCR_PSM must be in 0..13")
        need(0.0 <= self.ocr_confidence_threshold <= 100.0,
             "AHAIET_OCR_CONF_THRESHOLD must be in 0..100")
        need(self.max_segments > 0, "AHAIET_MAX_SEGMENTS must be > 0")
        need(self.max_passage_chars > 0, "AHAIET_MAX_PASSAGE_CHARS must be > 0")
        need(self.job_workers > 0, "AHAIET_JOB_WORKERS must be > 0")
        need(self.job_deadline_s > 0, "AHAIET_JOB_DEADLINE_S must be > 0")
        need(self.max_concurrent_ocr > 0, "AHAIET_MAX_CONCURRENT_OCR must be > 0")
        need(self.max_concurrent_translation > 0, "AHAIET_MAX_CONCURRENT_TRANSLATION must be > 0")
        need(self.preprocessing_max_bytes > 0, "AHAIET_PREPROCESSING_MAX_BYTES must be > 0")
        need(self.script_min_test_samples > 0, "AHAIET_SCRIPT_MIN_TEST_SAMPLES must be > 0")
        if problems:
            raise ValueError("Invalid AHAIET configuration: " + "; ".join(problems))

    @classmethod
    def from_env(cls) -> "Settings":
        tessdata = os.getenv("TESSDATA_PREFIX") or os.getenv("AHAIET_TESSDATA_PREFIX")
        return cls(
            upload_max_bytes=_int_env("AHAIET_UPLOAD_MAX_BYTES", 10 * 1024 * 1024),
            upload_max_pixels=_int_env("AHAIET_UPLOAD_MAX_PIXELS", 40_000_000),
            storage_dir=Path(os.getenv("AHAIET_STORAGE_DIR", str(BACKEND_ROOT / "data" / "uploads"))),
            retention_days=_int_env("AHAIET_RETENTION_DAYS", 30),
            db_path=Path(os.getenv("AHAIET_DB_PATH", str(BACKEND_ROOT / "data" / "ahaiet.db"))),
            models_manifest=Path(os.getenv("AHAIET_MODELS_MANIFEST", str(REPO_ROOT / "artifacts" / "manifests" / "models.json"))),
            datasets_manifest=Path(os.getenv("AHAIET_DATASETS_MANIFEST", str(REPO_ROOT / "artifacts" / "manifests" / "datasets.json"))),
            corpus_dir=Path(os.getenv("AHAIET_CORPUS_DIR", str(REPO_ROOT / "artifacts" / "corpora"))),
            tesseract_cmd=os.getenv("AHAIET_TESSERACT_CMD", "tesseract"),
            tesseract_lang=os.getenv("AHAIET_TESSERACT_LANG", "heb"),
            tessdata_prefix=Path(tessdata) if tessdata else None,
            ocr_confidence_threshold=float(os.getenv("AHAIET_OCR_CONF_THRESHOLD", "60")),
            ocr_psm=_int_env("AHAIET_OCR_PSM", 6),
            ocr_timeout_s=float(os.getenv("AHAIET_OCR_TIMEOUT_S", "120")),
            moses_cmd=os.getenv("AHAIET_MOSES_CMD", "moses"),
            marian_decoder_cmd=os.getenv("AHAIET_MARIAN_DECODER_CMD", "marian-decoder"),
            translation_timeout_s=float(os.getenv("AHAIET_TRANSLATION_TIMEOUT_S", "120")),
            max_segments=_int_env("AHAIET_MAX_SEGMENTS", 64),
            max_passage_chars=_int_env("AHAIET_MAX_PASSAGE_CHARS", 20000),
            translation_cache_enabled=os.getenv("AHAIET_TRANSLATION_CACHE", "1") not in ("0", "false", "no"),
            kraken_cmd=os.getenv("AHAIET_KRAKEN_CMD", "ketos"),
            cors_origins=_origins_env("AHAIET_CORS_ORIGINS",
                                      ("http://localhost:3000", "http://127.0.0.1:3000")),
            request_max_bytes=_int_env("AHAIET_REQUEST_MAX_BYTES", 0),
            rate_limit_uploads_per_min=_int_env("AHAIET_RATE_LIMIT_UPLOADS_PER_MIN", 30),
            rate_limit_ocr_per_min=_int_env("AHAIET_RATE_LIMIT_OCR_PER_MIN", 30),
            rate_limit_translate_per_min=_int_env("AHAIET_RATE_LIMIT_TRANSLATE_PER_MIN", 60),
            rate_limit_process_per_min=_int_env("AHAIET_RATE_LIMIT_PROCESS_PER_MIN", 30),
            history_enabled=_bool_env("AHAIET_HISTORY_ENABLED", True),
            retention_sweep_on_startup=_bool_env("AHAIET_RETENTION_SWEEP_ON_STARTUP", False),
            secure_delete_overwrite=_bool_env("AHAIET_SECURE_DELETE_OVERWRITE", False),
            persist_results=_bool_env("AHAIET_PERSIST_RESULTS", True),
            job_workers=_int_env("AHAIET_JOB_WORKERS", 2),
            job_result_ttl_s=_int_env("AHAIET_JOB_RESULT_TTL_S", 3600),
            job_deadline_s=float(os.getenv("AHAIET_JOB_DEADLINE_S", "600")),
            max_concurrent_ocr=_int_env("AHAIET_MAX_CONCURRENT_OCR", 2),
            max_concurrent_translation=_int_env("AHAIET_MAX_CONCURRENT_TRANSLATION", 2),
            preprocessing_max_bytes=_int_env("AHAIET_PREPROCESSING_MAX_BYTES", 512 * 1024 * 1024),
            script_min_test_samples=_int_env("AHAIET_SCRIPT_MIN_TEST_SAMPLES", 20),
            rate_limit_max_clients=_int_env("AHAIET_RATE_LIMIT_MAX_CLIENTS", 10000),
            trust_forwarded_for=_bool_env("AHAIET_TRUST_FORWARDED_FOR", False),
            access_token=os.getenv("AHAIET_ACCESS_TOKEN") or None,
            tesseract_probe_ttl_s=float(os.getenv("AHAIET_TESSERACT_PROBE_TTL_S", "30")),
        )

    @property
    def effective_request_max_bytes(self) -> int:
        """App-level body ceiling: the configured value, or the upload
        limit plus slack for multipart framing / JSON bodies."""
        if self.request_max_bytes > 0:
            return self.request_max_bytes
        return self.upload_max_bytes + 1024 * 1024

    @property
    def temp_dir(self) -> Path:
        """Directory for intermediate processing files. It lives inside
        the configured storage area (never the OS temp dir), so retention
        and filesystem restrictions cover scratch files too. Callers
        create it on demand and clean their files in finally blocks."""
        return self.storage_dir / "tmp"

settings = Settings.from_env()
