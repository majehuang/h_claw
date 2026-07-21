import secrets
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.crawler.browser_fetcher import fetch_browser
from app.crawler.browser_pool import BrowserPool
from app.crawler.detector import DomainRuleDefaults
from app.crawler.http_fetcher import fetch_http
from app.crawler.orchestrator import Orchestrator
from app.crawler.profile_manager import ProfileManager
from app.crawler.stealth_fetcher import fetch_stealth
from app.security.url_validator import validate_public_http_url
from app.storage.database import Database
from app.storage.profile_store import ProfileStore
from app.tools.service import Service


def _new_job_id() -> str:
    return f"cr_{secrets.token_hex(12)}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_profile_manager(settings: Settings) -> ProfileManager | None:
    """仅当注入了加密主密钥时启用持久 Profile（登录态）能力。"""
    if not settings.profile_encryption_key:
        return None

    store = ProfileStore(
        enc_dir=settings.profiles_dir,                               # /data，持久密文
        work_root=Path(tempfile.gettempdir()) / "hermes-profiles",  # tmpfs，明文工作区
        key=settings.profile_encryption_key,
    )

    async def session_factory(work_dir):
        from scrapling.fetchers import AsyncStealthySession

        session = AsyncStealthySession(
            max_pages=1, headless=True, user_data_dir=str(work_dir)
        )
        await session.start()
        return session

    return ProfileManager(
        store=store,
        session_factory=session_factory,
        max_active_profiles=settings.max_active_profiles,
    )


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
        return await fetch_http(url, timeout_seconds=timeout_seconds, validate=validate)

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
        profile_manager=_build_profile_manager(settings),
    )

    service = Service(
        orchestrator=orchestrator,
        db=database,
        data_dir=settings.data_dir,
        inline_limit_bytes=settings.max_inline_markdown_bytes,
        max_markdown_bytes=settings.max_markdown_bytes,
    )

    try:
        yield service
    finally:
        await pool.close()
        await database.close()
