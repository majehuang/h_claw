from starlette.testclient import TestClient

from app.main import build_asgi_app, metrics, set_service


class FakeLoginManager:
    def __init__(self, pngs):
        self._pngs = pngs

    def get_qr_png(self, login_id):
        return self._pngs.get(login_id)


class FakeService:
    def __init__(self, login_manager):
        self.login_manager = login_manager


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


def test_qr_endpoint_returns_png_bytes_for_active_login():
    set_service(FakeService(FakeLoginManager({"lg_1": b"PNGDATA"})))
    app = build_asgi_app()
    client = TestClient(app)

    response = client.get("/qr/lg_1")

    assert response.status_code == 200
    assert response.content == b"PNGDATA"
    assert response.headers["content-type"] == "image/png"


def test_qr_endpoint_404s_for_unknown_login_id():
    set_service(FakeService(FakeLoginManager({})))
    app = build_asgi_app()
    client = TestClient(app)

    response = client.get("/qr/nope")

    assert response.status_code == 404
