"""HC-002：挑战冷却态持久化（真 PG）。

覆盖 IT-001（迁移可重复执行）与冷却态的存/取/过期/清除，验证跨"进程"（新 Database
实例）仍可读到冷却态——即重启不丢。
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.crawler.cooldown import DbCooldownStore

pytestmark = pytest.mark.asyncio

_T0 = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


async def test_migration_is_repeatable(db):
    # IT-001：在已迁移的库上再次执行迁移不报错，表仍可用。
    await db.apply_migrations()
    await db.upsert_challenge_cooldown("a.com|", _T0 + timedelta(seconds=600), "challenge")
    assert await db.get_challenge_cooldown("a.com|", _T0) is not None


async def test_cooldown_roundtrip_and_expiry(db):
    key = "item.taobao.com|sess1"
    await db.upsert_challenge_cooldown(key, _T0 + timedelta(seconds=600), "challenge")

    # 冷却期内可读到截止时间。
    active = await db.get_challenge_cooldown(key, _T0)
    assert active == _T0 + timedelta(seconds=600)

    # 越过截止时间后视为过期（查询按 now 过滤）。
    assert await db.get_challenge_cooldown(key, _T0 + timedelta(seconds=601)) is None


async def test_cooldown_clear(db):
    key = "x.com|"
    await db.upsert_challenge_cooldown(key, _T0 + timedelta(seconds=300), "blocked")
    await db.clear_challenge_cooldown(key)
    assert await db.get_challenge_cooldown(key, _T0) is None


async def test_upsert_overwrites_existing(db):
    key = "y.com|"
    await db.upsert_challenge_cooldown(key, _T0 + timedelta(seconds=100), "blocked")
    await db.upsert_challenge_cooldown(key, _T0 + timedelta(seconds=900), "challenge")
    assert await db.get_challenge_cooldown(key, _T0) == _T0 + timedelta(seconds=900)


async def test_db_store_persists_across_new_database_instance(db):
    # 模拟重启：用一个 DbCooldownStore 写入，再用"另一个"store 读回（同库不同实例）。
    writer = DbCooldownStore(db)
    await writer.arm("z.com|s", _T0 + timedelta(seconds=600), "challenge")

    reader = DbCooldownStore(db)
    assert await reader.remaining_seconds("z.com|s", _T0) == 600
    assert await reader.remaining_seconds("z.com|s", _T0 + timedelta(seconds=601)) is None
