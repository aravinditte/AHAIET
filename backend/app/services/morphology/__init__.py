"""Morphology package: re-export the service functions so callers can
use `from app.services import morphology; morphology.analyze(...)`."""
from .service import (analyze, analyze_aramaic, analyze_hebrew,  # noqa: F401
                      corpus_available, status)
