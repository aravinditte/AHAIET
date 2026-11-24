"""Documentation link checker (AHAIET-053), runnable directly or via
pytest (test_docs_links_resolve). Every relative Markdown link and
every repo-relative path mentioned in docs/ACCEPTANCE_AUDIT.md must
resolve to a real file in the tree. Code only — run by the developer
or CI; not executed by the build assistant.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_PATH_RE = re.compile(r"`((?:backend|frontend|training|scripts|docs|artifacts)/[^`\s]+)`")


def broken_links() -> list[str]:
    broken: list[str] = []
    for md in sorted((REPO / "docs").glob("*.md")) + [REPO / "README.md"]:
        text = md.read_text(encoding="utf-8")
        for target in _LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            path = (md.parent / target.split("#")[0]).resolve()
            if not path.exists():
                broken.append(f"{md.name}: link -> {target}")
    audit = REPO / "docs" / "ACCEPTANCE_AUDIT.md"
    if audit.exists():
        for rel in _PATH_RE.findall(audit.read_text(encoding="utf-8")):
            if "*" in rel or "<" in rel:
                continue
            if not (REPO / rel.rstrip(".,)")).exists():
                broken.append(f"ACCEPTANCE_AUDIT.md: path -> {rel}")
    return broken


def test_docs_links_resolve():
    assert broken_links() == []


if __name__ == "__main__":
    problems = broken_links()
    for p in problems:
        print("BROKEN:", p)
    sys.exit(1 if problems else 0)
