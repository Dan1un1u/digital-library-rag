import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from dlrag.api.main import create_app
from dlrag.api.services import assemble
from dlrag.shared.config import Settings
from scripts.seed_demo import create_pdf


@pytest.fixture
def settings(tmp_path):
    return Settings(app_mode="mock", data_dir=tmp_path / "data", _env_file=None)


@pytest.fixture
def services(settings):
    return assemble(settings)


@pytest.fixture
def client(services):
    with TestClient(create_app(services=services), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "synthetic.pdf"
    pages = json.loads((Path(__file__).parents[1] / "fixtures/pages.json").read_text(encoding="utf-8"))
    create_pdf(path, pages)
    return path


@pytest.fixture
def imported(client, pdf):
    response = client.post("/documents", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")},
                           data={"metadata_json": json.dumps({"title": "合成测试资料", "year": 2024, "topics": ["自然科学", "合成测试"]})})
    assert response.status_code == 200, response.text
    return response.json()
