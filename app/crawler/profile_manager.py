"""持久化 Profile 的生命周期与并发管理（Phase 3a / M-P3-2）。

职责（见 phase-3 设计 §4.4 / §4.5）：
- **per-profile 锁**：同一 `session_id` 串行，保证 `user_data_dir` 单写、不被并发打开。
- **并发预算**：至多 `max_active_profiles` 个不同 profile 同时活跃。
- **生命周期**：加载（解密到 tmpfs）→ 绑定浏览器会话 → 用完关闭并回写密文，异常路径也回写。

本管理器自建浏览器会话（不经 BrowserPool），因此天然**豁免** BrowserPool 的
100 任务盲重启（§4.5）。
"""
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

SessionFactory = Callable[[Path], Awaitable[Any]]


class ProfileManager:
    def __init__(
        self,
        *,
        store: Any,
        session_factory: SessionFactory,
        max_active_profiles: int,
    ):
        self._store = store
        self._session_factory = session_factory
        self._budget = asyncio.Semaphore(max_active_profiles)
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    @asynccontextmanager
    async def use(self, session_id: str):
        """在受控上下文内提供一个绑定该 profile 持久目录的浏览器会话。

        先取 per-profile 锁（串行化同一 profile），再取并发预算槽（限制不同
        profile 的并发数）；退出时关闭会话并把 profile 回写为密文。
        """
        async with self._lock(session_id):
            async with self._budget:
                work_dir = self._store.load(session_id)
                session = await self._session_factory(work_dir)
                try:
                    yield session
                finally:
                    close = getattr(session, "close", None)
                    if close is not None:
                        await close()
                    self._store.seal(session_id, work_dir)
