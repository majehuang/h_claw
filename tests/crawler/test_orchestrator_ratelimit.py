"""HC-006：单域名限流 + singleflight 请求合并（UT-016 / UT-017 / UT-018）。"""
import asyncio
from datetime import datetime, timezone

import pytest

from app.crawler.detector import DomainRuleDefaults, FetchResponse
from app.crawler.orchestrator import CrawlRequest, Orchestrator

pytestmark = pytest.mark.asyncio

USABLE_HTML = (
    "<html><head><title>商品</title></head><body><p>"
    + ("商品详情正文，价格 ¥199。" * 60)
    + "</p></body></html>"
)


def _resp(url):
    return FetchResponse(request_url=url, final_url=url, status_code=200, html=USABLE_HTML)


class FakeDB:
    def __init__(self):
        self.upserts = []

    async def get_fresh_by_cache_key(self, cache_key, now):
        return None

    async def get_domain_rule(self, domain):
        return None

    async def upsert_crawl_result(self, record):
        self.upserts.append(record)


class TrackingFetcher:
    """记录并发峰值与总调用次数的假 fetcher，可控放行。"""

    def __init__(self, release: asyncio.Event):
        self._release = release
        self.total_calls = 0
        self.concurrent = 0
        self.peak_concurrent = 0

    async def __call__(self, url, **kwargs):
        self.total_calls += 1
        self.concurrent += 1
        self.peak_concurrent = max(self.peak_concurrent, self.concurrent)
        try:
            await self._release.wait()
            return _resp(url)
        finally:
            self.concurrent -= 1


def _orch(tmp_path, fetcher, *, max_concurrency=10, max_per_domain=1, job_seq=None):
    seq = job_seq or iter(f"cr_{i}" for i in range(1000))
    return Orchestrator(
        db=FakeDB(),
        data_dir=tmp_path,
        http_fetch=fetcher,
        browser_fetch=fetcher,
        stealth_fetch=fetcher,
        validate=lambda url: None,
        clock=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc),
        job_id_factory=lambda: next(seq),
        default_rule=DomainRuleDefaults(),
        cache_ttl_seconds=900,
        result_ttl_seconds=86400,
        max_concurrency=max_concurrency,
        max_per_domain=max_per_domain,
    )


async def test_single_domain_concurrency_capped(tmp_path):
    # UT-016：同域名不同 URL 并发 5，max_per_domain=1 → 任意时刻最多一个上游访问。
    release = asyncio.Event()
    fetcher = TrackingFetcher(release)
    orch = _orch(tmp_path, fetcher, max_per_domain=1)

    urls = [f"https://shop.example.com/p/{i}" for i in range(5)]
    tasks = [asyncio.create_task(orch.crawl(CrawlRequest(url=u))) for u in urls]
    await asyncio.sleep(0.05)
    # 此刻应只有 1 个 fetch 在进行（其余在域名信号量上排队）。
    assert fetcher.concurrent == 1
    release.set()
    outcomes = await asyncio.gather(*tasks)

    assert all(o.status == "SUCCESS" for o in outcomes)
    assert fetcher.total_calls == 5           # 5 个不同 URL 各抓一次
    assert fetcher.peak_concurrent == 1       # 但从不并发超过 1


async def test_different_domains_run_concurrently(tmp_path):
    # UT-017：两个不同域名可并发（全局配额允许时）。
    release = asyncio.Event()
    fetcher = TrackingFetcher(release)
    orch = _orch(tmp_path, fetcher, max_per_domain=1)

    tasks = [
        asyncio.create_task(orch.crawl(CrawlRequest(url="https://a.example.com/p"))),
        asyncio.create_task(orch.crawl(CrawlRequest(url="https://b.example.com/p"))),
    ]
    await asyncio.sleep(0.05)
    assert fetcher.concurrent == 2            # 不同域名互不阻塞
    release.set()
    outcomes = await asyncio.gather(*tasks)
    assert all(o.status == "SUCCESS" for o in outcomes)
    assert fetcher.peak_concurrent == 2


async def test_singleflight_merges_identical_requests(tmp_path):
    # UT-018：并发提交 10 个相同 cache_key 请求 → 只调用一次上游，结果一致。
    release = asyncio.Event()
    fetcher = TrackingFetcher(release)
    orch = _orch(tmp_path, fetcher)

    url = "https://shop.example.com/same"
    tasks = [asyncio.create_task(orch.crawl(CrawlRequest(url=url))) for _ in range(10)]
    await asyncio.sleep(0.05)
    release.set()
    outcomes = await asyncio.gather(*tasks)

    assert fetcher.total_calls == 1                       # 只打一次上游
    assert all(o.status == "SUCCESS" for o in outcomes)
    assert len({o.job_id for o in outcomes}) == 1         # 所有调用者拿到同一结果


async def test_singleflight_waiter_cancel_does_not_break_leader(tmp_path):
    # 边界：waiter 被取消不应影响 leader 完成。
    release = asyncio.Event()
    fetcher = TrackingFetcher(release)
    orch = _orch(tmp_path, fetcher)

    url = "https://shop.example.com/same"
    leader = asyncio.create_task(orch.crawl(CrawlRequest(url=url)))
    await asyncio.sleep(0.02)
    waiter = asyncio.create_task(orch.crawl(CrawlRequest(url=url)))
    await asyncio.sleep(0.02)
    waiter.cancel()
    release.set()
    result = await leader
    assert result.status == "SUCCESS"
    assert fetcher.total_calls == 1
