import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli import InputError, load_product
from app.config import Settings
from app.llm import LLMError
from app.web import app, get_runtime
from tests.conftest import FakeLLM, good_draft

SETTINGS = Settings(base_url="http://fake", api_key="x", model="fake-model", max_attempts=2)


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "in.json"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_product_invalid_json(tmp_path):
    with pytest.raises(InputError, match="некорректный JSON"):
        load_product(write(tmp_path, '{"name": "x",'))


def test_load_product_missing_name(tmp_path):
    with pytest.raises(InputError, match="name"):
        load_product(write(tmp_path, '{"manufacturer": "Манотомь"}'))


def test_load_product_specs_not_object(tmp_path):
    with pytest.raises(InputError, match="specs"):
        load_product(write(tmp_path, '{"name": "x", "specs": ["a"]}'))


def test_load_product_missing_file(tmp_path):
    with pytest.raises(InputError, match="не удалось прочитать"):
        load_product(tmp_path / "nope.json")


@pytest.fixture
def client():
    fake = FakeLLM(good_draft())
    app.dependency_overrides[get_runtime] = lambda: (SETTINGS, fake)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200 and "Черновик карточки" in resp.text


def test_generate_ok(client, manometer):
    resp = client.post("/api/generate", json=manometer.model_dump())
    assert resp.status_code == 200
    data = resp.json()
    assert data["card"]["seo_title"].startswith("Манометр")
    assert data["markdown"].startswith("# Черновик карточки")


def test_generate_invalid_json(client):
    resp = client.post("/api/generate", content="{not json", headers={"Content-Type": "application/json"})
    assert resp.status_code == 400 and "Некорректный JSON" in resp.json()["error"]


def test_generate_empty_name(client):
    resp = client.post("/api/generate", json={"name": "  ", "specs": {}})
    assert resp.status_code == 422
    assert any("name" in d for d in resp.json()["details"])


def test_generate_llm_error():
    class BrokenLLM:
        model = "broken"

        def complete_json(self, messages):
            raise LLMError("API отклонил ключ (401)")

    app.dependency_overrides[get_runtime] = lambda: (SETTINGS, BrokenLLM())
    try:
        resp = TestClient(app).post("/api/generate", json={"name": "Манометр"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 502 and "401" in resp.json()["error"]
