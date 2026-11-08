from fastapi.testclient import TestClient
import pytest

from nadeg.main import app


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def data():
    return {"title": "Испытательная система", "time": "4", "expression": "A & B",
            "elements": [{"id": "A", "rate": "0.93", "name": "Общий элемент"}, {"id": "B", "rate": "1.13"}]}


def test_page_and_calculation(client, data):
    assert client.get("/").status_code == 200
    response = client.post("/api/analyze", json=data)
    assert response.status_code == 200
    assert response.json()["probability"] == "0.999176168144"
    assert response.json()["model"] == "methodical"
    assert "<svg" in response.json()["svg"]


def test_page_has_no_model_picker(client):
    text = client.get("/").text
    assert 'id="model"' not in text
    assert "Экспоненциальная" not in text
    assert "Задание 1" in text and "Задание 2" in text


@pytest.mark.parametrize("model", ["linear", "exponential"])
def test_removed_models_are_rejected_by_all_calculation_endpoints(client, data, model):
    data["model"] = model
    assert client.post("/api/analyze", json=data).status_code == 422
    assert client.post("/api/optimize", json=data).status_code == 422
    assert client.post("/api/export/pdf", json={"problem": data}).status_code == 422


def test_analysis_supports_or_but_optimization_rejects_it(client, data):
    data['expression'] = 'A | B'
    assert client.post('/api/analyze', json=data).status_code == 200
    response = client.post('/api/optimize', json=data)
    assert response.status_code == 422
    assert 'последовательной' in response.json()['detail']


def test_bad_data_returns_readable_errors(client, data):
    data["elements"][0]["mass"] = -1
    response = client.post("/api/analyze", json=data)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert response.json()["errors"][0]["path"] == ["elements", 0, "mass"]


def test_parser_error_returns_422(client, data):
    data["expression"] = "MISSING"
    response = client.post("/api/analyze", json=data)
    assert response.status_code == 422
    assert "Неизвестный" in response.json()["detail"]


def test_exports_and_injection_escaping(client, data):
    data["elements"][0]["name"] = '=HYPERLINK("evil")'
    response = client.post("/api/export/csv", json={"problem": data})
    assert response.status_code == 200
    assert "'=HYPERLINK" in response.text
    response = client.post("/api/export/svg", json={"problem": data})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")


def test_allocation_bounds_are_validated(client, data):
    for allocation in [[99, 0], [True, 0], [0], [0.1, 0]]:
        assert client.post("/api/export/csv", json={"problem": data, "allocation": allocation}).status_code == 422


def test_pdf_is_generated_with_verified_allocation(client, data):
    response = client.post("/api/export/pdf", json={"problem": data, "allocation": [1, 0]})
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert len(response.content) > 10000


def test_oversized_requests_are_rejected(client):
    response = client.post("/api/analyze", content='{"data":"' + "x" * 131073 + '"}', headers={"content-type": "application/json"})
    assert response.status_code == 413
