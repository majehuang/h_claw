"""HC-007：挑战负缓存与熔断（UT-020 / UT-021 / UT-022）。

使用可推进的 fake clock，验证：挑战失败后进入冷却期，冷却期内相同请求不再打上游，
冷却结束后恢复正常抓取；成功只解除对应会话的熔断。
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.crawler.detector import DomainRuleDefaults, FetchResponse
from app.crawler.orchestrator import CrawlRequest, Orchestrator

pytestmark = pytest.mark.asyncio

USABLE_HTML = (
    "<html><head><title>商品</title></head><body><p>"
    + ("商品详情正文，价格 ¥199。" * 60)
    + "</p></body></html>"
)
CAPTCHA_HTML = "<html><body>请完成安全验证</body></html>"


def _resp(url, html=USABLE_HTML, status=200):
    return FetchResponse(request_url=url, final_url=url, status_code=status, html=html)


class FakeDB:
    def __init__(self):
        self.upserts = []

    async def get_fresh_by_cache_key(self, cache_key, now):
        return None

    async def get_domain_rule(self, domain):
        return None

    async def upsert_crawl_result(self, record):
        self.upserts.append(record)


class SwitchableFetcher:
    """可切换返回值 + 计数总调用次数。"""

    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def __call__(self, url, **kwargs):
        self.calls += 1
        return self.result


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now = self.now + timedelta(seconds=seconds)


def _orch(tmp_path, fetcher, clock, *, challenge_cooldown=600):
    seq = iter(f"cr_{i}" for i in range(1000))
    return Orchestrator(
        db=FakeDB(),
        data_dir=tmp_path,
        http_fetch=fetcher,
        browser_fetch=fetcher,
        stealth_fetch=fetcher,
        validate=lambda url: None,
        clock=clock,
        job_id_factory=lambda: next(seq),
        default_rule=DomainRuleDefaults(),
        cache_ttl_seconds=900,
        result_ttl_seconds=86400,
        max_concurrency=10,
        max_per_domain=5,
        challenge_cooldown_seconds=challenge_cooldown,
    )


async def test_challenge_sets_cooldown_and_blocks_repeat(tmp_path):
    # UT-020 + UT-021：首个请求命中挑战 → 进入冷却；冷却期内相同请求返回 COOLDOWN，不打上游。
    clock = Clock(datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc))
    fetcher = SwitchableFetcher(_resp("https://item.taobao.com/i", html=CAPTCHA_HTML))
    orch = _orch(tmp_path, fetcher, clock, challenge_cooldown=600)

    first = await orch.crawl(CrawlRequest(url="https://item.taobao.com/i"))
    assert first.status == "CAPTCHA_REQUIRED"
    assert fetcher.calls == 1

    second = await orch.crawl(CrawlRequest(url="https://item.taobao.com/i"))
    assert second.status == "COOLDOWN"
    assert second.error_code == "CHALLENGE_COOLDOWN"
    assert second.retry_after_seconds is not None and second.retry_after_seconds > 0
    assert fetcher.calls == 1  # 冷却期内没有新的上游访问


async def test_cooldown_blocks_even_other_url_same_domain(tmp_path):
    # 熔断按 domain 生效：同域名的其他 URL 在冷却期内同样被拦（不重复打上游）。
    clock = Clock(datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc))
    fetcher = SwitchableFetcher(_resp("https://item.taobao.com/a", html=CAPTCHA_HTML))
    orch = _orch(tmp_path, fetcher, clock)

    await orch.crawl(CrawlRequest(url="https://item.taobao.com/a"))
    other = await orch.crawl(CrawlRequest(url="https://item.taobao.com/b"))
    assert other.status == "COOLDOWN"
    assert fetcher.calls == 1


async def test_cooldown_expires_allows_new_crawl(tmp_path):
    # UT-022：推进时钟越过 next_allowed_at 后，允许创建新抓取任务。
    clock = Clock(datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc))
    fetcher = SwitchableFetcher(_resp("https://item.taobao.com/i", html=CAPTCHA_HTML))
    orch = _orch(tmp_path, fetcher, clock, challenge_cooldown=600)

    await orch.crawl(CrawlRequest(url="https://item.taobao.com/i"))
    assert fetcher.calls == 1

    clock.advance(601)  # 冷却结束
    third = await orch.crawl(CrawlRequest(url="https://item.taobao.com/i"))
    assert third.status == "CAPTCHA_REQUIRED"  # 再次尝试上游（仍是挑战页）
    assert fetcher.calls == 2                    # 冷却结束后才允许新的上游访问


async def test_success_clears_cooldown_for_session_only(tmp_path):
    # 成功恢复只清除对应会话/域名的熔断。
    clock = Clock(datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc))
    fetcher = SwitchableFetcher(_resp("https://item.taobao.com/i", html=CAPTCHA_HTML))
    orch = _orch(tmp_path, fetcher, clock, challenge_cooldown=600)

    await orch.crawl(CrawlRequest(url="https://item.taobao.com/i"))
    # 冷却结束 + 上游恢复正常 → 成功并解除熔断。
    clock.advance(601)
    fetcher.result = _resp("https://item.taobao.com/i", html=USABLE_HTML)
    ok = await orch.crawl(CrawlRequest(url="https://item.taobao.com/i"))
    assert ok.status == "SUCCESS"

    # 熔断已解除：下一次请求正常打上游（若再遇挑战会重新计冷却）。
    fetcher.result = _resp("https://item.taobao.com/i", html=CAPTCHA_HTML)
    again = await orch.crawl(CrawlRequest(url="https://item.taobao.com/i", force_refresh=True))
    assert again.status == "CAPTCHA_REQUIRED"


async def test_normal_success_never_sets_cooldown(tmp_path):
    # 回归：正常成功不设置任何熔断。
    clock = Clock(datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc))
    fetcher = SwitchableFetcher(_resp("https://shop.example.com/p", html=USABLE_HTML))
    orch = _orch(tmp_path, fetcher, clock)

    for _ in range(3):
        out = await orch.crawl(CrawlRequest(url="https://shop.example.com/p", force_refresh=True))
        assert out.status == "SUCCESS"
    assert fetcher.calls == 3
