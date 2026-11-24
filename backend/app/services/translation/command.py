"""Decoder command resolution (NEW-05, NEW-13).

A decoder command in configuration may be:
- a plain string: a binary name ("moses"), a path, or a name/path
  with arguments ("moses -f cfg" style strings are split with shlex);
- a command VECTOR (list form), e.g. [sys.executable, "decoder.py"],
  which is how test doubles and interpreter-hosted decoders are
  configured. Vectors are executed directly — never through a shell —
  and every element must be a nonempty string.
"""
from __future__ import annotations
import json
import os
import shlex
import shutil
from pathlib import Path


def resolve_command(cmd) -> list[str]:
    """Normalise a configured decoder command to an argv vector."""
    if isinstance(cmd, (list, tuple)):
        parts = [str(c) for c in cmd]
    elif isinstance(cmd, str):
        text = cmd.strip()
        if text.startswith("["):
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError("command vector JSON must be an array")
            parts = [str(c) for c in parsed]
        else:
            parts = shlex.split(text)
    else:
        raise ValueError(f"unsupported decoder command type: {type(cmd).__name__}")
    if not parts or any(not p for p in parts):
        raise ValueError("decoder command must not be empty")
    return parts


def command_available(parts: list[str]) -> bool:
    """True when argv[0] can actually be executed: a path must exist,
    a bare name must resolve on PATH. This is what makes a Python
    script invoked as [sys.executable, script] a genuinely executable
    test double while a bare non-executable file is not (NEW-05)."""
    exe = parts[0]
    if os.path.sep in exe or (os.path.altsep and os.path.altsep in exe):
        return Path(exe).exists()
    return shutil.which(exe) is not None


def display_command(parts: list[str]) -> str:
    return " ".join(parts)
