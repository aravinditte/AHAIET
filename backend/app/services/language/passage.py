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
    # AHAIET-012: the full line-layout token stream — one slot per
    # original line, blank lines included with their exact positions —
    # so reconstruction can reproduce leading/trailing/multiple blank
    # lines and paragraph breaks instead of collapsing them.
    line_slots: list[bool] = field(default_factory=list)  # True = blank line

    @property
    def has_multiple_nonblank_segments(self) -> bool:
        return len(self.segments) > 1

    @property
    def contains_multiple_lines(self) -> bool:
        """True when the ORIGINAL text has line boundaries at all
        (NEW-09) — including exactly one nonblank segment padded by
        blank lines. Routing decisions use this, not the segment
        count: any line-structured input goes through the
        layout-preserving passage flow."""
        return self.total_lines > 1

    @property
    def is_multiline(self) -> bool:
        # Backwards-compatible alias: multiple nonblank segments.
        return self.has_multiple_nonblank_segments


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
            out.line_slots.append(False)
            out.segments.append(Segment(index=len(out.segments),
                                        source_text=line.strip(),
                                        line_number=i + 1))
        else:
            out.line_slots.append(True)
            out.blank_lines += 1
    return out


def reassemble(segment_texts: list[str | None],
               segmentation: Segmentation | None = None) -> str:
    """Join per-segment English outputs in order. Untranslated segments
    contribute an empty line so the output keeps the input's line count
    and the gap is visible rather than silently closed up.

    When the Segmentation is supplied (AHAIET-012), the output is
    rebuilt from the original line slots: blank lines reappear at
    their exact original positions (leading, trailing, and repeated),
    so a source `verse1\n\nverse2` yields `translation1\n\ntranslation2`.
    Without it, the legacy join of the segment outputs is used."""
    if segmentation is None or not segmentation.line_slots:
        return "\n".join(t if t is not None else "" for t in segment_texts)
    out: list[str] = []
    seg_iter = iter(segment_texts)
    for is_blank in segmentation.line_slots:
        if is_blank:
            out.append("")
        else:
            nxt = next(seg_iter, None)
            out.append(nxt if nxt is not None else "")
    return "\n".join(out)
