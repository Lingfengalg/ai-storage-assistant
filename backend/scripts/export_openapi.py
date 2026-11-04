"""Run from repository root: python backend/scripts/export_openapi.py."""

import json
from pathlib import Path

from app.main import create_app

target = Path(__file__).resolve().parents[2] / "shared" / "openapi.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(
    json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(f"Exported {target.name}")
