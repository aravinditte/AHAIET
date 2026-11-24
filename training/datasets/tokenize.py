"""Command-line tokenizer for corpus preparation.

The tokenization rules live in exactly one place — the backend module
app/services/language/tokenize.py — so training files and runtime
inference can never drift apart. This module re-exports those functions
and adds a stdin/stdout CLI used by the SMT pipeline when the Moses
tokenizer scripts are not installed (the substitution is logged by the
orchestrator).

Usage:
  python tokenize.py --mode source --view vocalized   < in.txt > out.txt
  python tokenize.py --mode source --view consonantal < in.txt > out.txt
  python tokenize.py --mode target                    < in.txt > out.txt
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services.language.normalize import normalize_nodiac  # noqa: E402
from app.services.language.tokenize import (  # noqa: E402
    detokenize_target, tokenize_source, tokenize_target)

__all__ = ["tokenize_source", "tokenize_target", "detokenize_target",
           "tokenize_source_view", "main"]


def tokenize_source_view(text: str, view: str) -> list[str]:
    """Tokenize source text in one of the two documented training views.

    vocalized:    canonical text, niqqud/cantillation preserved.
    consonantal:  diacritic-stripped search-style view (normalize_nodiac);
                  a separate, labelled view — never a replacement for
                  the canonical text.
    """
    if view == "consonantal":
        text = normalize_nodiac(text)
    elif view != "vocalized":
        raise ValueError(f"unknown source view '{view}' (expected vocalized|consonantal)")
    return tokenize_source(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AHAIET corpus tokenizer (see module docstring)")
    ap.add_argument("--mode", choices=["source", "target"], required=True)
    ap.add_argument("--view", choices=["vocalized", "consonantal"], default="vocalized")
    args = ap.parse_args(argv)
    out_lines = []
    for line in sys.stdin.read().splitlines():
        if args.mode == "source":
            out_lines.append(" ".join(tokenize_source_view(line, args.view)))
        else:
            out_lines.append(" ".join(tokenize_target(line)))
    sys.stdout.write("\n".join(out_lines) + ("\n" if out_lines else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
