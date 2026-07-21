import asyncio
from pathlib import Path

import pytest

from app.crawler.profile_manager import ProfileManager

pytestmark = pytest.mark.asyncio


class FakeStore:
    def __init__(self):
        self.loaded = []
        self.sealed = []

    def load(self, session_id):
        self.loaded.append(session_id)
        return Path(f"/work/{session_id}")

    def seal(self, session_id, work_dir):
        self.sealed.append((session_id, str(work_dir)))


class FakeSession:
    def __init__(self, work_dir):
        self.work_dir = work_dir
        self.closed = False

    async def close(self):
        self.closed = True


def _manager(store, *, max_active=2):
    async def factory(work_dir):
        return FakeSession(work_dir)

    return ProfileManager(store=store, session_factory=factory, max_active_profiles=max_active)


async def test_use_loads_provides_session_and_seals():
    store = FakeStore()
    pm = _manager(store)

    async with pm.use("s1") as session:
        assert isinstance(session, FakeSession)
        assert str(session.work_dir) == "/work/s1"

    assert store.loaded == ["s1"]
    assert store.sealed == [("s1", "/work/s1")]
    assert session.closed is True


async def test_same_profile_is_serialized():
    store = FakeStore()
    pm = _manager(store)
    active = 0
    overlapped = False

    async def worker():
        nonlocal active, overlapped
        async with pm.use("s1"):
            active += 1
            if active > 1:
                overlapped = True
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(worker(), worker(), worker())
    assert overlapped is False  # 同一 profile 串行，绝不并发打开（user_data_dir 单写）


async def test_budget_limits_distinct_concurrent_profiles():
    store = FakeStore()
    pm = _manager(store, max_active=2)
    current = 0
    peak = 0

    async def worker(session_id):
        nonlocal current, peak
        async with pm.use(session_id):
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(0.02)
            current -= 1

    await asyncio.gather(worker("a"), worker("b"), worker("c"))
    assert peak <= 2  # 最多 2 个不同 profile 同时活跃


async def test_seals_even_when_body_raises():
    store = FakeStore()
    pm = _manager(store)

    with pytest.raises(RuntimeError):
        async with pm.use("s1"):
            raise RuntimeError("boom")

    assert store.sealed == [("s1", "/work/s1")]  # 异常路径也回写密文
