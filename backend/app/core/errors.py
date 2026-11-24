from __future__ import annotations
class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, detail: str | None = None):
        super().__init__(message)
        self.status_code, self.code, self.message, self.detail = status_code, code, message, detail
class UnavailableError(AppError):
    def __init__(self, code: str, message: str, detail: str | None = None):
        super().__init__(503, code, message, detail)
class ValidationAppError(AppError):
    def __init__(self, code: str, message: str, detail: str | None = None):
        super().__init__(400, code, message, detail)
def error_body(err: AppError) -> dict:
    return {"error": {"code": err.code, "message": err.message, "detail": err.detail}}

import re as _re

_PATH_RE = _re.compile(r"(?:[A-Za-z]:\\|/)[^\s'\"]+")

def sanitize_detail(detail: str | None, limit: int = 300) -> str | None:
    """Sanitized error detail for production responses (AHAIET-055):
    absolute filesystem paths are stripped and the text is bounded, so
    adapter failures cannot leak the operator's directory layout or a
    raw binary's unbounded stderr. The full detail belongs in
    operator-side logs only."""
    if detail is None:
        return None
    cleaned = _PATH_RE.sub("<path>", str(detail))
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit]
