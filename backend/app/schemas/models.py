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
class ProcessRequest(BaseModel):
    upload_id: str
    language_profile: str | None = None
    preprocessing_profile: str = "conservative"
    psm: int | None = None
class MorphologyRequest(BaseModel):
    text: str = Field(default="")
    language: str
class RetrievalRequest(BaseModel):
    text: str = Field(default="")
    language: str
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
    source_references: list = Field(default_factory=list)
    uncertain_spans: list = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model_versions: dict = Field(default_factory=dict)
    processing_time_ms: int = 0
