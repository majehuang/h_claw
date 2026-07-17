from app.observability.metrics import Metrics


def test_counter_increments():
    m = Metrics()
    m.increment("crawl_total")
    m.increment("crawl_total")
    assert m.snapshot()["crawl_total"] == 2


def test_counter_with_labels_are_separate():
    m = Metrics()
    m.increment("crawl_result", labels={"mode": "http", "status": "SUCCESS"})
    m.increment("crawl_result", labels={"mode": "browser", "status": "SUCCESS"})
    m.increment("crawl_result", labels={"mode": "http", "status": "SUCCESS"})

    snap = m.snapshot()
    assert snap['crawl_result{mode="http",status="SUCCESS"}'] == 2
    assert snap['crawl_result{mode="browser",status="SUCCESS"}'] == 1


def test_observe_records_gauge_latest_value():
    m = Metrics()
    m.observe("chromium_pages", 3)
    m.observe("chromium_pages", 5)
    assert m.snapshot()["chromium_pages"] == 5


def test_snapshot_is_a_copy():
    m = Metrics()
    m.increment("x")
    snap = m.snapshot()
    snap["x"] = 999
    assert m.snapshot()["x"] == 1


def test_labels_are_sorted_for_stable_keys():
    m = Metrics()
    m.increment("c", labels={"b": "2", "a": "1"})
    assert 'c{a="1",b="2"}' in m.snapshot()
