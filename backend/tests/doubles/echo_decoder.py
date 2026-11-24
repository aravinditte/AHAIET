"""Portable decoder test double (AHAIET-048).

A Python script invoked through sys.executable, so the subprocess
contract tests run identically on Windows and POSIX — no POSIX
shebang required. It echoes its stdin back line by line with a fixed
prefix, which is exactly the line-in/line-out contract the Moses and
Marian adapters rely on. It is a test double for the subprocess
contract only; it is not a translation model and is never used by the
application at runtime.

Usage: python echo_decoder.py [config args ignored...]
Reads stdin lines, writes "EN: <line>" per line.
"""
from __future__ import annotations
import sys


def main() -> int:
    for line in sys.stdin:
        line = line.rstrip("\n")
        if line.strip():
            sys.stdout.write(f"EN: {line}\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
