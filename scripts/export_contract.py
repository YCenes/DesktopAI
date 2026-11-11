"""OpenAPI snapshot üretimi; hiçbir gerçek oturum veya sunucu açmaz."""
import json
from pathlib import Path

from nova.api.app import create_app
from nova.infrastructure.config import Settings

target = Path(__file__).resolve().parents[1] / "contracts" / "backend.openapi.json"
target.parent.mkdir(exist_ok=True)
schema = create_app(Settings(session_token="0" * 64, port=43210)).openapi()
target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("OpenAPI snapshot oluşturuldu.")
