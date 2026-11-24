from __future__ import annotations
from pydantic import BaseModel, Field

class TranslateRequest(BaseModel):
    text: str = Field(default="")
    source_language: str | None = None
    corrected_source_text: str | None = None
class OcrRequest(BaseModel):
    upload_id: str
    language_profile: str | None = None
    preprocessing_profile: str = "conservative"
    psm: int | None = None
    # OCR engine routing: "auto" (Tesseract for the square Hebrew script
    # profile), "tesseract", or "kraken". The script profile selects the
    # writing system; historical profiles are served only by Kraken with
    # a verified checkpoint (see the script support matrix).
    engine: str = "auto"
    script_profile: str = "hebrew_square"
class ProcessRequest(BaseModel):
    upload_id: str
    language_profile: str | None = None
    preprocessing_profile: str = "conservative"
    psm: int | None = None
    engine: str = "auto"
    script_profile: str = "hebrew_square"
class MorphologyRequest(BaseModel):
    text: str = Field(default="")
    language: str
class RetrievalRequest(BaseModel):
    text: str = Field(default="")
    language: str
class VerificationCheck(BaseModel):
    """One deterministic verification check. Status is one of
    pass | warn | fail | not_applicable. A check flags risk; no check
    and no combination of checks establishes that a translation is
    semantically correct."""
    name: str
    status: str
    detail: str = ""
    evidence: dict = Field(default_factory=dict)

class VerificationReport(BaseModel):
    """Structured result of the candidate-verification service.
    overall_status is one of no_issues_found | warnings | high_risk —
    deliberately never 'correct' or 'verified'."""
    overall_status: str
    checks: list[VerificationCheck] = Field(default_factory=list)
    # Measured inputs only: OCR engine confidence (when the source came
    # from OCR), the retrieval match type, and metrics a real evaluation
    # run recorded on the model card. Never a computed probability that
    # the translation is right.
    empirical_uncertainty: dict = Field(default_factory=dict)
    note: str = ("Deterministic checks flag risks (omissions, additions, "
                 "number/negation/name mismatches). They cannot prove "
                 "semantic correctness.")

class PassageSegmentResult(BaseModel):
    index: int
    source_text: str
    status: str  # translated | unavailable | failed
    english_translation: str | None = None
    method: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

class TranslationProvenance(BaseModel):
    """Where a successful output came from, in full: the engine, the
    model identity and artifact hash, the dataset/model-card references,
    and the retrieval citation when a corpus match produced the text."""
    engine: str | None = None
    model_id: str | None = None
    model_version: str | None = None
    artifact_sha256: str | None = None
    evaluation_state: str | None = None
    dataset_card_sha256: str | None = None
    retrieval_citation: dict | None = None
    cached: bool = False

class TranslationResponse(BaseModel):
    request_id: str
    status: str
    detected_language: str | None = None
    selected_language: str | None = None
    script: str | None = None
    original_ocr_text: str | None = None
    corrected_source_text: str | None = None
    english_translation: str | None = None
    translation_method: str | None = None
    # Additive fields populated when a trained local model produced the
    # output (engine actually used, its recorded version and artifact
    # hash, and word-level source coverage incl. OOV words). They stay
    # null for verified_reference responses, whose shape is unchanged.
    engine: str | None = None
    model_version: str | None = None
    artifact_sha256: str | None = None
    coverage: dict | None = None
    source_references: list = Field(default_factory=list)
    uncertain_spans: list = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model_versions: dict = Field(default_factory=dict)
    processing_time_ms: int = 0
    # Additive hybrid-verification and passage fields. All stay null /
    # empty for responses produced before this work existed in shape;
    # verified_reference responses gain verification + provenance too.
    verification: VerificationReport | None = None
    provenance: TranslationProvenance | None = None
    segments: list[PassageSegmentResult] = Field(default_factory=list)
    unevaluated_model: bool = False
    cached: bool = False
    stage_timings_ms: dict = Field(default_factory=dict)
