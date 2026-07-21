"""登录 cookie → 加密 Profile 的持久化桥接（Phase 3b）。

扫码成功后，把登录 cookie（如 JD 的 pt_key/pt_pin）以 JSON 存入 profile 工作目录，
经 ProfileStore 加密落盘（明文只在 tmpfs），并写 account_profiles 元数据；crawl 时
以 `session_id` 加载并注入抓取。见设计 §5.5 / §6。
"""
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from app.storage.database import AccountProfile

_COOKIES_FILE = "cookies.json"


async def persist_login_profile(
    *,
    cookies: dict[str, str],
    domain: str,
    label: str | None,
    store: Any,
    db: Any,
    session_id: str,
    clock: Callable[[], datetime],
    ttl_seconds: int,
) -> AccountProfile:
    work_dir = store.load(session_id)  # 新 profile → 空目录
    (work_dir / _COOKIES_FILE).write_text(
        json.dumps(cookies, ensure_ascii=False), encoding="utf-8"
    )
    store.seal(session_id, work_dir)

    now = clock()
    profile = AccountProfile(
        session_id=session_id,
        domain=domain,
        label=label,
        status="ACTIVE",
        fingerprint_id=None,
        created_at=now,
        last_used_at=None,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    await db.upsert_profile(profile)
    return profile


def load_profile_cookies(store: Any, session_id: str) -> dict[str, str]:
    if not store.exists(session_id):
        return {}
    work_dir = store.load(session_id)
    path = work_dir / _COOKIES_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
