import asyncio
from collections.abc import Callable
from typing import Any, Protocol


class BrowserSession(Protocol):
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def fetch(self, url: str, **kwargs: Any) -> Any: ...
    def get_pool_stats(self) -> dict[str, int]: ...


def _default_dynamic_factory(max_pages: int) -> Callable[[], BrowserSession]:
    def _factory() -> BrowserSession:
        from scrapling.fetchers import AsyncDynamicSession

        return AsyncDynamicSession(max_pages=max_pages, headless=True)

    return _factory


def _default_stealth_factory(max_pages: int) -> Callable[[], BrowserSession]:
    def _factory() -> BrowserSession:
        from scrapling.fetchers import AsyncStealthySession

        return AsyncStealthySession(max_pages=max_pages, headless=True)

    return _factory


class BrowserPool:
    """长生命周期浏览器池，包装 Scrapling 的 Async(Dynamic|Stealthy)Session。

    Scrapling 已经负责共享浏览器进程与页面池（max_pages），本类只额外补齐：
    浏览器页面并发上限（信号量）、以及第 8 节要求的浏览器重启周期。
    跨 HTTP+浏览器的总并发与单域名串行由 orchestrator（M6）负责，因为它们
    横跨所有抓取层，不属于浏览器池的职责。
    """

    def __init__(
        self,
        *,
        max_browser_pages: int = 3,
        restart_after_tasks: int = 100,
        dynamic_factory: Callable[[], BrowserSession] | None = None,
        stealth_factory: Callable[[], BrowserSession] | None = None,
    ):
        self._max_pages = max_browser_pages
        self._restart_after = restart_after_tasks
        self._dynamic_factory = dynamic_factory or _default_dynamic_factory(max_browser_pages)
        self._stealth_factory = stealth_factory or _default_stealth_factory(max_browser_pages)
        self._semaphore = asyncio.Semaphore(max_browser_pages)
        self._restart_lock = asyncio.Lock()
        self._dynamic: BrowserSession | None = None
        self._stealth: BrowserSession | None = None
        self._task_count = 0

    async def start(self) -> None:
        self._dynamic = self._dynamic_factory()
        await self._dynamic.start()
        self._stealth = self._stealth_factory()
        await self._stealth.start()

    async def close(self) -> None:
        if self._dynamic is not None:
            await self._dynamic.close()
        if self._stealth is not None:
            await self._stealth.close()
        self._dynamic = None
        self._stealth = None

    async def fetch_dynamic(self, url: str, **kwargs: Any) -> Any:
        return await self._fetch(lambda: self._dynamic, url, **kwargs)

    async def fetch_stealth(self, url: str, **kwargs: Any) -> Any:
        return await self._fetch(lambda: self._stealth, url, **kwargs)

    async def _fetch(
        self, session_getter: Callable[[], BrowserSession | None], url: str, **kwargs: Any
    ) -> Any:
        async with self._semaphore:
            session = session_getter()
            if session is None:
                raise RuntimeError("BrowserPool 尚未 start() 或已关闭")
            response = await session.fetch(url, **kwargs)
        await self._maybe_restart()
        return response

    async def _maybe_restart(self) -> None:
        async with self._restart_lock:
            self._task_count += 1
            if self._task_count < self._restart_after:
                return
            # 排空在途任务：占满全部页面槽，确保重启时没有 fetch 正在进行。
            for _ in range(self._max_pages):
                await self._semaphore.acquire()
            try:
                await self.close()
                await self.start()
                self._task_count = 0
            finally:
                for _ in range(self._max_pages):
                    self._semaphore.release()

    def stats(self) -> dict[str, Any]:
        return {
            "task_count": self._task_count,
            "dynamic": self._dynamic.get_pool_stats() if self._dynamic else None,
            "stealth": self._stealth.get_pool_stats() if self._stealth else None,
        }
