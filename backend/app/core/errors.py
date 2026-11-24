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
