"""Retrieval package: re-export the service functions so callers can
use `from app.services import retrieval; retrieval.lookup(...)`."""
from .service import (bump_corpus_revision, corpus_counts, corpus_revision,  # noqa: F401
                      invalidate_lookup_cache, lookup, profile_evidence,
                      status)
