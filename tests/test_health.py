from starlette.testclient import TestClient

from app.main import build_asgi_app


def test_healthz_returns_ok():
    app = build_asgi_app()
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
