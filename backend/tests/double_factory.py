"""Genuinely executable decoder test doubles (NEW-05).

A test double is only useful if the adapter can really execute it.
This factory writes, per platform:
- POSIX: a Python script with a `#!` shebang AND chmod 0o755, so the
  bare path is directly executable;
- Windows: the same script plus a `.cmd` wrapper that forwards to
  the interpreter.

Every double also exposes a command VECTOR, [sys.executable, script],
which the adapters accept via the command-vector config form — the
vector is the portable route on both platforms and is what most
tests should use. A bare `.py` path without a shebang/permissions is
NOT executable and must never be handed to an adapter as a binary.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path


def write_double(tmp_path: Path, name: str, body: str) -> dict:
    """Write a double from a Python body. Returns
    {"script": Path, "path": Path (bare-executable form),
     "vector": [sys.executable, script]}."""
    script = tmp_path / f"{name}.py"
    script.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
    if os.name == "nt":
        wrapper = tmp_path / f"{name}.cmd"
        wrapper.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
                           encoding="utf-8")
        path = wrapper
    else:
        script.chmod(0o755)
        path = script
    return {"script": script, "path": path,
            "vector": [sys.executable, str(script)]}


def echo_double(tmp_path: Path, name: str, prefix: str,
                counter: Path | None = None) -> dict:
    """A double that echoes stdin lines back with a fixed prefix —
    the line-in/line-out decoder contract."""
    lines = ["import sys"]
    if counter is not None:
        lines.append(f"open({str(counter)!r}, 'a').write('x')")
    lines += ["for line in sys.stdin:",
              f"    sys.stdout.write({prefix!r} + line)"]
    return write_double(tmp_path, name, "\n".join(lines) + "\n")


def hanging_double(tmp_path: Path, name: str, seconds: int = 30) -> dict:
    """A double that never answers in time (timeout tests)."""
    return write_double(tmp_path, name,
                        f"import time\ntime.sleep({seconds})\n")
