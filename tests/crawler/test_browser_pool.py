import asyncio

import pytest

from app.crawler.browser_pool import BrowserPool

pytestmark = pytest.mark.asyncio


class FakeResponse:
    def __init__(self, url: str):
        self.url = url
        self.status = 200
        self.html_content = f"<html><body>{url}</body></html>"


class FakeSession:
    def __init__(self, kind: str, ledger: list[str]):
        self.kind = kind
        self.ledger = ledger
        self.started = False
        self.closed = False
        self.fetch_urls: list[str] = []
        self._gate: asyncio.Event | None = None
        self._live_counter: list[int] | None = None
        self._peak: list[int] | None = None
        ledger.append(f"{kind}:create")

    async def start(self):
        self.started = True
        self.ledger.append(f"{self.kind}:start")

    async def close(self):
        self.closed = True
        self.ledger.append(f"{self.kind}:close")

    async def fetch(self, url: str, **kwargs):
        self.fetch_urls.append(url)
        if self._live_counter is not None:
            self._live_counter[0] += 1
            self._peak[0] = max(self._peak[0], self._live_counter[0])
        if self._gate is not None:
            await self._gate.wait()
        if self._live_counter is not None:
            self._live_counter[0] -= 1
        return FakeResponse(url)

    def get_pool_stats(self):
        return {"total_pages": 0, "busy_pages": 0, "max_pages": 2}


def _pool(ledger, *, max_browser_pages=3, restart_after_tasks=100):
    return BrowserPool(
        max_browser_pages=max_browser_pages,
        restart_after_tasks=restart_after_tasks,
        dynamic_factory=lambda: FakeSession("dynamic", ledger),
        stealth_factory=lambda: FakeSession("stealth", ledger),
    )


async def test_start_creates_and_starts_both_sessions():
    ledger: list[str] = []
    pool = _pool(ledger)

    await pool.start()
    try:
        assert "dynamic:start" in ledger
        assert "stealth:start" in ledger
    finally:
        await pool.close()


async def test_close_closes_both_sessions():
    ledger: list[str] = []
    pool = _pool(ledger)
    await pool.start()

    await pool.close()

    assert ledger.count("dynamic:close") == 1
    assert ledger.count("stealth:close") == 1


async def test_fetch_dynamic_and_stealth_route_to_right_session():
    ledger: list[str] = []
    pool = _pool(ledger)
    await pool.start()
    try:
        dyn = await pool.fetch_dynamic("https://a.example.com")
        sth = await pool.fetch_stealth("https://b.example.com")
        assert dyn.url == "https://a.example.com"
        assert sth.url == "https://b.example.com"
    finally:
        await pool.close()


async def test_browser_semaphore_caps_concurrent_fetches():
    ledger: list[str] = []
    pool = _pool(ledger, max_browser_pages=2)
    await pool.start()

    gate = asyncio.Event()
    live = [0]
    peak = [0]
    for session in (pool._dynamic,):  # type: ignore[attr-defined]
        session._gate = gate
        session._live_counter = live
        session._peak = peak

    try:
        tasks = [
            asyncio.create_task(pool.fetch_dynamic(f"https://a.example.com/{i}"))
            for i in range(5)
        ]
        await asyncio.sleep(0.05)
        assert peak[0] == 2  # 只有 2 个并发在跑，其余排队
        gate.set()
        await asyncio.gather(*tasks)
    finally:
        gate.set()
        await pool.close()


async def test_sessions_restart_after_task_threshold():
    ledger: list[str] = []
    pool = _pool(ledger, restart_after_tasks=3)
    await pool.start()
    try:
        for i in range(3):
            await pool.fetch_dynamic(f"https://a.example.com/{i}")

        # 达到阈值后，旧 session 应被关闭并创建新的一对
        assert ledger.count("dynamic:close") == 1
        assert ledger.count("stealth:close") == 1
        assert ledger.count("dynamic:start") == 2
        assert ledger.count("stealth:start") == 2
    finally:
        await pool.close()


async def test_stats_reports_task_count_and_pool_stats():
    ledger: list[str] = []
    pool = _pool(ledger)
    await pool.start()
    try:
        await pool.fetch_dynamic("https://a.example.com")
        stats = pool.stats()
        assert stats["task_count"] == 1
        assert stats["dynamic"]["max_pages"] == 2
    finally:
        await pool.close()
