from __future__ import annotations
import shutil, subprocess
from pathlib import Path
from app.core.errors import UnavailableError
def run_moses(text: str, artifact_path: Path) -> str:
    exe = shutil.which("moses")
    if not exe or not artifact_path.exists():
        raise UnavailableError("moses_unavailable", "Moses SMT binary or model artifact is not available.", f"artifact={artifact_path}")
    proc = subprocess.run([exe, "-f", str(artifact_path)], input=text, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise UnavailableError("moses_failed", "Moses SMT failed.", (proc.stderr or "")[:500])
    return proc.stdout.strip()
