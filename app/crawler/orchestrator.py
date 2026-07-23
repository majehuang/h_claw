import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.converter.pipeline import convert_html_to_markdown
from app.crawler.cooldown import CooldownStore, InMemoryCooldownStore
from app.crawler.detector import (
    INTERACTIVE_CHALLENGE_REASONS,
    DomainRuleDefaults,
    FetchResponse,
    detect,
)
from app.crawler.http_fetcher import FetchError
from app.security.url_validator import URLValidationError
from app.storage.cache import compute_cache_key
from app.storage.database import CrawlResultRecord
from app.storage.results import result_paths, write_result

Fetcher = Callable[..., Awaitable[FetchResponse]]

# 直接终止、不再尝试后续层级的抓取错误（URL 本身有问题，换层也没用）。
_IMMEDIATE_TERMINAL_ERRORS = {
    "SSRF_BLOCKED": ("BLOCKED", False),
    "INVALID_URL": ("FAILED", False),
}

# 检测原因 → 终态状态与 error_code（所有层级都用尽后）。
_DETECTION_TERMINAL = {
    "captcha_detected": ("CAPTCHA_REQUIRED", "CHALLENGE_NOT_SOLVED"),
    "captcha_redirect": ("CAPTCHA_REQUIRED", "CHALLENGE_NOT_SOLVED"),
    "login_redirect": ("LOGIN_REQUIRED", "LOGIN_WALL"),
}
_DETECTION_TERMINAL_DEFAULT = ("BLOCKED", "UPSTREAM_BLOCKED")

# 升级到下一层无法绕过的检测原因：交互式挑战（滑块/验证码）换层也解不开，
# login_redirect 同理——目标站点要的是登录态，不是"更像真人的抓取层"，
# 继续升级只会对同一个跳转再打一次浏览器/隐身层，白白拖慢并浪费资源。
_NON_ESCALATING_REASONS = INTERACTIVE_CHALLENGE_REASONS | {"login_redirect"}

# 完整升级顺序：从轻到重。域名 preferred_mode 指定的是「起始层」，
# 从该层截断到末尾即为该域名的升级链（如 stealth → 仅 L3，browser → L2+L3）。
_ESCALATION_ORDER = ("http", "browser", "stealth")

_MODE_LAYERS = {
    "auto": _ESCALATION_ORDER,
    "http": ("http",),
    "browser": ("browser",),
    "stealth": ("stealth",),
}


def _resolve_layers(request_mode: str, preferred_mode: str) -> tuple[str, ...]:
    """决定实际抓取层链。

    - 调用方显式指定 mode（http/browser/stealth）时优先，域名规则不覆盖。
    - mode=auto 且域名 preferred_mode 指定了起始层时，从该层起截断升级链
      （白名单直连 L3，避免从 L1 逐层升级带来的多次请求触发频率限制）。
    - 否则沿用 auto 的完整升级链。
    """
    if request_mode != "auto":
        return _MODE_LAYERS.get(request_mode, _MODE_LAYERS["auto"])
    if preferred_mode in _ESCALATION_ORDER:
        return _ESCALATION_ORDER[_ESCALATION_ORDER.index(preferred_mode):]
    return _MODE_LAYERS["auto"]


@dataclass(frozen=True)
class CrawlRequest:
    url: str
    mode: str = "auto"
    include_images: bool = True
    force_refresh: bool = False
    timeout_seconds: int = 60
    session_id: str | None = None


@dataclass(frozen=True)
class CrawlOutcome:
    status: str
    job_id: str
    source_url: str
    final_url: str | None = None
    fetch_mode: str | None = None
    title: str | None = None
    markdown: str | None = None
    content_length: int | None = None
    resource_uri: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retriable: bool = False
    retry_after_seconds: int | None = None
    from_cache: bool = False


class Orchestrator:
    """mode=auto 时按第 7.4/7.5 节的固定状态机逐层升级，并按第 4.3 节
    统一封装错误返回。总并发上限（跨 HTTP+浏览器）在此非阻塞地控制：
    槽位已满时立即返回 RATE_LIMITED，而不是排队占满 MCP 调用生命周期。
    """

    def __init__(
        self,
        *,
        db: Any,
        data_dir: Path,
        http_fetch: Fetcher,
        browser_fetch: Fetcher,
        stealth_fetch: Fetcher,
        validate: Callable[[str], None],
        clock: Callable[[], datetime],
        job_id_factory: Callable[[], str],
        default_rule: DomainRuleDefaults,
        cache_ttl_seconds: int,
        result_ttl_seconds: int,
        max_concurrency: int,
        max_per_domain: int = 1,
        domain_wait_seconds: int = 30,
        challenge_cooldown_seconds: int = 600,
        rate_limit_cooldown_seconds: int = 120,
        blocked_cooldown_seconds: int = 300,
        http_timeout_seconds: int = 15,
        browser_timeout_seconds: int = 60,
        stealth_timeout_seconds: int = 90,
        locale: str = "zh-CN",
        profile_manager: Any = None,
        cooldown_store: CooldownStore | None = None,
    ):
        self._db = db
        # 登录态 profile 管理器：加载已登录的持久上下文（user_data_dir）起浏览器抓取。
        self._profile_manager = profile_manager
        self._data_dir = data_dir
        self._fetchers: dict[str, Fetcher] = {
            "http": http_fetch,
            "browser": browser_fetch,
            "stealth": stealth_fetch,
        }
        self._layer_timeouts = {
            "http": http_timeout_seconds,
            "browser": browser_timeout_seconds,
            "stealth": stealth_timeout_seconds,
        }
        self._validate = validate
        self._clock = clock
        self._job_id_factory = job_id_factory
        self._default_rule = default_rule
        self._cache_ttl = cache_ttl_seconds
        self._result_ttl = result_ttl_seconds
        self._max_concurrency = max_concurrency
        self._max_per_domain = max_per_domain
        self._domain_wait_seconds = domain_wait_seconds
        self._challenge_cooldown = challenge_cooldown_seconds
        self._rate_limit_cooldown = rate_limit_cooldown_seconds
        self._blocked_cooldown = blocked_cooldown_seconds
        self._locale = locale
        self._active = 0
        # 单域名并发闸门（HC-006）：每个域名键一个 Semaphore，容量 max_per_domain。
        self._domain_semaphores: dict[str, asyncio.Semaphore] = {}
        # Singleflight（HC-006）：同 cache_key 的并发请求合并为一次上游访问。
        self._inflight: dict[str, asyncio.Future] = {}
        # 挑战熔断（HC-007/HC-002）：冷却态经 CooldownStore 存取，默认进程内，生产用 DB 持久。
        self._cooldown_store: CooldownStore = cooldown_store or InMemoryCooldownStore()

    async def crawl(self, request: CrawlRequest, session: Any = None) -> CrawlOutcome:
        job_id = self._job_id_factory()

        try:
            self._validate(request.url)
        except URLValidationError as exc:
            return self._fetch_error_outcome(job_id, request, exc.error_code, str(exc))

        domain = urlsplit(request.url).hostname or ""
        rule, preferred_mode, default_session_id = await self._resolve_rule(domain)
        effective_session_id = request.session_id or default_session_id
        cache_key = compute_cache_key(
            request.url, request.include_images, self._locale, effective_session_id
        )

        if not request.force_refresh:
            cached = await self._db.get_fresh_by_cache_key(cache_key, self._clock())
            if cached is not None:
                return self._outcome_from_cached(cached)

        # 挑战熔断（HC-007/UT-020,UT-021）：冷却期内直接返回 COOLDOWN，不打上游、不重开挑战。
        domain_key = f"{domain}|{effective_session_id or ''}"
        remaining = await self._cooldown_remaining(domain_key)
        if remaining is not None:
            return self._cooldown_outcome(job_id, request, remaining)

        # Singleflight（HC-006/UT-018）：同 cache_key 已有在途请求时，直接复用其结果，
        # 不再重复打上游。shield 防止本 waiter 被取消时波及 leader。
        inflight = self._inflight.get(cache_key)
        if inflight is not None:
            return await asyncio.shield(inflight)

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._inflight[cache_key] = future
        try:
            outcome = await self._run_leader(
                request, job_id, session, domain, rule,
                preferred_mode, effective_session_id, cache_key,
            )
            if not future.done():
                future.set_result(outcome)
            return outcome
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
            raise
        finally:
            self._inflight.pop(cache_key, None)

    async def _run_leader(
        self,
        request: CrawlRequest,
        job_id: str,
        session: Any,
        domain: str,
        rule: DomainRuleDefaults,
        preferred_mode: str,
        effective_session_id: str | None,
        cache_key: str,
    ) -> CrawlOutcome:
        # 非阻塞全局并发闸门：单事件循环线程内 check-then-increment 之间无 await，天然原子。
        if self._active >= self._max_concurrency:
            return self._rate_limited(job_id, request)

        self._active += 1
        try:
            # 单域名并发闸门（HC-006/UT-016）：登录态请求按 domain+session 分桶，
            # 避免同域多请求放大触发目标站频率限制。等待有界，超时即返回 RATE_LIMITED。
            domain_key = f"{domain}|{effective_session_id or ''}"
            semaphore = self._domain_semaphores.setdefault(
                domain_key, asyncio.Semaphore(self._max_per_domain)
            )
            try:
                await asyncio.wait_for(
                    semaphore.acquire(), timeout=self._domain_wait_seconds
                )
            except asyncio.TimeoutError:
                return self._rate_limited(job_id, request)
            try:
                return await self._crawl_inner(
                    request, job_id, session, rule, preferred_mode,
                    effective_session_id, cache_key,
                )
            finally:
                semaphore.release()
        finally:
            self._active -= 1

    async def _cooldown_remaining(self, domain_key: str) -> int | None:
        """冷却剩余秒数；已过期返回 None（HC-007，经 CooldownStore）。"""
        return await self._cooldown_store.remaining_seconds(domain_key, self._clock())

    async def _set_cooldown(
        self, domain_key: str, seconds: int, reason: str | None
    ) -> None:
        until = self._clock() + timedelta(seconds=seconds)
        await self._cooldown_store.arm(domain_key, until, reason)

    async def _clear_cooldown(self, domain_key: str) -> None:
        # 成功恢复只清除对应会话的熔断，不影响其他账号（HC-007）。
        await self._cooldown_store.clear(domain_key)

    def _cooldown_for_reason(
        self, verdict_reason: str | None, last_error: FetchError | None
    ) -> tuple[int, str] | None:
        """按原因选择冷却时长与标签：交互式挑战/登录墙 > 403/503 阻断（HC-007）。

        login_redirect 复用挑战冷却时长：没有 session 就不可能通过，同一域名在
        冷却期内直接短路，避免每次调用都重新跑一遍三层升级（见 HC-005 同款逻辑）。
        """
        if verdict_reason in INTERACTIVE_CHALLENGE_REASONS:
            return self._challenge_cooldown, "challenge"
        if verdict_reason == "login_redirect":
            return self._challenge_cooldown, "login"
        if verdict_reason == "blocked_status":
            return self._blocked_cooldown, "blocked"
        return None

    def _cooldown_outcome(
        self, job_id: str, request: CrawlRequest, remaining: int
    ) -> CrawlOutcome:
        return CrawlOutcome(
            status="COOLDOWN",
            job_id=job_id,
            source_url=request.url,
            error_code="CHALLENGE_COOLDOWN",
            error_message=f"该站点处于挑战冷却期，请 {remaining} 秒后重试。",
            retriable=True,
            retry_after_seconds=remaining,
        )

    def _rate_limited(self, job_id: str, request: CrawlRequest) -> CrawlOutcome:
        return CrawlOutcome(
            status="FAILED",
            job_id=job_id,
            source_url=request.url,
            error_code="RATE_LIMITED",
            error_message="抓取服务并发已满，请稍后重试。",
            retriable=True,
            retry_after_seconds=5,
        )

    async def _crawl_inner(
        self,
        request: CrawlRequest,
        job_id: str,
        session: Any,
        rule: DomainRuleDefaults,
        preferred_mode: str,
        effective_session_id: str | None,
        cache_key: str,
    ) -> CrawlOutcome:
        domain = urlsplit(request.url).hostname or ""
        domain_key = f"{domain}|{effective_session_id or ''}"

        if effective_session_id is not None:
            return await self._crawl_with_profile(
                job_id, request, effective_session_id, cache_key, rule, domain_key
            )

        layers = _resolve_layers(request.mode, preferred_mode)

        last_error: FetchError | None = None
        last_verdict_reason: str | None = None
        for mode_name in layers:
            try:
                response = await self._fetchers[mode_name](
                    request.url,
                    timeout_seconds=self._layer_timeouts[mode_name],
                    validate=self._validate,
                    session=session,
                )
            except FetchError as exc:
                if exc.error_code in _IMMEDIATE_TERMINAL_ERRORS:
                    return self._fetch_error_outcome(
                        job_id, request, exc.error_code, str(exc)
                    )
                last_error = exc
                continue

            verdict = detect(response, rule)
            if verdict.ok:
                await self._clear_cooldown(domain_key)  # 成功即解除该会话熔断（HC-007）
                return await self._finalize(
                    job_id, request, response, mode_name, cache_key
                )
            last_verdict_reason = verdict.reason
            # HC-005/UT-019：检测到交互式挑战（滑块/验证码）或登录跳转后立即停止
            # 自动升级——升级到 stealth 也解不了人工挑战或登录墙，只会对目标站
            # 放大请求、白白拖慢响应。
            if verdict.reason in _NON_ESCALATING_REASONS:
                break

        return await self._terminal_outcome(
            job_id, request, cache_key, last_verdict_reason, last_error, domain_key
        )

    async def _resolve_rule(
        self, domain: str
    ) -> tuple[DomainRuleDefaults, str, str | None]:
        record = await self._db.get_domain_rule(domain)
        if record is None:
            return self._default_rule, "auto", None
        defaults = DomainRuleDefaults(
            min_content_bytes=record.min_content_bytes,
            escalate_status_codes=tuple(record.escalate_status_codes or (403, 429, 503)),
        )
        return defaults, record.preferred_mode or "auto", record.default_session_id

    async def _crawl_with_profile(
        self,
        job_id: str,
        request: CrawlRequest,
        session_id: str,
        cache_key: str,
        rule: DomainRuleDefaults,
        domain_key: str,
    ) -> CrawlOutcome:
        """带登录态 profile 的抓取：经 ProfileManager 加载已登录的持久上下文
        （user_data_dir），用该上下文起隐身浏览器抓取（浏览器天然已登录，JS 渲染的
        商品页可取到真实内容）。见 §16 浏览器原生登录方案。"""
        if self._profile_manager is None:
            return self._simple_error(
                job_id, request, "SESSION_NOT_FOUND", "Profile 功能未启用。"
            )
        profile = await self._db.get_profile(session_id)
        if profile is None:
            return self._simple_error(
                job_id, request, "SESSION_NOT_FOUND", f"会话 {session_id} 不存在。"
            )
        expired = profile.expires_at is not None and profile.expires_at <= self._clock()
        if profile.status != "ACTIVE" or expired:
            return self._simple_error(
                job_id, request, "SESSION_EXPIRED", "登录态已失效，请重新登录。"
            )

        async with self._profile_manager.use(session_id) as browser_session:
            try:
                response = await self._fetchers["stealth"](
                    request.url,
                    timeout_seconds=self._layer_timeouts["stealth"],
                    validate=self._validate,
                    session=browser_session,
                )
            except FetchError as exc:
                if exc.error_code in _IMMEDIATE_TERMINAL_ERRORS:
                    outcome = self._fetch_error_outcome(
                        job_id, request, exc.error_code, str(exc)
                    )
                else:
                    outcome = await self._terminal_outcome(
                        job_id, request, cache_key, None, exc, domain_key
                    )
            else:
                verdict = detect(response, rule)
                if verdict.ok:
                    await self._clear_cooldown(domain_key)
                    outcome = await self._finalize(
                        job_id, request, response, "stealth", cache_key
                    )
                else:
                    outcome = await self._terminal_outcome(
                        job_id, request, cache_key, verdict.reason, None, domain_key
                    )
        await self._db.touch_profile_last_used(session_id, self._clock())
        return outcome

    def _simple_error(
        self, job_id: str, request: CrawlRequest, error_code: str, message: str
    ) -> CrawlOutcome:
        return CrawlOutcome(
            status="FAILED",
            job_id=job_id,
            source_url=request.url,
            error_code=error_code,
            error_message=message,
            retriable=False,
        )

    async def _finalize(
        self,
        job_id: str,
        request: CrawlRequest,
        response: FetchResponse,
        mode_name: str,
        cache_key: str,
    ) -> CrawlOutcome:
        now = self._clock()
        result = convert_html_to_markdown(
            response.html,
            job_id=job_id,
            source_url=request.url,
            final_url=response.final_url,
            fetch_mode=mode_name,
            status_code=response.status_code,
            fetched_at=now.isoformat(),
            content_language=None,
        )
        paths = result_paths(self._data_dir, job_id)
        write_result(
            self._data_dir,
            job_id,
            result.markdown,
            metadata={
                "job_id": job_id,
                "source_url": request.url,
                "final_url": response.final_url,
                "title": result.title,
                "status": "SUCCESS",
                "fetch_mode": mode_name,
                "fetched_at": now.isoformat(),
            },
        )
        content_length = len(result.markdown)
        await self._db.upsert_crawl_result(
            CrawlResultRecord(
                job_id=job_id,
                cache_key=cache_key,
                source_url=request.url,
                final_url=response.final_url,
                title=result.title,
                status="SUCCESS",
                fetch_mode=mode_name,
                markdown_path=str(paths.markdown_path),
                content_length=content_length,
                status_code=response.status_code,
                error_code=None,
                error_message=None,
                created_at=now,
                expires_at=now + timedelta(seconds=self._cache_ttl),
            )
        )
        return CrawlOutcome(
            status="SUCCESS",
            job_id=job_id,
            source_url=request.url,
            final_url=response.final_url,
            fetch_mode=mode_name,
            title=result.title,
            markdown=result.markdown,
            content_length=content_length,
            resource_uri=f"crawl://results/{job_id}/content.md",
        )

    async def _terminal_outcome(
        self,
        job_id: str,
        request: CrawlRequest,
        cache_key: str,
        verdict_reason: str | None,
        last_error: FetchError | None,
        domain_key: str,
    ) -> CrawlOutcome:
        if last_error is not None and last_error.error_code == "FETCH_TIMEOUT":
            return await self._persist_failure(
                job_id, request, cache_key, "TIMEOUT", "FETCH_TIMEOUT",
                str(last_error), retriable=True,
            )

        # 挑战/阻断进入熔断，避免相同请求立刻重打上游（HC-007）。
        cooldown = self._cooldown_for_reason(verdict_reason, last_error)
        if cooldown is not None:
            seconds, reason = cooldown
            await self._set_cooldown(domain_key, seconds, reason)

        if verdict_reason is not None:
            status, error_code = _DETECTION_TERMINAL.get(
                verdict_reason, _DETECTION_TERMINAL_DEFAULT
            )
            return await self._persist_failure(
                job_id, request, cache_key, status, error_code,
                f"目标站点在所有可用层级均未通过（{verdict_reason}）。", retriable=False,
            )

        message = str(last_error) if last_error else "抓取失败，未取得有效内容。"
        return await self._persist_failure(
            job_id, request, cache_key, "BLOCKED", "UPSTREAM_BLOCKED", message,
            retriable=False,
        )

    async def _persist_failure(
        self,
        job_id: str,
        request: CrawlRequest,
        cache_key: str,
        status: str,
        error_code: str,
        message: str,
        retriable: bool,
    ) -> CrawlOutcome:
        now = self._clock()
        # 失败记录立即过期（expires_at=now），可按 job_id 查询但不会被当作新鲜缓存命中。
        await self._db.upsert_crawl_result(
            CrawlResultRecord(
                job_id=job_id,
                cache_key=cache_key,
                source_url=request.url,
                final_url=None,
                title=None,
                status=status,
                fetch_mode=None,
                markdown_path=None,
                content_length=None,
                status_code=None,
                error_code=error_code,
                error_message=message,
                created_at=now,
                expires_at=now,
            )
        )
        return CrawlOutcome(
            status=status,
            job_id=job_id,
            source_url=request.url,
            error_code=error_code,
            error_message=message,
            retriable=retriable,
        )

    def _fetch_error_outcome(
        self, job_id: str, request: CrawlRequest, error_code: str, message: str
    ) -> CrawlOutcome:
        status, retriable = _IMMEDIATE_TERMINAL_ERRORS.get(error_code, ("FAILED", False))
        return CrawlOutcome(
            status=status,
            job_id=job_id,
            source_url=request.url,
            error_code=error_code,
            error_message=message,
            retriable=retriable,
        )

    def _outcome_from_cached(self, cached: CrawlResultRecord) -> CrawlOutcome:
        markdown = None
        if cached.markdown_path:
            path = Path(cached.markdown_path)
            if path.exists():
                markdown = path.read_text(encoding="utf-8")
        return CrawlOutcome(
            status=cached.status,
            job_id=cached.job_id,
            source_url=cached.source_url,
            final_url=cached.final_url,
            fetch_mode=cached.fetch_mode,
            title=cached.title,
            markdown=markdown,
            content_length=cached.content_length,
            resource_uri=f"crawl://results/{cached.job_id}/content.md",
            from_cache=True,
        )
