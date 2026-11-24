"""HTTP security middleware: response headers, a request body ceiling,
and a per-client rate limiter for the expensive endpoints.

Design notes (see docs/SECURITY.md for the full threat model):
- These are pure ASGI middlewares so they also cover error responses
  produced by exception handlers and by the framework itself.
- The rate limiter is in-process and keyed by (client host, path). It is
  a resource-exhaustion guard for a single-operator local application,
  not a distributed quota system: limits reset when the process restarts
  and are not shared between processes. That is stated, not hidden.
- The body ceiling complements (never replaces) the upload validation in
  services/preprocessing: an oversized body is rejected before the app
  reads it, and the upload route still enforces its own byte/pixel
  limits on whatever passes.
"""
from __future__ import annotations
import json
import threading
import time
from collections import deque

SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    # The API serves JSON and stored images only; it never needs to load
    # scripts, styles, or frames of its own.
    (b"content-security-policy", b"default-src 'self'; frame-ancestors 'none'"),
)


def _error_response(status_code: int, code: str, message: str,
                    detail: str | None = None, extra_headers: list | None = None):
    """A Starlette JSONResponse carrying the standard error envelope."""
    from fastapi.responses import JSONResponse
    from app.core.errors import AppError, error_body
    resp = JSONResponse(status_code=status_code,
                        content=error_body(AppError(status_code, code, message, detail)))
    for name, value in (extra_headers or []):
        resp.headers[name] = value
    return resp


class SecurityHeadersMiddleware:
    """Add the SECURITY_HEADERS set to every HTTP response, including
    error responses, without overwriting a header a route set itself."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = [(k.lower(), v) for k, v in message.get("headers", [])]
                present = {k for k, _ in headers}
                for name, value in SECURITY_HEADERS:
                    if name not in present:
                        headers.append((name, value))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """Reject request bodies larger than max_bytes with a structured
    413 before the application reads them.

    The body is buffered up to the ceiling (bounded by max_bytes plus
    one chunk) and replayed to the application unchanged. Buffering is
    acceptable here because the ceiling is a small multiple of the
    upload limit, and it makes the guard correct for chunked bodies
    with no Content-Length as well as for declared lengths.
    """

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return
        declared = None
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    declared = int(value)
                except (TypeError, ValueError):
                    declared = None
        if declared is not None and declared > self.max_bytes:
            resp = _error_response(
                413, "request_too_large",
                f"Request body exceeds the limit of {self.max_bytes} bytes.",
                f"Content-Length was {declared} bytes.")
            await resp(scope, receive, send)
            return
        messages: list[dict] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                messages.append(message)
                continue
            total += len(message.get("body", b""))
            messages.append(message)
            if total > self.max_bytes:
                resp = _error_response(
                    413, "request_too_large",
                    f"Request body exceeds the limit of {self.max_bytes} bytes.",
                    f"Body exceeded {self.max_bytes} bytes while streaming.")
                await resp(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        replay = iter(messages)

        async def replay_receive():
            try:
                return next(replay)
            except StopIteration:
                return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)


class RateLimitMiddleware:
    """Fixed-window per-client rate limiter for selected POST paths.

    limits maps an exact request path to a maximum number of requests
    per window_seconds per client host. Requests over the budget get a
    structured 429 with a Retry-After header. Only the configured paths
    are limited; everything else passes through untouched.
    """

    def __init__(self, app, limits: dict[str, int], window_seconds: float = 60.0,
                 max_clients: int = 10000, trust_forwarded_for: bool = False):
        self.app = app
        self.limits = {p: n for p, n in limits.items() if n and n > 0}
        self.window = window_seconds
        self.max_clients = max_clients
        self.trust_forwarded_for = trust_forwarded_for
        self._hits: dict[tuple[str, str], deque] = {}
        self._lock = threading.Lock()
        self._last_prune = 0.0

    def _prune(self, now: float) -> None:
        """Periodic registry hygiene (AHAIET-043): drop buckets whose
        window has fully expired and enforce the hard cap on tracked
        client keys, so the registry cannot grow without bound for
        one-off client identifiers."""
        if now - self._last_prune < self.window:
            return
        self._last_prune = now
        expired = [k for k, bucket in self._hits.items()
                   if not bucket or now - bucket[-1] >= self.window]
        for k in expired:
            self._hits.pop(k, None)
        overflow = len(self._hits) - self.max_clients
        if overflow > 0:
            for k in list(self._hits)[:overflow]:
                self._hits.pop(k, None)

    def _allow(self, client: str, path: str, limit: int) -> tuple[bool, int]:
        now = time.monotonic()
        key = (client, path)
        with self._lock:
            self._prune(now)
            bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] >= self.window:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(self.window - (now - bucket[0])) + 1)
                return False, retry_after
            bucket.append(now)
            return True, 0

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        limit = self.limits.get(path)
        if limit is None:
            await self.app(scope, receive, send)
            return
        client = (scope.get("client") or ("unknown", 0))[0]
        if self.trust_forwarded_for:
            # Only behind a configured trusted reverse proxy
            # (AHAIET-043): otherwise X-Forwarded-For is
            # client-controlled and must not key the limiter.
            for name, value in scope.get("headers", []):
                if name.lower() == b"x-forwarded-for":
                    client = value.decode("latin-1").split(",")[0].strip() or client
                    break
        allowed, retry_after = self._allow(client, path, limit)
        if not allowed:
            resp = _error_response(
                429, "rate_limited",
                f"Too many requests to {path}; the per-client limit is "
                f"{limit} per {int(self.window)} seconds.",
                "Wait for the window to pass, or raise the configured limit "
                "(see docs/SECURITY.md).",
                extra_headers=[("Retry-After", str(retry_after))])
            await resp(scope, receive, send)
            return
        await self.app(scope, receive, send)


def error_envelope_bytes(status_code: int, code: str, message: str) -> bytes:
    """Serialised standard error envelope (used by tests and tooling)."""
    return json.dumps({"error": {"code": code, "message": message, "detail": None}}).encode("utf-8")
