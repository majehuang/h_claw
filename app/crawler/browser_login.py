"""浏览器原生登录的持有上下文 opener/closer（Phase 3d / BN2）。

配合 B1 `LoginManager` 状态机 + BN1 浏览器适配器：
- `open_browser_login`：起持久上下文（新 `user_data_dir` 落 tmpfs），返回活的 page
  （`handle`），并把 `user_data_dir` 记在 page 上供 closer 使用。page 保持存活，登录
  页的 JS 终化跨 begin→poll 在浏览器里跑。
- `close_browser_login`：成功时把该 `user_data_dir` 加密封存为 profile（A2 ProfileStore）
  并写 account_profiles，返回 `session_id`；无论成败都关闭上下文。
"""
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.storage.database import AccountProfile

# browser_launcher(user_data_dir: str) -> (context, page)
BrowserLauncher = Callable[[str], Awaitable[tuple[Any, Any]]]


async def open_browser_login(
    *,
    browser_launcher: BrowserLauncher,
    tmp_root: Path,
    id_factory: Callable[[], str],
) -> Any:
    user_data_dir = Path(tmp_root) / id_factory()
    _context, page = await browser_launcher(str(user_data_dir))
    # 把 user_data_dir 记在 page 上（每登录会话独立），供 closer 封存。
    page._hermes_udd = user_data_dir
    return page


async def close_browser_login(
    page: Any,
    *,
    success: bool,
    domain: str,
    store: Any,
    db: Any,
    session_id_factory: Callable[[], str],
    clock: Callable[[], datetime],
    ttl_seconds: int,
) -> str | None:
    user_data_dir = getattr(page, "_hermes_udd", None)
    # 先关闭上下文：chromium 在关闭时才把 cookie/localStorage 刷到 user_data_dir，
    # 必须刷盘后再封存，否则封存的 profile 缺登录态（抓取时会被打回登录页）。
    await page.context.close()
    if not success or user_data_dir is None:
        return None
    session_id = session_id_factory()
    # 已登录的 user_data_dir 即 profile：加密封存（明文只在 tmpfs）。
    store.seal(session_id, user_data_dir)
    now = clock()
    await db.upsert_profile(
        AccountProfile(
            session_id=session_id,
            domain=domain,
            label=None,
            status="ACTIVE",
            fingerprint_id=None,
            created_at=now,
            last_used_at=None,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
    )
    return session_id
