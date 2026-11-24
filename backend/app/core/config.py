from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent

def _int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    return int(v) if v not in (None, "") else default

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
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")

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
        )

settings = Settings.from_env()
