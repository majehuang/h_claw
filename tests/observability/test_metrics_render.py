from app.observability.metrics import Metrics, render_prometheus


def test_render_prometheus_text_format():
    m = Metrics()
    m.increment("crawl_total")
    m.increment("crawl_result", labels={"mode": "http", "status": "SUCCESS"})
    m.observe("chromium_pages", 3)

    text = render_prometheus(m)

    assert "crawl_total 1" in text
    assert 'crawl_result{mode="http",status="SUCCESS"} 1' in text
    assert "chromium_pages 3" in text
    assert text.endswith("\n")


def test_render_empty_metrics():
    assert render_prometheus(Metrics()) == ""
