#!/usr/bin/env python3
"""Report installed dependency versions against the declared bounds.

Reads the dependency specifiers from backend/pyproject.toml (runtime
dependencies plus the dev/training/kraken extras) and from
training/requirements.txt, then compares them with the versions
installed in the *current* Python environment (importlib.metadata —
pip's local state; this script makes no network calls).

Usage:
    python scripts/check_dependencies.py [--strict]

Exit code: 0 when every declared package is installed and in range
(or, without --strict, even when some are missing — missing optional
extras are normal); 1 with --strict when anything is missing or out
of range. The report is the point: it shows, per package, the declared
specifier, the installed version (or "not installed"), and the verdict.
"""
from __future__ import annotations
import argparse
import importlib.metadata as md
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _parse_version(text: str) -> tuple[int, ...]:
    parts = []
    for piece in re.split(r"[.\-+]", text.strip()):
        m = re.match(r"(\d+)", piece)
        parts.append(int(m.group(1)) if m else 0)
    return tuple(parts)


def _satisfies(installed: str, specifier: str) -> bool:
    """Minimal evaluator for the specifier shapes this repo declares:
    comma-separated >=, <, <=, >, == clauses (no ~=, no .* pins)."""
    inst = _parse_version(installed)
    for clause in specifier.split(","):
        clause = clause.strip()
        if not clause:
            continue
        m = re.match(r"(>=|<=|==|>|<)\s*(.+)", clause)
        if not m:
            return False
        op, wanted = m.group(1), _parse_version(m.group(2))
        n = max(len(inst), len(wanted))
        a = inst + (0,) * (n - len(inst))
        b = wanted + (0,) * (n - len(wanted))
        ok = {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b, "==": a == b}[op]
        if not ok:
            return False
    return True


def _split_requirement(req: str) -> tuple[str, str]:
    m = re.match(r"([A-Za-z0-9_.\-]+)\s*(.*)", req.strip())
    return (m.group(1), m.group(2).strip()) if m else (req.strip(), "")


def collect_requirements() -> list[tuple[str, str, str]]:
    """(name, specifier, origin) for every declared dependency."""
    out: list[tuple[str, str, str]] = []
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11 fallback: no stdlib tomllib
        tomllib = None
    pyproject = REPO / "backend" / "pyproject.toml"
    if tomllib is not None and pyproject.exists():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project", {})
        for req in project.get("dependencies", []):
            name, spec = _split_requirement(req)
            out.append((name, spec, "backend/pyproject.toml [project]"))
        for extra, reqs in (project.get("optional-dependencies") or {}).items():
            for req in reqs:
                name, spec = _split_requirement(req)
                out.append((name, spec, f"backend/pyproject.toml [extra: {extra}]"))
    req_file = REPO / "training" / "requirements.txt"
    if req_file.exists():
        for line in req_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                name, spec = _split_requirement(line)
                out.append((name, spec, "training/requirements.txt"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Installed versions vs declared dependency bounds (no network).")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when any declared package is missing or out of range")
    args = ap.parse_args(argv)
    problems = 0
    seen: set[tuple[str, str]] = set()
    for name, spec, origin in collect_requirements():
        if (name.lower(), spec) in seen:
            continue
        seen.add((name.lower(), spec))
        try:
            installed = md.version(name)
        except md.PackageNotFoundError:
            installed = None
        if installed is None:
            verdict = "not installed"
            problems += 1
        elif spec and not _satisfies(installed, spec):
            verdict = "OUT OF RANGE"
            problems += 1
        else:
            verdict = "ok"
        print(f"{name:<18} declared {spec or '(any)':<22} installed {installed or '-':<12} {verdict:<14} [{origin}]")
    print(f"\n{problems} package(s) missing or out of range "
          f"(optional extras being absent is normal; --strict turns this into a failure).")
    return 1 if (args.strict and problems) else 0


if __name__ == "__main__":
    sys.exit(main())
