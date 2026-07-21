from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app.crawler.detector import DomainRuleDefaults, FetchResponse
from app.crawler.http_fetcher import FetchError
from app.crawler.orchestrator import CrawlRequest, Orchestrator
from app.security.url_validator import URLValidationError
from app.storage.database import AccountProfile

pytestmark = pytest.mark.asyncio

USABLE_HTML = (
    "<html><head><title>示例商品</title></head><body><p>"
    + ("商品详情正文，价格 ¥199。" * 60)
    + "</p></body></html>"
)
BLOCKED_HTML = "<html><body>请完成安全验证</body></html>"
LOGIN_URL = "https://shop.example.com/login"


def _resp(url="https://shop.example.com/p/1", status=200, html=USABLE_HTML, final=None):
    return FetchResponse(
        request_url=url, final_url=final or url, status_code=status, html=html
    )


class FakeDB:
    def __init__(self, cached=None, domain_rule=None, profile=None):
        self._cached = cached
        self._domain_rule = domain_rule
        self._profile = profile
        self.upserts = []
        self.touched = []

    async def get_fresh_by_cache_key(self, cache_key, now):
        return self._cached

    async def get_domain_rule(self, domain):
        return self._domain_rule

    async def get_profile(self, session_id):
        return self._profile

    async def touch_profile_last_used(self, session_id, now):
        self.touched.append((session_id, now))

    async def upsert_crawl_result(self, record):
        self.upserts.append(record)


class FakeFetcher:
    def __init__(self, result):
        self.result = result
        self.calls: list[str] = []
        self.sessions: list = []
        self.cookies: list = []

    async def __call__(self, url, **kwargs):
        self.calls.append(url)
        self.sessions.append(kwargs.get("session"))
        self.cookies.append(kwargs.get("cookies"))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _profile(status="ACTIVE", expires_at=None):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    return AccountProfile(
        session_id="jd-user", domain="www.jd.com", label=None, status=status,
        fingerprint_id=None, created_at=now, last_used_at=None, expires_at=expires_at,
    )


class FakeProfileManager:
    def __init__(self, session_obj="profile-session"):
        self._session_obj = session_obj
        self.used: list[str] = []

    @asynccontextmanager
    async def use(self, session_id):
        self.used.append(session_id)
        yield self._session_obj


def _orchestrator(tmp_path, *, db=None, http=None, browser=None, stealth=None,
                  validate=None, max_concurrency=5, profile_manager=None):
    return Orchestrator(
        db=db or FakeDB(),
        data_dir=tmp_path,
        http_fetch=http or FakeFetcher(_resp()),
        browser_fetch=browser or FakeFetcher(_resp()),
        stealth_fetch=stealth or FakeFetcher(_resp()),
        validate=validate or (lambda url: None),
        clock=lambda: datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc),
        job_id_factory=lambda: "cr_testjob",
        default_rule=DomainRuleDefaults(),
        cache_ttl_seconds=900,
        result_ttl_seconds=86400,
        max_concurrency=max_concurrency,
        profile_manager=profile_manager,
    )


async def test_http_success_does_not_escalate(tmp_path):
    http = FakeFetcher(_resp())
    browser = FakeFetcher(_resp())
    orch = _orchestrator(tmp_path, http=http, browser=browser)

    outcome = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/1"))

    assert outcome.status == "SUCCESS"
    assert outcome.fetch_mode == "http"
    assert outcome.title == "示例商品"
    assert http.calls == ["https://shop.example.com/p/1"]
    assert browser.calls == []  # HTTP 可用，不应升级


async def test_escalates_http_to_browser_on_short_content(tmp_path):
    http = FakeFetcher(_resp(html="<html><body>太短</body></html>"))
    browser = FakeFetcher(_resp())
    orch = _orchestrator(tmp_path, http=http, browser=browser)

    outcome = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/1"))

    assert outcome.status == "SUCCESS"
    assert outcome.fetch_mode == "browser"
    assert browser.calls == ["https://shop.example.com/p/1"]


async def test_escalates_to_stealth_when_browser_still_blocked(tmp_path):
    http = FakeFetcher(_resp(status=403, html=BLOCKED_HTML))
    browser = FakeFetcher(_resp(status=403, html=BLOCKED_HTML))
    stealth = FakeFetcher(_resp())
    orch = _orchestrator(tmp_path, http=http, browser=browser, stealth=stealth)

    outcome = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/1"))

    assert outcome.status == "SUCCESS"
    assert outcome.fetch_mode == "stealth"
    assert stealth.calls == ["https://shop.example.com/p/1"]


async def test_all_layers_blocked_returns_blocked(tmp_path):
    blocked = _resp(status=403, html="<html><body>403 forbidden nothing here</body></html>")
    orch = _orchestrator(
        tmp_path,
        http=FakeFetcher(blocked),
        browser=FakeFetcher(blocked),
        stealth=FakeFetcher(blocked),
    )

    outcome = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/1"))

    assert outcome.status == "BLOCKED"
    assert outcome.error_code == "UPSTREAM_BLOCKED"
    assert outcome.retriable is False


async def test_captcha_on_last_layer_returns_captcha_required(tmp_path):
    captcha = _resp(html=BLOCKED_HTML)
    orch = _orchestrator(
        tmp_path,
        http=FakeFetcher(captcha),
        browser=FakeFetcher(captcha),
        stealth=FakeFetcher(captcha),
    )

    outcome = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/1"))

    assert outcome.status == "CAPTCHA_REQUIRED"
    assert outcome.error_code == "CHALLENGE_NOT_SOLVED"


async def test_login_redirect_on_last_layer_returns_login_required(tmp_path):
    login = _resp(final=LOGIN_URL)
    orch = _orchestrator(
        tmp_path,
        http=FakeFetcher(login),
        browser=FakeFetcher(login),
        stealth=FakeFetcher(login),
    )

    outcome = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/1"))

    assert outcome.status == "LOGIN_REQUIRED"
    assert outcome.error_code == "LOGIN_WALL"


async def test_ssrf_validation_failure_is_terminal_without_fetch(tmp_path):
    http = FakeFetcher(_resp())

    def _reject(url):
        raise URLValidationError("SSRF_BLOCKED", "内网地址")

    orch = _orchestrator(tmp_path, http=http, validate=_reject)

    outcome = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/1"))

    assert outcome.status == "BLOCKED"
    assert outcome.error_code == "SSRF_BLOCKED"
    assert http.calls == []


async def test_timeout_error_returns_timeout_status(tmp_path):
    http = FakeFetcher(FetchError("FETCH_TIMEOUT", "超时"))
    browser = FakeFetcher(FetchError("FETCH_TIMEOUT", "超时"))
    stealth = FakeFetcher(FetchError("FETCH_TIMEOUT", "超时"))
    orch = _orchestrator(tmp_path, http=http, browser=browser, stealth=stealth)

    outcome = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/1"))

    assert outcome.status == "TIMEOUT"
    assert outcome.error_code == "FETCH_TIMEOUT"
    assert outcome.retriable is True


async def test_mode_http_only_does_not_escalate(tmp_path):
    http = FakeFetcher(_resp(html="<html><body>太短</body></html>"))
    browser = FakeFetcher(_resp())
    orch = _orchestrator(tmp_path, http=http, browser=browser)

    outcome = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/1", mode="http"))

    assert browser.calls == []
    assert outcome.status == "BLOCKED"


async def test_mode_stealth_only_uses_stealth(tmp_path):
    http = FakeFetcher(_resp())
    stealth = FakeFetcher(_resp())
    orch = _orchestrator(tmp_path, http=http, stealth=stealth)

    outcome = await orch.crawl(
        CrawlRequest(url="https://shop.example.com/p/1", mode="stealth")
    )

    assert http.calls == []
    assert stealth.calls == ["https://shop.example.com/p/1"]
    assert outcome.fetch_mode == "stealth"


async def test_domain_preferred_stealth_skips_http_and_browser(tmp_path):
    from app.storage.database import DomainRule

    # 即便 HTTP 层能返回可用内容，白名单域名（preferred_mode=stealth）也应直连 L3，
    # 不再从 L1 升级，避免多层请求触发目标站频率限制。
    http = FakeFetcher(_resp())
    browser = FakeFetcher(_resp())
    stealth = FakeFetcher(_resp())
    rule = DomainRule(domain="shop.example.com", preferred_mode="stealth")
    orch = _orchestrator(
        tmp_path, db=FakeDB(domain_rule=rule),
        http=http, browser=browser, stealth=stealth,
    )

    outcome = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/1"))

    assert outcome.status == "SUCCESS"
    assert outcome.fetch_mode == "stealth"
    assert http.calls == []
    assert browser.calls == []
    assert stealth.calls == ["https://shop.example.com/p/1"]


async def test_domain_preferred_browser_starts_at_browser_and_can_escalate(tmp_path):
    from app.storage.database import DomainRule

    # preferred_mode=browser：从 L2 起步，仍可在不足时升级到 L3，但不打 L1。
    http = FakeFetcher(_resp())
    browser = FakeFetcher(_resp(html="<html><body>太短</body></html>"))
    stealth = FakeFetcher(_resp())
    rule = DomainRule(domain="shop.example.com", preferred_mode="browser")
    orch = _orchestrator(
        tmp_path, db=FakeDB(domain_rule=rule),
        http=http, browser=browser, stealth=stealth,
    )

    outcome = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/1"))

    assert outcome.status == "SUCCESS"
    assert outcome.fetch_mode == "stealth"
    assert http.calls == []
    assert browser.calls == ["https://shop.example.com/p/1"]
    assert stealth.calls == ["https://shop.example.com/p/1"]


async def test_explicit_request_mode_overrides_domain_preferred_mode(tmp_path):
    from app.storage.database import DomainRule

    # 调用方显式指定 mode 时优先于域名规则；preferred_mode 只作用于 auto。
    http = FakeFetcher(_resp(html="<html><body>太短</body></html>"))
    stealth = FakeFetcher(_resp())
    rule = DomainRule(domain="shop.example.com", preferred_mode="stealth")
    orch = _orchestrator(
        tmp_path, db=FakeDB(domain_rule=rule), http=http, stealth=stealth,
    )

    outcome = await orch.crawl(
        CrawlRequest(url="https://shop.example.com/p/1", mode="http")
    )

    assert http.calls == ["https://shop.example.com/p/1"]
    assert stealth.calls == []
    assert outcome.status == "BLOCKED"


async def test_domain_preferred_auto_uses_full_escalation(tmp_path):
    from app.storage.database import DomainRule

    # preferred_mode=auto（默认）时行为不变：从 L1 起步的完整升级链。
    http = FakeFetcher(_resp())
    browser = FakeFetcher(_resp())
    rule = DomainRule(domain="shop.example.com", preferred_mode="auto")
    orch = _orchestrator(
        tmp_path, db=FakeDB(domain_rule=rule), http=http, browser=browser,
    )

    outcome = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/1"))

    assert outcome.fetch_mode == "http"
    assert http.calls == ["https://shop.example.com/p/1"]
    assert browser.calls == []


async def test_session_id_routes_through_profile_browser(tmp_path):
    stealth = FakeFetcher(_resp())
    pm = FakeProfileManager(session_obj="jd-browser")
    db = FakeDB(profile=_profile())
    orch = _orchestrator(tmp_path, db=db, stealth=stealth, profile_manager=pm)

    outcome = await orch.crawl(
        CrawlRequest(url="https://www.jd.com/p/1", session_id="jd-user")
    )

    assert outcome.status == "SUCCESS"
    assert outcome.fetch_mode == "stealth"
    assert pm.used == ["jd-user"]                    # 经 ProfileManager 加载已登录上下文
    assert stealth.calls == ["https://www.jd.com/p/1"]
    assert stealth.sessions == ["jd-browser"]        # 用该 profile 的浏览器会话抓取
    assert db.touched == [("jd-user", datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc))]


async def test_session_id_unknown_profile_returns_session_not_found(tmp_path):
    stealth = FakeFetcher(_resp())
    orch = _orchestrator(
        tmp_path, db=FakeDB(profile=None), stealth=stealth,
        profile_manager=FakeProfileManager(),
    )

    outcome = await orch.crawl(
        CrawlRequest(url="https://www.jd.com/p/1", session_id="missing")
    )

    assert outcome.status == "FAILED"
    assert outcome.error_code == "SESSION_NOT_FOUND"
    assert stealth.calls == []


async def test_session_id_revoked_returns_session_expired(tmp_path):
    stealth = FakeFetcher(_resp())
    orch = _orchestrator(
        tmp_path, db=FakeDB(profile=_profile(status="REVOKED")),
        stealth=stealth, profile_manager=FakeProfileManager(),
    )

    outcome = await orch.crawl(
        CrawlRequest(url="https://www.jd.com/p/1", session_id="jd-user")
    )

    assert outcome.error_code == "SESSION_EXPIRED"
    assert stealth.calls == []


async def test_session_id_expired_profile_returns_session_expired(tmp_path):
    past = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc) - timedelta(days=1)
    stealth = FakeFetcher(_resp())
    orch = _orchestrator(
        tmp_path, db=FakeDB(profile=_profile(expires_at=past)),
        stealth=stealth, profile_manager=FakeProfileManager(),
    )

    outcome = await orch.crawl(
        CrawlRequest(url="https://www.jd.com/p/1", session_id="jd-user")
    )

    assert outcome.error_code == "SESSION_EXPIRED"
    assert stealth.calls == []


async def test_domain_default_session_id_used_when_request_has_none(tmp_path):
    from app.storage.database import DomainRule

    stealth = FakeFetcher(_resp())
    pm = FakeProfileManager(session_obj="jd-browser")
    rule = DomainRule(domain="www.jd.com", default_session_id="jd-user")
    db = FakeDB(domain_rule=rule, profile=_profile())
    orch = _orchestrator(tmp_path, db=db, stealth=stealth, profile_manager=pm)

    outcome = await orch.crawl(CrawlRequest(url="https://www.jd.com/p/1"))

    assert outcome.status == "SUCCESS"
    assert pm.used == ["jd-user"]
    assert stealth.sessions == ["jd-browser"]


async def test_cache_hit_returns_cached_without_fetching(tmp_path):
    from app.storage.database import CrawlResultRecord

    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    cached = CrawlResultRecord(
        job_id="cr_cached", cache_key="k", source_url="https://shop.example.com/p/1",
        final_url="https://shop.example.com/p/1", title="缓存商品", status="SUCCESS",
        fetch_mode="http", markdown_path=str(tmp_path / "results/cr_cached/content.md"),
        content_length=100, status_code=200, error_code=None, error_message=None,
        created_at=now, expires_at=now,
    )
    http = FakeFetcher(_resp())
    orch = _orchestrator(tmp_path, db=FakeDB(cached=cached), http=http)

    outcome = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/1"))

    assert outcome.status == "SUCCESS"
    assert outcome.job_id == "cr_cached"
    assert outcome.from_cache is True
    assert http.calls == []


async def test_force_refresh_bypasses_cache(tmp_path):
    from app.storage.database import CrawlResultRecord

    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    cached = CrawlResultRecord(
        job_id="cr_cached", cache_key="k", source_url="https://shop.example.com/p/1",
        final_url=None, title="缓存", status="SUCCESS", fetch_mode="http",
        markdown_path=None, content_length=None, status_code=200, error_code=None,
        error_message=None, created_at=now, expires_at=now,
    )
    http = FakeFetcher(_resp())
    orch = _orchestrator(tmp_path, db=FakeDB(cached=cached), http=http)

    outcome = await orch.crawl(
        CrawlRequest(url="https://shop.example.com/p/1", force_refresh=True)
    )

    assert outcome.from_cache is False
    assert http.calls == ["https://shop.example.com/p/1"]


async def test_success_writes_result_file_and_db_record(tmp_path):
    db = FakeDB()
    orch = _orchestrator(tmp_path, db=db)

    outcome = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/1"))

    markdown_file = tmp_path / "results" / "cr_testjob" / "content.md"
    assert markdown_file.exists()
    assert "示例商品" in markdown_file.read_text(encoding="utf-8")
    assert len(db.upserts) == 1
    assert db.upserts[0].status == "SUCCESS"
    assert outcome.markdown is not None


async def test_concurrency_limit_returns_rate_limited(tmp_path):
    import asyncio

    gate = asyncio.Event()

    class BlockingFetcher:
        calls: list[str] = []

        async def __call__(self, url, **kwargs):
            BlockingFetcher.calls.append(url)
            await gate.wait()
            return _resp()

    orch = _orchestrator(tmp_path, http=BlockingFetcher(), max_concurrency=1)

    first = asyncio.create_task(orch.crawl(CrawlRequest(url="https://shop.example.com/p/1")))
    await asyncio.sleep(0.05)
    # 并发槽已被第一个请求占满，第二个应立即返回 RATE_LIMITED 而非排队。
    second = await orch.crawl(CrawlRequest(url="https://shop.example.com/p/2"))
    assert second.status == "FAILED" or second.error_code == "RATE_LIMITED"
    assert second.error_code == "RATE_LIMITED"
    assert second.retriable is True

    gate.set()
    await first
