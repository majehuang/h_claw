from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.converter.pipeline import convert_html_to_markdown
from app.crawler.detector import DomainRuleDefaults, FetchResponse, detect
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

_MODE_LAYERS = {
    "auto": ("http", "browser", "stealth"),
    "http": ("http",),
    "browser": ("browser",),
    "stealth": ("stealth",),
}


@dataclass(frozen=True)
class CrawlRequest:
    url: str
    mode: str = "auto"
    include_images: bool = True
    force_refresh: bool = False
    timeout_seconds: int = 60


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
        http_timeout_seconds: int = 15,
        browser_timeout_seconds: int = 60,
        stealth_timeout_seconds: int = 90,
        locale: str = "zh-CN",
    ):
        self._db = db
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
        self._locale = locale
        self._active = 0

    async def crawl(self, request: CrawlRequest, session: Any = None) -> CrawlOutcome:
        job_id = self._job_id_factory()

        # 非阻塞并发闸门：单事件循环线程内 check-then-increment 之间无 await，天然原子。
        if self._active >= self._max_concurrency:
            return CrawlOutcome(
                status="FAILED",
                job_id=job_id,
                source_url=request.url,
                error_code="RATE_LIMITED",
                error_message="抓取服务并发已满，请稍后重试。",
                retriable=True,
                retry_after_seconds=5,
            )

        self._active += 1
        try:
            return await self._crawl_inner(request, job_id, session)
        finally:
            self._active -= 1

    async def _crawl_inner(
        self, request: CrawlRequest, job_id: str, session: Any
    ) -> CrawlOutcome:
        try:
            self._validate(request.url)
        except URLValidationError as exc:
            return self._fetch_error_outcome(job_id, request, exc.error_code, str(exc))

        domain = urlsplit(request.url).hostname or ""
        cache_key = compute_cache_key(
            request.url, request.mode, request.include_images, self._locale, None
        )

        if not request.force_refresh:
            cached = await self._db.get_fresh_by_cache_key(cache_key, self._clock())
            if cached is not None:
                return self._outcome_from_cached(cached)

        rule = await self._resolve_rule(domain)
        layers = _MODE_LAYERS.get(request.mode, _MODE_LAYERS["auto"])

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
                return await self._finalize(
                    job_id, request, response, mode_name, cache_key
                )
            last_verdict_reason = verdict.reason

        return await self._terminal_outcome(
            job_id, request, cache_key, last_verdict_reason, last_error
        )

    async def _resolve_rule(self, domain: str) -> DomainRuleDefaults:
        record = await self._db.get_domain_rule(domain)
        if record is None:
            return self._default_rule
        return DomainRuleDefaults(
            min_content_bytes=record.min_content_bytes,
            escalate_status_codes=tuple(record.escalate_status_codes or (403, 429, 503)),
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
    ) -> CrawlOutcome:
        if last_error is not None and last_error.error_code == "FETCH_TIMEOUT":
            return await self._persist_failure(
                job_id, request, cache_key, "TIMEOUT", "FETCH_TIMEOUT",
                str(last_error), retriable=True,
            )

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
