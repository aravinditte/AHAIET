"""Stage timing instrumentation.

A tiny dependency-free helper used by the OCR, process, and translation
paths to record how long each pipeline stage actually took on this
machine. It only measures; it sets no targets and asserts nothing about
speed. Timings are reported to callers as an additive response field
(`stage_timings_ms`) and stored on job rows so a developer can profile
real runs locally (see docs/VERIFICATION.md).

Stage names used across the codebase:
  decode, preprocessing, ocr, language, retrieval, translation,
  verification, total
"""
from __future__ import annotations
import time
from contextlib import contextmanager


class StageTimer:
    """Accumulates per-stage durations in milliseconds."""

    def __init__(self) -> None:
        self._stages: dict[str, float] = {}
        self._started = time.perf_counter()

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self._stages[name] = self._stages.get(name, 0.0) + (time.perf_counter() - start) * 1000.0

    def record(self, name: str, duration_ms: float) -> None:
        self._stages[name] = self._stages.get(name, 0.0) + float(duration_ms)

    def merge(self, other: dict | None, prefix: str = "") -> None:
        for name, value in (other or {}).items():
            if isinstance(value, (int, float)):
                self.record(f"{prefix}{name}", float(value))

    def as_dict(self, include_total: bool = True) -> dict[str, int]:
        out = {name: int(round(value)) for name, value in self._stages.items()}
        if include_total:
            out["total"] = int(round((time.perf_counter() - self._started) * 1000.0))
        return out
