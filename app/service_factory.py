import secrets
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.crawler.browser_fetcher import fetch_browser
from app.crawler.browser_pool import BrowserPool
from app.crawler.detector import DomainRuleDefaults
from app.crawler.browser_login import close_browser_login, open_browser_login
from app.crawler.http_fetcher import fetch_http
from app.crawler.login_adapters.browser import (
    JdBrowserLoginAdapter,
    TaobaoBrowserLoginAdapter,
)
from app.crawler.login_manager import LoginManager
from app.crawler.orchestrator import Orchestrator
from app.crawler.profile_manager import ProfileManager
from app.crawler.stealth_fetcher import fetch_stealth
from app.security.url_validator import validate_public_http_url
from app.storage.database import Database
from app.storage.profile_store import ProfileStore
from app.tools.service import Service

_LOGIN_TTL_SECONDS = 300


def _new_job_id() -> str:
    return f"cr_{secrets.token_hex(12)}"


def _new_session_id() -> str:
    return f"login_{secrets.token_hex(8)}"


def _new_login_id() -> str:
    return f"lg_{secrets.token_hex(6)}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_login_infra(settings: Settings, database: Database, playwright: Any):
    """构建登录态设施：ProfileManager（登录态抓取，加载 user_data_dir 起浏览器）
    + LoginManager（浏览器原生扫码登录，§16）。

    仅当注入了加密主密钥且 playwright 就绪时启用；否则返回 (None, None)。
    """
    if not settings.profile_encryption_key or playwright is None:
        return None, None

    store = ProfileStore(
        enc_dir=settings.profiles_dir,                               # /data，持久密文
        work_root=Path(tempfile.gettempdir()) / "hermes-profiles",  # tmpfs，明文工作区
        key=settings.profile_encryption_key,
    )

    # 抓取侧：加载 profile 的 user_data_dir → 起已登录的隐身浏览器（BN3）。
    async def profile_session_factory(work_dir):
        from scrapling.fetchers import AsyncStealthySession

        session = AsyncStealthySession(
            max_pages=1, headless=True, user_data_dir=str(work_dir)
        )
        await session.start()
        return session

    profile_manager = ProfileManager(
        store=store,
        session_factory=profile_session_factory,
        max_active_profiles=settings.max_active_profiles,
    )

    # 登录侧：浏览器原生登录（在浏览器内完成 JS 终化，产出已登录 user_data_dir）。
    login_tmp_root = Path(tempfile.gettempdir()) / "hermes-login"

    async def browser_launcher(user_data_dir: str):
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir, headless=True,
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        return context, page

    async def session_opener(domain: str):
        return await open_browser_login(
            browser_launcher=browser_launcher,
            tmp_root=login_tmp_root, id_factory=_new_login_id,
        )

    async def session_closer(handle, *, success: bool, domain: str):
        return await close_browser_login(
            handle, success=success, domain=domain,
            store=store, db=database, session_id_factory=_new_session_id,
            clock=_now, ttl_seconds=settings.profile_ttl_seconds,
        )

    login_manager = LoginManager(
        adapters=[JdBrowserLoginAdapter(), TaobaoBrowserLoginAdapter()],
        session_opener=session_opener,
        session_closer=session_closer,
        clock=_now,
        id_factory=_new_login_id,
        ttl_seconds=_LOGIN_TTL_SECONDS,
    )
    return profile_manager, login_manager


@asynccontextmanager
async def build_service(settings: Settings):
    """装配完整服务依赖（数据库连接池、浏览器池、orchestrator），
    作为长生命周期资源，进程启动时创建、退出时释放。
    """
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL 未配置")

    database = await Database.connect(
        settings.database_url, min_size=1, max_size=settings.max_concurrency + 1
    )
    await database.apply_migrations()

    pool = BrowserPool(max_browser_pages=settings.max_browser_pages)
    await pool.start()

    async def browser_fetch(url, *, timeout_seconds, validate, session=None):
        return await fetch_browser(
            url, pool=pool, timeout_seconds=timeout_seconds,
            validate=validate, session=session,
        )

    async def stealth_fetch(url, *, timeout_seconds, validate, session=None):
        return await fetch_stealth(
            url, pool=pool, timeout_seconds=timeout_seconds,
            validate=validate, session=session,
        )

    async def http_fetch(url, *, timeout_seconds, validate, session=None):
        return await fetch_http(
            url, timeout_seconds=timeout_seconds, validate=validate
        )

    playwright = None
    if settings.profile_encryption_key:
        from patchright.async_api import async_playwright

        playwright = await async_playwright().start()
    profile_manager, login_manager = _build_login_infra(settings, database, playwright)

    orchestrator = Orchestrator(
        db=database,
        data_dir=settings.data_dir,
        http_fetch=http_fetch,
        browser_fetch=browser_fetch,
        stealth_fetch=stealth_fetch,
        validate=validate_public_http_url,
        clock=_now,
        job_id_factory=_new_job_id,
        default_rule=DomainRuleDefaults(),
        cache_ttl_seconds=settings.cache_ttl_seconds,
        result_ttl_seconds=settings.result_ttl_seconds,
        max_concurrency=settings.max_concurrency,
        http_timeout_seconds=settings.http_timeout_seconds,
        browser_timeout_seconds=settings.browser_timeout_seconds,
        stealth_timeout_seconds=settings.stealth_timeout_seconds,
        profile_manager=profile_manager,
    )

    service = Service(
        orchestrator=orchestrator,
        db=database,
        data_dir=settings.data_dir,
        inline_limit_bytes=settings.max_inline_markdown_bytes,
        max_markdown_bytes=settings.max_markdown_bytes,
        login_manager=login_manager,
    )

    try:
        yield service
    finally:
        await pool.close()
        if playwright is not None:
            await playwright.stop()
        await database.close()
