import os
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from app.main import create_app
import app.main as main_module

def test_static_mount_serves_index_html_when_dist_exists(tmp_path, monkeypatch):
    # Create fake dist directory with index.html
    dist_dir = tmp_path / "frontend" / "dist"
    dist_dir.mkdir(parents=True)
    index_file = dist_dir / "index.html"
    index_file.write_text("<!DOCTYPE html><html><body><div id='root'>Vera Test Build UI</div></body></html>", encoding="utf-8")

    # Mock dependencies
    llm = MagicMock()
    tavily = MagicMock()
    memory = MagicMock()
    memory.list_watches.return_value = []

    # Point FRONTEND_DIST to the temporary directory
    monkeypatch.setattr(main_module, "FRONTEND_DIST", str(dist_dir))

    app = create_app(llm, tavily, memory)
    client = TestClient(app)

    # Root should return 200 with HTML from index.html
    res = client.get("/")
    assert res.status_code == 200
    assert "Vera Test Build UI" in res.text

    # API route should still work with higher priority
    res_api = client.get("/api/telemetry")
    assert res_api.status_code == 200
