from starlette.testclient import TestClient

from app.main import build_asgi_app, metrics


def test_healthz_returns_ok():
    app = build_asgi_app()
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_endpoint_renders_prometheus_text():
    metrics.increment("test_metric_probe")
    app = build_asgi_app()
    client = TestClient(app)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "test_metric_probe" in response.text
