import json
from pathlib import Path

from app.main import create_app


def test_openapi_snapshot_matches_backend():
    path = Path(__file__).resolve().parents[2] / "shared" / "openapi.json"
    assert json.loads(path.read_text(encoding="utf-8")) == create_app().openapi()
