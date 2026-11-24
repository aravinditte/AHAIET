# Evaluation
evaluate_ocr.py runs the backend OCR service over the fixtures in training/ocr/fixtures/ and writes measured CER/WER + raw output to training/ocr/fixtures/ocr_measurement.json. It produces nothing until run on a machine with a provisioned Tesseract binary; no scores are recorded anywhere before that run.
