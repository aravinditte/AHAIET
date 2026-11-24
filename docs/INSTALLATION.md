# Installation (Windows-first)
Prerequisites: Windows PowerShell, VS Code, Python 3.11+ (py launcher), Node.js 20+/npm. Optional: Tesseract, WSL2 (Moses training, the translation-model work), Docker, NVIDIA GPU — none required to start the app.
1. .\scripts\setup-windows.ps1  (backend venv + pip install -e ".[dev]", frontend npm install)
2. .\scripts\verify-installation.ps1  (versions, Tesseract presence, backend pytest)
3. .\scripts\start-backend.ps1  (uvicorn 127.0.0.1:8000)
4. .\scripts\start-frontend.ps1  (next dev, port 3000)
Separate concerns: application installation (above) != dataset provisioning != OCR model installation != translation training != translation model installation. Each later step is explicit and recorded in artifacts/manifests/. Troubleshooting: backend unreachable in UI -> start backend first; OCR unavailable -> docs/OCR.md; port in use -> change --port and NEXT_PUBLIC_API_BASE together.
