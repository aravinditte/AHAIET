"""Shared validation of decoder subprocess output (AHAIET-021).

Rules for one segment:
- exit code 0 with empty / whitespace-only stdout is NOT a success:
  it raises translation_empty_output.
- multiline stdout for a single segment is an alignment error
  (translation_output_alignment) unless every extra line is blank —
  blank padding lines are dropped, never joined silently.
For a batch, the non-blank output lines must align exactly with the
input segments, one line per segment, in order.
"""
from __future__ import annotations
from app.core.errors import UnavailableError


def validate_single(stdout: str, engine: str) -> str:
    lines = [ln for ln in (stdout or "").splitlines() if ln.strip()]
    if not lines:
        raise UnavailableError(
            "translation_empty_output",
            f"The {engine} decoder exited successfully but produced no output text, "
            "so no translation was produced.",
            "Empty decoder output is treated as a failure, never as an empty translation.")
    if len(lines) > 1:
        raise UnavailableError(
            "translation_output_alignment",
            f"The {engine} decoder produced {len(lines)} output lines for one input segment; "
            "the output cannot be aligned to the segment, so no translation was produced.",
            "Only trailing/leading blank lines are tolerated; extra text lines are an error.")
    return lines[0].strip()


def validate_batch(stdout: str, expected: int, engine: str) -> list[str]:
    lines = [ln for ln in (stdout or "").splitlines() if ln.strip()]
    if len(lines) != expected:
        raise UnavailableError(
            "translation_output_alignment",
            f"The {engine} decoder produced {len(lines)} output lines for {expected} input "
            "segments; batch output must align one line per segment, so no batch "
            "translation was produced.",
            "Line-count alignment is strict for batched decoding.")
    return [ln.strip() for ln in lines]
