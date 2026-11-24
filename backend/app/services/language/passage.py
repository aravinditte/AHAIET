"""Passage segmentation for complete multiline texts.

Splits a multiline source text into line-sized segments (verse-like
units) so each segment can be routed through retrieval / trained-model
translation independently, then reassembled in the original order.
Blank lines are structure, not segments: they are preserved as
paragraph breaks in the reassembled output and counted so callers can
see the input's shape. Nothing is merged, reordered, or dropped.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Segment:
    index: int
    source_text: str
    line_number: int  # 1-based line in the original input


@dataclass
class Segmentation:
    segments: list[Segment] = field(default_factory=list)
    blank_lines: int = 0
    total_lines: int = 0

    @property
    def is_multiline(self) -> bool:
        return len(self.segments) > 1


def split_segments(text: str) -> Segmentation:
    """One non-blank line = one segment. CRLF and lone CR are normalised
    to LF for splitting only; the segment text itself is the stripped
    line content (leading/trailing whitespace on a line carries no
    linguistic content in the corpus verse format)."""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")
    out = Segmentation(total_lines=len(lines))
    for i, line in enumerate(lines):
        if line.strip():
            out.segments.append(Segment(index=len(out.segments),
                                        source_text=line.strip(),
                                        line_number=i + 1))
        else:
            out.blank_lines += 1
    return out


def reassemble(segment_texts: list[str | None]) -> str:
    """Join per-segment English outputs in order. Untranslated segments
    contribute an empty line so the output keeps the input's line count
    and the gap is visible rather than silently closed up."""
    return "\n".join(t if t is not None else "" for t in segment_texts)
