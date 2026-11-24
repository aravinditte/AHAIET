#!/usr/bin/env bash
# Provision the Tesseract OCR engine + Hebrew traineddata (Linux/macOS).
# Explicit provisioning only - the application never downloads at runtime.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
tessdata="$repo/.tools/tessdata"
mkdir -p "$tessdata"

echo "== Tesseract binary =="
if command -v tesseract >/dev/null 2>&1; then
  command -v tesseract; tesseract --version | head -1
else
  echo "Tesseract is NOT on PATH. Install it, e.g.:"
  echo "  Debian/Ubuntu: sudo apt-get install tesseract-ocr"
  echo "  macOS:         brew install tesseract"
  echo "Then re-run this script."
fi

echo "== Hebrew + English traineddata (Apache-2.0, tesseract-ocr/tessdata) =="
for lang in heb eng; do
  dest="$tessdata/$lang.traineddata"
  if [ -f "$dest" ]; then
    echo "$lang.traineddata already present: $dest"
  else
    url="https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/$lang.traineddata"
    echo "Downloading $url"
    curl -sL "$url" -o "$dest"
  fi
  sha256sum "$dest" || shasum -a 256 "$dest"
done

echo "== Backend environment =="
echo "export TESSDATA_PREFIX=\"$tessdata\""
echo "Set AHAIET_TESSERACT_CMD if tesseract is not on PATH."
echo "Then start the backend and check GET /api/capabilities - ocr.status should be 'available'."
