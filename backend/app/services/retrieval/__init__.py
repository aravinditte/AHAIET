"""Retrieval package: re-export the service functions so callers can
use `from app.services import retrieval; retrieval.lookup(...)`."""
from .service import (corpus_counts, invalidate_lookup_cache, lookup,  # noqa: F401
                      status)
