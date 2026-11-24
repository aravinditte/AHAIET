# API (base http://127.0.0.1:8000)
All errors: {"error":{"code","message","detail"}}.
- GET /api/health -> {status:"ok",service,version,db_ok}
- GET /api/capabilities -> live checks: db_ok, upload limits/formats, preprocessing (pillow, opencv bool), ocr {tesseract{available,path,reason}, kraken{available,reason}, status}, translation {status, reason}, languages.
- GET /api/languages -> biblical_hebrew + biblical_aramaic (separate, profile_defined, translation model_not_provisioned) + 8 future profiles as unsupported/not_available.
- GET /api/models -> contents of artifacts/manifests/models.json verbatim.
- POST /api/uploads (multipart file) -> {id,format,width,height,size_bytes,sha256}; 400 invalid_image / unsupported_format / upload_too_large / image_too_many_pixels. Validation is by content (Pillow), never extension.
- GET /api/uploads/{id} -> stored image bytes for preview; 404 upload_not_found.
- POST /api/ocr {upload_id, language_profile?} -> 200 {request_id,status,original_ocr_text,language,processing_time_ms} when a real engine exists; 503 ocr_unavailable otherwise.
- POST /api/translate {text, source_language?, corrected_source_text?} -> TranslationResponse fields: request_id,status,detected_language,selected_language,script,original_ocr_text,corrected_source_text,english_translation,translation_method,source_references,uncertain_spans,warnings,model_versions,processing_time_ms. 400 empty_text; 503 translation_model_unavailable when no provisioned artifact exists.
- POST /api/process {upload_id, language_profile?} -> creates a jobs row, runs OCR stage; {job_id,status,stage,error}. With no OCR engine the job ends status=failed, stage=ocr, with the reason recorded.
- GET /api/jobs/{id} -> job row; 404 job_not_found. GET /api/jobs/{id}/result -> {job_id,status,stage,error,result}.
- GET /api/history -> {history:[...]} (rows are written by /api/process). DELETE /api/history/{record_id} -> {deleted:id}; 404 history_not_found.
