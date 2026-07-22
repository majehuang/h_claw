"""HC-002：InMemoryCooldownStore 与 DbCooldownStore 的行为契约（无需真 PG）。"""
from datetime import datetime, timedelta, timezone

import pytest

from app.crawler.cooldown import DbCooldownStore, InMemoryCooldownStore

pytestmark = pytest.mark.asyncio

_T0 = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


async def test_in_memory_remaining_and_expiry():
    store = InMemoryCooldownStore()
    await store.arm("k", _T0 + timedelta(seconds=600))
    assert await store.remaining_seconds("k", _T0) == 600
    assert await store.remaining_seconds("k", _T0 + timedelta(seconds=601)) is None


async def test_in_memory_clear_only_target_key():
    store = InMemoryCooldownStore()
    await store.arm("a", _T0 + timedelta(seconds=600))
    await store.arm("b", _T0 + timedelta(seconds=600))
    await store.clear("a")
    assert await store.remaining_seconds("a", _T0) is None
    assert await store.remaining_seconds("b", _T0) == 600


async def test_in_memory_unset_key_returns_none():
    store = InMemoryCooldownStore()
    assert await store.remaining_seconds("missing", _T0) is None


class FakeDB:
    """记录调用的假 DB，验证 DbCooldownStore 正确委托。"""

    def __init__(self):
        self.armed = []
        self.cleared = []
        self.value = None

    async def get_challenge_cooldown(self, key, now):
        return self.value

    async def upsert_challenge_cooldown(self, key, until, reason=None):
        self.armed.append((key, until, reason))

    async def clear_challenge_cooldown(self, key):
        self.cleared.append(key)


async def test_db_store_delegates_to_database():
    fake = FakeDB()
    store = DbCooldownStore(fake)

    await store.arm("k", _T0 + timedelta(seconds=600), "challenge")
    assert fake.armed == [("k", _T0 + timedelta(seconds=600), "challenge")]

    fake.value = _T0 + timedelta(seconds=600)
    assert await store.remaining_seconds("k", _T0) == 600

    await store.clear("k")
    assert fake.cleared == ["k"]
