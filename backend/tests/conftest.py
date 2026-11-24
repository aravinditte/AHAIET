import io, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app

@pytest.fixture()
def settings(tmp_path):
    return Settings(storage_dir=tmp_path / "uploads", db_path=tmp_path / "test.db",
                    models_manifest=Path(__file__).resolve().parents[2] / "artifacts" / "manifests" / "models.json",
                    datasets_manifest=Path(__file__).resolve().parents[2] / "artifacts" / "manifests" / "datasets.json")
@pytest.fixture()
def client(settings):
    return TestClient(create_app(settings), raise_server_exceptions=False)
def png_bytes(w=16, h=16, color=(255,255,255)):
    buf = io.BytesIO(); Image.new("RGB", (w,h), color).save(buf, format="PNG"); return buf.getvalue()
