from __future__ import annotations
def is_available() -> bool:
    try:
        import kraken  # noqa: F401
        return True
    except Exception:
        return False
