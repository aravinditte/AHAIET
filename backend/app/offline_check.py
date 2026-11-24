"""Offline self-check: statically scan the backend for outbound-call
constructs and report anything that could make a network call at
runtime.

    python -m app.offline_check            # human-readable report
    python -m app.offline_check --json     # machine-readable report

Exit code is 0 when no runtime finding exists, 1 otherwise.

The setup/runtime boundary (see docs/OFFLINE_OPERATION.md):
- SETUP-ONLY code may use the network during explicit provisioning:
  the corpus importer (app/corpus/import_morphhb.py, only when run with
  --download by the operator) and the shell/PowerShell provisioning
  scripts under scripts/ (not part of this package, not scanned here).
  Those files are allowlisted below and reported as informational.
- RUNTIME code (API routes, services, storage, adapters) must make no
  network calls at all: OCR and translation are local subprocesses or
  in-process libraries, corpora and models are local files, and there
  is no telemetry, update check, or remote registry lookup.

The scan is a static text scan for the constructs that could open a
connection. It is a guardrail, not a proof: the runtime proof is the
offline integration test (backend/tests/test_offline.py), which blocks
sockets and exercises the real request paths.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent

# Files that are allowed to contain outbound-call constructs, with the
# reason. Each is setup-only tooling, never imported by the API app
# (app/main.py imports routes -> services -> storage only).
ALLOWLIST: dict[str, str] = {
    "corpus/import_morphhb.py": "setup-only corpus importer; network use happens "
                                "only under its explicit --download flag",
    "offline_check.py": "this scanner; it contains the patterns it searches for",
}

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("urllib.request", re.compile(r"\burllib\.request\b")),
    ("urlopen", re.compile(r"\burlopen\b")),
    ("requests library", re.compile(r"^\s*(?:import\s+requests\b|from\s+requests\b|requests\.(?:get|post|put|delete|request|Session)\b)", re.M)),
    ("httpx client", re.compile(r"\bhttpx\.(?:Client|AsyncClient|get|post|request)\b")),
    ("socket module", re.compile(r"^\s*(?:import\s+socket\b|from\s+socket\b|socket\.socket\b)", re.M)),
    ("http.client", re.compile(r"\bhttp\.client\b")),
]


def scan(root: Path | None = None) -> dict:
    """Scan the app package. Returns {runtime_findings, setup_only} —
    each a list of {file, line, construct} metadata entries."""
    root = root or PACKAGE_ROOT
    runtime_findings: list[dict] = []
    setup_only: list[dict] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for construct, pattern in PATTERNS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                entry = {"file": rel, "line": line, "construct": construct}
                if rel in ALLOWLIST:
                    entry["reason"] = ALLOWLIST[rel]
                    setup_only.append(entry)
                else:
                    runtime_findings.append(entry)
    return {"runtime_findings": runtime_findings, "setup_only": setup_only}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Static offline self-check: scan the backend package for "
                    "outbound-call constructs outside the setup-only allowlist.")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)
    report = scan()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if report["runtime_findings"]:
            print("RUNTIME FINDINGS (must be empty for offline operation):")
            for f in report["runtime_findings"]:
                print(f"  {f['file']}:{f['line']}  {f['construct']}")
        else:
            print("No outbound-call constructs found in runtime code.")
        if report["setup_only"]:
            print("Setup-only allowlist (network permitted during explicit provisioning):")
            for f in report["setup_only"]:
                print(f"  {f['file']}:{f['line']}  {f['construct']} — {f['reason']}")
    return 1 if report["runtime_findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
